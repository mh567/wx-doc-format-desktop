from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from wxdoc_desktop import __version__
from wxdoc_desktop.instance import (
    InstanceLock,
    RuntimeDescriptor,
    activate,
    descriptor_path,
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
    opened: list[str] = []
    monkeypatch.setattr("wxdoc_desktop.server.webbrowser.open", lambda url: opened.append(url))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    descriptor = RuntimeDescriptor(os.getpid(), server.server_port, state.instance_token, __version__, time.time(), "test")
    try:
        forbidden, payload = _post(descriptor.url + "api/activate", {"X-Magic-Instance": "invalid-token-value-000000000"})
        assert forbidden == 403
        assert payload["status"] == "forbidden"

        result = activate(descriptor)
        assert result.status == "activated"
        deadline = time.monotonic() + 1
        while not opened and time.monotonic() < deadline:
            time.sleep(0.01)
        assert opened == [descriptor.url]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        state.close()


def test_heartbeat_blocks_idle_until_client_expires():
    state = ApplicationState(managed=True, idle_timeout=0.02, client_timeout=0.08)
    try:
        state.touch("browser-client")
        time.sleep(0.03)
        assert state.idle() is False
        time.sleep(0.07)
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


def test_repeated_launcher_reuses_helper_and_shutdown_cleans_descriptor(runtime_dir: Path):
    root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "MAGIC_FORMAT_RUNTIME_DIR": str(runtime_dir),
            "MAGIC_FORMAT_NO_BROWSER": "1",
            "PYTHONPATH": str(root / "src"),
        }
    )
    descriptor: RuntimeDescriptor | None = None
    try:
        first = subprocess.run(
            [sys.executable, "-m", "wxdoc_desktop"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=12,
        )
        assert first.returncode == 0, first.stderr
        descriptor = read_descriptor()
        assert descriptor is not None

        second = subprocess.run(
            [sys.executable, "-m", "wxdoc_desktop"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=12,
        )
        assert second.returncode == 0, second.stderr
        assert read_descriptor() is not None
        assert read_descriptor().pid == descriptor.pid

        with urllib.request.urlopen(descriptor.url + "api/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
            token = health["token"]
        assert health["instance"] == {"managed": True, "activation_count": 2}
        status, payload = _post(descriptor.url + "api/shutdown", {"X-WX-Token": token})
        assert status == 200
        assert payload["ok"] is True
        deadline = time.monotonic() + 3
        while descriptor_path().exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not descriptor_path().exists()
    finally:
        if descriptor_path().exists():
            current = read_descriptor()
            if current is not None:
                try:
                    with urllib.request.urlopen(current.url + "api/health", timeout=1) as response:
                        token = json.loads(response.read().decode("utf-8"))["token"]
                    _post(current.url + "api/shutdown", {"X-WX-Token": token})
                except OSError:
                    pass
