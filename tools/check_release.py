#!/usr/bin/env python3
"""Validate the version contract used by packages, tags, and reports."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    args = parser.parse_args()

    version = _read(ROOT / "VERSION")
    manifest = json.loads((ROOT / "VENDORED_MANIFEST.json").read_text(encoding="utf-8"))
    version_module: dict[str, object] = {}
    exec((ROOT / "src" / "wxdoc_desktop" / "_version.py").read_text(encoding="utf-8"), version_module)

    observed = {
        "VERSION": version,
        "UPSTREAM_VERSION": _read(ROOT / "UPSTREAM_VERSION"),
        "engine_version": _read(ROOT / "src" / "wxdoc_core" / "engine_version.txt"),
        "application_version": version_module["__version__"],
        "manifest_version": manifest["upstream_version"],
    }
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Invalid VERSION: {version!r}")
    mismatches = {name: value for name, value in observed.items() if value != version}
    if mismatches:
        raise SystemExit(f"Version mismatch: expected {version}; observed {mismatches}")
    if args.tag and args.tag != f"v{version}":
        raise SystemExit(f"Tag {args.tag!r} must equal v{version}")
    print(f"Version contract verified: {version}")


if __name__ == "__main__":
    main()
