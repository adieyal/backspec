"""Evidence, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.kernel.llm import LLMPort
from reqx.modules.discovery.facade import SourceFile
from reqx.modules.evidence.domain import Earlier, NothingFound, Observation, Rejected
from reqx.modules.evidence.use_cases import ObservationSet, fingerprint, observe

__all__ = ["Earlier", "EvidenceFacade", "NothingFound", "Observation", "ObservationSet", "Rejected"]


class EvidenceFacade:
    def __init__(self, llm: LLMPort, workers: int = 4):
        self._llm = llm
        self._workers = workers

    def observe(self, files: list[SourceFile], earlier: dict[str, Earlier] | None = None) -> ObservationSet:
        return observe(files, self._llm, self._workers, earlier=earlier)

    def fingerprint(self) -> str:
        """Identifies the way files are observed; earlier observations made another way are not reused."""
        return fingerprint()
