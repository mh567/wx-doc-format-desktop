#!/usr/bin/env python3
"""Validate the version contract used by packages, tags, and reports."""

from __future__ import annotations

import argparse
import re
import tomllib
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
    version_module: dict[str, object] = {}
    exec((ROOT / "src" / "wxdoc_desktop" / "_version.py").read_text(encoding="utf-8"), version_module)

    observed = {
        "VERSION": version,
        "UPSTREAM_VERSION": _read(ROOT / "UPSTREAM_VERSION"),
        "application_version": version_module["__version__"],
    }
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Invalid VERSION: {version!r}")
    mismatches = {name: value for name, value in observed.items() if value != version}
    if mismatches:
        raise SystemExit(f"Version mismatch: expected {version}; observed {mismatches}")
    if args.tag and args.tag != f"v{version}":
        raise SystemExit(f"Tag {args.tag!r} must equal v{version}")

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project.get("dependencies"):
        raise SystemExit("Desktop runtime dependencies must remain empty; the compiled Skill owns document dependencies")
    if list((ROOT / "src" / "wxdoc_core").glob("*.py")) or (ROOT / "tools" / "sync_upstream.py").exists():
        raise SystemExit("Vendored Skill Python sources are forbidden in the Desktop repository")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    unsupported = [name for name in ("windows-x86_64", "kylin-v10-x86_64") if name in workflow]
    if unsupported:
        raise SystemExit("Release workflow includes platforms without compiled Skill runtimes: " + ", ".join(unsupported))
    print(f"Version contract verified: {version}")


if __name__ == "__main__":
    main()
