"""Synthesise requirements capability by capability, then challenge each one."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from reqx.kernel import prompts
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from reqx.kernel.text import short_hash
from reqx.modules.capabilities.facade import Capability
from reqx.modules.evidence.facade import Observation
from reqx.modules.requirements.domain import (AssessReply, ConsolidateReply, Requirement, SynthReply, assess_block,
                                              build, consolidate_input, merge_requirements, settle, synth_input)

SYNTH_BATCH = 180    # observations per synthesis call
CONSOLIDATE_MIN = 8  # a capability with more requirements than max(this, a third of its observations) is consolidated
ASSESS_BATCH = 12    # requirements per support call


def fingerprint() -> str:
    """Changes whenever the way requirements are written, merged or judged does. Requirements an
    earlier run made another way are not reused."""
    return short_hash(prompts.load("synthesise"), prompts.load("consolidate"), prompts.load("assess"),
                      SYNTH_BATCH, CONSOLIDATE_MIN, ASSESS_BATCH)


@dataclass
class Synthesis:
    requirements: list[Requirement] = field(default_factory=list)
    open_questions: dict[str, list[str]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)   # capability -> why
    unconsolidated: dict[str, str] = field(default_factory=dict)   # capability -> why the merge pass failed


def synthesise(capabilities: list[Capability], by_capability: dict[str, list[Observation]],
               llm: LLMPort, workers: int = 4) -> Synthesis:
    instructions = prompts.load("synthesise")
    jobs = []
    for capability in capabilities:
        observations = by_capability.get(capability.id, [])
        for start in range(0, len(observations), SYNTH_BATCH):
            jobs.append((capability, observations[start:start + SYNTH_BATCH]))

    def run(job: tuple[Capability, list[Observation]]) -> SynthReply | LLMError:
        capability, observations = job
        prompt = (f"{instructions}\n\n# The capability\n\nCAPABILITY: {capability.id}\nNAME: {capability.name}\n"
                  f"SUMMARY: {capability.summary}\n\n# The observations\n\n{synth_input(observations)}")
        try:
            return ask(llm, LLMRequest("synthesise", prompt, "strong"), SynthReply)
        except LLMError as error:
            return error

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, jobs))
    result = Synthesis()
    seen: set[str] = set()
    for (capability, observations), reply in zip(jobs, replies):
        if isinstance(reply, LLMError):
            result.failed[capability.id] = str(reply)[:300]
            continue
        known = {o.id: o for o in observations}
        for raw in reply.requirements:
            requirement = build(raw, capability.id, known)
            if requirement and requirement.id not in seen:
                seen.add(requirement.id)
                result.requirements.append(requirement)
        if reply.open_questions:
            result.open_questions.setdefault(capability.id, []).extend(reply.open_questions)
    consolidate(result, capabilities, by_capability, {c for c, _ in jobs_by_cap(jobs, True)}, llm, workers)
    return result


def jobs_by_cap(jobs: list[tuple[Capability, list[Observation]]], multi_only: bool) -> list[tuple[str, int]]:
    """(capability id, number of batches) for each capability; with multi_only, only those
    synthesised in more than one batch."""
    counts: dict[str, int] = {}
    for capability, _ in jobs:
        counts[capability.id] = counts.get(capability.id, 0) + 1
    return [(c, n) for c, n in counts.items() if n > 1 or not multi_only]


def consolidate(result: Synthesis, capabilities: list[Capability], by_capability: dict[str, list[Observation]],
                batched: set[str], llm: LLMPort, workers: int = 4) -> None:
    """Merge requirements that state the same behaviour, for each capability that was synthesised
    in more than one batch or came out too fine. Failure keeps the originals and is recorded."""
    by_id = {c.id: c for c in capabilities}
    own: dict[str, list[Requirement]] = {}
    for requirement in result.requirements:
        own.setdefault(requirement.capability, []).append(requirement)
    due = [cid for cid, reqs in own.items()
           if cid in by_id and len(reqs) > 1
           and (cid in batched or len(reqs) > max(CONSOLIDATE_MIN, len(by_capability.get(cid, [])) / 3))]
    if not due:
        return
    instructions = prompts.load("consolidate")

    def run(cid: str) -> ConsolidateReply | LLMError:
        prompt = (f"{instructions}\n\n# The capability\n\nCAPABILITY: {cid}\nNAME: {by_id[cid].name}\n"
                  f"SUMMARY: {by_id[cid].summary}\n\n# The requirements\n\n{consolidate_input(own[cid])}")
        try:
            return ask(llm, LLMRequest("consolidate", prompt, "strong"), ConsolidateReply)
        except LLMError as error:
            return error

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, due))
    for cid, reply in zip(due, replies):
        if isinstance(reply, LLMError):
            result.unconsolidated[cid] = str(reply)[:300]
        else:
            own[cid] = merge_requirements(own[cid], reply.groups)
    order = list(own)
    result.requirements = [r for cid in order for r in own[cid]]


def assess(requirements: list[Requirement], file_lines: dict[str, list[str]], llm: LLMPort,
           workers: int = 4) -> list[Requirement]:
    """Each requirement with a support verdict, keyed by id. One left without a verdict stays
    `not_assessed`; it is never assumed to be supported."""
    instructions = prompts.load("assess")
    batches = [requirements[start:start + ASSESS_BATCH] for start in range(0, len(requirements), ASSESS_BATCH)]

    def run(batch: list[Requirement]) -> AssessReply:
        blocks = "\n".join(assess_block(r, file_lines) for r in batch)
        try:
            return ask(llm, LLMRequest("assess", f"{instructions}\n\n# The requirements\n\n{blocks}", "strong"), AssessReply)
        except LLMError:
            return AssessReply()

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, batches))
    verdicts = {v.id: v for reply in replies for v in reply.verdicts}
    return [settle(requirement, verdicts.get(requirement.id)) for requirement in requirements]
