"""Triage, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.kernel.llm import LLMPort
from reqx.modules.discovery.facade import SourceFile
from reqx.modules.triage.domain import DEFAULT_AUDIT, EarlierVerdict, Verdict, clopper_pearson
from reqx.modules.triage.use_cases import TriageResult, fingerprint, triage

__all__ = ["DEFAULT_AUDIT", "EarlierVerdict", "TriageFacade", "TriageResult", "Verdict", "clopper_pearson"]


class TriageFacade:
    def __init__(self, llm: LLMPort, workers: int = 4):
        self._llm = llm
        self._workers = workers

    def assess(self, files: list[SourceFile], earlier: dict[str, EarlierVerdict] | None = None,
               audit: float = DEFAULT_AUDIT) -> TriageResult:
        """A verdict for each file that could be judged, and which skipped files the audit reads anyway."""
        return triage(files, self._llm, self._workers, earlier, audit)

    def fingerprint(self) -> str:
        """Identifies the way files are triaged; verdicts made another way are not reused."""
        return fingerprint()
