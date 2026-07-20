from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import threading
import webbrowser
from contextlib import contextmanager
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
    with _system_browser_environment():
        return webbrowser.open(url)


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
