from __future__ import annotations

import html
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .native_runtime import NativeRuntime, NativeRuntimeError


MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_DOCX_FILES = 5_000
MAX_DOCX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


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


@dataclass(frozen=True)
class ReviewRequest:
    input_path: Path
    report_path: Path | None = None
    markdown_path: Path | None = None
    html_path: Path | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    input_path: Path
    report_path: Path
    markdown_path: Path
    html_path: Path
    score: float
    grade: str
    passed: bool
    dimension_scores: dict
    summary: dict
    issues: tuple[dict, ...]
    compliant_items: tuple[str, ...]
    risk_warnings: tuple[str, ...]
    application_version: str
    engine_version: str
    template_sha256: str

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("input_path", "report_path", "markdown_path", "html_path"):
            data[key] = str(data[key])
        for key in ("issues", "compliant_items", "risk_warnings"):
            data[key] = list(data[key])
        data["issue_count"] = self.issue_count
        return data


def default_review_paths(source: Path, report_dir: Path | None = None) -> tuple[Path, Path, Path]:
    directory = report_dir or source.parent
    stem = f"{source.stem}_审查报告"
    return directory / f"{stem}.json", directory / f"{stem}.md", directory / f"{stem}.html"


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
    if source.suffix.lower() not in {".docx", ".md"}:
        raise ConversionError("仅支持 .docx 和 .md 文件。")
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ConversionError("文件超过 100 MB 安全限制。")
    if source.suffix.lower() == ".docx":
        _validate_docx_archive(source)
    return source


_AUDIT_MESSAGES = {
    "model_audit": "文档模型审计未通过",
    "saved_output_audit": "输出文档审计未通过",
    "appendix_preservation_audit": "附录保真审计未通过",
}

_DIAGNOSTIC_MESSAGES = {
    "source_heading_level_normalized": "标题层级已按大纲契约归一，建议复核标题层级",
    "markdown_title_generated": "源文档缺少一级标题，已按文件名生成文档标题",
    "unresolved_list_parent": "存在无法确定层级的列表，相关列表未套用列项样式",
    "render_plan_list_mismatch": "列表渲染结果与渲染计划不一致",
    "caption_target_missing": "题注缺少对应的表格或图片",
    "caption_placement_violation": "题注位置与模板契约不符",
    "external_resource_unresolved": "存在无法解析的外部资源",
    "protected_target": "受保护内容发生了变化",
    "opaque_node_skipped": "存在无法重建的行内对象，已按源引用保留",
}


def _summary_warnings(report: dict) -> tuple[dict, ...]:
    """Translate the compiled Skill's public summary into review items."""

    summary = report.get("public_summary") or {}
    items: list[dict] = []
    for name, observed in sorted((summary.get("audits") or {}).items()):
        if observed == "failed":
            items.append(
                {
                    "type": str(name),
                    "message": _AUDIT_MESSAGES.get(str(name), "文档审计未通过"),
                }
            )
    style_count = summary.get("unexpected_styles_count")
    if isinstance(style_count, int) and style_count > 0:
        items.append(
            {
                "type": "unexpected_styles",
                "message": f"发现 {style_count} 处模板外样式",
            }
        )
    for code in summary.get("diagnostic_codes") or []:
        text = str(code)
        items.append(
            {
                "type": text,
                "message": _DIAGNOSTIC_MESSAGES.get(text, "转换过程记录了需人工关注的诊断"),
            }
        )
    return tuple(items)


def _write_html_report(report: dict, path: Path, source: Path, output: Path) -> None:
    warnings = report.get("risk_warnings", [])
    warning_items = "".join(
        f"<li><strong>{html.escape(str(item.get('message', '')))}</strong>"
        f"<span>{html.escape(str(item.get('type', '')))}</span></li>"
        for item in warnings
    ) or "<li><strong>未发现需复核项</strong><span>已通过自动结构与样式审计。</span></li>"
    status = "已完成，建议复核" if warnings else "已完成"
    application = report["application"]
    markup = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>WX 文档转换报告</title>
<style>body{{font:15px/1.7 system-ui,sans-serif;color:#202622;background:#f4f6f3;margin:0}}main{{max-width:820px;margin:48px auto;padding:40px;background:#fff;border:1px solid #dfe5df;border-radius:24px}}h1{{font-size:28px;margin:0 0 8px}}.status{{color:#176b4d;font-weight:700}}dl{{display:grid;grid-template-columns:150px 1fr;gap:8px 16px;padding:24px 0;border-bottom:1px solid #e6ebe6}}dt{{color:#677169}}dd{{margin:0;word-break:break-all}}ul{{padding:0;list-style:none}}li{{padding:16px 0;border-bottom:1px solid #edf0ed;display:grid;gap:4px}}li span{{color:#667069}}</style>
<main><p class="status">{status}</p><h1>WX 文档转换报告</h1>
<dl><dt>源文件</dt><dd>{html.escape(source.name)}</dd><dt>输出文件</dt><dd>{html.escape(output.name)}</dd>
<dt>应用版本</dt><dd>{html.escape(application['version'])}</dd><dt>规则引擎</dt><dd>{html.escape(application['engine_version'])}</dd>
<dt>生成时间</dt><dd>{datetime.now(timezone.utc).isoformat()}</dd></dl><h2>复核摘要</h2><ul>{warning_items}</ul></main>"""
    path.write_text(markup, encoding="utf-8")


def _publish_native_artifact(staged: Path, destination: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(staged, temporary)
        shutil.copymode(staged, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def convert_document(request: ConversionRequest) -> ConversionResult:
    source = validate_input(request.input_path)
    output = (request.output_path or default_output_path(source)).expanduser().resolve()
    report_html = (request.report_path or output.with_name(output.stem + "_报告.html")).expanduser().resolve()
    report_json = report_html.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    report_html.parent.mkdir(parents=True, exist_ok=True)
    runtime = NativeRuntime.discover()
    try:
        with tempfile.TemporaryDirectory(prefix="wx-doc-format-native-") as native_workspace:
            native_root = Path(native_workspace)
            # The compiled runtime accepts only ASCII paths on macOS. Keep every
            # path passed to it stable and ASCII, then publish artifacts under
            # the user's requested names after conversion succeeds.
            staged_source = native_root / f"input{source.suffix.lower()}"
            staged_output = native_root / "output.docx"
            staged_report = native_root / "report.json"
            shutil.copyfile(source, staged_source)
            report = runtime.convert(
                staged_source,
                staged_output,
                staged_report,
                strict_normalize=request.strict_normalize,
            )
            _publish_native_artifact(staged_output, output)
            _publish_native_artifact(staged_report, report_json)
    except NativeRuntimeError as exc:
        output.unlink(missing_ok=True)
        report_json.unlink(missing_ok=True)
        raise ConversionError(str(exc)) from exc
    except OSError as exc:
        output.unlink(missing_ok=True)
        report_json.unlink(missing_ok=True)
        raise ConversionError(f"无法写入转换结果：{exc}") from exc
    report["application"] = {
        "version": __version__,
        "engine_version": runtime.version,
        "engine_mode": "native-runtime",
        "template_sha256": runtime.template_sha256,
        "offline": True,
    }
    warnings = _summary_warnings(report)
    report["risk_warnings"] = [dict(item) for item in warnings]
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_html_report(report, report_html, source, output)
    summary = report.get("public_summary") or {}
    return ConversionResult(
        status="review" if summary.get("manual_review_required") else "completed",
        input_path=source,
        output_path=output,
        report_path=report_html,
        json_report_path=report_json,
        warning_count=len(warnings),
        warnings=warnings,
        application_version=__version__,
        engine_version=runtime.version,
        template_sha256=runtime.template_sha256,
    )


def review_document(request: ReviewRequest) -> ReviewResult:
    source = validate_input(request.input_path)
    if source.suffix.lower() != ".docx":
        raise ConversionError("审查仅支持 .docx 文件。")
    default_json, default_markdown, default_html = default_review_paths(source)
    report_json = (request.report_path or default_json).expanduser().resolve()
    report_markdown = (request.markdown_path or default_markdown).expanduser().resolve()
    report_html = (request.html_path or default_html).expanduser().resolve()
    for path in (report_json, report_markdown, report_html):
        path.parent.mkdir(parents=True, exist_ok=True)
    runtime = NativeRuntime.discover()
    try:
        with tempfile.TemporaryDirectory(prefix="wx-doc-format-native-") as native_workspace:
            native_root = Path(native_workspace)
            # The compiled runtime accepts only ASCII paths on macOS, so every
            # path handed to it stays stable and ASCII. Artifacts are published
            # under the user's names after the review succeeds.
            staged_source = native_root / "input.docx"
            staged_json = native_root / "review.json"
            staged_markdown = native_root / "review.md"
            staged_html = native_root / "review.html"
            shutil.copyfile(source, staged_source)
            report = runtime.review(
                staged_source,
                report_path=staged_json,
                markdown_path=staged_markdown,
                html_path=staged_html,
            )
            _publish_native_artifact(staged_json, report_json)
            _publish_native_artifact(staged_markdown, report_markdown)
            _publish_native_artifact(staged_html, report_html)
    except NativeRuntimeError as exc:
        _unlink_review_outputs(report_json, report_markdown, report_html)
        raise ConversionError(str(exc)) from exc
    except OSError as exc:
        _unlink_review_outputs(report_json, report_markdown, report_html)
        raise ConversionError(f"无法写入审查结果：{exc}") from exc
    report["application"] = {
        "version": __version__,
        "engine_version": runtime.version,
        "engine_mode": "native-runtime",
        "template_sha256": runtime.template_sha256,
        "offline": True,
    }
    report["input_file"] = request.display_name or source.name
    report["template_file"] = runtime.template.name
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ReviewResult(
        input_path=source,
        report_path=report_json,
        markdown_path=report_markdown,
        html_path=report_html,
        score=float(report.get("score", 0)),
        grade=str(report.get("grade", "unknown")),
        passed=bool(report.get("passed", False)),
        dimension_scores=dict(report.get("dimension_scores") or {}),
        summary=dict(report.get("summary") or {}),
        issues=tuple(report.get("issues") or ()),
        compliant_items=tuple(str(item) for item in report.get("compliant_items") or ()),
        risk_warnings=tuple(str(item) for item in report.get("risk_warnings") or ()),
        application_version=__version__,
        engine_version=runtime.version,
        template_sha256=runtime.template_sha256,
    )


def _unlink_review_outputs(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
