"""Deterministic WX formatting engine."""

from importlib.resources import files


def engine_version() -> str:
    return files(__package__).joinpath("engine_version.txt").read_text(encoding="utf-8").strip()


__all__ = ["engine_version"]
