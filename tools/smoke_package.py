#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import time
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


def post(url: str, token: str) -> None:
    request = urllib.request.Request(
        url,
        method="POST",
        headers={"X-WX-Token": token, "Content-Length": "0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Shutdown returned HTTP {response.status}.")


def main() -> None:
    executable = executable_path()
    if not executable.is_file():
        raise SystemExit(f"Missing packaged executable: {executable}")

    with tempfile.TemporaryDirectory(prefix="magic-format-package-smoke-") as temporary:
        runtime = Path(temporary) / "runtime"
        environment = os.environ.copy()
        environment.update(
            {
                "MAGIC_FORMAT_RUNTIME_DIR": str(runtime),
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
