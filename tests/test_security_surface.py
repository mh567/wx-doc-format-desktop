from pathlib import Path

import pytest

from wxdoc_desktop.native_runtime import NativeRuntime, NativeRuntimeError


ROOT = Path(__file__).parents[1]


def test_desktop_no_longer_vendors_skill_python_core():
    assert not list((ROOT / "src" / "wxdoc_core").glob("*.py"))
    assert not (ROOT / "tools" / "sync_upstream.py").exists()


def test_runtime_has_no_remote_update_client():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "wxdoc_desktop").glob("*.py"))
    banned = ("requests.get", "httpx", "socket.create_connection", "shell=True", "raw.githubusercontent.com")
    assert all(token not in combined for token in banned)
    adapter = (ROOT / "src" / "wxdoc_desktop" / "native_runtime.py").read_text(encoding="utf-8")
    assert "subprocess.run" in adapter
    assert '"--input"' in adapter
    instance = (ROOT / "src" / "wxdoc_desktop" / "instance.py").read_text(encoding="utf-8")
    assert "http://127.0.0.1:" in instance


def test_native_runtime_rejects_tampered_template(native_skill_runtime: Path):
    template = native_skill_runtime / "assets" / "wx_template.docx"
    template.write_bytes(template.read_bytes() + b"tampered")

    with pytest.raises(NativeRuntimeError, match="模板 SHA256"):
        NativeRuntime.discover()


def test_frontend_uses_magic_format_single_workspace():
    html = (ROOT / "src" / "wxdoc_desktop" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Magic Format" in html
    assert 'class="intro"' not in html
    assert html.count('class="converter"') == 1
    assert "支持 .docx 和 .md 文件" in html
