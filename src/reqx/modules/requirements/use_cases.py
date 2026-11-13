"""Synthesise requirements capability by capability, then challenge each one."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from reqx.kernel import prompts
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from reqx.modules.capabilities.facade import Capability
from reqx.modules.evidence.facade import Observation
from reqx.modules.requirements.domain import (AssessReply, Requirement, SynthReply, assess_block, build,
                                              settle, synth_input)

SYNTH_BATCH = 180    # observations per synthesis call
ASSESS_BATCH = 12    # requirements per support call


@dataclass
class Synthesis:
    requirements: list[Requirement] = field(default_factory=list)
    open_questions: dict[str, list[str]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)   # capability -> why


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
    return result


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
