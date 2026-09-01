import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

from docx import Document


ROOT = Path(__file__).parents[1]


def test_prepare_native_skill_verifies_and_extracts_release_archive(tmp_path: Path):
    package_root = tmp_path / "fixture" / "wx-doc-format-skill-0.12.19-macos-arm64"
    executable = package_root / "runtime" / "wx-doc-format"
    template = package_root / "assets" / "wx_template.docx"
    executable.parent.mkdir(parents=True)
    template.parent.mkdir(parents=True)
    executable.write_text("native-runtime", encoding="utf-8")
    document = Document()
    document.core_properties.author = "private-author"
    document.core_properties.last_modified_by = "private-editor"
    document.save(template)
    (package_root / "VERSION").write_text("0.12.19\n", encoding="utf-8")
    files = []
    for path in (package_root / "VERSION", executable, template):
        files.append(
            {
                "path": path.relative_to(package_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (package_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "wx-doc-format-skill",
                "version": "0.12.19",
                "platform": "macos-arm64",
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "wx-doc-format-skill-0.12.19-macos-arm64.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(package_root, arcname=package_root.name)
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n",
        encoding="utf-8",
    )
    output = tmp_path / "prepared"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging" / "prepare_native_skill.py"),
            "--archive",
            str(archive),
            "--checksums",
            str(checksums),
            "--output-dir",
            str(output),
            "--version",
            "0.12.19",
            "--platform",
            "macos-arm64",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output / "runtime" / "wx-doc-format").read_text(encoding="utf-8") == "native-runtime"
    assert not list(output.rglob("*.py"))
    assert sorted(path.name for path in output.iterdir()) == [
        "DESKTOP_RUNTIME.json",
        "VERSION",
        "assets",
        "runtime",
    ]
    provenance = json.loads((output / "DESKTOP_RUNTIME.json").read_text(encoding="utf-8"))
    assert provenance["source_archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    properties = Document(output / "assets" / "wx_template.docx").core_properties
    assert properties.author in {None, ""}
    assert properties.last_modified_by in {None, ""}
    with ZipFile(output / "assets" / "wx_template.docx") as template_archive:
        assert not any(name.startswith("customXml/") for name in template_archive.namelist())
        assert "docProps/custom.xml" not in template_archive.namelist()
