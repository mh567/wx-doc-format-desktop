import json
import sys
from pathlib import Path

import pytest
from docx import Document

from wxdoc_desktop.service import ConversionError, ConversionRequest, convert_document


VERSION = (Path(__file__).parents[1] / "VERSION").read_text(encoding="utf-8").strip()

PASSING_REPORT = {
    "status": "completed",
    "public_summary": {
        "schema_version": "1.0",
        "status": "completed",
        "audits": {"model_audit": "passed", "saved_output_audit": "passed"},
        "unexpected_styles_count": 0,
        "manual_review_required": False,
        "diagnostic_codes": [],
    },
}


def test_native_runtime_stages_artifacts_before_publishing(tmp_path: Path, monkeypatch):
    source = tmp_path / "源文档.md"
    source.write_text("# 暂存测试\n", encoding="utf-8")
    output = tmp_path / "用户结果" / "结果.docx"
    seen: dict[str, Path] = {}

    class StagingRuntime:
        version = VERSION
        template_sha256 = "a" * 64

        def convert(self, source_path, staged_output, staged_report, *, strict_normalize):
            assert source_path.name == "input.md"
            assert source_path.parent != source.parent
            assert source_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
            assert strict_normalize is True
            assert staged_output.name == "output.docx"
            assert staged_report.name == "report.json"
            assert staged_output.parent != output.parent
            assert staged_report.parent != output.parent
            seen["output"] = staged_output
            seen["report"] = staged_report
            staged_output.write_bytes(b"staged-docx")
            staged_report.write_text(json.dumps(PASSING_REPORT), encoding="utf-8")
            return dict(PASSING_REPORT)

    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: StagingRuntime())

    result = convert_document(ConversionRequest(source, output))

    assert output.read_bytes() == b"staged-docx"
    assert result.json_report_path.is_file()
    assert seen["output"].parent != output.parent
    assert seen["report"].parent != output.parent


def test_conversion_uses_embedded_native_skill_runtime(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("# 原生运行时接入测试\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    result = convert_document(ConversionRequest(source, output))
    report = json.loads(result.json_report_path.read_text(encoding="utf-8"))

    assert report["native_marker"] == "called"
    assert report["application"]["engine_mode"] == "native-runtime"
    assert result.engine_version == VERSION


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
    assert report["public_summary"]["audits"]["saved_output_audit"] == "passed"
    assert report["risk_warnings"] == []
    assert result.status == "completed"


def _runtime_returning(payload: dict):
    class StaticRuntime:
        version = VERSION
        template_sha256 = "a" * 64

        def convert(self, source_path, staged_output, staged_report, *, strict_normalize):
            staged_output.write_bytes(b"staged-docx")
            staged_report.write_text(json.dumps(payload), encoding="utf-8")
            return dict(payload)

    return StaticRuntime()


def test_review_summary_surfaces_warnings_and_review_status(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# 复核测试\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    payload = {
        "status": "completed_with_warnings",
        "public_summary": {
            "schema_version": "1.0",
            "status": "completed_with_warnings",
            "audits": {"model_audit": "passed", "saved_output_audit": "failed"},
            "unexpected_styles_count": 2,
            "manual_review_required": True,
            "diagnostic_codes": ["source_heading_level_normalized"],
        },
    }
    monkeypatch.setattr(
        "wxdoc_desktop.service.NativeRuntime.discover",
        lambda: _runtime_returning(payload),
    )

    result = convert_document(ConversionRequest(source, output))

    assert result.status == "review"
    report = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    assert {item["type"] for item in report["risk_warnings"]} == {
        "saved_output_audit",
        "unexpected_styles",
        "source_heading_level_normalized",
    }
    assert result.warning_count == len(report["risk_warnings"])
    assert "模板外样式" in result.report_path.read_text(encoding="utf-8")


def test_report_without_public_summary_is_rejected(tmp_path: Path, native_skill_runtime: Path):
    script = native_skill_runtime / "runtime" / "wx-doc-format"
    script.write_text(
        f"#!{sys.executable}\n"
        "import argparse, shutil\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--version', action='store_true')\n"
        "parser.add_argument('--input')\n"
        "parser.add_argument('--output')\n"
        "parser.add_argument('--template')\n"
        "parser.add_argument('--report')\n"
        "parser.add_argument('--strict-normalize', action='store_true')\n"
        "parser.add_argument('--no-strict-normalize', action='store_true')\n"
        "args = parser.parse_args()\n"
        "if not args.version:\n"
        "    shutil.copyfile(args.template, args.output)\n"
        "    open(args.report, 'w', encoding='utf-8').write('{\"status\": \"completed\"}')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    source = tmp_path / "source.md"
    source.write_text("# 摘要缺失\n", encoding="utf-8")

    with pytest.raises(ConversionError):
        convert_document(ConversionRequest(source, tmp_path / "output.docx"))
