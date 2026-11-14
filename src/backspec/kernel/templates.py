"""The page templates, shipped with the package."""
from __future__ import annotations

from importlib import resources


def load(name: str) -> str:
    return resources.files("backspec.templates").joinpath(name).read_text(encoding="utf-8")


def load_bytes(name: str) -> bytes:
    return resources.files("backspec.templates").joinpath(name).read_bytes()
