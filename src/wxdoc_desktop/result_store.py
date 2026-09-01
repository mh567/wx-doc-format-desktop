from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


APP_DIRECTORY = "Magic Format"
SETTINGS_NAME = "settings.json"
INDEX_NAME = ".magic-format-results.json"


@dataclass(frozen=True)
class ResultPaths:
    document: Path
    report: Path
    details: Path


def _application_data_directory() -> Path:
    override = os.environ.get("MAGIC_FORMAT_SETTINGS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRECTORY
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_DIRECTORY
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "magic-format"


def default_result_directory() -> Path:
    override = os.environ.get("MAGIC_FORMAT_RESULTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return _application_data_directory() / "转换结果"
    return Path.home() / "Documents" / APP_DIRECTORY / "转换结果"


class ResultDirectorySettings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _application_data_directory() / SETTINGS_NAME

    def load(self) -> Path:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            configured = payload.get("result_directory")
            if isinstance(configured, str) and configured.strip():
                return self._ensure_directory(Path(configured))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return self._ensure_directory(default_result_directory())

    def save(self, directory: Path) -> Path:
        resolved = self._ensure_directory(directory)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"result_directory": str(resolved)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return resolved

    @staticmethod
    def _ensure_directory(directory: Path) -> Path:
        resolved = directory.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        if not resolved.is_dir():
            raise OSError("结果目录不可用。")
        return resolved


def source_fingerprint(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResultNameRegistry:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser().resolve()
        self.path = self.directory / INDEX_NAME

    def paths_for(self, source_name: str, fingerprint: str) -> ResultPaths:
        records = self._load_records()
        record = records.get(fingerprint)
        if record is None:
            stem = self._choose_stem(Path(source_name).stem, fingerprint, records)
            record = {"source_name": Path(source_name).name, "stem": stem}
            records[fingerprint] = record
            self._save_records(records)
        stem = str(record["stem"])
        return ResultPaths(
            document=self.directory / f"{stem}.docx",
            report=self.directory / f"{stem}_报告.html",
            details=self.directory / f"{stem}_报告.json",
        )

    def _choose_stem(self, source_stem: str, fingerprint: str, records: dict[str, dict]) -> str:
        base = f"{source_stem}_WX格式"
        occupied = {str(record.get("stem", "")) for record in records.values()}
        if base not in occupied and not self._paths_exist(base):
            return base
        short = fingerprint[:8]
        candidate = f"{base}_{short}"
        if candidate not in occupied and not self._paths_exist(candidate):
            return candidate
        return f"{base}_{fingerprint[:16]}"

    def _paths_exist(self, stem: str) -> bool:
        return any(
            (self.directory / name).exists()
            for name in (f"{stem}.docx", f"{stem}_报告.html", f"{stem}_报告.json")
        )

    def _load_records(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = payload.get("records", {})
            return records if isinstance(records, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_records(self, records: dict[str, dict]) -> None:
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
