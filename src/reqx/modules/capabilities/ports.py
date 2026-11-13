"""What capabilities needs from the outside world: somewhere to keep the owner's capability list."""
from __future__ import annotations

from typing import Protocol

from reqx.modules.capabilities.domain import Capability


class CapabilitiesStorePort(Protocol):
    @property
    def location(self) -> str:
        """Where the list lives, for messages."""
        ...

    def read(self) -> object | None:
        """The parsed content of the stored list, or None when nothing is stored there.
        Content that cannot be parsed at all raises `CapabilitiesFileError`."""
        ...

    def write(self, capabilities: list[Capability]) -> None:
        ...
