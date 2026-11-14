"""What review needs from the outside world."""
from __future__ import annotations

from typing import Protocol

from backspec.modules.review.domain import ReviewEntry


class ReviewStorePort(Protocol):
    def load(self) -> list[ReviewEntry]:
        """Every entry, in file order. No file means no entries."""
        ...

    def save(self, entries: list[ReviewEntry]) -> None:
        ...
