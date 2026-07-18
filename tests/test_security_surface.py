from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_deterministic_core_has_no_llm_or_command_bridge():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "wxdoc_core").glob("*.py"))
    banned = ("anthropic", "openai", "LLM_COMMAND", "shell=True", "subprocess.run")
    assert all(token not in combined for token in banned)


def test_runtime_has_no_remote_update_client():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "wxdoc_desktop").glob("*.py"))
    banned = ("requests.get", "urllib.request", "httpx", "socket.create_connection", "subprocess.run")
    assert all(token not in combined for token in banned)
