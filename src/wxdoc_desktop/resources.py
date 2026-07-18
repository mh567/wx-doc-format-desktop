from __future__ import annotations

import hashlib
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager


def _asset(name: str):
    return files("wxdoc_desktop").joinpath("assets", name)


def template_sha256() -> str:
    return _asset("wx_template.sha256").read_text(encoding="utf-8").strip()


@contextmanager
def verified_template() -> Iterator[Path]:
    resource = _asset("wx_template.docx")
    with as_file(resource) as path:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = template_sha256()
        if actual != expected:
            raise RuntimeError("内置模板校验失败，程序文件可能不完整。")
        yield path


def static_text(name: str) -> str:
    return files("wxdoc_desktop").joinpath("static", name).read_text(encoding="utf-8")
