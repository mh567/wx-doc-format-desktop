from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .environment import (
    choose_result_directory,
    environment_report,
    open_browser,
    open_default_browser,
    open_local_directory,
    open_local_file,
    reveal_local_file,
)
from .instance import InstanceLock, RuntimeDescriptor, remove_descriptor, write_descriptor
from .resources import static_text
from .result_store import ResultDirectorySettings, ResultNameRegistry, source_fingerprint
from .service import MAX_INPUT_BYTES, ConversionError, ConversionRequest, ConversionResult, convert_document


class ApplicationState:
    def __init__(
        self,
        *,
        managed: bool = False,
        idle_timeout: float = 900.0,
        client_timeout: float = 45.0,
        result_settings: ResultDirectorySettings | None = None,
    ) -> None:
        self.csrf_token = secrets.token_urlsafe(32)
        self.instance_token = secrets.token_urlsafe(32)
        self.workspace = tempfile.TemporaryDirectory(prefix="wx-doc-format-")
        self.root = Path(self.workspace.name)
        self.result_settings = result_settings or ResultDirectorySettings()
        self.result_directory = self.result_settings.load()
        self.result_registry = ResultNameRegistry(self.result_directory)
        self.jobs: dict[str, ConversionResult] = {}
        self.lock = threading.Lock()
        self.managed = managed
        self.idle_timeout = idle_timeout
        self.client_timeout = client_timeout
        self.last_activity = time.monotonic()
        self.clients: dict[str, float] = {}
        self.busy_count = 0
        self.activation_count = 0

    def touch(self, client_id: str | None = None) -> None:
        now = time.monotonic()
        with self.lock:
            self.last_activity = now
            if client_id:
                self.clients[client_id] = now

    def active_clients(self) -> int:
        now = time.monotonic()
        with self.lock:
            expired = [client_id for client_id, seen in self.clients.items() if now - seen > self.client_timeout]
            for client_id in expired:
                self.clients.pop(client_id, None)
            return len(self.clients)

    def idle(self) -> bool:
        if self.active_clients():
            return False
        with self.lock:
            return self.busy_count == 0 and time.monotonic() - self.last_activity >= self.idle_timeout

    def can_restart_for_version(self) -> bool:
        if self.active_clients():
            return False
        with self.lock:
            return self.busy_count == 0

    def busy(self) -> bool:
        with self.lock:
            return self.busy_count > 0

    def set_result_directory(self, directory: Path) -> Path:
        with self.lock:
            self.result_directory = self.result_settings.save(directory)
            self.result_registry = ResultNameRegistry(self.result_directory)
            return self.result_directory

    @contextmanager
    def conversion(self):
        with self.lock:
            self.busy_count += 1
            self.last_activity = time.monotonic()
        try:
            yield
        finally:
            with self.lock:
                self.busy_count -= 1
                self.last_activity = time.monotonic()

    def close(self) -> None:
        self.workspace.cleanup()


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def __init__(self, address, handler, state: ApplicationState):
        super().__init__(address, handler)
        self.state = state


class Handler(BaseHTTPRequestHandler):
    server_version = "MagicFormat/1"

    @property
    def state(self) -> ApplicationState:
        return self.server.state

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, content: str, content_type: str) -> None:
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _valid_token(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-WX-Token", ""), self.state.csrf_token)

    def _valid_instance_token(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Magic-Instance", ""), self.state.instance_token)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self._text(static_text("index.html"), "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self._text(static_text("styles.css"), "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._text(static_text("app.js"), "text/javascript; charset=utf-8")
            return
        if path == "/api/health":
            self.state.touch()
            self._json(
                {
                    "ok": True,
                    "token": self.state.csrf_token,
                    "environment": environment_report(),
                    "instance": {"managed": self.state.managed, "activation_count": self.state.activation_count},
                    "result_directory": str(self.state.result_directory),
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/activate":
            if not self._valid_instance_token():
                self._json({"ok": False, "status": "forbidden"}, 403)
                return
            requested_version = self.headers.get("X-Magic-Version", "")
            if requested_version and requested_version != __version__:
                if self.state.can_restart_for_version():
                    self._json({"ok": False, "status": "restart-version", "message": "正在切换到新版本。"}, 426)
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self._json(
                        {"ok": False, "status": "busy-version", "message": "当前版本仍有打开的页面或转换任务，请完成后再启动新版本。"},
                        409,
                    )
                return
            with self.state.lock:
                self.state.activation_count += 1
            self.state.touch()
            self._json({"ok": True, "status": "activated", "version": __version__})
            return
        if not self._valid_token():
            self._json({"ok": False, "message": "本地会话已失效，请刷新页面。"}, 403)
            return
        if path == "/api/shutdown":
            if self.state.busy():
                self._json({"ok": False, "message": "文档仍在转换，请完成后再退出。"}, 409)
                return
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/heartbeat":
            client_id = self.headers.get("X-Magic-Client", "")
            if not 8 <= len(client_id) <= 128:
                self._json({"ok": False, "message": "页面标识无效。"}, 400)
                return
            self.state.touch(client_id)
            self._json({"ok": True})
            return
        if path == "/api/result-directory/open":
            action = open_local_directory(self.state.result_directory)
            if not action.success:
                self._json({"ok": False, "message": action.message or "无法打开结果目录。"}, 422)
                return
            self._json({"ok": True})
            return
        if path == "/api/result-directory/select":
            directory = choose_result_directory()
            if directory is None:
                self._json({"ok": True, "canceled": True})
                return
            try:
                selected = self.state.set_result_directory(directory)
            except OSError as exc:
                self._json({"ok": False, "message": str(exc)}, 422)
                return
            self._json({"ok": True, "result_directory": str(selected)})
            return
        if path.startswith("/api/jobs/"):
            parts = path.removeprefix("/api/jobs/").split("/")
            if len(parts) != 2 or parts[1] not in {"open-document", "reveal", "open-report"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            with self.state.lock:
                result = self.state.jobs.get(parts[0])
            if result is None:
                self._json({"ok": False, "message": "转换结果已失效，请重新转换。"}, 404)
                return
            if parts[1] == "open-document":
                action = open_local_file(result.output_path)
            elif parts[1] == "reveal":
                action = reveal_local_file(result.output_path)
            else:
                action = open_browser(result.report_path.as_uri())
            if not action.success:
                self._json({"ok": False, "message": action.message or "无法打开目标。"}, 422)
                return
            self._json({"ok": True})
            return
        if path != "/api/convert":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_INPUT_BYTES:
            self._json({"ok": False, "message": "文件为空或超过 100 MB 限制。"}, 400)
            return

        encoded_name = self.headers.get("X-WX-Filename", "")
        filename = Path(urllib.parse.unquote(encoded_name)).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".docx", ".md"}:
            self._json({"ok": False, "message": "仅支持 .docx 和 .md 文件。"}, 400)
            return

        job_token = secrets.token_urlsafe(18)
        job_dir = self.state.root / job_token
        job_dir.mkdir(mode=0o700)
        source = job_dir / ("source" + suffix)
        source.write_bytes(self.rfile.read(length))
        try:
            fingerprint = source_fingerprint(source)
            with self.state.lock:
                paths = self.state.result_registry.paths_for(filename, fingerprint)
        except OSError as exc:
            self._json({"ok": False, "message": f"无法准备结果目录：{exc}"}, 422)
            return
        with self.state.conversion():
            try:
                result = convert_document(ConversionRequest(source, paths.document, paths.report))
            except (ConversionError, OSError, ValueError) as exc:
                self._json({"ok": False, "message": str(exc)}, 422)
                return
            except Exception:
                self._json({"ok": False, "message": "转换过程遇到未预期问题，请导出环境报告。"}, 500)
                return

        with self.state.lock:
            self.state.jobs[job_token] = result
        self._json(
            {
                "ok": True,
                "status": result.status,
                "filename": filename,
                "warning_count": result.warning_count,
                "warnings": [item.get("type", "review") for item in result.warnings],
                "job": job_token,
            }
        )


def _idle_monitor(server: LocalServer) -> None:
    interval = min(5.0, max(0.1, server.state.idle_timeout / 4))
    while True:
        time.sleep(interval)
        if server.state.idle():
            server.shutdown()
            return


def run_server(*, open_browser: bool = True, managed: bool = False, idle_timeout: float = 900.0) -> int:
    instance_lock = InstanceLock() if managed else None
    if instance_lock is not None and not instance_lock.acquire():
        return 0
    state = ApplicationState(managed=managed, idle_timeout=idle_timeout)
    server = LocalServer(("127.0.0.1", 0), Handler, state)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Magic Format: {url}")
    if managed:
        write_descriptor(
            RuntimeDescriptor(
                pid=os.getpid(),
                port=server.server_port,
                token=state.instance_token,
                version=__version__,
                started_at=time.time(),
                executable=sys.executable,
            )
        )
        threading.Thread(target=_idle_monitor, args=(server,), daemon=True).start()
    if open_browser:
        threading.Timer(0.35, lambda: open_default_browser(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()
        if managed:
            remove_descriptor(state.instance_token)
        if instance_lock is not None:
            instance_lock.release()
    return 0
