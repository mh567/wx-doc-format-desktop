import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from docx import Document

from wxdoc_desktop.native_runtime import NativeRuntime, NativeRuntimeError
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
            Document().save(staged_output)
            staged_report.write_text(json.dumps(PASSING_REPORT), encoding="utf-8")
            return dict(PASSING_REPORT)

    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: StagingRuntime())

    result = convert_document(ConversionRequest(source, output))

    assert Document(output).paragraphs == []
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
            Document().save(staged_output)
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


def test_desktop_policy_surfaces_audit_findings_and_unknown_diagnostics(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# 风险\n", encoding="utf-8")
    payload = {
        "public_summary": {
            "schema_version": "1.0",
            "delivery_policy": "desktop",
            "conversion_status": "completed",
            "audit_status": "issues",
            "delivery_status": "delivered_with_warnings",
            "audit_findings": [
                {
                    "code": "inline_content_changed",
                    "category": "content_integrity",
                    "severity": "critical",
                    "certainty": "suspected",
                    "block_id": "block-17",
                    "location": "第1段 <script>",
                    "message": "行内内容存在差异",
                }
            ],
            "audits": {"saved_output_audit": "failed"},
            "manual_review_required": False,
            "diagnostic_codes": ["new_future_diagnostic"],
        },
    }
    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: _runtime_returning(payload))

    result = convert_document(ConversionRequest(source, tmp_path / "output.docx"))

    assert result.output_path.is_file()
    assert result.status == "review"
    report = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    assert report["public_summary"]["delivery_policy"] == "desktop"
    assert {item["type"] for item in report["risk_warnings"]} >= {
        "saved_output_audit", "inline_content_changed", "new_future_diagnostic"
    }
    markup = result.report_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in markup
    assert "block-17" in markup
    assert "suspected" in markup
    assert "<script>" not in markup


def test_failed_conversion_preserves_report_and_exposes_report_path(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# 失败\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"previous output")
    old_report = output.with_name("output_报告.json")
    old_report.write_text('{"old":true}', encoding="utf-8")
    diagnostic = {"public_summary": {"audit_findings": [{"code": "inline_content_changed"}]}}

    class FailingRuntime:
        version = VERSION
        template_sha256 = "a" * 64

        def convert(self, *args, **kwargs):
            raise NativeRuntimeError("运行时失败", report=diagnostic)

    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: FailingRuntime())
    with pytest.raises(ConversionError, match="报告已保存至") as caught:
        convert_document(ConversionRequest(source, output))

    assert output.read_bytes() == b"previous output"
    assert old_report.read_text(encoding="utf-8") == '{"old":true}'
    report_path = Path(caught.value.report_path)
    assert report_path.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8"))["public_summary"] == diagnostic["public_summary"]


def test_failed_conversion_without_runtime_report_writes_minimal_diagnostic(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# no report\n", encoding="utf-8")

    class FailingRuntime:
        version = VERSION
        template_sha256 = "a" * 64

        def convert(self, *args, **kwargs):
            raise NativeRuntimeError("native operational failure")

    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: FailingRuntime())
    with pytest.raises(ConversionError, match="native operational failure") as caught:
        convert_document(ConversionRequest(source, tmp_path / "output.docx"))

    failure_report = Path(caught.value.report_path)
    payload = json.loads(failure_report.read_text(encoding="utf-8"))
    assert payload["public_summary"]["audit_status"] == "incomplete"
    assert payload["desktop_failure"]["delivery_status"] == "not_delivered"


def test_unwritable_failure_report_does_not_mask_conversion_error(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# report denied\n", encoding="utf-8")

    class FailingRuntime:
        version = VERSION
        template_sha256 = "a" * 64

        def convert(self, *args, **kwargs):
            raise NativeRuntimeError("native operational failure")

    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: FailingRuntime())

    def deny_report_write(*args, **kwargs):
        raise PermissionError("denied")

    real_open = os.open

    def deny_only_failure_report(path, *args, **kwargs):
        if "_失败-" in Path(path).name:
            return deny_report_write(path, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("wxdoc_desktop.service.os.open", deny_only_failure_report)
    with pytest.raises(ConversionError, match="native operational failure") as caught:
        convert_document(ConversionRequest(source, tmp_path / "output.docx"))

    assert caught.value.report_path is None


def test_hardlink_destination_collision_is_rejected(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("# hardlink\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    os.link(source, output)

    with pytest.raises(ConversionError, match="指向同一文件"):
        convert_document(ConversionRequest(source, output))


def test_invalid_generated_docx_is_a_conversion_failure_and_keeps_previous_output(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# invalid DOCX\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    output.write_bytes(b"previous valid output")

    class InvalidOutputRuntime:
        version = VERSION
        template_sha256 = "a" * 64

        def convert(self, source_path, staged_output, staged_report, *, strict_normalize):
            staged_output.write_bytes(b"not a DOCX archive")
            staged_report.write_text(json.dumps(PASSING_REPORT), encoding="utf-8")
            return dict(PASSING_REPORT)

    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: InvalidOutputRuntime())
    with pytest.raises(ConversionError, match="有效 DOCX"):
        convert_document(ConversionRequest(source, output))

    assert output.read_bytes() == b"previous valid output"


def test_three_artifact_publish_failure_rolls_back_existing_files(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# 事务\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    html_report = tmp_path / "output_报告.html"
    json_report = html_report.with_suffix(".json")
    output.write_bytes(b"old docx")
    html_report.write_text("old html", encoding="utf-8")
    json_report.write_text("old json", encoding="utf-8")
    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: _runtime_returning(PASSING_REPORT))
    real_replace = os.replace
    failed = False

    def fail_html_once(src, dst):
        nonlocal failed
        if Path(dst) == html_report and not failed:
            failed = True
            raise OSError("simulated report publish failure")
        return real_replace(src, dst)

    monkeypatch.setattr("wxdoc_desktop.service.os.replace", fail_html_once)
    with pytest.raises(ConversionError, match="模拟|simulated"):
        convert_document(ConversionRequest(source, output))

    assert output.read_bytes() == b"old docx"
    assert html_report.read_text(encoding="utf-8") == "old html"
    assert json_report.read_text(encoding="utf-8") == "old json"


def test_failed_rollback_preserves_old_file_backup_and_reports_its_path(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# rollback backup\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    html_report = tmp_path / "output_报告.html"
    output.write_bytes(b"old docx bytes")
    html_report.write_text("old html", encoding="utf-8")
    monkeypatch.setattr("wxdoc_desktop.service.NativeRuntime.discover", lambda: _runtime_returning(PASSING_REPORT))
    real_replace = os.replace
    real_copy2 = shutil.copy2
    failed_html_commit = False

    def fail_publish_and_restore(src, dst):
        nonlocal failed_html_commit
        if Path(dst) == html_report and not failed_html_commit:
            failed_html_commit = True
            raise OSError("publish failed")
        if Path(dst) == output and ".backup." in Path(src).name:
            raise OSError("restore denied")
        return real_replace(src, dst)

    def fail_backup_copy(src, dst, *args, **kwargs):
        if Path(dst) == output and ".backup." in Path(src).name:
            raise OSError("copy restore denied")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr("wxdoc_desktop.service.os.replace", fail_publish_and_restore)
    monkeypatch.setattr("wxdoc_desktop.service.shutil.copy2", fail_backup_copy)
    with pytest.raises(ConversionError, match="旧文件备份保留在") as caught:
        convert_document(ConversionRequest(source, output))

    recovery_path_text = str(caught.value).split("旧文件备份保留在：", 1)[1].split("。", 1)[0]
    recovery_paths = recovery_path_text.split("，")
    assert any(Path(path).is_file() and Path(path).read_bytes() == b"old docx bytes" for path in recovery_paths)


def test_conversion_rejects_output_paths_that_collide_with_source(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("# 保护源文件\n", encoding="utf-8")

    with pytest.raises(ConversionError, match="路径不能重合"):
        convert_document(ConversionRequest(source, source))


def test_native_convert_passes_desktop_delivery_policy(tmp_path: Path, native_skill_runtime: Path):
    source = tmp_path / "source.md"
    source.write_text("# policy\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    report = tmp_path / "report.json"

    result = NativeRuntime.discover().convert(source, output, report, strict_normalize=True)

    assert result["public_summary"]["delivery_policy"] == "desktop"


def test_native_runtime_nonzero_exit_keeps_parsed_diagnostic_report(tmp_path: Path, native_skill_runtime: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# failed process\n", encoding="utf-8")
    output = tmp_path / "output.docx"
    report_path = tmp_path / "report.json"
    diagnostic = {"public_summary": {"audit_status": "incomplete"}}

    def fail_after_writing_report(command, **kwargs):
        report_path.write_text(json.dumps(diagnostic), encoding="utf-8")
        output.write_bytes(b"a process exit does not make this a successful delivery")
        return subprocess.CompletedProcess(command, 9, "", "runtime operational failure")

    monkeypatch.setattr("wxdoc_desktop.native_runtime.subprocess.run", fail_after_writing_report)
    with pytest.raises(NativeRuntimeError, match="runtime operational failure") as caught:
        NativeRuntime.discover().convert(source, output, report_path, strict_normalize=True)

    assert caught.value.report == diagnostic


def test_native_runtime_non_dictionary_report_has_safe_fallback(tmp_path: Path, native_skill_runtime: Path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("# invalid report\n", encoding="utf-8")

    def return_non_dictionary_report(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        report = Path(command[command.index("--report") + 1])
        Document().save(output)
        report.write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("wxdoc_desktop.native_runtime.subprocess.run", return_non_dictionary_report)
    with pytest.raises(NativeRuntimeError, match="报告结构无效") as caught:
        NativeRuntime.discover().convert(source, tmp_path / "output.docx", tmp_path / "report.json", strict_normalize=True)

    assert caught.value.report["public_summary"]["audit_status"] == "incomplete"
