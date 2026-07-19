from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document

from wxdoc_desktop.environment import environment_report
from wxdoc_desktop import __version__
from wxdoc_desktop.resources import template_sha256, verified_template
from wxdoc_desktop.service import ConversionError, validate_input


def test_vendored_core_contains_all_local_imports():
    import ast

    root = Path(__file__).parents[1] / "src" / "wxdoc_core"
    modules = {path.stem for path in root.glob("*.py")}
    missing: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                dependency = node.module.split(".", 1)[0]
                if dependency not in modules:
                    missing.add(dependency)
    assert missing == set()


ROOT = Path(__file__).parents[1]


def test_embedded_template_is_verified():
    with verified_template() as path:
        assert path.is_file()
        assert len(template_sha256()) == 64


def test_embedded_template_has_no_personal_or_custom_metadata():
    with verified_template() as path:
        properties = Document(path).core_properties
        assert properties.author in {None, ""}
        assert properties.last_modified_by in {None, ""}
        with ZipFile(path) as archive:
            names = archive.namelist()
        assert not any(name.startswith("customXml/") for name in names)
        assert "docProps/custom.xml" not in names


def test_environment_report_has_no_document_content():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    report = environment_report()
    assert report["template_verified"] is True
    assert report["engine_version"] == version
    assert report["application_version"] == version
    assert __version__ == version
    assert "documents" not in report


def test_environment_report_handles_headless_linux(monkeypatch):
    def unavailable_browser():
        raise __import__("webbrowser").Error("no runnable browser")

    monkeypatch.setattr("wxdoc_desktop.environment.webbrowser.get", unavailable_browser)
    report = environment_report()
    assert report["default_browser_available"] is False


def test_rejects_unsupported_input(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    with pytest.raises(ConversionError):
        validate_input(source)
