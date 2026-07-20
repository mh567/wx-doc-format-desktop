from __future__ import annotations

import json
import os
import stat
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from wxdoc_desktop import __version__
from wxdoc_desktop.environment import BrowserOpenResult
from wxdoc_desktop.instance import (
    ActivationResult,
    InstanceLock,
    RuntimeDescriptor,
    activate,
    descriptor_path,
    launch,
    read_descriptor,
    remove_descriptor,
    write_descriptor,
)
from wxdoc_desktop.server import ApplicationState, Handler, LocalServer


@pytest.fixture
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "runtime"
    monkeypatch.setenv("MAGIC_FORMAT_RUNTIME_DIR", str(path))
    return path


def test_descriptor_is_atomic_private_and_token_guarded(runtime_dir: Path):
    descriptor = RuntimeDescriptor(os.getpid(), 42123, "a" * 32, __version__, time.time(), "/tmp/MagicFormat")
    write_descriptor(descriptor)

    assert read_descriptor() == descriptor
    if os.name != "nt":
        assert stat.S_IMODE(descriptor_path().stat().st_mode) == 0o600
    remove_descriptor("b" * 32)
    assert descriptor_path().is_file()
    remove_descriptor(descriptor.token)
    assert not descriptor_path().exists()


def test_corrupt_descriptor_is_ignored(runtime_dir: Path):
    descriptor_path().write_text("{broken", encoding="utf-8")
    assert read_descriptor() is None


def test_instance_lock_excludes_a_second_server(runtime_dir: Path):
    first = InstanceLock()
    second = InstanceLock()
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()


def _post(url: str, headers: dict[str, str]) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="POST", headers={**headers, "Content-Length": "0"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_activate_reuses_server_and_requires_instance_token(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    state = ApplicationState(managed=True, idle_timeout=60)
    server = LocalServer(("127.0.0.1", 0), Handler, state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    descriptor = RuntimeDescriptor(os.getpid(), server.server_port, state.instance_token, __version__, time.time(), "test")
    try:
        forbidden, payload = _post(descriptor.url + "api/activate", {"X-Magic-Instance": "invalid-token-value-000000000"})
        assert forbidden == 403
        assert payload["status"] == "forbidden"

        result = activate(descriptor)
        assert result.status == "activated"
        second = activate(descriptor)
        assert second.status == "activated"
        assert state.activation_count == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        state.close()


def test_launch_opens_interface_in_launcher(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    descriptor = RuntimeDescriptor(os.getpid(), 42123, "a" * 32, __version__, time.time(), "test")
    opened: list[str] = []
    monkeypatch.setattr("wxdoc_desktop.instance.read_descriptor", lambda: descriptor)
    monkeypatch.setattr("wxdoc_desktop.instance.activate", lambda _descriptor: ActivationResult("activated"))
    monkeypatch.setattr(
        "wxdoc_desktop.instance.open_browser",
        lambda url: opened.append(url) or BrowserOpenResult(True, "xdg-open"),
    )

    assert launch().status == "activated"
    assert opened == [descriptor.url]


def test_launch_reports_browser_failure_with_manual_url(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    descriptor = RuntimeDescriptor(os.getpid(), 42123, "a" * 32, __version__, time.time(), "test")
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr("wxdoc_desktop.instance.read_descriptor", lambda: descriptor)
    monkeypatch.setattr("wxdoc_desktop.instance.activate", lambda _descriptor: ActivationResult("activated"))
    monkeypatch.setattr(
        "wxdoc_desktop.instance.open_browser",
        lambda _url: BrowserOpenResult(False, message=f"请手动访问 {descriptor.url}"),
    )
    monkeypatch.setattr(
        "wxdoc_desktop.instance.show_browser_open_failure",
        lambda url, message: notices.append((url, message)) or True,
    )

    result = launch()
    assert result.status == "browser-failed"
    assert descriptor.url in result.message
    assert notices == [(descriptor.url, result.message)]


def test_launch_can_skip_browser_for_package_smoke(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    descriptor = RuntimeDescriptor(os.getpid(), 42123, "a" * 32, __version__, time.time(), "test")
    monkeypatch.setenv("MAGIC_FORMAT_NO_BROWSER", "1")
    monkeypatch.setattr("wxdoc_desktop.instance.read_descriptor", lambda: descriptor)
    monkeypatch.setattr("wxdoc_desktop.instance.activate", lambda _descriptor: ActivationResult("activated"))
    monkeypatch.setattr("wxdoc_desktop.instance.open_browser", lambda _url: pytest.fail("不应调用浏览器"))

    assert launch().status == "activated"


def test_heartbeat_blocks_idle_until_client_expires(monkeypatch: pytest.MonkeyPatch):
    clock = [100.0]
    monkeypatch.setattr("wxdoc_desktop.server.time.monotonic", lambda: clock[0])
    state = ApplicationState(managed=True, idle_timeout=0.02, client_timeout=0.08)
    try:
        state.touch("browser-client")
        clock[0] += 0.03
        assert state.idle() is False
        clock[0] += 0.07
        assert state.idle() is True
    finally:
        state.close()


def test_conversion_guard_blocks_idle_exit():
    state = ApplicationState(managed=True, idle_timeout=0)
    try:
        with state.conversion():
            assert state.busy() is True
            assert state.idle() is False
        assert state.busy() is False
        assert state.idle() is True
    finally:
        state.close()
