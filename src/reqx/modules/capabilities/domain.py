"""Capabilities: feature areas as a user would name them, and which observations belong to each.

Grouping is by observation, not by file: one large file often feeds several capabilities.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

PLUMBING = "plumbing"
UNASSIGNED = "unassigned"


class Capability(BaseModel):
    id: str
    name: str
    summary: str = ""
    includes: list[str] = Field(default_factory=list)


class OrientReply(BaseModel):
    capabilities: list[Capability]


class AssignReply(BaseModel):
    assignments: dict[str, str]


def listing(observations: list[tuple[str, str, str]]) -> str:
    """Observations as `id | statement` lines under a `## path` header per file.
    Each item is (id, path, statement)."""
    out: list[str] = []
    current = None
    for obs_id, path, statement in observations:
        if path != current:
            out.append(f"## {path}")
            current = path
        out.append(f"{obs_id} | {statement}")
    return "\n".join(out)


def thin(items: list, limit: int) -> list:
    """At most `limit` items, taken evenly across the list, so that every file is represented."""
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(index * step)] for index in range(limit)]
