"""Requirements: complete behaviours, written from verified observations and then challenged.

Two rules hold by construction. A requirement cites observations by id and the program copies
their locations, so no citation in the output was written by a model at this step. And whether
the cited code supports the claim is a separate verdict from whether the citation exists.
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from reqx.kernel.text import numbered, short_hash

Support = Literal["direct", "partial", "insufficient", "conflicting", "not_assessed"]
CONTEXT_LINES = 10
MAX_EVIDENCE_SHOWN = 6
MAX_SPAN_SHOWN = 40


class Observed(Protocol):
    """What this module needs to know about a verified observation."""
    id: str
    kind: str
    path: str
    lines: tuple[int, int]
    statement: str
    quote: str


class Evidence(BaseModel):
    observation: str
    role: Literal["establishes", "context"]
    path: str
    lines: tuple[int, int]
    quote: str


class Requirement(BaseModel):
    id: str
    capability: str
    statement: str
    conditions: list[str] = Field(default_factory=list)
    level: Literal["user", "system", "technical"] = "user"
    scope: Literal["local", "cross_file"]
    support: Support = "not_assessed"
    support_note: str = ""
    review: Literal["unreviewed", "confirmed", "edited", "needs_review"] = "unreviewed"
    evidence: list[Evidence]


class CitedObservation(BaseModel):
    observation: str
    role: str = "establishes"


class RawRequirement(BaseModel):
    statement: str
    conditions: list[str] = Field(default_factory=list)
    level: str = "user"
    evidence: list[CitedObservation] = Field(default_factory=list)


class SynthReply(BaseModel):
    requirements: list[RawRequirement] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    id: str
    support: str
    note: str = ""


class AssessReply(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


def synth_input(observations: list[Observed]) -> str:
    out: list[str] = []
    for o in sorted(observations, key=lambda o: (o.path, o.lines[0])):
        out += [f"{o.id} | {o.kind} | {o.path}:{o.lines[0]}-{o.lines[1]}", f"  {o.statement}",
                f"  quote: {o.quote[:160]}", ""]
    return "\n".join(out)


def build(raw: RawRequirement, capability: str, known: dict[str, Observed]) -> Requirement | None:
    """A requirement with its evidence copied from the observations it names, or None when it
    names no real observation. Ids the model invented are dropped, not trusted."""
    evidence = []
    for cited in raw.evidence:
        obs = known.get(cited.observation)
        if obs is None:
            continue
        evidence.append(Evidence(observation=obs.id, role="context" if cited.role == "context" else "establishes",
                                 path=obs.path, lines=obs.lines, quote=obs.quote))
    if not evidence or not raw.statement.strip():
        return None
    level = raw.level if raw.level in ("user", "system", "technical") else "user"
    return Requirement(
        id="REQ-" + short_hash(capability, raw.statement), capability=capability,
        statement=raw.statement.strip(), conditions=raw.conditions, level=level,  # type: ignore[arg-type]
        scope="cross_file" if len({e.path for e in evidence}) > 1 else "local", evidence=evidence)


def assess_block(requirement: Requirement, file_lines: dict[str, list[str]]) -> str:
    """One requirement with the code it cites: the cited lines marked `>`, with context."""
    out = [f"##### {requirement.id}", f"STATEMENT: {requirement.statement}"]
    if requirement.conditions:
        out.append("CONDITIONS: " + " ; ".join(requirement.conditions))
    for number, evidence in enumerate(requirement.evidence[:MAX_EVIDENCE_SHOWN], 1):
        lines = file_lines[evidence.path]
        first, last = evidence.lines[0], min(evidence.lines[1], evidence.lines[0] + MAX_SPAN_SHOWN)
        start, end = max(1, first - CONTEXT_LINES), min(len(lines), last + CONTEXT_LINES)
        out.append(f"--- evidence {number}: {evidence.path} lines {first}-{last}")
        for text in numbered(lines[start - 1:end], start):
            line_number = int(text[:5])
            out.append((">" if first <= line_number <= last else " ") + text)
    out.append("")
    return "\n".join(out)


def settle(requirement: Requirement, verdict: Verdict | None) -> Requirement:
    """The requirement with its support verdict. Evidence that only shows something exists can
    never earn more than `insufficient`, whatever the model said."""
    if verdict is None or verdict.support not in ("direct", "partial", "insufficient", "conflicting"):
        return requirement
    support: Support = verdict.support  # type: ignore[assignment]
    note = verdict.note
    if all(e.role == "context" for e in requirement.evidence) and support in ("direct", "partial"):
        support, note = "insufficient", "Every cited observation only shows that something exists."
    return requirement.model_copy(update={"support": support, "support_note": note})
