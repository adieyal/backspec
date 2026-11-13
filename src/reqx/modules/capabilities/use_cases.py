"""Orient: propose capabilities from the observations. Assign: place every observation in one."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from reqx.kernel import prompts
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from reqx.modules.capabilities.domain import (PLUMBING, UNASSIGNED, AssignReply, Capability, OrientReply,
                                              listing, thin)
from reqx.modules.evidence.facade import Observation

ORIENT_LIMIT = 2000   # observation lines one orient call is shown
ASSIGN_CHUNK = 280


def _items(observations: list[Observation]) -> list[tuple[str, str, str]]:
    ordered = sorted(observations, key=lambda o: (o.path, o.lines[0]))
    return [(o.id, o.path, o.statement) for o in ordered]


def orient(observations: list[Observation], llm: LLMPort) -> list[Capability]:
    shown = listing(thin(_items(observations), ORIENT_LIMIT))
    reply = ask(llm, LLMRequest("orient", f"{prompts.load('orient')}\n\n# The observations\n\n{shown}", "fast"), OrientReply)
    capabilities = {c.id: c for c in reply.capabilities}
    capabilities.setdefault(PLUMBING, Capability(id=PLUMBING, name="Internal mechanics",
                                                 summary="Machinery no user or operator would notice."))
    return list(capabilities.values())


def assign(observations: list[Observation], capabilities: list[Capability], llm: LLMPort,
           workers: int = 4) -> dict[str, str]:
    """Observation id -> capability id. An observation the model skipped, or sent to a capability
    that does not exist, is `unassigned`: it is still reported, never dropped."""
    known = {c.id for c in capabilities}
    described = "\n".join(f"- {c.id}: {c.name}. {c.summary} Includes: {'; '.join(c.includes)}" for c in capabilities)
    items = _items(observations)
    chunks = [items[start:start + ASSIGN_CHUNK] for start in range(0, len(items), ASSIGN_CHUNK)]
    instructions = prompts.load("assign")

    def run(chunk: list[tuple[str, str, str]]) -> dict[str, str]:
        prompt = f"{instructions}\n\n# The capabilities\n\n{described}\n\n# The observations\n\n{listing(chunk)}"
        try:
            return ask(llm, LLMRequest("assign", prompt, "fast"), AssignReply).assignments
        except LLMError:
            return {}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, chunks))
    placed: dict[str, str] = {}
    for reply in replies:
        placed.update(reply)
    return {o.id: placed[o.id] if placed.get(o.id) in known else UNASSIGNED for o in observations}
