"""Capabilities: feature areas as a user would name them, and which observations belong to each.

Grouping is by observation, not by file: one large file often feeds several capabilities.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

PLUMBING = "plumbing"
UNASSIGNED = "unassigned"
ID_PATTERN = re.compile(r"[a-z0-9_]+")


class CapabilitiesFileError(ValueError):
    """The capabilities file is unusable. The message names the file and every problem."""


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


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_capabilities(data: object, source: str) -> list[Capability]:
    """Turn what was read from a capabilities file into capabilities, or refuse it.

    Every problem is collected, so the owner can fix the file in one pass. `plumbing` is added
    when the file lacks it."""
    problems: list[str] = []
    if isinstance(data, dict) and isinstance(data.get("capabilities"), list):
        data = data["capabilities"]
    if not isinstance(data, list):
        raise CapabilitiesFileError(f"{source}: expected a list of capabilities (or a `capabilities:` key holding one)")
    found: list[Capability] = []
    seen: set[str] = set()
    for position, entry in enumerate(data, start=1):
        label = f"entry {position}"
        if not isinstance(entry, dict):
            problems.append(f"{label}: expected a mapping with id, name, summary and includes")
            continue
        cap_id = entry.get("id")
        if isinstance(cap_id, str) and cap_id:
            label = f"entry {position} ({cap_id})"
        if not isinstance(cap_id, str) or not ID_PATTERN.fullmatch(cap_id):
            problems.append(f"{label}: id must be lowercase letters, digits and underscores, got {cap_id!r}")
        elif cap_id in seen:
            problems.append(f"{label}: id {cap_id!r} is used more than once")
        else:
            seen.add(cap_id)
        if not _text(entry.get("name")):
            problems.append(f"{label}: name must not be empty")
        summary, includes = entry.get("summary", ""), entry.get("includes", [])
        if summary is None:
            summary = ""
        if not isinstance(summary, str):
            problems.append(f"{label}: summary must be text")
        if includes is None:
            includes = []
        if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
            problems.append(f"{label}: includes must be a list of text")
        if not problems:
            found.append(Capability(id=cap_id, name=entry["name"].strip(), summary=summary.strip(), includes=includes))
    if problems:
        raise CapabilitiesFileError(f"{source} is not usable:\n" + "\n".join(f"  - {p}" for p in problems))
    return with_plumbing(found)


def with_plumbing(capabilities: list[Capability]) -> list[Capability]:
    if any(c.id == PLUMBING for c in capabilities):
        return list(capabilities)
    return [*capabilities, Capability(id=PLUMBING, name="Internal mechanics",
                                      summary="Machinery no user or operator would notice.")]
