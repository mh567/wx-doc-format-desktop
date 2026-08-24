import json
from pathlib import Path

from docx import Document

from wxdoc_desktop.service import ConversionRequest, convert_document


def test_docx_conversion_writes_document_and_reports(tmp_path: Path):
    version = (Path(__file__).parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    source = tmp_path / "sample.docx"
    document = Document()
    document.add_heading("项目概述", level=1)
    document.add_paragraph("这是一段用于独立程序回归测试的正文。")
    document.save(source)

    output = tmp_path / "sample_WX格式.docx"
    result = convert_document(ConversionRequest(source, output))

    assert result.output_path.is_file()
    assert result.report_path.is_file()
    assert result.json_report_path.is_file()
    assert result.status in {"completed", "review"}
    report = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    assert report["application"]["offline"] is True
    assert report["application"]["engine_version"] == version
    assert report["application"]["version"] == version
    assert report["template_finalizer"]["corrections"][0]["mode"] == "template_fragment"
    assert report["template_finalizer"]["style_audit"]["unexpected_styles"] == []


def test_markdown_conversion_preserves_structured_content(tmp_path: Path):
    source = tmp_path / "sample.md"
    source.write_text(
        "# 测试文档\n\n"
        "## 功能说明\n\n"
        "1. 第一项\n"
        "2. 第二项\n\n"
        "| 名称 | 说明 |\n"
        "| --- | --- |\n"
        "| 状态 | 正常 |\n\n"
        "`client_id` 保持可读。\n",
        encoding="utf-8",
    )

    output = tmp_path / "sample_WX格式.docx"
    result = convert_document(ConversionRequest(source, output))

    assert result.output_path.is_file()
    report = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    source_audit = report["markdown_source_audit"]
    assert source_audit["title_count"] == 1
    assert source_audit["heading_count"] == 1
    assert source_audit["list_items"] == 2
    assert source_audit["table_count"] == 1
    assert source_audit["table_rows"] == 2
    assert report["markdown_preservation_audit"]["passed"] is True
    assert report["markdown_preservation_audit"]["markdown_residue"] == []
    contract = report["markdown_recognition_contract"]
    assert contract["dialect"] == "commonmark+table"
    assert contract["semantic_sequence"]


def test_vendored_markdown_recognition_module_is_manifested():
    root = Path(__file__).parents[1]
    manifest = json.loads((root / "VENDORED_MANIFEST.json").read_text(encoding="utf-8"))
    module = root / "src" / "wxdoc_core" / "markdown_recognition.py"

    assert module.is_file()
    assert "markdown_recognition.py" in manifest["modules"]


def test_markdown_desktop_end_to_end_preserves_fallback_title_separator_lists_and_inline_styles(tmp_path: Path):
    source = tmp_path / "无起始标题.md"
    source.write_text(
        "---\n\n"
        "```\ncode before heading\n```\n\n"
        "> quote before heading\n\n"
        "正文一\n\n正文二\n\n"
        "- 原始列表 `代码`\n\n"
        "列 | 值\n--- | ---\n甲 | **强调**\n\n"
        "# 后置 H1\n",
        encoding="utf-8",
    )
    output = tmp_path / "desktop_markdown.docx"
    result = convert_document(ConversionRequest(source, output))
    report = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    preservation = report["markdown_preservation_audit"]

    assert result.status == "review"
    assert report["markdown_title_audit"] == {
        "code": "markdown_title_generated",
        "source": "filename",
        "leading_h1_absent": True,
        "title": "无起始标题",
    }
    assert any(item["type"] == "markdown_title_generated" for item in report["risk_warnings"])
    assert preservation["source_ast"]["list_items"] == 1
    assert preservation["normalized_ast"]["list_items"] == 1
    assert preservation["passed"] is True
    assert sum(1 for item in preservation["semantic_sequence"]["rendered"] if item[0] == "separator") == 1

    document = Document(output)
    visible = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "分隔线" not in visible
    assert any(paragraph.text == "后置 H1" and paragraph.style.name.startswith("Heading") for paragraph in document.paragraphs)
    style_names = [run.style.name for paragraph in document.paragraphs for run in paragraph.runs]
    style_names.extend(run.style.name for table in document.tables for row in table.rows for cell in row.cells for paragraph in cell.paragraphs for run in paragraph.runs)
    assert any(name.startswith("MarkdownCode") for name in style_names)
    assert any(name.startswith("MarkdownStrong") for name in style_names)
