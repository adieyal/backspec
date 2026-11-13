"""Carry ids forward, apply a person's decisions, and record new ones."""
from __future__ import annotations

from dataclasses import dataclass

from reqx.modules.requirements.facade import Requirement
from reqx.modules.review.domain import (Decision, Known, ReviewEntry, ReviewSummary, UnknownRequirement,
                                        anchors_of, carry_ids, decide)
from reqx.modules.review.ports import ReviewStorePort


@dataclass
class ReviewOutcome:
    requirements: list[Requirement]
    summary: ReviewSummary


def requirement_anchors(requirement: Requirement) -> frozenset:
    return anchors_of((e.path, e.quote) for e in requirement.evidence)


def _known(previous: list[Requirement], entries: list[ReviewEntry]) -> list[Known]:
    """What the last run knew. A rejected requirement is not in the last result, but its entry
    holds its anchors, so it can still be recognised."""
    by_id = {e.id: e for e in entries}
    known = [Known(r.id, requirement_anchors(r), r.review != "unreviewed" or r.id in by_id) for r in previous]
    seen = {k.id for k in known}
    return known + [Known(e.id, frozenset(map(tuple, e.anchors)), True) for e in entries if e.id not in seen]


def apply_review(requirements: list[Requirement], previous: list[Requirement],
                 entries: list[ReviewEntry]) -> ReviewOutcome:
    carries = carry_ids([(r.id, requirement_anchors(r)) for r in requirements], _known(previous, entries))
    by_id = {e.id: e for e in entries}              # a later entry for the same id wins
    summary = ReviewSummary(carried=sum(c.carried for c in carries))
    summary.new = len(requirements) - summary.carried
    matched: set[str] = set()
    out: list[Requirement] = []
    for requirement, carry in zip(requirements, carries):
        requirement = requirement.model_copy(update={"id": carry.id})
        entry = by_id.get(carry.id)
        if entry is not None:
            matched.add(entry.id)
        if carry.ambiguous_reviewed:
            out.append(requirement.model_copy(update={"review": "needs_review"}))
        elif entry is None:
            out.append(requirement)
        else:
            outcome = decide(entry, requirement_anchors(requirement))
            if outcome == "rejected":
                summary.rejected_hidden += 1
            elif outcome == "needs_review":
                out.append(requirement.model_copy(update={"review": "needs_review"}))
            elif outcome == "confirmed":
                out.append(requirement.model_copy(update={"review": "confirmed"}))
            else:
                update: dict = {"review": "edited"}
                if entry.statement is not None:
                    update["statement"] = entry.statement
                if entry.conditions is not None:
                    update["conditions"] = list(entry.conditions)
                out.append(requirement.model_copy(update=update))
    summary.confirmed = sum(r.review == "confirmed" for r in out)
    summary.edited = sum(r.review == "edited" for r in out)
    summary.needs_review = sum(r.review == "needs_review" for r in out)
    summary.stale_entries = list(dict.fromkeys(e.id for e in entries if e.id not in matched))
    return ReviewOutcome(out, summary)


def record(store: ReviewStorePort, requirements: list[Requirement], requirement_id: str, decision: Decision, *,
           statement: str | None, conditions: list[str] | None, reviewer: str, date: str,
           note: str | None) -> ReviewEntry:
    """Write or replace the entry for a requirement, copying its anchors from `requirements`."""
    found = next((r for r in requirements if r.id == requirement_id), None)
    if found is None:
        raise UnknownRequirement(requirement_id)
    entry = ReviewEntry(id=requirement_id, decision=decision, statement=statement, conditions=conditions,
                        reviewer=reviewer, date=date, note=note,
                        anchors=sorted(requirement_anchors(found)))
    entries = store.load()
    if any(e.id == requirement_id for e in entries):
        entries = [entry if e.id == requirement_id else e for e in entries]
    else:
        entries.append(entry)
    store.save(entries)
    return entry
