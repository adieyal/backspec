"""Look at and empty the model-reply cache that `CachedLLM` writes.

A cache directory holds only files named `<stage>-<hex>.json`. Anything else in a directory
means it is not a reqx cache, and it is refused untouched: nothing is deleted outside such files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CACHE_FILE = re.compile(r"^(?P<stage>[A-Za-z][A-Za-z0-9_]*)-[0-9a-f]{16,64}\.json$")


class NotACache(ValueError):
    """The directory holds something other than cached replies."""


@dataclass
class CacheInfo:
    directory: Path
    per_stage: dict[str, int] = field(default_factory=dict)
    size: int = 0
    files: list[Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.per_stage.values())


def inspect(directory: Path) -> CacheInfo:
    """The cached replies in `directory`. A directory that does not exist is an empty cache.
    Raises NotACache for one that holds anything else."""
    info = CacheInfo(directory)
    if not directory.exists():
        return info
    if not directory.is_dir():
        raise NotACache(f"{directory} is not a directory")
    for entry in sorted(directory.iterdir()):
        match = CACHE_FILE.match(entry.name)
        if not match or entry.is_symlink() or not entry.is_file():
            raise NotACache(f"{directory} does not look like a reqx cache: {entry.name} is not a cached reply")
        stage = match.group("stage")
        info.per_stage[stage] = info.per_stage.get(stage, 0) + 1
        info.size += entry.stat().st_size
        info.files.append(entry)
    info.per_stage = dict(sorted(info.per_stage.items()))
    return info


def clear(directory: Path, delete: bool) -> CacheInfo:
    """What is cached, deleted when `delete` is true. Only the files `inspect` found are removed."""
    info = inspect(directory)
    if delete:
        for entry in info.files:
            entry.unlink()
    return info


def describe(info: CacheInfo) -> str:
    lines = [f"cache directory: {info.directory}"]
    lines += [f"  {stage}: {count}" for stage, count in info.per_stage.items()]
    lines.append(f"{info.total} cached replies, {info.size} bytes")
    return "\n".join(lines)
