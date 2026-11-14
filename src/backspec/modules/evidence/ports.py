"""What evidence needs from outside."""
from __future__ import annotations

from typing import Protocol

from backspec.modules.evidence.domain import Symbol


class SyntaxPort(Protocol):
    def symbols(self, path: str, text: str) -> list[Symbol] | None:
        """The definitions in a file, nested ones included, or None when the file cannot be parsed."""
        ...
