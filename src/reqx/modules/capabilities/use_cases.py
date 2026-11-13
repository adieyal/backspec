"""Orient: propose capabilities from the observations. Assign: place every observation in one."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from reqx.kernel import prompts
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from reqx.modules.capabilities.domain import (UNASSIGNED, AssignReply, Capability, OrientReply, listing,
                                              parse_capabilities, thin, with_plumbing)
from reqx.modules.capabilities.ports import CapabilitiesStorePort
from reqx.modules.evidence.facade import Observation

ORIENT_LIMIT = 2000   # observation lines one orient call is shown
ASSIGN_CHUNK = 280


def _items(observations: list[Observation]) -> list[tuple[str, str, str]]:
    ordered = sorted(observations, key=lambda o: (o.path, o.lines[0]))
    return [(o.id, o.path, o.statement) for o in ordered]


def orient(observations: list[Observation], llm: LLMPort) -> list[Capability]:
    shown = listing(thin(_items(observations), ORIENT_LIMIT))
    reply = ask(llm, LLMRequest("orient", f"{prompts.load('orient')}\n\n# The observations\n\n{shown}", "fast"), OrientReply)
    return with_plumbing(list({c.id: c for c in reply.capabilities}.values()))


def load(store: CapabilitiesStorePort) -> list[Capability] | None:
    """The owner's capability list, validated, or None when there is none. Refuses a bad file."""
    data = store.read()
    return None if data is None else parse_capabilities(data, store.location)


def assign(observations: list[Observation], capabilities: list[Capability], llm: LLMPort,
           workers: int = 4, earlier: dict[str, str] | None = None) -> dict[str, str]:
    """Observation id -> capability id. An observation the model skipped, or sent to a capability
    that does not exist, is `unassigned`: it is still reported, never dropped.

    An observation an earlier run placed in a capability that still exists stays there; only
    the others are put to the model."""
    known = {c.id for c in capabilities}
    kept = {o.id: earlier[o.id] for o in observations
            if earlier and earlier.get(o.id) in known and earlier[o.id] != UNASSIGNED}
    everything, observations = observations, [o for o in observations if o.id not in kept]
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
    placed.update(kept)
    return {o.id: placed[o.id] if placed.get(o.id) in known else UNASSIGNED for o in everything}
