"""Evidence, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.kernel.llm import LLMPort
from backspec.modules.discovery.facade import SourceFile
from backspec.modules.evidence.domain import Earlier, NothingFound, Observation, Rejected, Symbol, line_digest
from backspec.modules.evidence.ports import SyntaxPort
from backspec.modules.evidence.use_cases import ObservationSet, fingerprint, observe

__all__ = ["Earlier", "EvidenceFacade", "NothingFound", "Observation", "ObservationSet", "Rejected", "Symbol", "SyntaxPort", "line_digest"]


class EvidenceFacade:
    def __init__(self, llm: LLMPort, workers: int = 4, syntax: SyntaxPort | None = None):
        self._llm = llm
        self._syntax = syntax
        self._workers = workers

    def observe(self, files: list[SourceFile], earlier: dict[str, Earlier] | None = None,
                parts: dict[str, list[tuple[int, int]]] | None = None) -> ObservationSet:
        """`parts`: files of which only these line ranges are read (path -> ranges)."""
        return observe(files, self._llm, self._workers, earlier=earlier, syntax=self._syntax, parts=parts)

    def fingerprint(self) -> str:
        """Identifies the way files are observed; earlier observations made another way are not reused."""
        return fingerprint(syntax=self._syntax is not None)
