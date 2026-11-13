"""Requirements, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.kernel.llm import LLMPort
from reqx.modules.capabilities.facade import Capability
from reqx.modules.evidence.facade import Observation
from reqx.modules.requirements.domain import Evidence, Requirement
from reqx.modules.requirements.use_cases import Synthesis, assess, fingerprint, synthesise

__all__ = ["Evidence", "Requirement", "RequirementsFacade", "Synthesis"]


class RequirementsFacade:
    def __init__(self, llm: LLMPort, workers: int = 4):
        self._llm = llm
        self._workers = workers

    def synthesise(self, capabilities: list[Capability], by_capability: dict[str, list[Observation]]) -> Synthesis:
        return synthesise(capabilities, by_capability, self._llm, self._workers)

    def fingerprint(self) -> str:
        """Identifies the way requirements are written and judged; those made another way are not reused."""
        return fingerprint()

    def assess(self, requirements: list[Requirement], file_lines: dict[str, list[str]]) -> list[Requirement]:
        return assess(requirements, file_lines, self._llm, self._workers)
