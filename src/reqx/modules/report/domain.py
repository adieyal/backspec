"""The per-file ledger. Every file found ends in exactly one state, with a reason.

This is processing coverage: what was read. It says nothing about whether the requirements in
a file were found.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

State = Literal["excluded", "skipped", "extracted", "no_requirements", "candidates_rejected", "failed"]


class FileCoverage(BaseModel):
    path: str
    state: State
    reason: str = ""
    observations: int = 0
    rejected: int = 0
    cited_by: int = 0   # requirements that cite this file
    source_hash: str = ""   # the file as it was read, for files that were read


def file_state(observations: int, rejected: int, failed: str | None, nothing_reason: str | None) -> tuple[State, str]:
    """The state of a file that was sent to the observe stage."""
    if failed:
        return "failed", failed
    if observations:
        return "extracted", ""
    if rejected:
        return "candidates_rejected", f"{rejected} observation(s) failed the citation check"
    return "no_requirements", nothing_reason or "the model reported nothing for this file"
