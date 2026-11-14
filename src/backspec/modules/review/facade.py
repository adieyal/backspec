"""Review, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.modules.requirements.facade import Requirement
from backspec.modules.review.domain import (Decision, ReviewEntry, ReviewFileError, ReviewSummary,
                                        UnknownRequirement)
from backspec.modules.review.ports import ReviewStorePort
from backspec.modules.review.use_cases import ReviewOutcome, apply_review, record

__all__ = ["Decision", "ReviewEntry", "ReviewFacade", "ReviewFileError", "ReviewOutcome", "ReviewStorePort",
           "ReviewSummary", "UnknownRequirement"]


class ReviewFacade:
    def __init__(self, store: ReviewStorePort | None = None):
        self._store = store

    def applies(self, previous: list[Requirement] | None) -> bool:
        """The step runs only when there is a previous result or a review file to work from."""
        return previous is not None or self._store is not None

    def apply(self, requirements: list[Requirement], previous: list[Requirement] | None) -> ReviewOutcome:
        entries = self._store.load() if self._store else []
        return apply_review(requirements, previous or [], entries)

    def record(self, requirements: list[Requirement], requirement_id: str, decision: Decision, *,
               statement: str | None = None, conditions: list[str] | None = None, reviewer: str, date: str,
               note: str | None = None) -> ReviewEntry:
        if self._store is None:
            raise ValueError("no review file to write to")
        return record(self._store, requirements, requirement_id, decision, statement=statement,
                      conditions=conditions, reviewer=reviewer, date=date, note=note)
