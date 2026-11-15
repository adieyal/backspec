"""Requirements: complete behaviours, written from verified observations and then challenged.

Two rules hold by construction. A requirement cites observations by id and the program copies
their locations, so no citation in the output was written by a model at this step. And whether
the cited code supports the claim is a separate verdict from whether the citation exists.
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backspec.kernel.text import numbered, short_hash

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
    symbol: str | None = None   # copied from the observation


class Scenario(BaseModel):
    """One concrete case, in the form given / when / then, resting on observations that show it."""
    name: str
    given: str
    when: str
    then: str
    evidence: list[Evidence]


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
    merged_from: list[str] = Field(default_factory=list)   # statements merged into this one
    scenarios: list[Scenario] = Field(default_factory=list)


class CitedObservation(BaseModel):
    observation: str
    role: str = "establishes"


class RawScenario(BaseModel):
    name: str | None = None
    given: str | None = None
    when: str | None = None
    then: str | None = None
    evidence: list[CitedObservation] = Field(default_factory=list)


class RawRequirement(BaseModel):
    statement: str
    conditions: list[str] = Field(default_factory=list)
    level: str = "user"
    evidence: list[CitedObservation] = Field(default_factory=list)
    scenarios: list[RawScenario] = Field(default_factory=list)


class SynthReply(BaseModel):
    requirements: list[RawRequirement] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class MergeGroup(BaseModel):
    statement: str
    conditions: list[str] = Field(default_factory=list)
    level: str = "user"
    merge: list[str] = Field(default_factory=list)


class ConsolidateReply(BaseModel):
    groups: list[MergeGroup] = Field(default_factory=list)


class Verdict(BaseModel):
    id: str
    support: str
    note: str = ""


class AssessReply(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


def synth_input(observations: list[Observed]) -> str:
    out: list[str] = []
    for o in sorted(observations, key=lambda o: (o.path, o.lines[0])):
        out += [f"{o.id} | {o.kind} | {o.path}:{o.lines[0]}-{o.lines[1]}{_in(getattr(o, 'symbol', None))}",
                f"  {o.statement}", f"  quote: {o.quote[:160]}", ""]
    return "\n".join(out)


def _in(symbol: str | None) -> str:
    """Where a citation sits, as ` | in name`, so that two operations are not taken for one."""
    return f" | in {symbol}" if symbol else ""


def _places(evidence: list[Evidence]) -> str:
    """The distinct places a requirement's evidence comes from: the symbol, or the file without one."""
    return ", ".join(dict.fromkeys(f"{e.path}:{e.symbol}" if e.symbol else e.path for e in evidence))


def _copied(cited: list[CitedObservation], known: dict[str, Observed]) -> list[Evidence]:
    """Evidence copied from the observations named; an id the model invented is dropped."""
    evidence = []
    for c in cited:
        obs = known.get(c.observation)
        if obs is not None:
            evidence.append(Evidence(observation=obs.id, role="context" if c.role == "context" else "establishes",
                                     path=obs.path, lines=obs.lines, quote=obs.quote,
                                     symbol=getattr(obs, "symbol", None)))
    return evidence


def build_scenarios(raws: list[RawScenario], known: dict[str, Observed]) -> tuple[list[Scenario], int]:
    """The scenarios that are complete (name, given, when and then all non-empty) and cite at
    least one real observation, with evidence copied from it; and how many were dropped."""
    kept: list[Scenario] = []
    dropped = 0
    for raw in raws:
        parts = [(p or "").strip() for p in (raw.name, raw.given, raw.when, raw.then)]
        evidence = _copied(raw.evidence, known)
        if not all(parts) or not evidence:
            dropped += 1
            continue
        kept.append(Scenario(name=parts[0], given=parts[1], when=parts[2], then=parts[3], evidence=evidence))
    return _distinct_scenarios(kept), dropped


def _scenario_key(s: Scenario) -> tuple[str, ...]:
    return tuple(" ".join(t.lower().split()) for t in (s.name, s.given, s.when, s.then))


def _distinct_scenarios(scenarios: list[Scenario]) -> list[Scenario]:
    """The scenarios without repeats (same name and text), first one kept, order kept."""
    seen: dict[tuple[str, ...], Scenario] = {}
    for s in scenarios:
        seen.setdefault(_scenario_key(s), s)
    return list(seen.values())


def build_requirement(raw: RawRequirement, capability: str, known: dict[str, Observed]) -> tuple[Requirement | None, int]:
    """A requirement with its evidence copied from the observations it names, or None when it
    names no real observation; and the number of its scenarios that were dropped. Ids the model
    invented are dropped, not trusted."""
    evidence = _copied(raw.evidence, known)
    if not evidence or not raw.statement.strip():
        return None, 0
    scenarios, dropped = build_scenarios(raw.scenarios, known)
    level = raw.level if raw.level in ("user", "system", "technical") else "user"
    return Requirement(
        id="REQ-" + short_hash(capability, raw.statement), capability=capability,
        statement=raw.statement.strip(), conditions=raw.conditions, level=level,  # type: ignore[arg-type]
        scope="cross_file" if len({e.path for e in evidence}) > 1 else "local", evidence=evidence,
        scenarios=scenarios), dropped


def build(raw: RawRequirement, capability: str, known: dict[str, Observed]) -> Requirement | None:
    return build_requirement(raw, capability, known)[0]


def consolidate_input(requirements: list[Requirement]) -> str:
    out: list[str] = []
    for r in requirements:
        out += [f"{r.id} | {r.level}", f"  statement: {r.statement}"]
        if r.conditions:
            out.append("  conditions: " + " ; ".join(r.conditions))
        out += ["  observations: " + ", ".join(e.observation for e in r.evidence),
                "  from: " + _places(r.evidence), ""]
    return "\n".join(out)


def merge_requirements(requirements: list[Requirement], groups: list[MergeGroup]) -> list[Requirement]:
    """The requirements with each model-proposed group merged into one. The program builds the
    merged requirement: evidence is the union (by observation id, order kept) and scope is
    recomputed. An unmentioned requirement is kept as it is. An unknown id is ignored, a
    requirement named in two groups goes to the first, and a group left with fewer than two
    known requirements merges nothing."""
    by_id = {r.id: r for r in requirements}
    claimed: set[str] = set()
    merged_at: dict[str, Requirement] = {}     # id of the first merged requirement -> the merged one
    absorbed: set[str] = set()
    for group in groups:
        ids = [i for i in dict.fromkeys(group.merge) if i in by_id and i not in claimed]
        if len(ids) < 2 or not group.statement.strip():
            continue
        claimed.update(ids)
        sources = [by_id[i] for i in ids]
        evidence: dict[str, Evidence] = {}
        for source in sources:
            for e in source.evidence:
                evidence.setdefault(e.observation, e)
        statement = group.statement.strip()
        level = group.level if group.level in ("user", "system", "technical") else sources[0].level
        capability = sources[0].capability
        merged = Requirement(
            id="REQ-" + short_hash(capability, statement), capability=capability, statement=statement,
            conditions=group.conditions, level=level,  # type: ignore[arg-type]
            scope="cross_file" if len({e.path for e in evidence.values()}) > 1 else "local",
            evidence=list(evidence.values()), merged_from=[s.statement for s in sources],
            scenarios=_distinct_scenarios([sc for source in sources for sc in source.scenarios]))
        merged_at[ids[0]] = merged
        absorbed.update(ids[1:])
    out: list[Requirement] = []
    for r in requirements:
        if r.id in absorbed:
            continue
        out.append(merged_at.get(r.id, r))
    return _fold_same_id(out)


def _fold_same_id(requirements: list[Requirement]) -> list[Requirement]:
    """Two requirements with one id (a merged statement equal to another's) become one, with the
    evidence of both."""
    out: dict[str, Requirement] = {}
    for r in requirements:
        first = out.get(r.id)
        if first is None:
            out[r.id] = r
            continue
        evidence = {e.observation: e for e in first.evidence}
        for e in r.evidence:
            evidence.setdefault(e.observation, e)
        out[r.id] = first.model_copy(update={
            "evidence": list(evidence.values()),
            "scenarios": _distinct_scenarios([*first.scenarios, *r.scenarios]), "merged_from": first.merged_from + [r.statement],
            "scope": "cross_file" if len({e.path for e in evidence.values()}) > 1 else "local"})
    return list(out.values())


def assess_block(requirement: Requirement, file_lines: dict[str, list[str]]) -> str:
    """One requirement with the code it cites: the cited lines marked `>`, with context."""
    out = [f"##### {requirement.id}", f"STATEMENT: {requirement.statement}"]
    if requirement.conditions:
        out.append("CONDITIONS: " + " ; ".join(requirement.conditions))
    for number, evidence in enumerate(requirement.evidence[:MAX_EVIDENCE_SHOWN], 1):
        lines = file_lines[evidence.path]
        first, last = evidence.lines[0], min(evidence.lines[1], evidence.lines[0] + MAX_SPAN_SHOWN)
        start, end = max(1, first - CONTEXT_LINES), min(len(lines), last + CONTEXT_LINES)
        out.append(f"--- evidence {number}: {evidence.path} lines {first}-{last}{_in(evidence.symbol)}")
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
