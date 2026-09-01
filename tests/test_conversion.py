import json
from pathlib import Path

from docx import Document

from wxdoc_desktop.service import ConversionRequest, convert_document


def test_native_runtime_stages_artifacts_before_publishing(tmp_path: Path, monkeypatch):
    source = tmp_path / "源文档.md"
    source.write_text("# 暂存测试\n", encoding="utf-8")
    output = tmp_path / "用户结果" / "结果.docx"
    seen: dict[str, Path] = {}

    class StagingRuntime:
        version = "0.12.19"
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
            staged_report.write_text(
                json.dumps({"skill_version": self.version, "risk_warnings": []}),
                encoding="utf-8",
            )
            return {"skill_version": self.version, "risk_warnings": []}

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
    assert result.engine_version == "0.12.19"


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
