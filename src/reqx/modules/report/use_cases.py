"""Assemble the coverage ledger and render a result for people to read."""
from __future__ import annotations

import collections

from reqx.modules.discovery.facade import Discovery
from reqx.modules.evidence.facade import Earlier, ObservationSet, line_digest
from reqx.modules.report.domain import FileCoverage, file_state
from reqx.modules.report.dto import Coverage, ExtractionResult
from reqx.modules.requirements.facade import Requirement


def build_coverage(discovery: Discovery, observed: ObservationSet, requirements: list[Requirement],
                   assignments: dict[str, str]) -> Coverage:
    per_file = collections.Counter(o.path for o in observed.observations)
    rejected = collections.Counter(r.path for r in observed.rejected)
    nothing = {entry.path: entry.reason for entry in observed.nothing}
    cited = collections.Counter(path for r in requirements for path in {e.path for e in r.evidence})
    files = [FileCoverage(path=left.path, state=left.state, reason=left.reason) for left in discovery.left]
    for source in discovery.files:
        state, reason = file_state(per_file[source.path], rejected[source.path],
                                   observed.failed.get(source.path), nothing.get(source.path))
        files.append(FileCoverage(path=source.path, state=state, reason=reason, observations=per_file[source.path],
                                  rejected=rejected[source.path], cited_by=cited[source.path],
                                  source_hash=source.source_hash, line_digest=line_digest(source.lines)))
    files.sort(key=lambda f: f.path)
    used = {e.observation for r in requirements for e in r.evidence}
    unused = collections.Counter(assignments.get(o.id, "unassigned") for o in observed.observations if o.id not in used)
    return Coverage(summary=dict(collections.Counter(f.state for f in files)), files=files,
                    unused_observations=dict(sorted(unused.items())))


def earlier_evidence(previous: ExtractionResult, fingerprint: str) -> dict[str, Earlier]:
    """What a saved result established about each file it read, for a later run to reuse.
    Empty when that result observed files another way, or stopped on a failure for the file."""
    if not fingerprint or previous.run.observe_fingerprint != fingerprint:
        return {}
    by_path: dict[str, list] = collections.defaultdict(list)
    for observation in previous.observations:
        by_path[observation.path].append(observation)
    earlier = {}
    for covered in previous.coverage.files:
        if covered.source_hash and covered.state in ("extracted", "no_requirements"):
            earlier[covered.path] = Earlier(
                source_hash=covered.source_hash, observations=tuple(by_path.get(covered.path, [])),
                nothing_reason=covered.reason if covered.state == "no_requirements" else None,
                line_digest=covered.line_digest)
    return earlier


def to_markdown(result: ExtractionResult, include_technical: bool = False) -> str:
    """The catalogue grouped by capability, each requirement with its support and citations."""
    by_capability: dict[str, list[Requirement]] = collections.defaultdict(list)
    for requirement in result.requirements:
        if include_technical or requirement.level != "technical":
            by_capability[requirement.capability].append(requirement)
    out = ["# Requirements", ""]
    summary = ", ".join(f"{count} {state}" for state, count in sorted(result.coverage.summary.items()))
    out += [f"{len(result.requirements)} requirements from {len(result.observations)} verified observations. "
            f"Files: {summary}. Run status: {result.run.status}.", ""]
    for capability in result.capabilities:
        requirements = by_capability.get(capability.id)
        if not requirements:
            continue
        out += [f"## {capability.name}", "", capability.summary, ""]
        for requirement in requirements:
            out.append(f"- **{requirement.statement}** `{requirement.id}` (support: {requirement.support})")
            for condition in requirement.conditions:
                out.append(f"    - Condition: {condition}")
            if requirement.support_note and requirement.support != "direct":
                out.append(f"    - Not shown: {requirement.support_note}")
            cites = ", ".join(f"`{e.path}:{e.lines[0]}-{e.lines[1]}`" for e in requirement.evidence[:6])
            more = f" and {len(requirement.evidence) - 6} more" if len(requirement.evidence) > 6 else ""
            out.append(f"    - Evidence: {cites}{more}")
        for question in result.diagnostics.open_questions.get(capability.id, []):
            out.append(f"- Open question: {question}")
        out.append("")
    return "\n".join(out)
