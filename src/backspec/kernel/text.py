"""Small text helpers shared by every module."""
from __future__ import annotations

import hashlib
import re


def squash(text: str) -> str:
    """Text with every run of whitespace as one space, for comparing quotes with code."""
    return re.sub(r"\s+", " ", text).strip()


def numbered(lines: list[str], first: int) -> list[str]:
    """Lines prefixed with their real line number. A model copies the number; it never counts."""
    return [f"{first + offset:5d}| {line}" for offset, line in enumerate(lines)]


def short_hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:8]


def sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()
