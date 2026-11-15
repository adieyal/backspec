"""What following calls needs from outside: a parser that finds definitions and calls."""
from __future__ import annotations

from typing import Protocol

from backspec.modules.evidence.facade import Symbol
from backspec.modules.reach.domain import Call


class CallsPort(Protocol):
    def symbols(self, path: str, text: str) -> list[Symbol] | None:
        """The definitions in a file, nested ones included, or None when it cannot be parsed."""
        ...

    def calls(self, path: str, text: str) -> list[Call] | None:
        """Every name called in a file, with its line, and attributes used without a call
        (`called` false), or None when it cannot be parsed."""
        ...

    def properties(self, path: str, text: str) -> set[int] | None:
        """The first lines (as `symbols` gives them) of definitions read as attributes rather
        than called: properties and their setters. Empty for a language without them."""
        ...
