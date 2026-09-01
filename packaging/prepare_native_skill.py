#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


REPOSITORY = "mh567/wx-doc-format-skill"
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine == "arm64":
        return "macos-arm64"
    if system == "linux" and machine in {"arm64", "aarch64"}:
        return "kylin-v10-arm64"
    raise ValueError(f"当前平台没有已发布的编译运行时：{system}-{machine}")


def archive_name(version: str, target: str) -> str:
    suffix = ".zip" if target.startswith("windows-") else ".tar.gz"
    return f"wx-doc-format-skill-{version}-{target}{suffix}"


def _safe_relative(name: str) -> Path:
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"运行时归档包含不安全路径：{name}")
    return Path(*normalized.parts)


def _extract_archive(archive: Path, destination: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                relative = _safe_relative(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"运行时归档包含符号链接：{info.filename}")
                target = destination / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if mode & stat.S_IXUSR:
                    target.chmod(target.stat().st_mode | 0o755)
        return
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            relative = _safe_relative(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"运行时归档包含不允许的链接或设备：{member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError(f"无法读取运行时归档文件：{member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _expected_archive_sha(checksums: Path, name: str) -> str:
    matches = []
    for line in checksums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            matches.append(parts[0])
    if len(matches) != 1 or len(matches[0]) != 64:
        raise ValueError(f"SHA256SUMS.txt 中缺少唯一资产记录：{name}")
    return matches[0]


def _validate_manifest(root: Path, version: str, target: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_header = {
        "schema_version": 1,
        "product": "wx-doc-format-skill",
        "version": version,
        "platform": target,
    }
    observed = {key: manifest.get(key) for key in expected_header}
    if observed != expected_header:
        raise ValueError(f"原生运行时清单不匹配：{observed}")
    for item in manifest.get("files", []):
        relative = _safe_relative(str(item.get("path", "")))
        path = root / relative
        if not path.is_file():
            raise ValueError(f"原生运行时清单文件缺失：{relative.as_posix()}")
        if path.stat().st_size != item.get("size") or sha256_file(path) != item.get("sha256"):
            raise ValueError(f"原生运行时文件校验失败：{relative.as_posix()}")
    executable = root / "runtime" / ("wx-doc-format.exe" if target.startswith("windows-") else "wx-doc-format")
    if not executable.is_file() or not (root / "assets" / "wx_template.docx").is_file():
        raise ValueError("原生运行时缺少可执行文件或模板。")
    if (root / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise ValueError("原生运行时 VERSION 不匹配。")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sanitize_template_xml(name: str, payload: bytes) -> bytes:
    if name not in {"docProps/core.xml", "_rels/.rels", "word/_rels/document.xml.rels", "[Content_Types].xml"}:
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
            kind = relationship.attrib.get("Type", "")
            if kind.endswith(("/customXml", "/custom-properties")):
                root.remove(relationship)
                changed = True
    else:
        for override in list(root):
            part_name = override.attrib.get("PartName", "")
            if part_name.startswith("/customXml/") or part_name == "/docProps/custom.xml":
                root.remove(override)
                changed = True
    if not changed:
        return payload
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def sanitize_template(path: Path) -> None:
    temporary = path.with_suffix(".sanitized.docx")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename.startswith("customXml/") or item.filename == "docProps/custom.xml":
                continue
            target.writestr(item, _sanitize_template_xml(item.filename, source.read(item.filename)))
    os.replace(temporary, path)


def prepare_desktop_payload(
    root: Path,
    *,
    version: str,
    target: str,
    source_archive_sha256: str,
) -> None:
    retained = {"runtime", "assets", "VERSION"}
    for path in root.iterdir():
        if path.name in retained:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    assets = root / "assets"
    for path in assets.iterdir():
        if path.name == "wx_template.docx":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    provenance = {
        "schema_version": 1,
        "source_repository": REPOSITORY,
        "source_version": version,
        "platform": target,
        "source_archive_sha256": source_archive_sha256,
        "template_sha256": sha256_file(assets / "wx_template.docx"),
    }
    (root / "DESKTOP_RUNTIME.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_native_skill(
    archive: Path,
    checksums: Path,
    output_dir: Path,
    *,
    version: str,
    target: str,
) -> Path:
    expected = _expected_archive_sha(checksums, archive.name)
    actual = sha256_file(archive)
    if actual != expected:
        raise ValueError(f"原生运行时归档 SHA256 不匹配：{archive.name}")
    with tempfile.TemporaryDirectory(prefix="magic-format-native-") as temporary:
        staging = Path(temporary)
        _extract_archive(archive, staging)
        roots = [path for path in staging.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValueError("原生运行时归档必须只包含一个根目录。")
        root = roots[0]
        _validate_manifest(root, version, target)
        sanitize_template(root / "assets" / "wx_template.docx")
        prepare_desktop_payload(
            root,
            version=version,
            target=target,
            source_archive_sha256=actual,
        )
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.copytree(root, output_dir)
    return output_dir


def download_release_assets(version: str, target: str, destination: Path) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    name = archive_name(version, target)
    base = f"https://github.com/{REPOSITORY}/releases/download/v{version}"
    archive = destination / name
    checksums = destination / "SHA256SUMS.txt"
    for remote_name, local_path in ((name, archive), ("SHA256SUMS.txt", checksums)):
        request = urllib.request.Request(f"{base}/{remote_name}", headers={"User-Agent": "MagicFormat-Builder"})
        with urllib.request.urlopen(request, timeout=120) as response, local_path.open("wb") as output:
            shutil.copyfileobj(response, output)
    return archive, checksums


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a verified compiled wx-doc-format Skill runtime.")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", dest="target", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    archive = args.archive
    checksums = args.checksums
    if archive is None or checksums is None:
        cache = Path(os.environ.get("MAGIC_FORMAT_NATIVE_CACHE", Path(__file__).parents[1] / "build" / "native-downloads"))
        archive, checksums = download_release_assets(args.version, args.target, cache)
    prepared = prepare_native_skill(
        archive.resolve(),
        checksums.resolve(),
        args.output_dir.resolve(),
        version=args.version,
        target=args.target,
    )
    print(prepared)


if __name__ == "__main__":
    main()
