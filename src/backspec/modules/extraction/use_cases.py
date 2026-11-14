"""The pipeline: discover, triage, observe and verify, orient, assign, synthesise, assess, report.

The program drives. A model is asked to read and to write statements; structure, citations and
merging are done here and in the modules this composes.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Callable

from backspec.kernel.llm import LLMError
from backspec.kernel.prompts import PROMPT_VERSION
from backspec.kernel.usage import Spend
from backspec.modules.capabilities.facade import PLUMBING, UNASSIGNED, CapabilitiesFacade, Capability
from backspec.modules.discovery.facade import DiscoveryFacade
from backspec.modules.evidence.facade import EvidenceFacade
from backspec.modules.lint.facade import lint_findings
from backspec.modules.report.facade import Diagnostics, ExtractionResult, Run, StageUsage, build_coverage, earlier_evidence, earlier_triage
from backspec.modules.requirements.facade import Requirement, RequirementsFacade
from backspec.modules.review.facade import ReviewFacade, ReviewSummary
from backspec.modules.triage.facade import DEFAULT_AUDIT, TriageFacade

TOOL_VERSION = "0.0.1"
Progress = Callable[[str], None]


@dataclass
class Settings:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    default_excludes: bool = True
    assess_support: bool = True
    gate: bool = False   # stop once the capabilities are settled, before assignment and synthesis
    triage: bool = True            # a cheap first look; files surely of no relevance are not read in full
    triage_audit: float = DEFAULT_AUDIT   # share of the skipped files read anyway; 0 is off, 1.0 reads them all


def run(root: str, provider: str, settings: Settings, discovery: DiscoveryFacade, evidence: EvidenceFacade,
        capabilities: CapabilitiesFacade, requirements: RequirementsFacade,
        usage: Callable[[], tuple[int, int]] = lambda: (0, 0), progress: Progress = lambda _: None,
        review: ReviewFacade | None = None, before: ExtractionResult | None = None,
        reuse: bool = True, spend: Callable[[], Spend] = Spend, triage: TriageFacade | None = None) -> ExtractionResult:
    """`before` is the previous result, if there is one. Requirement ids are carried forward from
    it, and with `reuse` so is everything whose inputs have not changed: observations of unchanged
    files, the capabilities, where each observation was placed, and the requirements of any
    capability whose observations are the same. A model is asked only about what is new."""
    # An unusable capabilities file is refused before any file is read or model called.
    from_file = capabilities.load()
    kept = before if reuse else None
    found = discovery.discover(settings.include, settings.exclude, settings.default_excludes)
    progress(f"discovered {len(found.files)} files to read, {len(found.left)} left out")

    triaged = None
    if settings.triage and triage is not None:
        verdicts = earlier_triage(kept, triage.fingerprint()) if kept else None
        triaged = triage.assess(list(found.files), verdicts, settings.triage_audit)
        progress(f"triaged {len(found.files)} files: {len(triaged.skipped)} skipped, "
                 f"{len(found.files) - len(triaged.skipped)} to read, {len(triaged.audited)} skipped files "
                 f"read anyway as an audit; {triaged.reused_files} verdicts reused, "
                 f"{len(triaged.unresolved)} without a verdict (read), in {triaged.batches} batches")
    to_read = triaged.to_read(list(found.files)) if triaged else list(found.files)

    earlier = earlier_evidence(kept, evidence.fingerprint()) if kept else None
    observed = evidence.observe(to_read, earlier)
    progress(f"observed {len(observed.observations)} verified, {len(observed.rejected)} rejected, "
             f"in {observed.batches} batches; {observed.reused_files} unchanged files reused, "
             f"{observed.partly_read_files} changed files read in part")

    if triaged is not None and triaged.audited:
        found_by_audit = {o.path for o in observed.observations} & set(triaged.audited)
        progress(f"triage audit: {len(found_by_audit)} of {len(triaged.audited)} audited files had a verified observation")

    caps: list[Capability] = []
    assignments: dict[str, str] = {}
    source = "oriented"
    orient_failed = ""
    if from_file is not None:
        caps, source = from_file, "file"
        progress(f"using {len(caps)} capabilities from {capabilities.location}")
    elif kept and any(c.id not in (PLUMBING, UNASSIGNED) for c in kept.capabilities):
        caps, source = [c for c in kept.capabilities if c.id != UNASSIGNED], "previous"
        progress(f"using {len(caps)} capabilities from the previous result")
    elif observed.observations:
        try:
            caps = capabilities.orient(observed.observations)
            progress(f"oriented into {len(caps)} capabilities")
            if settings.gate:
                capabilities.save(caps)
                progress(f"capabilities written to {capabilities.location}")
        except LLMError as error:   # nothing can be placed without capabilities: record it and stop
            orient_failed = str(error)[:300]

    unresolved = dict(triaged.unresolved) if triaged else {}

    def describe(status: str, **more: object) -> Run:
        calls, cached = usage()
        used = spend()
        return Run(status=status, tool_version=TOOL_VERSION, prompt_version=PROMPT_VERSION, provider=provider,
                   root=root, calls=calls, cached_calls=cached, capabilities_source=source,
                   input_tokens=used.input_tokens, output_tokens=used.output_tokens,
                   tokens_estimated=used.estimated, cost_usd=used.cost_usd, budget_reached=used.budget_reached,
                   usage_by_stage={s: StageUsage(**u) for s, u in used.by_stage.items()},
                   observe_fingerprint=evidence.fingerprint(), reused_files=observed.reused_files, **_analysis_counts(observed),
                   partly_read_files=observed.partly_read_files, synthesis_fingerprint=requirements.fingerprint(),
                   triage_fingerprint=triage.fingerprint() if triaged is not None and triage else "", **more)

    all_observations = sorted(observed.observations, key=lambda o: (o.path, o.lines[0], o.id))
    if orient_failed:
        progress(f"orient failed: {orient_failed}")
        return ExtractionResult(
            run=describe("partial"), capabilities=[], requirements=[], observations=all_observations,
            assignments={}, coverage=build_coverage(found, observed, [], {}),
            diagnostics=Diagnostics(rejected=observed.rejected, failed_stages={"orient": orient_failed}))
    if settings.gate:
        # Stopped on purpose: the run is `partial` and says where it stopped.
        progress("gate: stopping before assignment and synthesis; edit the file, then run again")
        gated = ExtractionResult(
            run=describe("partial", stopped_after="capabilities"), capabilities=caps, requirements=[],
            observations=all_observations, assignments={}, coverage=build_coverage(found, observed, [], {}, triaged),
            diagnostics=Diagnostics(rejected=observed.rejected, triage_unresolved=unresolved))
        gated.diagnostics.lint = lint_findings(gated)
        return gated

    if observed.observations:
        assignments = capabilities.assign(observed.observations, caps, kept.assignments if kept else None)
        if UNASSIGNED in assignments.values():
            caps.append(Capability(id=UNASSIGNED, name="Unassigned",
                                   summary="Observations that were not placed in a capability."))

    by_capability = collections.defaultdict(list)
    for observation in observed.observations:
        by_capability[assignments[observation.id]].append(observation)
    product = [c for c in caps if c.id != PLUMBING]

    # A capability whose observations are exactly those the previous result had keeps its requirements.
    reused: list[Requirement] = []
    reused_capabilities: list[str] = []
    current = {o.id: o for o in observed.observations}
    open_questions: dict[str, list[str]] = {}
    if kept and kept.run.stopped_after is None and kept.run.synthesis_fingerprint == requirements.fingerprint():
        placed_before = collections.defaultdict(set)
        for observation_id, capability_id in kept.assignments.items():
            placed_before[capability_id].add(observation_id)
        made_before = collections.defaultdict(list)
        for requirement in [*kept.requirements, *kept.hidden]:
            made_before[requirement.capability].append(requirement)
        unsettled = {*kept.diagnostics.failed_capabilities, *kept.diagnostics.unconsolidated}
        for capability in product:
            now = {o.id for o in by_capability.get(capability.id, [])}
            if now and now == placed_before.get(capability.id) and capability.id not in unsettled:
                reused_capabilities.append(capability.id)
                # review is applied afresh below, so a decision withdrawn since then is withdrawn here too
                reused += [_refreshed(r, current) for r in made_before[capability.id]]
                if capability.id in kept.diagnostics.open_questions:
                    open_questions[capability.id] = kept.diagnostics.open_questions[capability.id]
    synthesis = requirements.synthesise([c for c in product if c.id not in reused_capabilities], by_capability)
    open_questions.update(synthesis.open_questions)
    progress(f"synthesised {len(synthesis.requirements)} requirements; "
             f"{len(reused)} kept from {len(reused_capabilities)} unchanged capabilities")

    final = [*reused, *synthesis.requirements]
    if settings.assess_support:
        unjudged = [r for r in final if r.support == "not_assessed"]
        if unjudged:
            judged = {r.id: r for r in requirements.assess(unjudged, {f.path: f.lines for f in found.files})}
            final = [judged.get(r.id, r) for r in final]
            counts = collections.Counter(r.support for r in final)
            progress("assessed support: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    review_summary: ReviewSummary | None = None
    hidden: list[Requirement] = []
    previous = [*before.requirements, *before.hidden] if before else None
    if review is not None and review.applies(previous):
        reviewed = review.apply(final, previous)
        final, review_summary, hidden = reviewed.requirements, reviewed.summary, reviewed.hidden
        progress(f"review: {review_summary.carried} ids carried, {review_summary.rejected_hidden} rejected hidden, "
                 f"{review_summary.needs_review} need review, {len(review_summary.stale_entries)} stale entries")
    final = sorted(final, key=lambda r: (r.capability, r.id))

    complete = not observed.failed and not synthesis.failed and not spend().budget_reached
    result = ExtractionResult(
        run=describe("complete" if complete else "partial", reused_capabilities=sorted(reused_capabilities)),
        capabilities=caps, requirements=final, hidden=sorted(hidden, key=lambda r: (r.capability, r.id)),
        observations=all_observations, assignments=assignments,
        coverage=build_coverage(found, observed, [*final, *hidden], assignments, triaged),
        diagnostics=Diagnostics(rejected=observed.rejected, failed_capabilities=synthesis.failed,
                                unconsolidated=synthesis.unconsolidated,
                                dropped_scenarios=synthesis.dropped_scenarios, open_questions=open_questions,
                                review=review_summary, triage_unresolved=unresolved))
    result.diagnostics.lint = lint_findings(result)
    return result


def _analysis_counts(observed) -> dict[str, int]:
    modes = list(observed.analysis.values())
    return {"syntax_files": modes.count("syntax"), "text_files": modes.count("text")}


def _refreshed(requirement: Requirement, current: dict) -> Requirement:
    """A kept requirement with its evidence pointing at where the cited code is now. The lines
    may have moved since it was written; the cited text has not changed."""
    def moved(evidence: list) -> list:
        return [e.model_copy(update={"path": current[e.observation].path, "lines": current[e.observation].lines,
                                     "quote": current[e.observation].quote,
                                     "symbol": getattr(current[e.observation], "symbol", None)})
                if e.observation in current else e for e in evidence]
    scenarios = [s.model_copy(update={"evidence": moved(s.evidence)}) for s in requirement.scenarios]
    return requirement.model_copy(update={"review": "unreviewed", "evidence": moved(requirement.evidence),
                                          "scenarios": scenarios})


def orient_only(settings: Settings, discovery: DiscoveryFacade, evidence: EvidenceFacade,
                capabilities: CapabilitiesFacade, force: bool = False,
                progress: Progress = lambda _: None) -> list[Capability]:
    """Discover, observe, orient and write the capabilities file; nothing after that.
    Refuses to replace an existing file unless `force`, before any model is called."""
    if capabilities.exists() and not force:
        raise FileExistsError(f"{capabilities.location} already exists; pass --force to replace it")
    found = discovery.discover(settings.include, settings.exclude, settings.default_excludes)
    progress(f"discovered {len(found.files)} files to read, {len(found.left)} left out")
    observed = evidence.observe(list(found.files))
    progress(f"observed {len(observed.observations)} verified, {len(observed.rejected)} rejected")
    if not observed.observations:
        raise ValueError("no observations were verified, so there is nothing to orient from; no file was written")
    caps = capabilities.orient(observed.observations)
    capabilities.save(caps)
    progress(f"capabilities written to {capabilities.location}")
    return caps
