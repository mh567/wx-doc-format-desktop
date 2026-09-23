import hashlib
import json
import os
from pathlib import Path

import pytest
from docx import Document


VERSION = (Path(__file__).parents[1] / "VERSION").read_text(encoding="utf-8").strip()

CONVERT_REPORT = {
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

REVIEW_REPORT = {
    "input_file": "input.docx",
    "template_file": "wx_template.docx",
    "score": 87.3,
    "grade": "良",
    "passed": True,
    "dimension_scores": {
        "format_conformance": 84.0,
        "heading_hierarchy": 85.0,
        "list_structure": 100.0,
        "table_format": 92.0,
        "toc_structure": 90.0,
        "appendix_structure": 100.0,
        "caption": 93.0,
        "note_structure": 94.0,
        "numbering_page": 92.0,
    },
    "summary": {"total_issues": 2, "critical": 0, "high": 1, "medium": 1, "low": 0},
    "issues": [
        {
            "code": "format_value_mismatch",
            "level": "high",
            "title": "元素格式与模板不一致",
            "suggestion": "将正文样式统一为模板正文。",
            "location": "正文（12 段）",
        },
        {
            "code": "heading_style_mismatch",
            "level": "medium",
            "title": "标题样式与模板不一致",
            "suggestion": "标题改用模板标题样式。",
            "location": "标题（3 处）",
        },
    ],
    "compliant_items": ["附录结构符合模板要求"],
    "risk_warnings": ["存在 1 个高优先级问题，建议立即修复"],
    "ai_review": {"status": "not_requested"},
}


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
        "parser.add_argument('--review', action='store_true')\n"
        "parser.add_argument('--report-md')\n"
        "parser.add_argument('--report-html')\n"
        "args = parser.parse_args()\n"
        "if args.version:\n"
        f"    print('{VERSION}')\n"
        "elif args.review:\n"
        "    if args.output:\n"
        "        raise SystemExit('review does not accept --output')\n"
        f"    payload = {json.dumps(REVIEW_REPORT)!r}\n"
        "    open(args.report, 'w', encoding='utf-8').write(payload)\n"
        "    if args.report_md:\n"
        "        open(args.report_md, 'w', encoding='utf-8').write('# 文档格式审查报告\\n')\n"
        "    if args.report_html:\n"
        "        open(args.report_html, 'w', encoding='utf-8').write('<html lang=\"zh-CN\"></html>')\n"
        "else:\n"
        "    shutil.copyfile(args.template, args.output)\n"
        f"    payload = {json.dumps(CONVERT_REPORT)!r}\n"
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
