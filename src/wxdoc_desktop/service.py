from __future__ import annotations

import html
import io
import json
import os
import re
import tempfile
import zipfile
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

from wxdoc_core import engine_version
from wxdoc_core.audit import audit_document, collect_content_warnings
from wxdoc_core.caption_placement import (
    audit_model_caption_placement,
    audit_rendered_caption_placement,
)
from wxdoc_core.document_model import (
    compare_document_models,
    summarize_document_model,
    validate_document_model,
)
from wxdoc_core.docx_pipeline import infer_docx_role, parse_docx_to_model
from wxdoc_core.docx_render import render_docx_direct
from wxdoc_core.front_matter import (
    analyze_front_matter,
    audit_output_structure,
    front_matter_source_positions,
    inject_document_title,
)
from wxdoc_core.list_detector import analyze_docx_lists, audit_list_preservation
from wxdoc_core.md_pipeline import parse_md_to_model
from wxdoc_core.model_normalization import (
    normalize_document_model,
    summarize_source_document_model,
)
from wxdoc_core.reporting import add_risk_warnings, new_report
from wxdoc_core.table_semantics import audit_model_table_semantics
from wxdoc_core.template_finalizer import apply_template_finalizer
from wxdoc_core.template_profile import load_template_profile
from wxdoc_core.text_utils import (
    build_document_model_from_output,
    heading_level_from_style,
    looks_like_code_sample_table,
    paragraph_num_info,
    scan_non_text_objects,
    set_table_autofit_to_window,
    strip_heading_marker,
)
from wxdoc_core.toc_detector import (
    audit_toc_replacement,
    detect_toc_regions,
    finalize_toc_selection,
    selected_source_positions,
)
from wxdoc_core.word_model_renderer import render_document_model

from . import __version__
from .environment import environment_report
from .resources import template_sha256, verified_template


MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_DOCX_FILES = 5_000
MAX_DOCX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
ROW_HEIGHT_CM = 0.69
ROW_HEIGHT_RULE = "at-least"


class ConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConversionRequest:
    input_path: Path
    output_path: Path | None = None
    report_path: Path | None = None
    strict_normalize: bool = True


@dataclass(frozen=True)
class ConversionResult:
    status: str
    input_path: Path
    output_path: Path
    report_path: Path
    json_report_path: Path
    warning_count: int
    warnings: tuple[dict, ...]
    application_version: str
    engine_version: str
    template_sha256: str

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("input_path", "output_path", "report_path", "json_report_path"):
            data[key] = str(data[key])
        data["warnings"] = list(self.warnings)
        return data


def default_output_path(source: Path, output_dir: Path | None = None) -> Path:
    directory = output_dir or source.parent
    return directory / f"{source.stem}_WX格式.docx"


def _validate_docx_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_FILES:
                raise ConversionError("文档内部文件数量过多。")
            expanded = sum(member.file_size for member in members)
            compressed = sum(max(member.compress_size, 1) for member in members)
            if expanded > MAX_DOCX_EXPANDED_BYTES:
                raise ConversionError("文档解压后体积超出安全限制。")
            if compressed and expanded / compressed > MAX_COMPRESSION_RATIO:
                raise ConversionError("文档压缩比异常，已停止处理。")
            for member in members:
                normalized = member.filename.replace("\\", "/")
                if normalized.startswith("/") or "../" in f"/{normalized}":
                    raise ConversionError("文档包含不安全的内部路径。")
    except zipfile.BadZipFile as exc:
        raise ConversionError("无法读取该 DOCX，文件可能已损坏。") from exc


def validate_input(path: Path) -> Path:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ConversionError("请选择存在的文件。")
    if source.suffix.lower() not in {".docx", ".md", ".markdown"}:
        raise ConversionError("仅支持 DOCX 和 Markdown 文件。")
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ConversionError("文件超过 100 MB 安全限制。")
    if source.suffix.lower() == ".docx":
        _validate_docx_archive(source)
    return source


def _open_template_renamed_media(template_path: Path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(template_path, "r") as source:
        with zipfile.ZipFile(buffer, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename.startswith("word/media/") and not item.filename.endswith("/"):
                    dot = item.filename.rfind(".")
                    name = item.filename[:dot] + "_tmpl" + item.filename[dot:] if dot > 0 else item.filename + "_tmpl"
                    target.writestr(name, data)
                elif item.filename == "word/_rels/document.xml.rels":
                    relationships = data.decode("utf-8")
                    relationships = re.sub(
                        r'Target="media/([^"]+?)\.(png|jpg|jpeg|gif|bmp|emf|wmf)"',
                        r'Target="media/\1_tmpl.\2"',
                        relationships,
                    )
                    target.writestr(item, relationships.encode("utf-8"))
                else:
                    target.writestr(item, data)
    temporary = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    temporary.write(buffer.getvalue())
    temporary.close()
    document = Document(temporary.name)
    document._tmpl_path = temporary.name
    return document


def _clear_document_body(document) -> None:
    from docx.oxml.ns import qn

    body = document.element.body
    section = None
    if len(body) and body[-1].tag == qn("w:sectPr"):
        section = deepcopy(body[-1])
    for child in list(body):
        body.remove(child)
    if section is not None:
        body.append(section)


def _audit_document(document, template_profile: dict, table_roles: list[str]) -> dict:
    from docx.oxml.ns import qn

    return audit_document(
        document,
        ROW_HEIGHT_CM,
        ROW_HEIGHT_RULE,
        heading_level_from_style=heading_level_from_style,
        paragraph_direct_num_info=paragraph_num_info,
        existing_heading_number=lambda text: strip_heading_marker(text) != text,
        looks_like_code_sample_table=looks_like_code_sample_table,
        qn=qn,
        center_alignment=WD_ALIGN_PARAGRAPH.CENTER,
        template_profile=template_profile,
        table_roles=table_roles,
    )


def _convert_markdown(source: Path, output_document, report: dict, numbering_ids: dict) -> dict:
    source_model = parse_md_to_model(source, report, skill_version=engine_version)
    summarize_source_document_model(report, source_model)
    normalized = normalize_document_model(source_model, report)
    report["table_semantics_audit"] = audit_model_table_semantics(normalized)
    report["caption_placement_model_audit"] = audit_model_caption_placement(normalized)
    render_document_model(
        normalized,
        output_document,
        report,
        ROW_HEIGHT_CM,
        ROW_HEIGHT_RULE,
        numbering_ids,
        template_profile=report.get("template_profile"),
    )
    return {"source": source_model, "normalized": normalized}


def _convert_docx(source: Path, output_document, report: dict, numbering_ids: dict, strict: bool) -> dict:
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    source_document = Document(source)
    toc_context = detect_toc_regions(source_document, report)
    finalize_toc_selection(toc_context, report, method="rules")
    front_matter = analyze_front_matter(source_document, toc_context, source, report)
    excluded = selected_source_positions(toc_context) | front_matter_source_positions(front_matter)
    numbering = analyze_docx_lists(source_document, report, excluded_source_positions=excluded)
    source_model = parse_docx_to_model(
        source,
        source_document,
        strict,
        0,
        skill_version=engine_version,
        new_report=lambda: {},
        iter_blocks=lambda document: (
            Paragraph(child, document) if child.tag == qn("w:p") else Table(child, document)
            for child in document.element.body.iterchildren()
            if child.tag in (qn("w:p"), qn("w:tbl"))
        ),
        paragraph_class=Paragraph,
        infer_docx_role=infer_docx_role,
        looks_like_code_sample_table=looks_like_code_sample_table,
        caption_pattern=None,
        excluded_source_positions=excluded,
        numbering_context=numbering,
    )
    report["parse_report"] = source_model.get("parse_report", {})
    source_model = inject_document_title(source_model, front_matter)
    summarize_source_document_model(report, source_model)
    normalized = normalize_document_model(source_model, report)
    report["table_semantics_audit"] = audit_model_table_semantics(normalized)
    report["caption_placement_model_audit"] = audit_model_caption_placement(normalized)
    render_docx_direct(
        source_document,
        output_document,
        report,
        ROW_HEIGHT_CM,
        ROW_HEIGHT_RULE,
        numbering_ids,
        template_profile=report.get("template_profile"),
        strict_normalize=strict,
        role_overrides=None,
        heading_level_overrides={},
        table_type_overrides={},
        model=normalized,
        excluded_source_positions=excluded,
    )
    return {
        "source": source_model,
        "normalized": normalized,
        "toc_context": toc_context,
        "front_matter_context": front_matter,
    }


def _risk_label(risk_type: str) -> str:
    return {
        "media_not_fully_preserved": "图片或媒体需复核",
        "non_text_objects": "文本框或复杂对象需复核",
        "document_model_diff": "文档结构发生规范化调整",
        "template_layout": "目录、页码或分节需 WPS/Word 复核",
        "template_styles": "发现模板外样式",
        "caption_placement": "题注位置需复核",
    }.get(risk_type, "建议复核该文档")


def _write_html_report(report: dict, path: Path, source: Path, output: Path) -> None:
    warnings = report.get("risk_warnings", [])
    warning_items = "".join(
        f"<li><strong>{html.escape(_risk_label(str(item.get('type', ''))))}</strong>"
        f"<span>{html.escape(str(item.get('message', '')))}</span></li>"
        for item in warnings
    ) or "<li><strong>未发现需复核项</strong><span>已通过自动结构与样式审计。</span></li>"
    status = "已完成，建议复核" if warnings else "已完成"
    markup = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>WX 文档转换报告</title>
<style>body{{font:15px/1.7 system-ui,sans-serif;color:#202622;background:#f4f6f3;margin:0}}main{{max-width:820px;margin:48px auto;padding:40px;background:#fff;border:1px solid #dfe5df;border-radius:24px}}h1{{font-size:28px;margin:0 0 8px}}.status{{color:#176b4d;font-weight:700}}dl{{display:grid;grid-template-columns:150px 1fr;gap:8px 16px;padding:24px 0;border-bottom:1px solid #e6ebe6}}dt{{color:#677169}}dd{{margin:0;word-break:break-all}}ul{{padding:0;list-style:none}}li{{padding:16px 0;border-bottom:1px solid #edf0ed;display:grid;gap:4px}}li span{{color:#667069}}</style>
<main><p class="status">{status}</p><h1>WX 文档转换报告</h1>
<dl><dt>源文件</dt><dd>{html.escape(source.name)}</dd><dt>输出文件</dt><dd>{html.escape(output.name)}</dd>
<dt>应用版本</dt><dd>{html.escape(__version__)}</dd><dt>规则引擎</dt><dd>{html.escape(engine_version())}</dd>
<dt>生成时间</dt><dd>{datetime.now(timezone.utc).isoformat()}</dd></dl><h2>复核摘要</h2><ul>{warning_items}</ul></main>"""
    path.write_text(markup, encoding="utf-8")


def convert_document(request: ConversionRequest) -> ConversionResult:
    source = validate_input(request.input_path)
    output = (request.output_path or default_output_path(source)).expanduser().resolve()
    report_html = (request.report_path or output.with_name(output.stem + "_报告.html")).expanduser().resolve()
    report_json = report_html.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    report_html.parent.mkdir(parents=True, exist_ok=True)

    with verified_template() as template:
        profile = load_template_profile(template)
        output_document = _open_template_renamed_media(template)
        temporary_output: Path | None = None
        try:
            _clear_document_body(output_document)
            numbering_ids = profile.get("numbering_ids", {})
            report = new_report(engine_version())
            report["application"] = {
                "version": __version__,
                "engine_version": engine_version(),
                "template_sha256": template_sha256(),
                "offline": True,
                "environment": environment_report(),
            }
            report["template_profile"] = {
                "path": "embedded:wx_template.docx",
                "resolved_styles": profile.get("resolved_styles", {}),
                "missing_roles": profile.get("missing_roles", []),
                "numbering_ids": profile.get("numbering_ids", {}),
                "table_style": profile.get("table_style", {}),
            }
            report["non_text_objects"] = scan_non_text_objects(source)

            if source.suffix.lower() == ".docx":
                models = _convert_docx(source, output_document, report, numbering_ids, request.strict_normalize)
            else:
                models = _convert_markdown(source, output_document, report, numbering_ids)

            normalized = models["normalized"]
            table_roles = [
                block.get("table_type", "data")
                for block in normalized.get("document", {}).get("blocks", [])
                if block.get("block_type") == "table"
            ]
            report["template_finalizer"] = apply_template_finalizer(
                output_document,
                profile,
                ROW_HEIGHT_CM,
                ROW_HEIGHT_RULE,
                row_height_rule_enum=WD_ROW_HEIGHT_RULE,
                cm=Cm,
                left_alignment=WD_ALIGN_PARAGRAPH.LEFT,
                center_alignment=WD_ALIGN_PARAGRAPH.CENTER,
                set_table_autofit_to_window=set_table_autofit_to_window,
                looks_like_code_sample_table=looks_like_code_sample_table,
                table_roles=table_roles,
            )
            report["toc_replacement_audit"] = audit_toc_replacement(
                output_document,
                models.get("toc_context"),
            )
            report["output_structure_audit"] = audit_output_structure(output_document, profile)
            report["caption_placement_audit"] = audit_rendered_caption_placement(output_document)
            rendered = build_document_model_from_output(output_document, source, report)
            report["rendered_document_model_summary"] = report.get("document_model_summary", {})
            report["rendered_document_model_issues"] = report.get("document_model_issues", [])
            report["document_model_summary"] = summarize_document_model(normalized)
            report["document_model_issues"] = validate_document_model(normalized)
            report["document_model_diff"] = compare_document_models(normalized, rendered)
            report["audit"] = _audit_document(output_document, profile, table_roles)
            report["list_preservation_audit"] = audit_list_preservation(
                output_document,
                normalized,
                report.get("source_lists"),
                profile,
            )
            report["content_warnings"] = collect_content_warnings(output_document)
            add_risk_warnings(report, ROW_HEIGHT_RULE)

            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".docx", dir=output.parent)
            handle.close()
            temporary_output = Path(handle.name)
            output_document.save(temporary_output)
            os.replace(temporary_output, output)
            temporary_output = None
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _write_html_report(report, report_html, source, output)

            warnings = tuple(report.get("risk_warnings", []))
            return ConversionResult(
                status="review" if warnings else "completed",
                input_path=source,
                output_path=output,
                report_path=report_html,
                json_report_path=report_json,
                warning_count=len(warnings),
                warnings=warnings,
                application_version=__version__,
                engine_version=engine_version(),
                template_sha256=template_sha256(),
            )
        finally:
            if temporary_output is not None:
                temporary_output.unlink(missing_ok=True)
            template_copy = getattr(output_document, "_tmpl_path", None)
            if template_copy:
                Path(template_copy).unlink(missing_ok=True)
