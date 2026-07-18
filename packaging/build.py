#!/usr/bin/env python3
from __future__ import annotations

import platform
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build" / ".pyinstaller"))

import PyInstaller.__main__


def main() -> None:
    system = platform.system()
    arguments = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name=WXDocFormat",
        f"--paths={ROOT / 'src'}",
        "--collect-data=docx",
        f"--add-data={ROOT / 'packaging' / 'docx-parts-placeholder'}:docx/parts",
        f"--add-data={ROOT / 'src' / 'wxdoc_desktop' / 'assets'}:wxdoc_desktop/assets",
        f"--add-data={ROOT / 'src' / 'wxdoc_desktop' / 'static'}:wxdoc_desktop/static",
        f"--add-data={ROOT / 'src' / 'wxdoc_core' / 'engine_version.txt'}:wxdoc_core",
        str(ROOT / "launcher.py"),
    ]
    if system in {"Darwin", "Windows"}:
        arguments.insert(3, "--windowed")
    if system == "Darwin":
        arguments.insert(4, "--target-architecture=arm64")
        arguments.extend(["--osx-bundle-identifier=cn.wxdoc.format.desktop"])
    PyInstaller.__main__.run(arguments)


if __name__ == "__main__":
    main()
