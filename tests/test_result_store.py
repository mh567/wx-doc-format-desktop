from pathlib import Path

from wxdoc_desktop.result_store import (
    ResultDirectorySettings,
    ResultNameRegistry,
    default_result_directory,
    source_fingerprint,
)


def test_macos_default_results_stay_in_application_support(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("wxdoc_desktop.result_store.sys.platform", "darwin")
    monkeypatch.setattr("wxdoc_desktop.result_store.Path.home", lambda: tmp_path)

    assert default_result_directory() == tmp_path / "Library" / "Application Support" / "Magic Format" / "转换结果"


def test_result_directory_setting_is_persistent_and_customizable(tmp_path: Path):
    settings = ResultDirectorySettings(tmp_path / "settings" / "settings.json")
    selected = settings.save(tmp_path / "custom-results")

    assert settings.load() == selected
    assert selected.is_dir()


def test_same_source_overwrites_and_same_named_different_source_is_disambiguated(tmp_path: Path):
    directory = tmp_path / "results"
    directory.mkdir()
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    registry = ResultNameRegistry(directory)

    first_paths = registry.paths_for("方案.docx", source_fingerprint(first))
    repeated_paths = registry.paths_for("方案.docx", source_fingerprint(first))
    second_paths = registry.paths_for("方案.docx", source_fingerprint(second))

    assert first_paths.document.name == "方案_WX格式.docx"
    assert repeated_paths == first_paths
    assert second_paths.document.name.startswith("方案_WX格式_")
    assert second_paths.document.name.endswith(".docx")
    assert second_paths.report.stem.startswith(second_paths.document.stem)
