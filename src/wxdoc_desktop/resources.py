from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from importlib.resources import files

from .native_runtime import NativeRuntime


def template_sha256() -> str:
    return NativeRuntime.discover().template_sha256


@contextmanager
def verified_template() -> Iterator[Path]:
    yield NativeRuntime.discover().template


def static_text(name: str) -> str:
    return files("wxdoc_desktop").joinpath("static", name).read_text(encoding="utf-8")
