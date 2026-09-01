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

from prepare_native_skill import (
    current_platform,
    download_release_assets,
    prepare_native_skill,
)


def prepare_runtime() -> Path:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    target = current_platform()
    archive_value = os.environ.get("MAGIC_FORMAT_SKILL_ARCHIVE")
    checksums_value = os.environ.get("MAGIC_FORMAT_SKILL_CHECKSUMS")
    if bool(archive_value) != bool(checksums_value):
        raise RuntimeError("MAGIC_FORMAT_SKILL_ARCHIVE 和 MAGIC_FORMAT_SKILL_CHECKSUMS 必须同时设置。")
    if archive_value and checksums_value:
        archive = Path(archive_value).expanduser().resolve()
        checksums = Path(checksums_value).expanduser().resolve()
    else:
        archive, checksums = download_release_assets(version, target, ROOT / "build" / "native-downloads")
    return prepare_native_skill(
        archive,
        checksums,
        ROOT / "build" / "native-skill",
        version=version,
        target=target,
    )


def main() -> None:
    system = platform.system()
    native_skill = prepare_runtime()
    arguments = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name=MagicFormat",
        f"--paths={ROOT / 'src'}",
        f"--add-data={ROOT / 'src' / 'wxdoc_desktop' / 'static'}:wxdoc_desktop/static",
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
        embedded_skill = bundle / "Contents" / "Resources" / "native_skill"
        shutil.copytree(native_skill, embedded_skill)
        subprocess.run(["xattr", "-cr", str(embedded_skill)], check=True)
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
        shutil.copytree(native_skill, application_dir / "native_skill")
        suffix = ".exe" if system == "Windows" else ""
        shutil.copy2(application_dir / f"MagicFormat{suffix}", application_dir / f"MagicFormatServer{suffix}")


if __name__ == "__main__":
    main()
