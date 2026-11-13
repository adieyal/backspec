"""Staleness, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.modules.report.facade import ExtractionResult
from reqx.modules.staleness.domain import RequirementStatus, StatusReport, summary
from reqx.modules.staleness.ports import RepoPort
from reqx.modules.staleness.use_cases import check

__all__ = ["RepoPort", "RequirementStatus", "StalenessFacade", "StatusReport", "summary"]


class StalenessFacade:
    def __init__(self, repo: RepoPort):
        self._repo = repo

    def check(self, result: ExtractionResult) -> StatusReport:
        return check(result, self._repo)
