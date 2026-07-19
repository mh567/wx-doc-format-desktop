from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from . import __version__


APP_DIRECTORY = "Magic Format"
DESCRIPTOR_NAME = "server.json"
LOCK_NAME = "server.lock"


def runtime_directory() -> Path:
    override = os.environ.get("MAGIC_FORMAT_RUNTIME_DIR")
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / APP_DIRECTORY / "runtime"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        root = base / APP_DIRECTORY / "runtime"
    else:
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        root = Path(xdg_runtime) / "magic-format" if xdg_runtime else Path.home() / ".local" / "state" / "magic-format" / "runtime"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


@dataclass(frozen=True)
class RuntimeDescriptor:
    pid: int
    port: int
    token: str
    version: str
    started_at: float
    executable: str

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


def descriptor_path() -> Path:
    return runtime_directory() / DESCRIPTOR_NAME


def read_descriptor() -> RuntimeDescriptor | None:
    try:
        payload = json.loads(descriptor_path().read_text(encoding="utf-8"))
        descriptor = RuntimeDescriptor(
            pid=int(payload["pid"]),
            port=int(payload["port"]),
            token=str(payload["token"]),
            version=str(payload["version"]),
            started_at=float(payload["started_at"]),
            executable=str(payload["executable"]),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if descriptor.pid <= 0 or not 1 <= descriptor.port <= 65535 or len(descriptor.token) < 24:
        return None
    return descriptor


def write_descriptor(descriptor: RuntimeDescriptor) -> None:
    path = descriptor_path()
    temporary = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    handle = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(asdict(descriptor), stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def remove_descriptor(expected_token: str | None = None) -> None:
    path = descriptor_path()
    if expected_token is not None:
        current = read_descriptor()
        if current is not None and current.token != expected_token:
            return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class InstanceLock:
    def __init__(self) -> None:
        self._stream: BinaryIO | None = None

    def acquire(self) -> bool:
        path = runtime_directory() / LOCK_NAME
        stream = path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            stream.close()
            return False
        self._stream = stream
        return True

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
            self._stream = None

    def __enter__(self) -> InstanceLock:
        if not self.acquire():
            raise RuntimeError("Magic Format 已有后台服务正在运行。")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@dataclass(frozen=True)
class ActivationResult:
    status: str
    message: str = ""


def activate(descriptor: RuntimeDescriptor, *, timeout: float = 1.5) -> ActivationResult:
    headers = {
        "X-Magic-Instance": descriptor.token,
        "X-Magic-Version": __version__,
        "Content-Length": "0",
    }
    if os.environ.get("MAGIC_FORMAT_NO_BROWSER") == "1":
        headers["X-Magic-No-Browser"] = "1"
    request = urllib.request.Request(
        descriptor.url + "api/activate",
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return ActivationResult(str(payload.get("status", "activated")), str(payload.get("message", "")))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            payload = {}
        return ActivationResult(str(payload.get("status", "unavailable")), str(payload.get("message", "")))
    except (OSError, ValueError, json.JSONDecodeError):
        return ActivationResult("unreachable")


def _helper_command() -> list[str]:
    if getattr(sys, "frozen", False):
        helper = Path(sys.executable).with_name("MagicFormatServer" + (".exe" if os.name == "nt" else ""))
        if helper.is_file():
            return [str(helper), "serve-helper"]
        return [sys.executable, "serve-helper"]
    return [sys.executable, "-m", "wxdoc_desktop", "serve-helper"]


def start_helper() -> None:
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )
    else:
        options["start_new_session"] = True
    subprocess.Popen(_helper_command(), **options)


def launch(*, wait_seconds: float = 20.0) -> ActivationResult:
    descriptor = read_descriptor()
    if descriptor is not None:
        result = activate(descriptor)
        if result.status in {"activated", "busy-version"}:
            return result
        if result.status == "restart-version":
            deadline = time.monotonic() + min(wait_seconds, 3.0)
            while time.monotonic() < deadline and read_descriptor() is not None:
                time.sleep(0.1)

    try:
        start_helper()
    except OSError as exc:
        return ActivationResult("failed", f"后台服务未能启动：{exc}")
    deadline = time.monotonic() + wait_seconds
    last_descriptor: RuntimeDescriptor | None = None
    while time.monotonic() < deadline:
        current = read_descriptor()
        if current is not None:
            last_descriptor = current
            result = activate(current)
            if result.status != "unreachable":
                return result
        time.sleep(0.1)
    if last_descriptor is not None:
        return ActivationResult("unreachable", "后台服务已启动，但本地界面暂时无法连接。")
    return ActivationResult("failed", "后台服务未能启动。")
