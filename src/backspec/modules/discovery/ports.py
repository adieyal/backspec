"""What discovery needs from the outside world."""
from __future__ import annotations

from typing import Protocol


class RepoPort(Protocol):
    def list_paths(self) -> list[str]:
        """Every candidate file under the root, relative, with forward slashes, sorted.
        Files that version control ignores are already left out."""
        ...

    def read(self, path: str) -> bytes:
        ...
