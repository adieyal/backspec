"""Following calls into other files, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.modules.discovery.facade import SourceFile
from backspec.modules.reach.domain import (DEFAULT_DEPTH, GENERIC_NAMES, MAX_DEFINITIONS, AmbiguousName, Call,
                                           FollowedFile, FollowReport, ReachedSymbol, SkippedName)
from backspec.modules.reach.ports import CallsPort
from backspec.modules.reach.use_cases import plan

__all__ = ["AmbiguousName", "Call", "CallsPort", "DEFAULT_DEPTH", "FollowReport", "FollowedFile", "GENERIC_NAMES",
           "MAX_DEFINITIONS", "ReachFacade", "ReachedSymbol", "SkippedName"]


class ReachFacade:
    def __init__(self, syntax: CallsPort | None):
        self._syntax = syntax

    def plan(self, seeds: list[SourceFile], followed: list[SourceFile], patterns: list[str],
             depth: int = DEFAULT_DEPTH) -> FollowReport:
        """Which parts of `followed` the `seeds` reach by calls, up to `depth` calls away."""
        return plan(seeds, followed, self._syntax, patterns, depth)
