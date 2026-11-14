"""The per-file ledger. Every file found ends in exactly one state, with a reason.

This is processing coverage: what was read. It says nothing about whether the requirements in
a file were found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

State = Literal["excluded", "skipped", "extracted", "no_requirements", "candidates_rejected", "failed",
               "triaged_out"]


class FileCoverage(BaseModel):
    path: str
    state: State
    reason: str = ""
    observations: int = 0
    rejected: int = 0
    lines: int = 0   # length of the file as it was read, for files that were read
    cited_by: int = 0   # requirements that cite this file
    source_hash: str = ""   # the file as it was read, for files that were read
    analysis: Literal["syntax", "text"] = "text"   # how a file that was read was analysed
    line_digest: str = ""   # a short digest per line, so a later run can tell which lines changed
    triage_role: str = ""        # the role triage gave the file; empty if it was not triaged
    triage_relevance: str = ""   # high, medium, low, none or unknown
    triage_skipped: bool = False   # triage judged it surely irrelevant, so it was not read unless audited
    triage_audited: bool = False   # skipped by triage but read anyway, as part of the audit
    found_by_audit: bool = False   # audited, and a verified observation came of it


def file_state(observations: int, rejected: int, failed: str | None, nothing_reason: str | None) -> tuple[State, str]:
    """The state of a file that was sent to the observe stage."""
    if failed:
        return "failed", failed
    if observations:
        return "extracted", ""
    if rejected:
        return "candidates_rejected", f"{rejected} observation(s) failed the citation check"
    return "no_requirements", nothing_reason or "the model reported nothing for this file"


@dataclass(frozen=True)
class RenderOutput:
    """What a renderer returns: one text document, or a set of files (relative path -> text)."""
    text: str | None = None
    files: dict[str, str] = field(default_factory=dict)

    @property
    def is_tree(self) -> bool:
        return self.text is None


TITLE_MAX = 60
_CLAUSE_END = re.compile(r"[,;:]\s|\s[-\u2013\u2014]\s|[.!?]\s")
_TRAILING = " \t\n.,;:!?-\u2013\u2014"
_MODAL = re.compile(r"\b(SHALL|MUST)\b")
_LOWER_MODAL = re.compile(r"\b(shall|must)\b", re.I)


def one_line(text: str) -> str:
    """The text on one line, runs of white space made single spaces."""
    return " ".join(text.split())


def requirement_title(statement: str) -> str:
    """A short title from a statement: its first clause, cut at a word to at most TITLE_MAX
    characters, with no trailing punctuation."""
    text = one_line(statement)
    match = _CLAUSE_END.search(text)
    clause = text[:match.start()] if match else text
    clause = clause.strip(_TRAILING) or text.strip(_TRAILING) or text
    if len(clause) > TITLE_MAX:
        cut = clause[:TITLE_MAX + 1]
        clause = cut[:cut.rfind(" ")] if " " in cut[1:] else cut[:TITLE_MAX]
        clause = clause.strip(_TRAILING) or clause
    return clause


def with_shall(statement: str) -> str:
    """The statement rewritten only as far as needed to contain SHALL or MUST. One that has
    them is unchanged; one with a lower-case shall or must has it upper-cased; any other is
    wrapped, never reworded."""
    text = one_line(statement)
    if _MODAL.search(text):
        return text
    if _LOWER_MODAL.search(text):
        return _LOWER_MODAL.sub(lambda m: m.group(1).upper(), text)
    return f"The system SHALL ensure: {text}"
WORTH_A_LOOK_LINES = 80
TRUNCATE_AT = 30


class CoverageReport(BaseModel):
    """A saved result's coverage, read for people: what happened to each file and what to look at."""
    counts: dict[str, int]
    files: dict[str, list[FileCoverage]]   # state -> files, every state but `excluded`
    unused_observations: dict[str, int]    # capability -> observations no requirement cites
    worth_a_look: list[FileCoverage]


def worth_looking_at(entry: FileCoverage) -> bool:
    """A file that was read, is long, and yielded nothing or was never cited."""
    return bool(entry.source_hash) and entry.lines > WORTH_A_LOOK_LINES and (
        entry.observations == 0 or entry.cited_by == 0)


def _clip(lines: list[str], show_all: bool) -> list[str]:
    if show_all or len(lines) <= TRUNCATE_AT:
        return lines
    return lines[:TRUNCATE_AT] + [f"  ... and {len(lines) - TRUNCATE_AT} more (--all shows every line)"]


def coverage_text(report: CoverageReport, show_all: bool = False) -> str:
    out = ["files per state: " + (", ".join(f"{n} {s}" for s, n in sorted(report.counts.items())) or "none")]
    for state, entries in report.files.items():
        out += ["", f"{state} ({len(entries)}):"]
        out += _clip([f"  {e.path}" + (f"  ({e.reason})" if e.reason else "") for e in entries], show_all)
    out += ["", "unused observations per capability:"]
    out += _clip([f"  {c}: {n}" for c, n in report.unused_observations.items()] or ["  none"], show_all)
    out += ["", "worth a look (read, over %d lines, no observation or cited by no requirement):" % WORTH_A_LOOK_LINES]
    out += _clip([f"  {e.path}  ({e.lines} lines, {e.observations} observations, cited by {e.cited_by})"
                  for e in report.worth_a_look] or ["  none"], show_all)
    return "\n".join(out)
