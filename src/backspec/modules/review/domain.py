"""Review: a person's decisions about requirements, and ids that survive a re-run.

A requirement's id is a hash of its wording, so it changes whenever the wording does. What
stays put between runs is the code it rests on. Its anchors are the set of (path, quote with
whitespace squashed) over its evidence, and ids are carried from the previous run by how much
two requirements' anchors overlap. Capability ids are never used: they can be renamed.

Pure logic, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from pydantic import BaseModel, Field

from backspec.kernel.text import squash

MATCH_THRESHOLD = 0.5

Anchors = frozenset  # frozenset[tuple[str, str]]
Decision = Literal["confirm", "edit", "reject"]
Outcome = Literal["confirmed", "edited", "rejected", "needs_review"]


class ReviewFileError(ValueError):
    """The review file exists but cannot be read as review entries."""


class UnknownRequirement(LookupError):
    """A requirement id that is not in the result it was looked up in."""


class ReviewEntry(BaseModel):
    id: str
    decision: Decision
    statement: str | None = None              # for edit; absent keeps the statement
    conditions: list[str] | None = None       # for edit; absent keeps the conditions
    reviewer: str
    date: str
    note: str | None = None
    anchors: list[tuple[str, str]] = Field(default_factory=list)   # written by the tool


class ReviewSummary(BaseModel):
    carried: int = 0
    new: int = 0
    confirmed: int = 0
    edited: int = 0
    rejected_hidden: int = 0
    needs_review: int = 0
    stale_entries: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Known:
    """A requirement from before: its id, its anchors, and whether a person had looked at it."""
    id: str
    anchors: frozenset
    reviewed: bool


@dataclass(frozen=True)
class Carry:
    id: str                     # the id this requirement ends with, unique among the run
    carried: bool               # it took a previous id
    ambiguous_reviewed: bool    # the match was ambiguous and a candidate had been reviewed


def anchors_of(evidence: Iterable[tuple[str, str]]) -> frozenset:
    return frozenset((path, squash(quote)) for path, quote in evidence)


def overlap(a: frozenset, b: frozenset) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _single_best(scores: Sequence[float]) -> int | None:
    """The index of the one highest score, if it reaches the threshold and nothing ties it."""
    top = max(scores, default=0.0)
    if top < MATCH_THRESHOLD:
        return None
    winners = [index for index, score in enumerate(scores) if score == top]
    return winners[0] if len(winners) == 1 else None


def carry_ids(new: Sequence[tuple[str, frozenset]], previous: Sequence[Known]) -> list[Carry]:
    """For each new requirement (its own id, its anchors), the id it ends with.

    It takes a previous id only when that previous requirement is its single best match and it
    is that one's single best match too. Otherwise it keeps its own id, flagged when the match
    was ambiguous and any candidate had been reviewed. Ids in the result are unique."""
    scores = [[overlap(anchors, old.anchors) for old in previous] for _, anchors in new]
    chosen: list[int | None] = []
    flagged: list[bool] = []
    for row in scores:
        best = _single_best(row)
        mutual = best is not None and _single_best([other[best] for other in scores]) == len(chosen)
        chosen.append(best if mutual else None)
        candidates = [k for k, score in enumerate(row) if score >= MATCH_THRESHOLD]
        flagged.append(not mutual and any(previous[k].reviewed for k in candidates))
    used: set[str] = set()
    ids: list[str | None] = [None] * len(new)
    for index, match in enumerate(chosen):          # carried ids claim their place first
        if match is not None:
            ids[index] = _free(previous[match].id, used)
    for index, (own, _) in enumerate(new):
        if ids[index] is None:
            ids[index] = _free(own, used)
    return [Carry(id=ids[i], carried=chosen[i] is not None, ambiguous_reviewed=flagged[i])  # type: ignore[arg-type]
            for i in range(len(new))]


def _free(wanted: str, used: set[str]) -> str:
    candidate, number = wanted, 1
    while candidate in used:
        number += 1
        candidate = f"{wanted}-{number}"
    used.add(candidate)
    return candidate


def decide(entry: ReviewEntry, current: frozenset) -> Outcome:
    """What an entry does to a requirement. If the evidence is not what the person saw, the
    requirement stays as it is and needs another look, whatever they decided."""
    if frozenset(map(tuple, entry.anchors)) != current:
        return "needs_review"
    return {"confirm": "confirmed", "edit": "edited", "reject": "rejected"}[entry.decision]  # type: ignore[return-value]
