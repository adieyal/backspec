"""The pipeline: discover, observe and verify, orient, assign, synthesise, assess, report.

The program drives. A model is asked to read and to write statements; structure, citations and
merging are done here and in the modules this composes.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Callable

from reqx.kernel.prompts import PROMPT_VERSION
from reqx.modules.capabilities.facade import PLUMBING, UNASSIGNED, CapabilitiesFacade, Capability
from reqx.modules.discovery.facade import DiscoveryFacade
from reqx.modules.evidence.facade import EvidenceFacade
from reqx.modules.report.facade import Diagnostics, ExtractionResult, Run, build_coverage
from reqx.modules.requirements.facade import Requirement, RequirementsFacade
from reqx.modules.review.facade import ReviewFacade, ReviewSummary

TOOL_VERSION = "0.0.1"
Progress = Callable[[str], None]


@dataclass
class Settings:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    default_excludes: bool = True
    assess_support: bool = True
    gate: bool = False   # stop once the capabilities are settled, before assignment and synthesis


def run(root: str, provider: str, settings: Settings, discovery: DiscoveryFacade, evidence: EvidenceFacade,
        capabilities: CapabilitiesFacade, requirements: RequirementsFacade,
        usage: Callable[[], tuple[int, int]] = lambda: (0, 0), progress: Progress = lambda _: None,
        review: ReviewFacade | None = None, previous: list[Requirement] | None = None) -> ExtractionResult:
    # An unusable capabilities file is refused before any file is read or model called.
    from_file = capabilities.load()
    found = discovery.discover(settings.include, settings.exclude, settings.default_excludes)
    progress(f"discovered {len(found.files)} files to read, {len(found.left)} left out")

    observed = evidence.observe(list(found.files))
    progress(f"observed {len(observed.observations)} verified, {len(observed.rejected)} rejected, "
             f"in {observed.batches} batches")

    caps: list[Capability] = []
    assignments: dict[str, str] = {}
    source = "file" if from_file is not None else "oriented"
    if from_file is not None:
        caps = from_file
        progress(f"using {len(caps)} capabilities from {capabilities.location}")
    elif observed.observations:
        caps = capabilities.orient(observed.observations)
        progress(f"oriented into {len(caps)} capabilities")
        if settings.gate:
            capabilities.save(caps)
            progress(f"capabilities written to {capabilities.location}")

    if settings.gate:
        # Stopped on purpose: the run is `partial` and says where it stopped.
        progress("gate: stopping before assignment and synthesis; edit the file, then run again")
        calls, cached = usage()
        return ExtractionResult(
            run=Run(status="partial", tool_version=TOOL_VERSION, prompt_version=PROMPT_VERSION, provider=provider,
                    root=root, calls=calls, cached_calls=cached, capabilities_source=source,
                    stopped_after="capabilities"),
            capabilities=caps, requirements=[],
            observations=sorted(observed.observations, key=lambda o: (o.path, o.lines[0], o.id)),
            assignments={}, coverage=build_coverage(found, observed, [], {}),
            diagnostics=Diagnostics(rejected=observed.rejected))

    if observed.observations:
        assignments = capabilities.assign(observed.observations, caps)
        if UNASSIGNED in assignments.values():
            caps.append(Capability(id=UNASSIGNED, name="Unassigned",
                                   summary="Observations that were not placed in a capability."))

    by_capability = collections.defaultdict(list)
    for observation in observed.observations:
        by_capability[assignments[observation.id]].append(observation)
    product = [c for c in caps if c.id != PLUMBING]
    synthesis = requirements.synthesise(product, by_capability)
    progress(f"synthesised {len(synthesis.requirements)} requirements")

    final = synthesis.requirements
    if settings.assess_support and final:
        final = requirements.assess(final, {f.path: f.lines for f in found.files})
        counts = collections.Counter(r.support for r in final)
        progress("assessed support: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    review_summary: ReviewSummary | None = None
    if review is not None and review.applies(previous):
        reviewed = review.apply(final, previous)
        final, review_summary = reviewed.requirements, reviewed.summary
        progress(f"review: {review_summary.carried} ids carried, {review_summary.rejected_hidden} rejected hidden, "
                 f"{review_summary.needs_review} need review, {len(review_summary.stale_entries)} stale entries")
    final = sorted(final, key=lambda r: (r.capability, r.id))

    calls, cached = usage()
    complete = not observed.failed and not synthesis.failed
    return ExtractionResult(
        run=Run(status="complete" if complete else "partial", tool_version=TOOL_VERSION,
                prompt_version=PROMPT_VERSION, provider=provider, root=root, calls=calls, cached_calls=cached,
                capabilities_source=source),
        capabilities=caps, requirements=final,
        observations=sorted(observed.observations, key=lambda o: (o.path, o.lines[0], o.id)),
        assignments=assignments,
        coverage=build_coverage(found, observed, final, assignments),
        diagnostics=Diagnostics(rejected=observed.rejected, failed_capabilities=synthesis.failed,
                                open_questions=synthesis.open_questions,
                                review=review_summary))


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
