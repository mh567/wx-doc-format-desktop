from __future__ import annotations

import json
import mimetypes
import secrets
import tempfile
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .environment import environment_report
from .resources import static_text
from .service import MAX_INPUT_BYTES, ConversionError, ConversionRequest, convert_document


class ApplicationState:
    def __init__(self) -> None:
        self.csrf_token = secrets.token_urlsafe(32)
        self.workspace = tempfile.TemporaryDirectory(prefix="wx-doc-format-")
        self.root = Path(self.workspace.name)
        self.artifacts: dict[tuple[str, str], Path] = {}
        self.lock = threading.Lock()

    def close(self) -> None:
        self.workspace.cleanup()


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def __init__(self, address, handler, state: ApplicationState):
        super().__init__(address, handler)
        self.state = state


class Handler(BaseHTTPRequestHandler):
    server_version = "WXDocFormat/0.1"

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
            self._json({"ok": True, "token": self.state.csrf_token, "environment": environment_report()})
            return
        if path.startswith("/download/"):
            parts = path.strip("/").split("/")
            if len(parts) != 3:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            artifact = self.state.artifacts.get((parts[1], parts[2]))
            if artifact is None or not artifact.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = artifact.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(artifact.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            quoted = urllib.parse.quote(artifact.name)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if not self._valid_token():
            self._json({"ok": False, "message": "本地会话已失效，请刷新页面。"}, 403)
            return
        if path == "/api/shutdown":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
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
        if suffix not in {".docx", ".md", ".markdown"}:
            self._json({"ok": False, "message": "仅支持 DOCX 和 Markdown 文件。"}, 400)
            return

        job_token = secrets.token_urlsafe(18)
        job_dir = self.state.root / job_token
        job_dir.mkdir(mode=0o700)
        source = job_dir / ("source" + suffix)
        source.write_bytes(self.rfile.read(length))
        output = job_dir / f"{Path(filename).stem}_WX格式.docx"
        report = job_dir / f"{Path(filename).stem}_WX格式_报告.html"
        try:
            result = convert_document(ConversionRequest(source, output, report))
        except (ConversionError, OSError, ValueError) as exc:
            self._json({"ok": False, "message": str(exc)}, 422)
            return
        except Exception:
            self._json({"ok": False, "message": "转换过程遇到未预期问题，请导出环境报告。"}, 500)
            return

        with self.state.lock:
            self.state.artifacts[(job_token, "document")] = result.output_path
            self.state.artifacts[(job_token, "report")] = result.report_path
            self.state.artifacts[(job_token, "details")] = result.json_report_path
        self._json(
            {
                "ok": True,
                "status": result.status,
                "filename": filename,
                "warning_count": result.warning_count,
                "warnings": [item.get("type", "review") for item in result.warnings],
                "downloads": {
                    "document": f"/download/{job_token}/document",
                    "report": f"/download/{job_token}/report",
                    "details": f"/download/{job_token}/details",
                },
            }
        )


def run_server(*, open_browser: bool = True) -> None:
    state = ApplicationState()
    server = LocalServer(("127.0.0.1", 0), Handler, state)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"WX 文档格式转换已启动: {url}")
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()
