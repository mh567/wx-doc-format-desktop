import hashlib
import json
import os
from pathlib import Path

import pytest
from docx import Document


VERSION = (Path(__file__).parents[1] / "VERSION").read_text(encoding="utf-8").strip()


@pytest.fixture(autouse=True)
def native_skill_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "native-skill"
    runtime = root / "runtime" / "wx-doc-format"
    template = root / "assets" / "wx_template.docx"
    runtime.parent.mkdir(parents=True)
    template.parent.mkdir(parents=True)
    document = Document()
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.save(template)
    report = {
        "native_marker": "called",
        "status": "completed",
        "public_summary": {
            "schema_version": "1.0",
            "status": "completed",
            "audits": {
                "audit": "not_run",
                "model_audit": "passed",
                "saved_output_audit": "passed",
                "appendix_preservation_audit": "passed",
            },
            "unexpected_styles_count": 0,
            "manual_review_required": False,
            "diagnostic_codes": [],
        },
    }
    runtime.write_text(
        f"#!{os.sys.executable}\n"
        "import argparse, json, shutil\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--version', action='store_true')\n"
        "parser.add_argument('--input')\n"
        "parser.add_argument('--output')\n"
        "parser.add_argument('--template')\n"
        "parser.add_argument('--report')\n"
        "parser.add_argument('--strict-normalize', action='store_true')\n"
        "parser.add_argument('--no-strict-normalize', action='store_true')\n"
        "args = parser.parse_args()\n"
        "if args.version:\n"
        f"    print('{VERSION}')\n"
        "else:\n"
        "    shutil.copyfile(args.template, args.output)\n"
        f"    payload = {json.dumps(report)!r}\n"
        "    open(args.report, 'w', encoding='utf-8').write(payload)\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    (root / "VERSION").write_text(f"{VERSION}\n", encoding="utf-8")
    (root / "DESKTOP_RUNTIME.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_repository": "mh567/wx-doc-format-skill",
                "source_version": VERSION,
                "platform": "test",
                "source_archive_sha256": "a" * 64,
                "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAGIC_FORMAT_SKILL_ROOT", str(root))
    return root
