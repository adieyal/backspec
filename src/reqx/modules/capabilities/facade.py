"""Capabilities, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.kernel.llm import LLMPort
from reqx.modules.capabilities.domain import PLUMBING, UNASSIGNED, Capability
from reqx.modules.capabilities.use_cases import assign, orient
from reqx.modules.evidence.facade import Observation

__all__ = ["PLUMBING", "UNASSIGNED", "CapabilitiesFacade", "Capability"]


class CapabilitiesFacade:
    def __init__(self, llm: LLMPort, workers: int = 4):
        self._llm = llm
        self._workers = workers

    def orient(self, observations: list[Observation]) -> list[Capability]:
        return orient(observations, self._llm)

    def assign(self, observations: list[Observation], capabilities: list[Capability]) -> dict[str, str]:
        return assign(observations, capabilities, self._llm, self._workers)
