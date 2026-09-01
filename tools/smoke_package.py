#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).parents[1]


def executable_path() -> Path:
    if platform.system() == "Darwin":
        return ROOT / "dist" / "MagicFormat.app" / "Contents" / "MacOS" / "MagicFormat"
    if platform.system() == "Windows":
        return ROOT / "dist" / "MagicFormat" / "MagicFormat.exe"
    return ROOT / "dist" / "MagicFormat" / "MagicFormat"


def read_descriptor(path: Path, deadline: float) -> dict:
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.1)
    raise RuntimeError("Packaged Helper did not publish its runtime descriptor.")


def post(
    url: str,
    token: str,
    *,
    body: bytes = b"",
    filename: str | None = None,
    timeout: float = 5,
) -> dict:
    headers = {
        "X-WX-Token": token,
        "Content-Length": str(len(body)),
    }
    if filename is not None:
        headers["X-WX-Filename"] = urllib.parse.quote(filename)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Packaged request returned HTTP {response.status}.")
        payload = response.read()
    return json.loads(payload.decode("utf-8")) if payload else {}


def main() -> None:
    executable = executable_path()
    if not executable.is_file():
        raise SystemExit(f"Missing packaged executable: {executable}")
    if platform.system() == "Darwin":
        native_skill = executable.parent.parent / "Resources" / "native_skill"
    else:
        native_skill = executable.parent / "native_skill"
    native_executable = native_skill / "runtime" / ("wx-doc-format.exe" if platform.system() == "Windows" else "wx-doc-format")
    if not native_executable.is_file():
        raise RuntimeError(f"Packaged compiled Skill runtime is missing: {native_executable}")
    if list(native_skill.rglob("*.py")):
        raise RuntimeError("Packaged native Skill contains forbidden Python source files.")
    native_version = subprocess.run(
        [str(native_executable), "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()
    expected_version = (ROOT / "UPSTREAM_VERSION").read_text(encoding="utf-8").strip()
    if native_version != expected_version:
        raise RuntimeError(f"Packaged native Skill version mismatch: {native_version} != {expected_version}")

    with tempfile.TemporaryDirectory(prefix="magic-format-package-smoke-") as temporary:
        runtime = Path(temporary) / "runtime"
        environment = os.environ.copy()
        environment.update(
            {
                "MAGIC_FORMAT_RUNTIME_DIR": str(runtime),
                "MAGIC_FORMAT_SETTINGS_DIR": str(Path(temporary) / "settings"),
                "MAGIC_FORMAT_RESULTS_DIR": str(Path(temporary) / "results"),
                "MAGIC_FORMAT_NO_BROWSER": "1",
            }
        )
        descriptor_path = runtime / "server.json"
        descriptor: dict | None = None
        try:
            for _ in range(2):
                result = subprocess.run(
                    [str(executable)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=40,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr or f"Launcher exited with {result.returncode}.")
                current = read_descriptor(descriptor_path, time.monotonic() + 20)
                if descriptor is None:
                    descriptor = current
                elif current["pid"] != descriptor["pid"]:
                    raise RuntimeError("Repeated launch created a second Helper process.")

            base = f"http://127.0.0.1:{descriptor['port']}"
            with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            if health["instance"]["activation_count"] != 2:
                raise RuntimeError("Repeated launch did not activate the existing Helper twice.")
            if health["environment"].get("engine_mode") != "native-runtime":
                raise RuntimeError(f"Packaged Helper is not using the native runtime: {health['environment']}")
            converted = post(
                base + "/api/convert",
                health["token"],
                body=(
                    "# 打包冒烟\n\n"
                    "1. 第一项\n"
                    "2. 第二项\n\n"
                    "| 名称 | 状态 |\n"
                    "| --- | --- |\n"
                    "| Markdown | 正常 |\n"
                ).encode("utf-8"),
                filename="package-smoke.md",
                timeout=30,
            )
            if converted.get("ok") is not True:
                raise RuntimeError(f"Packaged Markdown conversion failed: {converted}")
            post(base + "/api/shutdown", health["token"])
            deadline = time.monotonic() + 10
            while descriptor_path.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            if descriptor_path.exists():
                raise RuntimeError("Helper did not clean its runtime descriptor after shutdown.")
            print(f"Package smoke test passed: {platform.system()} pid={descriptor['pid']}")
        finally:
            if descriptor_path.exists() and descriptor is not None:
                try:
                    base = f"http://127.0.0.1:{descriptor['port']}"
                    with urllib.request.urlopen(base + "/api/health", timeout=2) as response:
                        health = json.loads(response.read().decode("utf-8"))
                    post(base + "/api/shutdown", health["token"])
                except OSError:
                    pass


if __name__ == "__main__":
    main()
