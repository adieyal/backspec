"""Assemble the coverage ledger and render a result for people to read."""
from __future__ import annotations

import collections

from backspec.modules.discovery.facade import Discovery
from backspec.modules.evidence.facade import Earlier, ObservationSet, line_digest
from backspec.modules.report.domain import CoverageReport, FileCoverage, file_state, worth_looking_at
from backspec.modules.report.dto import Coverage, ExtractionResult, TriageAudit
from backspec.modules.requirements.facade import Requirement
from backspec.modules.triage.facade import EarlierVerdict, TriageResult, Verdict, clopper_pearson


def build_coverage(discovery: Discovery, observed: ObservationSet, requirements: list[Requirement],
                   assignments: dict[str, str], triage: TriageResult | None = None) -> Coverage:
    per_file = collections.Counter(o.path for o in observed.observations)
    rejected = collections.Counter(r.path for r in observed.rejected)
    nothing = {entry.path: entry.reason for entry in observed.nothing}
    cited = collections.Counter(path for r in requirements for path in {e.path for e in r.evidence})
    files = [FileCoverage(path=left.path, state=left.state, reason=left.reason) for left in discovery.left]
    verdicts = triage.verdicts if triage else {}
    audited = set(triage.audited) if triage else set()
    for source in discovery.files:
        verdict = verdicts.get(source.path)
        out = bool(verdict and verdict.skipped)   # triage skipped it
        read = not out or source.path in audited
        failed = observed.failed.get(source.path)
        state, reason = file_state(per_file[source.path], rejected[source.path], failed, nothing.get(source.path))
        if out and (not read or (state in ("no_requirements", "candidates_rejected"))):
            # not read, or audited and yielded nothing: the triage role is the reason
            state, reason = "triaged_out", verdict.role
        files.append(FileCoverage(
            path=source.path, state=state, reason=reason, observations=per_file[source.path],
            rejected=rejected[source.path], lines=len(source.text.splitlines()),
            analysis=observed.analysis.get(source.path, "text"), cited_by=cited[source.path], source_hash=source.source_hash,
            line_digest=line_digest(source.lines) if read else "",
            triage_role=verdict.role if verdict else "", triage_relevance=verdict.relevance if verdict else "",
            triage_skipped=out, triage_audited=out and read,
            found_by_audit=out and read and per_file[source.path] > 0))
    files.sort(key=lambda f: f.path)
    used = {e.observation for r in requirements for e in r.evidence}
    unused = collections.Counter(assignments.get(o.id, "unassigned") for o in observed.observations if o.id not in used)
    return Coverage(summary=dict(collections.Counter(f.state for f in files)), files=files,
                    unused_observations=dict(sorted(unused.items())),
                    triage_audit=_triage_audit(triage, per_file, observed.failed) if triage else None)


def _triage_audit(triage: TriageResult, per_file: collections.Counter, failed: dict[str, str]) -> TriageAudit:
    read = [path for path in triage.audited if path not in failed]
    yielded = sorted(path for path in read if per_file[path] > 0)
    return TriageAudit(skipped=len(triage.skipped), audited=len(read), yielded=len(yielded), yielded_paths=yielded,
                       failed_paths=sorted(path for path in triage.audited if path in failed),
                       miss_rate_interval=clopper_pearson(len(yielded), len(read)))


def earlier_triage(previous: ExtractionResult, fingerprint: str) -> dict[str, EarlierVerdict]:
    """The verdicts a saved result reached, for a later run to keep for files that have not changed.
    Empty when that result was triaged another way."""
    if not fingerprint or previous.run.triage_fingerprint != fingerprint:
        return {}
    return {covered.path: EarlierVerdict(covered.source_hash, Verdict(covered.triage_role, covered.triage_relevance,
                                                                       covered.triage_skipped))
            for covered in previous.coverage.files if covered.source_hash and covered.triage_relevance}


def coverage_report(result: ExtractionResult) -> CoverageReport:
    """What a saved result says about its files. No model and no file system: only the result."""
    by_state: dict[str, list[FileCoverage]] = {}
    for entry in result.coverage.files:
        if entry.state != "excluded":
            by_state.setdefault(entry.state, []).append(entry)
    return CoverageReport(counts=dict(result.coverage.summary), files=dict(sorted(by_state.items())),
                          unused_observations=dict(result.coverage.unused_observations),
                          worth_a_look=[e for e in result.coverage.files if worth_looking_at(e)])


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
        audited_blank = covered.state == "triaged_out" and covered.triage_audited   # read by the audit, nothing found
        if covered.source_hash and (covered.state in ("extracted", "no_requirements") or audited_blank):
            earlier[covered.path] = Earlier(
                source_hash=covered.source_hash, observations=tuple(by_path.get(covered.path, [])),
                nothing_reason=covered.reason if covered.state == "no_requirements" else
                ("audited; nothing verified" if audited_blank else None),
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
            cites = ", ".join(f"`{e.path}:{e.lines[0]}-{e.lines[1]}`" + (f" ({e.symbol})" if e.symbol else "") for e in requirement.evidence[:6])
            more = f" and {len(requirement.evidence) - 6} more" if len(requirement.evidence) > 6 else ""
            out.append(f"    - Evidence: {cites}{more}")
            for scenario in requirement.scenarios:
                out += [f"    - Scenario: {scenario.name}", f"        - Given: {scenario.given}",
                        f"        - When: {scenario.when}", f"        - Then: {scenario.then}"]
        for question in result.diagnostics.open_questions.get(capability.id, []):
            out.append(f"- Open question: {question}")
        out.append("")
    return "\n".join(out)
