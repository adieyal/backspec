"""Capabilities, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.kernel.llm import LLMPort
from backspec.modules.capabilities.domain import PLUMBING, UNASSIGNED, CapabilitiesFileError, Capability
from backspec.modules.capabilities.ports import CapabilitiesStorePort
from backspec.modules.capabilities.use_cases import assign, load, orient
from backspec.modules.evidence.facade import Observation

__all__ = ["PLUMBING", "UNASSIGNED", "CapabilitiesFacade", "CapabilitiesFileError", "CapabilitiesStorePort",
           "Capability"]


class CapabilitiesFacade:
    def __init__(self, llm: LLMPort, workers: int = 4, store: CapabilitiesStorePort | None = None):
        self._llm = llm
        self._workers = workers
        self._store = store

    @property
    def location(self) -> str:
        return self._store.location if self._store else ""

    def load(self) -> list[Capability] | None:
        """The capabilities file's list (with `plumbing`), None if there is no file. Raises
        `CapabilitiesFileError` naming every problem in a file that breaks the rules."""
        return load(self._store) if self._store else None

    def exists(self) -> bool:
        """Whether there is a file at all, usable or not."""
        if self._store is None:
            return False
        try:
            return self._store.read() is not None
        except CapabilitiesFileError:
            return True

    def save(self, capabilities: list[Capability]) -> None:
        if self._store is None:
            raise ValueError("no capabilities file is configured")
        self._store.write(capabilities)

    def orient(self, observations: list[Observation]) -> list[Capability]:
        return orient(observations, self._llm)

    def assign(self, observations: list[Observation], capabilities: list[Capability],
               earlier: dict[str, str] | None = None) -> dict[str, str]:
        return assign(observations, capabilities, self._llm, self._workers, earlier)
