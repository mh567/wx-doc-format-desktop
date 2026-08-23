from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from wxdoc_core import engine_version

from . import __version__
from .resources import template_sha256, verified_template


_BROWSER_ENVIRONMENT_LOCK = threading.Lock()


@contextmanager
def _system_browser_environment():
    if not sys.platform.startswith("linux"):
        yield
        return

    with _BROWSER_ENVIRONMENT_LOCK:
        bundled_library_path = os.environ.get("LD_LIBRARY_PATH")
        original_library_path = os.environ.get("LD_LIBRARY_PATH_ORIG")
        if original_library_path is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = original_library_path
        try:
            yield
        finally:
            if bundled_library_path is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = bundled_library_path


def open_default_browser(url: str) -> bool:
    return open_browser(url).success


@dataclass(frozen=True)
class BrowserOpenResult:
    success: bool
    method: str = ""
    message: str = ""


@dataclass(frozen=True)
class LocalActionResult:
    success: bool
    method: str = ""
    message: str = ""


def _browser_subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    if sys.platform.startswith("linux"):
        original_library_path = environment.get("LD_LIBRARY_PATH_ORIG")
        if original_library_path is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original_library_path
    return environment


def _launch_browser_command(command: list[str], environment: dict[str, str]) -> tuple[bool, str]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            env=environment,
        )
    except OSError as exc:
        return False, str(exc)
    try:
        return process.wait(timeout=0.75) == 0, f"退出码 {process.returncode}"
    except subprocess.TimeoutExpired:
        return True, ""


def _launch_local_command(command: list[str], *, capture_output: bool = False) -> tuple[bool, str]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            text=capture_output,
            close_fds=True,
            start_new_session=True,
            env=_browser_subprocess_environment(),
        )
    except OSError as exc:
        return False, str(exc)
    if not capture_output:
        return True, ""
    stdout, stderr = process.communicate()
    if process.returncode == 0:
        return True, stdout
    return False, stderr.strip() or f"退出码 {process.returncode}"


def choose_result_directory() -> Path | None:
    if sys.platform == "darwin":
        success, output = _launch_local_command(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择转换结果目录")'],
            capture_output=True,
        )
        return Path(output.strip()).resolve() if success and output.strip() else None
    if os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $dialog.SelectedPath }"
        )
        success, output = _launch_local_command(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True
        )
        return Path(output.strip()).resolve() if success and output.strip() else None
    environment = _browser_subprocess_environment()
    if shutil.which("zenity", path=environment.get("PATH")):
        success, output = _launch_local_command(
            ["zenity", "--file-selection", "--directory", "--title=选择转换结果目录"], capture_output=True
        )
        return Path(output.strip()).resolve() if success and output.strip() else None
    if shutil.which("kdialog", path=environment.get("PATH")):
        success, output = _launch_local_command(["kdialog", "--getexistingdirectory", str(Path.home())], capture_output=True)
        return Path(output.strip()).resolve() if success and output.strip() else None
    return None


def open_local_file(path: Path) -> LocalActionResult:
    target = path.expanduser().resolve()
    if not target.is_file():
        return LocalActionResult(False, message="目标文件不存在。")
    if sys.platform == "darwin":
        command, method = ["open", str(target)], "open"
    elif os.name == "nt":
        command, method = ["explorer", str(target)], "explorer"
    else:
        command, method = ["xdg-open", str(target)], "xdg-open"
    success, message = _launch_local_command(command)
    return LocalActionResult(success, method if success else "", message)


def reveal_local_file(path: Path) -> LocalActionResult:
    target = path.expanduser().resolve()
    if not target.is_file():
        return LocalActionResult(False, message="目标文件不存在。")
    if sys.platform == "darwin":
        command, method = ["open", "-R", str(target)], "open"
    elif os.name == "nt":
        command, method = ["explorer", "/select," + str(target)], "explorer"
    else:
        command, method = ["xdg-open", str(target.parent)], "xdg-open"
    success, message = _launch_local_command(command)
    return LocalActionResult(success, method if success else "", message)


def open_local_directory(path: Path) -> LocalActionResult:
    target = path.expanduser().resolve()
    if not target.is_dir():
        return LocalActionResult(False, message="结果目录不存在。")
    if sys.platform == "darwin":
        command, method = ["open", str(target)], "open"
    elif os.name == "nt":
        command, method = ["explorer", str(target)], "explorer"
    else:
        command, method = ["xdg-open", str(target)], "xdg-open"
    success, message = _launch_local_command(command)
    return LocalActionResult(success, method if success else "", message)


def open_browser(url: str) -> BrowserOpenResult:
    if sys.platform.startswith("linux"):
        environment = _browser_subprocess_environment()
        candidates = (("xdg-open", ["xdg-open", url]), ("gio", ["gio", "open", url]))
        failures: list[str] = []
        for method, command in candidates:
            if shutil.which(command[0], path=environment.get("PATH")) is None:
                continue
            success, detail = _launch_browser_command(command, environment)
            if success:
                return BrowserOpenResult(True, method)
            failures.append(f"{method}: {detail}")
    else:
        failures = []

    with _system_browser_environment():
        try:
            if webbrowser.open(url):
                return BrowserOpenResult(True, "webbrowser")
            failures.append("webbrowser: 未找到可用的默认浏览器")
        except (OSError, webbrowser.Error) as exc:
            failures.append(f"webbrowser: {exc}")
    detail = "；".join(failures) if failures else "未找到可用的默认浏览器"
    return BrowserOpenResult(False, message=f"无法自动打开浏览器。请手动访问 {url} 详情：{detail}")


def show_browser_open_failure(url: str, message: str) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    environment = _browser_subprocess_environment()
    text = message or f"无法自动打开浏览器。请手动访问 {url}"
    candidates = (
        ["zenity", "--error", "--title=Magic Format", f"--text={text}"],
        ["kdialog", "--title", "Magic Format", "--error", text],
        ["notify-send", "Magic Format", text],
    )
    for command in candidates:
        if shutil.which(command[0], path=environment.get("PATH")) is None:
            continue
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env=environment,
            )
            return True
        except OSError:
            continue
    return False


def _glibc_version() -> str | None:
    libc_name, libc_version = platform.libc_ver()
    if libc_name or libc_version:
        return " ".join(part for part in (libc_name, libc_version) if part)
    return None


def _browser_available() -> bool:
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def environment_report() -> dict:
    template_ok = False
    try:
        with verified_template():
            template_ok = True
    except Exception:
        template_ok = False
    return {
        "application_version": __version__,
        "engine_version": engine_version(),
        "template_sha256": template_sha256(),
        "template_verified": template_ok,
        "system": platform.system(),
        "system_release": platform.release(),
        "system_version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "glibc": _glibc_version(),
        "temporary_directory": tempfile.gettempdir(),
        "temporary_directory_writable": Path(tempfile.gettempdir()).is_dir(),
        "default_browser_available": _browser_available(),
        "executable": str(Path(sys.executable).resolve()),
    }


def write_environment_report(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(environment_report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
