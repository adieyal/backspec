"""Staleness, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.modules.report.facade import ExtractionResult
from backspec.modules.staleness.domain import RequirementStatus, StatusReport, summary
from backspec.modules.staleness.ports import RepoPort
from backspec.modules.staleness.use_cases import check

__all__ = ["RepoPort", "RequirementStatus", "StalenessFacade", "StatusReport", "summary"]


class StalenessFacade:
    def __init__(self, repo: RepoPort):
        self._repo = repo

    def check(self, result: ExtractionResult) -> StatusReport:
        return check(result, self._repo)
