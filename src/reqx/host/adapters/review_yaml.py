"""Review entries in a YAML file: `entries:` is a list, one mapping per entry."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from reqx.modules.review.facade import ReviewEntry, ReviewFileError


class YamlReviewStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[ReviewEntry]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            rows = data.get("entries") if isinstance(data, dict) else data
            if rows is None:
                return []
            if not isinstance(rows, list):
                raise ValueError("expected a list of entries")
            return [ReviewEntry.model_validate(row) for row in rows]
        except (yaml.YAMLError, ValueError, ValidationError) as error:
            raise ReviewFileError(f"{self.path}: {error}") from error

    def save(self, entries: list[ReviewEntry]) -> None:
        rows = [e.model_dump(mode="json", exclude_none=True) for e in entries]
        self.path.write_text(yaml.safe_dump({"entries": rows}, sort_keys=False, allow_unicode=True),
                             encoding="utf-8")
