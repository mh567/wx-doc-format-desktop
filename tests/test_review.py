from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from docx import Document

from wxdoc_desktop.native_runtime import NativeRuntime, NativeRuntimeError
from wxdoc_desktop.resources import static_text
from wxdoc_desktop.server import ApplicationState, Handler, LocalServer
from wxdoc_desktop.service import ConversionError, ReviewRequest, default_review_paths, review_document


def _docx(path: Path, text: str = "项目概述") -> Path:
    document = Document()
    document.add_heading(text, level=1)
    document.save(path)
    return path


def _post(url: str, headers: dict[str, str], body: bytes = b"") -> tuple[int, dict]:
    request = urllib.request.Request(url, data=body, method="POST", headers={**headers, "Content-Length": str(len(body))})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def test_native_runtime_review_runs_without_output(tmp_path: Path):
    source = _docx(tmp_path / "plan.docx")
    report_path = tmp_path / "review.json"
    markdown_path = tmp_path / "review.md"
    html_path = tmp_path / "review.html"

    report = NativeRuntime.discover().review(
        source,
        report_path=report_path,
        markdown_path=markdown_path,
        html_path=html_path,
    )

    assert report["score"] == 87.3
    assert report["grade"] == "良"
    assert set(report["dimension_scores"]) >= {"format_conformance", "numbering_page"}
    assert markdown_path.is_file()
    assert html_path.is_file()


def test_native_runtime_review_rejects_a_report_without_scores(tmp_path: Path, native_skill_runtime: Path):
    runtime_script = native_skill_runtime / "runtime" / "wx-doc-format"
    runtime_script.write_text(
        runtime_script.read_text(encoding="utf-8").replace('"score": 87.3', '"score": null'),
        encoding="utf-8",
    )
    runtime_script.chmod(0o755)
    source = _docx(tmp_path / "plan.docx")

    with pytest.raises(NativeRuntimeError, match="评分数据"):
        NativeRuntime.discover().review(source, report_path=tmp_path / "review.json")


def test_review_document_returns_score_and_writes_reports(tmp_path: Path):
    source = _docx(tmp_path / "plan.docx")

    result = review_document(ReviewRequest(input_path=source))

    assert result.score == 87.3
    assert result.grade == "良"
    assert result.passed is True
    assert result.issue_count == 2
    assert result.issues[0]["locations"] == ["第2章 系统设计 · 第1段", "第2章 系统设计 · 第3段"]
    assert result.issues[0]["count"] == 2
    assert result.summary["issue_types"] == 2
    assert result.dimension_scores["format_conformance"] == 84.0
    assert result.risk_warnings == ("存在 1 个高优先级问题，建议立即修复",)
    assert result.report_path.is_file()
    assert result.markdown_path.is_file()
    assert result.html_path.is_file()
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["input_file"] == "plan.docx"
    assert "wx-doc-format-native-" not in json.dumps(payload)


def test_review_document_defaults_name_reports_after_the_source(tmp_path: Path):
    source = _docx(tmp_path / "plan.docx")

    report_json, report_markdown, report_html = default_review_paths(source)

    assert report_json == tmp_path / "plan_审查报告.json"
    assert report_markdown == tmp_path / "plan_审查报告.md"
    assert report_html == tmp_path / "plan_审查报告.html"


def test_review_document_rejects_markdown_input(tmp_path: Path):
    source = tmp_path / "notes.md"
    source.write_text("# 标题\n", encoding="utf-8")

    with pytest.raises(ConversionError, match=r"审查仅支持 \.docx 文件"):
        review_document(ReviewRequest(input_path=source))


def test_review_endpoint_returns_score_and_downloads(tmp_path: Path):
    source = _docx(tmp_path / "plan.docx")
    state = ApplicationState(managed=True, idle_timeout=60)
    server = LocalServer(("127.0.0.1", 0), Handler, state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    headers = {"X-WX-Token": state.csrf_token, "X-WX-Filename": "plan.docx"}
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, payload = _post(base_url + "/api/review", headers, source.read_bytes())
        assert status == 200
        assert payload["score"] == 87.3
        assert payload["grade"] == "良"
        assert set(payload["downloads"]) == {"details", "markdown", "report"}
        assert state.root.resolve() in state.artifacts[(payload["job"], "details")].resolve().parents
        details_status, _, details_body = _get(base_url + payload["downloads"]["details"])
        assert details_status == 200
        assert json.loads(details_body.decode("utf-8"))["input_file"] == "plan.docx"
        html_status, _, html_body = _get(base_url + payload["downloads"]["report"])
        assert html_status == 200
        assert b"zh-CN" in html_body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        state.close()


def test_review_endpoint_rejects_non_docx_and_missing_token(tmp_path: Path):
    state = ApplicationState(managed=True, idle_timeout=60)
    server = LocalServer(("127.0.0.1", 0), Handler, state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, payload = _post(
            base_url + "/api/review",
            {"X-WX-Token": state.csrf_token, "X-WX-Filename": "notes.md"},
            "# 标题".encode("utf-8"),
        )
        assert status == 400
        assert "审查仅支持 .docx 文件" in payload["message"]

        status, payload = _post(
            base_url + "/api/review",
            {"X-WX-Token": "wrong", "X-WX-Filename": "plan.docx"},
            b"data",
        )
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        state.close()


def test_frontend_exposes_review_tab_and_score():
    html = static_text("index.html")
    app = static_text("app.js")
    styles = static_text("styles.css")

    assert html.count('class="converter"') == 1
    assert 'id="viewReview"' in html
    assert 'id="tabReview"' in html
    assert "/api/review" in app
    assert "score-ring" in styles
    assert "dimension_scores" in app
    assert "issue.locations" in app
    assert "issue-location-list" in styles
