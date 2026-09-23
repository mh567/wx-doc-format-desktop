from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__


class NativeRuntimeError(RuntimeError):
    pass


PUBLIC_SUMMARY_SCHEMA = "1.0"

_REVIEW_FAILURE_PREFIXES = {
    "REVIEW_INPUT_UNSUPPORTED": "审查仅支持 .docx 文件。",
    "REVIEW_FAILED": "无法审查该文档：",
}


def _review_failure(detail: str) -> str:
    text = detail.strip()
    for prefix, message in _REVIEW_FAILURE_PREFIXES.items():
        if text.startswith(prefix):
            remainder = text[len(prefix):].lstrip(":： ").strip()
            return f"{message}{remainder}" if message.endswith("：") else message
    if "unrecognized arguments" in text or "invalid choice" in text:
        return "当前原生运行时版本不支持审查功能。"
    return f"原生审查失败：{text}"


@dataclass(frozen=True)
class NativeRuntime:
    root: Path
    executable: Path
    template: Path
    version: str
    template_sha256: str

    @classmethod
    def discover(cls) -> "NativeRuntime":
        configured = os.environ.get("MAGIC_FORMAT_SKILL_ROOT")
        if configured and not getattr(sys, "frozen", False):
            root = Path(configured).expanduser().resolve()
        else:
            if getattr(sys, "frozen", False):
                executable_dir = Path(sys.executable).resolve().parent
                if sys.platform == "darwin":
                    root = executable_dir.parent / "Resources" / "native_skill"
                else:
                    root = executable_dir / "native_skill"
            else:
                root = Path(__file__).resolve().parent / "native_skill"
        suffix = ".exe" if os.name == "nt" else ""
        executable = root / "runtime" / f"wx-doc-format{suffix}"
        template = root / "assets" / "wx_template.docx"
        version_file = root / "VERSION"
        provenance_file = root / "DESKTOP_RUNTIME.json"
        missing = [path for path in (executable, template, version_file, provenance_file) if not path.is_file()]
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise NativeRuntimeError(f"原生转换运行时文件不完整：{names}")
        version = version_file.read_text(encoding="utf-8").strip()
        if version != __version__:
            raise NativeRuntimeError(f"原生转换运行时版本不一致：应用 {__version__}，运行时 {version}")
        try:
            provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeRuntimeError("原生转换运行时来源记录无法读取。") from exc
        expected_provenance = {
            "schema_version": 1,
            "source_repository": "mh567/wx-doc-format-skill",
            "source_version": version,
        }
        observed = {key: provenance.get(key) for key in expected_provenance}
        if observed != expected_provenance:
            raise NativeRuntimeError(f"原生转换运行时来源记录不一致：{observed}")
        template_digest = hashlib.sha256(template.read_bytes()).hexdigest()
        if provenance.get("template_sha256") != template_digest:
            raise NativeRuntimeError("原生转换模板 SHA256 校验失败。")
        archive_digest = provenance.get("source_archive_sha256")
        if not isinstance(archive_digest, str) or len(archive_digest) != 64:
            raise NativeRuntimeError("原生转换运行时来源归档 SHA256 无效。")
        return cls(
            root=root,
            executable=executable,
            template=template,
            version=version,
            template_sha256=template_digest,
        )

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["WX_DOC_FORMAT_OFFLINE"] = "1"
        environment["WX_DOC_FORMAT_RELEASE"] = "1"
        if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
            original = environment.get("LD_LIBRARY_PATH_ORIG")
            if original is None:
                environment.pop("LD_LIBRARY_PATH", None)
            else:
                environment["LD_LIBRARY_PATH"] = original
        return environment

    def convert(
        self,
        source: Path,
        output: Path,
        report_path: Path,
        *,
        strict_normalize: bool,
    ) -> dict:
        command = [
            str(self.executable),
            "--input",
            str(source),
            "--output",
            str(output),
            "--template",
            str(self.template),
            "--report",
            str(report_path),
            "--strict-normalize" if strict_normalize else "--no-strict-normalize",
        ]
        try:
            completed = subprocess.run(
                command,
                env=self.environment(),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NativeRuntimeError(f"无法执行原生转换运行时：{exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
            raise NativeRuntimeError(f"原生转换失败：{detail}")
        if not output.is_file() or not report_path.is_file():
            raise NativeRuntimeError("原生转换未生成完整的文档和报告。")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeRuntimeError("无法读取原生转换报告。") from exc
        summary = report.get("public_summary")
        if not isinstance(summary, dict) or summary.get("schema_version") != PUBLIC_SUMMARY_SCHEMA:
            raise NativeRuntimeError("原生转换报告缺少可用的公开摘要。")
        return report

    def review(
        self,
        source: Path,
        *,
        report_path: Path,
        markdown_path: Path | None = None,
        html_path: Path | None = None,
    ) -> dict:
        command = [
            str(self.executable),
            "--review",
            "--input",
            str(source),
            "--template",
            str(self.template),
            "--report",
            str(report_path),
        ]
        if markdown_path is not None:
            command.extend(["--report-md", str(markdown_path)])
        if html_path is not None:
            command.extend(["--report-html", str(html_path)])
        try:
            completed = subprocess.run(
                command,
                env=self.environment(),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NativeRuntimeError(f"无法执行原生审查运行时：{exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
            raise NativeRuntimeError(_review_failure(detail))
        if not report_path.is_file():
            raise NativeRuntimeError("原生审查未生成报告。")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeRuntimeError("无法读取原生审查报告。") from exc
        if (
            not isinstance(report, dict)
            or not isinstance(report.get("score"), (int, float))
            or isinstance(report.get("score"), bool)
            or not isinstance(report.get("dimension_scores"), dict)
        ):
            raise NativeRuntimeError("原生审查报告缺少评分数据。")
        return report
