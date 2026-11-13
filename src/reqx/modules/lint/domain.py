"""Lint: deterministic checks on a result. No model is involved.

A finding is an `error` when the result contradicts itself (a citation that points at nothing, a
duplicate id) and a `warning` when it is merely suspect (a vague or compound statement). The
checks read a result only through the small protocols below, so this module needs nothing of the
report that holds the result.
"""
from __future__ import annotations

from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, Field

from reqx.kernel.text import squash

Severity = Literal["error", "warning"]
MIN_STATEMENT = 25
PLUMBING, UNASSIGNED = "plumbing", "unassigned"


class Finding(BaseModel):
    code: str
    severity: Severity
    ids: list[str] = Field(default_factory=list)   # the requirement, capability or observation ids concerned
    message: str


class LintReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def failed(self, strict: bool = False) -> bool:
        return bool(self.errors or (strict and self.warnings))


class _Named(Protocol):
    id: str


class _Evidence(Protocol):
    observation: str
    role: str
    path: str
    lines: tuple[int, int]


class _Requirement(Protocol):
    id: str
    capability: str
    statement: str
    support: str
    evidence: Sequence[_Evidence]


class _Observation(Protocol):
    id: str
    path: str
    lines: tuple[int, int]


class _Run(Protocol):
    stopped_after: str | None


class Linted(Protocol):
    run: _Run
    capabilities: Sequence[_Named]
    requirements: Sequence[_Requirement]
    observations: Sequence[_Observation]


def normalise(statement: str) -> str:
    return squash(statement).lower()


def joins_obligations(statement: str) -> bool:
    return "; " in statement or " and also " in statement or statement.count(" and ") > 2


def check(result: Linted) -> list[Finding]:
    found: list[Finding] = []
    capability_ids = {c.id for c in result.capabilities}
    observations = {o.id: o for o in result.observations}

    def add(code: str, severity: Severity, ids: list[str], message: str) -> None:
        found.append(Finding(code=code, severity=severity, ids=ids, message=message))

    seen: dict[str, int] = {}
    for requirement in result.requirements:
        seen[requirement.id] = seen.get(requirement.id, 0) + 1
    for requirement_id, count in seen.items():
        if count > 1:
            add("duplicate_requirement_id", "error", [requirement_id], f"{count} requirements share the id {requirement_id}")

    for r in result.requirements:
        if r.capability not in capability_ids:
            add("unknown_capability", "error", [r.id, r.capability],
                f"{r.id} names the capability {r.capability!r}, which the result does not have")
        if not r.evidence:
            add("no_evidence", "error", [r.id], f"{r.id} has no evidence")
        for e in r.evidence:
            seen_observation = observations.get(e.observation)
            if seen_observation is None:
                add("unknown_observation", "error", [r.id, e.observation],
                    f"{r.id} cites {e.observation}, which is not among the observations")
            elif (e.path, tuple(e.lines)) != (seen_observation.path, tuple(seen_observation.lines)):
                add("evidence_mismatch", "error", [r.id, e.observation],
                    f"{r.id}: evidence says {e.path}:{e.lines[0]}-{e.lines[1]} but {e.observation} is "
                    f"{seen_observation.path}:{seen_observation.lines[0]}-{seen_observation.lines[1]}")

    if result.run.stopped_after is None:
        used = {r.capability for r in result.requirements}
        for capability in result.capabilities:
            if capability.id not in (PLUMBING, UNASSIGNED) and capability.id not in used:
                add("capability_without_requirements", "warning", [capability.id],
                    f"capability {capability.id} has no requirements")

    by_statement: dict[tuple[str, str], list[str]] = {}
    for r in result.requirements:
        by_statement.setdefault((r.capability, normalise(r.statement)), []).append(r.id)
    for (capability, _), ids in by_statement.items():
        if len(ids) > 1:
            add("duplicate_statement", "warning", ids, f"{', '.join(ids)} say the same thing in {capability}")

    for r in result.requirements:
        if len(r.statement.strip()) < MIN_STATEMENT:
            add("short_statement", "warning", [r.id], f"{r.id}: the statement is shorter than {MIN_STATEMENT} characters")
        if joins_obligations(r.statement):
            add("compound_statement", "warning", [r.id], f"{r.id}: the statement probably joins several obligations; consider splitting it")
        if r.evidence and all(e.role == "context" for e in r.evidence):
            add("context_only_evidence", "warning", [r.id], f"{r.id}: all of its evidence is context, none establishes it")
        if r.support in ("insufficient", "conflicting"):
            add("weak_support", "warning", [r.id], f"{r.id}: the support check found it {r.support}")
    return found


def summary(report: LintReport) -> str:
    """Findings grouped by severity, then a one-line count."""
    lines: list[str] = []
    for title, items in (("errors", report.errors), ("warnings", report.warnings)):
        if items:
            lines.append(f"{title}:")
            lines += [f"  {f.code}  {f.message}" for f in items]
    lines.append(f"{len(report.errors)} errors, {len(report.warnings)} warnings")
    return "\n".join(lines)
