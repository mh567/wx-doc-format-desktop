from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_deterministic_core_has_no_llm_or_command_bridge():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "wxdoc_core").glob("*.py"))
    banned = ("anthropic", "openai", "LLM_COMMAND", "shell=True", "subprocess.run")
    assert all(token not in combined for token in banned)


def test_runtime_has_no_remote_update_client():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "wxdoc_desktop").glob("*.py"))
    banned = ("requests.get", "httpx", "socket.create_connection", "subprocess.run", "raw.githubusercontent.com")
    assert all(token not in combined for token in banned)
    instance = (ROOT / "src" / "wxdoc_desktop" / "instance.py").read_text(encoding="utf-8")
    assert "http://127.0.0.1:" in instance


def test_frontend_uses_magic_format_single_workspace():
    html = (ROOT / "src" / "wxdoc_desktop" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Magic Format" in html
    assert 'class="intro"' not in html
    assert html.count('class="converter"') == 1
    assert "支持 DOCX、MD 和 MARKDOWN" in html
