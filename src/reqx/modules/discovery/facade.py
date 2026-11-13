"""Discovery, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.modules.discovery.domain import Discovery, Left, SourceFile
from reqx.modules.discovery.ports import RepoPort
from reqx.modules.discovery.use_cases import discover

__all__ = ["Discovery", "DiscoveryFacade", "Left", "RepoPort", "SourceFile"]


class DiscoveryFacade:
    def __init__(self, repo: RepoPort):
        self._repo = repo

    def discover(self, include: list[str], exclude: list[str], default_excludes: bool = True) -> Discovery:
        return discover(self._repo, include, exclude, default_excludes)
