"""Orient: propose capabilities from the observations. Assign: place every observation in one."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from backspec.kernel import prompts
from backspec.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from backspec.modules.capabilities.domain import (PLUMBING, UNASSIGNED, AssignReply, Capability, OrientReply,
                                              belongs_in_plumbing, listing, parse_capabilities, standard_plumbing,
                                              thin, with_plumbing)
from backspec.modules.capabilities.ports import CapabilitiesStorePort
from backspec.modules.evidence.facade import Observation

ORIENT_LIMIT = 2000   # observation lines one orient call is shown
ASSIGN_CHUNK = 280


def _items(observations: list[Observation]) -> list[tuple[str, str, str]]:
    ordered = sorted(observations, key=lambda o: (o.path, o.lines[0]))
    return [(o.id, o.path, f"{o.kind} | {o.statement}") for o in ordered]


def orient(observations: list[Observation], llm: LLMPort) -> list[Capability]:
    """Capabilities proposed by a model. `plumbing` is always the program's own: a model that
    widens it (to "validation details", say) would hide behaviour from every later stage."""
    shown = listing(thin(_items(observations), ORIENT_LIMIT))
    reply = ask(llm, LLMRequest("orient", f"{prompts.load('orient')}\n\n# The observations\n\n{shown}", "fast"), OrientReply)
    proposed = [c for c in {c.id: c for c in reply.capabilities}.values() if c.id != PLUMBING]
    return [*proposed, standard_plumbing()]


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

    def allowed(observation: Observation, capability: str | None) -> bool:
        return capability in known and (capability != PLUMBING or belongs_in_plumbing(observation.kind))

    kept = {o.id: earlier[o.id] for o in observations
            if earlier and allowed(o, earlier.get(o.id)) and earlier[o.id] != UNASSIGNED}
    everything, observations = observations, [o for o in observations if o.id not in kept]
    placed = _ask_assign(observations, capabilities, llm, workers)
    # Plumbing is never written up. An observation of a kind someone would notice (a refusal, a
    # change, what is shown) that was put there is asked about once more, without plumbing to
    # choose; if it is still not placed, it is `unassigned`, which is written up and reported.
    misplaced = [o for o in observations if placed.get(o.id) == PLUMBING and not belongs_in_plumbing(o.kind)]
    if misplaced:
        placed.update(_ask_assign(misplaced, [c for c in capabilities if c.id != PLUMBING], llm, workers))
    placed.update(kept)
    return {o.id: placed[o.id] if allowed(o, placed.get(o.id)) else UNASSIGNED for o in everything}


def _ask_assign(observations: list[Observation], capabilities: list[Capability], llm: LLMPort,
                workers: int) -> dict[str, str]:
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
    return placed
