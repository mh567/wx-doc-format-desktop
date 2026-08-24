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
