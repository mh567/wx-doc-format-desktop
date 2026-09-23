from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .environment import environment_report, write_environment_report
from .service import (
    ConversionError,
    ConversionRequest,
    ReviewRequest,
    convert_document,
    default_output_path,
    default_review_paths,
    review_document,
)


def _convert(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None
    results = []
    failed = False
    for input_path in args.inputs:
        try:
            output_path = default_output_path(input_path, output_dir)
            result = convert_document(ConversionRequest(input_path=input_path, output_path=output_path))
            results.append(result.to_dict())
            if not args.json:
                label = "已完成，建议复核" if result.status == "review" else "已完成"
                print(f"{label}: {result.output_path}")
        except (ConversionError, OSError, ValueError) as exc:
            failed = True
            results.append({"status": "failed", "input_path": str(input_path), "message": str(exc)})
            if not args.json:
                print(f"转换失败: {input_path}: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def _review(args: argparse.Namespace) -> int:
    report_dir = args.report_dir.expanduser().resolve() if args.report_dir else None
    results = []
    failed = False
    for input_path in args.inputs:
        try:
            report_json, report_markdown, report_html = default_review_paths(input_path, report_dir)
            result = review_document(
                ReviewRequest(
                    input_path=input_path,
                    report_path=report_json,
                    markdown_path=report_markdown,
                    html_path=report_html,
                )
            )
            results.append(result.to_dict())
            if not args.json:
                print(f"审查完成：{result.score}/100（{result.grade}）: {result.report_path}")
        except (ConversionError, OSError, ValueError) as exc:
            failed = True
            results.append({"status": "failed", "input_path": str(input_path), "message": str(exc)})
            if not args.json:
                print(f"审查失败: {input_path}: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="magic-format", description="Magic Format 文档格式转换")
    subparsers = parser.add_subparsers(dest="command")

    convert = subparsers.add_parser("convert", help="转换 DOCX 或 Markdown")
    convert.add_argument("inputs", nargs="+", type=Path)
    convert.add_argument("--output-dir", type=Path)
    convert.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    convert.set_defaults(handler=_convert)

    review = subparsers.add_parser("review", help="审查 DOCX 是否符合模板要求并打分")
    review.add_argument("inputs", nargs="+", type=Path)
    review.add_argument("--report-dir", type=Path)
    review.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    review.set_defaults(handler=_review)

    serve = subparsers.add_parser("serve", help="启动本地操作界面")
    serve.add_argument("--no-browser", action="store_true")
    serve.set_defaults(handler=lambda args: _serve(args))

    helper = subparsers.add_parser("serve-helper", help=argparse.SUPPRESS)
    helper.set_defaults(handler=_serve_helper)

    environment = subparsers.add_parser("env", help="导出不含文档内容的环境报告")
    environment.add_argument("--output", type=Path)
    environment.set_defaults(handler=_environment)
    return parser


def _serve(args: argparse.Namespace) -> int:
    from .server import run_server

    run_server(open_browser=not args.no_browser)
    return 0


def _serve_helper(args: argparse.Namespace) -> int:
    from .server import run_server

    return run_server(open_browser=False, managed=True)


def _launch(args: argparse.Namespace) -> int:
    from .instance import launch

    result = launch()
    if result.status == "busy-version":
        print(result.message or "当前版本正在处理文档，请完成后再启动新版本。", file=sys.stderr)
        return 2
    if result.status != "activated":
        print(result.message or "Magic Format 启动失败。", file=sys.stderr)
        return 1
    return 0


def _environment(args: argparse.Namespace) -> int:
    if args.output:
        print(write_environment_report(args.output))
    else:
        print(json.dumps(environment_report(), ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        args.handler = _launch
    raise SystemExit(args.handler(args))
