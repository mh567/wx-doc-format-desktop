#!/usr/bin/env python3
from __future__ import annotations

import platform
import os
import plistlib
import shutil
import subprocess
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
        "--name=MagicFormat",
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
        arguments.extend(["--osx-bundle-identifier=cn.magic-format.desktop"])
    PyInstaller.__main__.run(arguments)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if system == "Darwin":
        bundle = ROOT / "dist" / "MagicFormat.app"
        executable_dir = bundle / "Contents" / "MacOS"
        shutil.copy2(executable_dir / "MagicFormat", executable_dir / "MagicFormatServer")
        plist_path = bundle / "Contents" / "Info.plist"
        with plist_path.open("rb") as stream:
            metadata = plistlib.load(stream)
        metadata.update(
            {
                "CFBundleDisplayName": "Magic Format",
                "CFBundleName": "Magic Format",
                "CFBundleShortVersionString": version,
                "CFBundleVersion": version,
            }
        )
        with plist_path.open("wb") as stream:
            plistlib.dump(metadata, stream)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
    else:
        application_dir = ROOT / "dist" / "MagicFormat"
        suffix = ".exe" if system == "Windows" else ""
        shutil.copy2(application_dir / f"MagicFormat{suffix}", application_dir / f"MagicFormatServer{suffix}")


if __name__ == "__main__":
    main()
