"""Staleness: whether the files a result rests on are still what was read.

A file is `unchanged`, `changed` or `missing`. A requirement is `current` when every file it
cites is unchanged, `source_missing` when any is missing, and otherwise `stale`. No model is
involved: it is a comparison of hashes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from reqx.kernel.text import sha256

FileState = Literal["unchanged", "changed", "missing"]
RequirementState = Literal["current", "stale", "source_missing"]


def hash_of(data: bytes) -> str | None:
    """The hash of a file as discovery takes it: of the decoded text. None when the file can no
    longer be read as text."""
    if b"\x00" in data[:8192]:
        return None
    try:
        return sha256(data.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def classify_file(recorded: str | None, current: str | None) -> FileState:
    if current is None:
        return "missing"
    return "unchanged" if recorded == current else "changed"


def classify_requirement(states: dict[str, FileState]) -> RequirementState:
    values = set(states.values())
    if "missing" in values:
        return "source_missing"
    return "stale" if "changed" in values else "current"


class RequirementStatus(BaseModel):
    id: str
    capability: str
    statement: str
    status: RequirementState
    changed: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class StatusReport(BaseModel):
    counts: dict[str, int]
    changed_files: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    requirements: list[RequirementStatus] = Field(default_factory=list)

    @property
    def all_current(self) -> bool:
        return not self.changed_files and not self.missing_files and \
            all(r.status == "current" for r in self.requirements)


def summary(report: StatusReport) -> str:
    """The short human form: a line of counts, then each requirement that is not current."""
    counts = report.counts
    lines = [f"{counts.get('current', 0)} current, {counts.get('stale', 0)} stale, "
             f"{counts.get('source_missing', 0)} source_missing"]
    for item in report.requirements:
        if item.status == "current":
            continue
        lines.append(f"{item.status}  {item.id}  {item.statement}")
        lines += [f"    changed  {path}" for path in item.changed]
        lines += [f"    missing  {path}" for path in item.missing]
    return "\n".join(lines)
