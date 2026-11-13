"""Evidence, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.kernel.llm import LLMPort
from reqx.modules.discovery.facade import SourceFile
from reqx.modules.evidence.domain import NothingFound, Observation, Rejected
from reqx.modules.evidence.use_cases import ObservationSet, observe

__all__ = ["EvidenceFacade", "NothingFound", "Observation", "ObservationSet", "Rejected"]


class EvidenceFacade:
    def __init__(self, llm: LLMPort, workers: int = 4):
        self._llm = llm
        self._workers = workers

    def observe(self, files: list[SourceFile]) -> ObservationSet:
        return observe(files, self._llm, self._workers)
