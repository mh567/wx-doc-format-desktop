#!/usr/bin/env python3
"""Vendor the deterministic WX engine from a tagged upstream checkout."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


MODULES = (
    "appendix_semantics",
    "audit",
    "caption_placement",
    "document_model",
    "docx_pipeline",
    "docx_render",
    "fallback_styles",
    "front_matter",
    "list_detector",
    "list_group_detection",
    "list_style_mapping",
    "md_pipeline",
    "model_normalization",
    "note_semantics",
    "reporting",
    "table_formatting",
    "table_semantics",
    "template_finalizer",
    "template_profile",
    "text_utils",
    "toc_contract",
    "toc_detector",
    "unordered_lists",
    "word_model_renderer",
)

CORE_PROPERTY_NAMES = {
    "title",
    "subject",
    "creator",
    "lastModifiedBy",
    "keywords",
    "description",
    "category",
    "contentStatus",
    "identifier",
    "language",
    "version",
    "created",
    "modified",
    "revision",
}

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_imports(text: str) -> str:
    names = "|".join(re.escape(name) for name in MODULES)
    return re.sub(
        rf"(?m)^(\s*)from ({names}) import ",
        r"\1from .\2 import ",
        text,
    )


def validate_module_closure(source: Path) -> None:
    available_modules = {path.stem for path in (source / "scripts").glob("*.py")}
    selected_modules = set(MODULES)
    missing: dict[str, list[str]] = {}
    for module in MODULES:
        source_path = source / "scripts" / f"{module}.py"
        if not source_path.is_file():
            raise SystemExit(f"Missing upstream module: {source_path}")
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        local_imports = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } & available_modules
        omitted = sorted(local_imports - selected_modules)
        if omitted:
            missing[source_path.name] = omitted
    if missing:
        details = "; ".join(
            f"{filename}: {', '.join(imports)}"
            for filename, imports in sorted(missing.items())
        )
        raise SystemExit(f"Upstream module closure is incomplete: {details}")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sanitize_xml(name: str, payload: bytes) -> bytes:
    if name not in {
        "docProps/core.xml",
        "_rels/.rels",
        "word/_rels/document.xml.rels",
        "[Content_Types].xml",
    }:
        return payload
    root = ET.fromstring(payload)
    changed = False
    if name == "docProps/core.xml":
        for element in list(root):
            if _local_name(element.tag) in CORE_PROPERTY_NAMES:
                root.remove(element)
                changed = True
    elif name in {"_rels/.rels", "word/_rels/document.xml.rels"}:
        for relationship in list(root):
            relationship_type = relationship.attrib.get("Type", "")
            if relationship_type.endswith(("/customXml", "/custom-properties")):
                root.remove(relationship)
                changed = True
    elif name == "[Content_Types].xml":
        for override in list(root):
            part_name = override.attrib.get("PartName", "")
            if part_name.startswith("/customXml/") or part_name == "/docProps/custom.xml":
                root.remove(override)
                changed = True
    if not changed:
        return payload
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def sanitize_template(source: Path, destination: Path) -> None:
    with ZipFile(source) as input_archive, ZipFile(destination, "w", compression=ZIP_DEFLATED) as output_archive:
        for item in input_archive.infolist():
            if item.filename.startswith("customXml/") or item.filename == "docProps/custom.xml":
                continue
            output_archive.writestr(item, _sanitize_xml(item.filename, input_archive.read(item.filename)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()

    source = args.source.resolve()
    destination = args.destination.resolve()
    core_dir = destination / "src" / "wxdoc_core"
    asset_dir = destination / "src" / "wxdoc_desktop" / "assets"
    core_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    validate_module_closure(source)
    manifest: dict[str, object] = {"modules": {}, "template": {}}
    for module in MODULES:
        source_path = source / "scripts" / f"{module}.py"
        if not source_path.is_file():
            raise SystemExit(f"Missing upstream module: {source_path}")
        target_path = core_dir / source_path.name
        target_path.write_text(
            package_imports(source_path.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        manifest["modules"][source_path.name] = {
            "upstream_sha256": digest(source_path),
            "vendored_sha256": digest(target_path),
        }

    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Invalid upstream VERSION: {version!r}")
    (destination / "VERSION").write_text(version + "\n", encoding="utf-8")
    (core_dir / "engine_version.txt").write_text(version + "\n", encoding="utf-8")
    (destination / "src" / "wxdoc_desktop" / "_version.py").write_text(
        '"""Generated from the upstream Skill VERSION file."""\n\n'
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )

    source_template = source / "assets" / "wx_template.docx"
    target_template = asset_dir / "wx_template.docx"
    sanitize_template(source_template, target_template)
    template_sha = digest(target_template)
    (asset_dir / "wx_template.sha256").write_text(template_sha + "\n", encoding="utf-8")
    manifest["template"] = {
        "path": "src/wxdoc_desktop/assets/wx_template.docx",
        "sha256": template_sha,
    }
    manifest["upstream_version"] = version

    (destination / "UPSTREAM_VERSION").write_text(version + "\n", encoding="utf-8")
    (destination / "VENDORED_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
