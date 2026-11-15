"""Plumbing is never written up, so nothing a user or caller would notice may end up there."""
import json
import re

from backspec.host.adapters.fake import FakeLLM
from backspec.modules.capabilities.domain import PLUMBING, UNASSIGNED, Capability, with_plumbing
from backspec.modules.capabilities.use_cases import assign, orient
from backspec.modules.evidence.domain import Observation

CAPS = with_plumbing([Capability(id="authoring", name="Authoring")])


def obs(obs_id, kind, statement="A step ordering that is not a list is refused."):
    return Observation(id=obs_id, statement=statement, kind=kind, path="a.py", lines=(1, 2), quote="raise x",
                       source_hash="h", verified="exact")


def ids(prompt):
    return re.findall(r"^(OBS-\w+) \|", prompt, re.M)


def test_a_refusal_put_in_plumbing_is_asked_about_again_without_plumbing():
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        target = "authoring" if len(prompts) > 1 else PLUMBING
        return {"assignments": {i: target for i in ids(prompt)}}
    placed = assign([obs("OBS-1", "error_path"), obs("OBS-2", "other", "Imports are sorted.")], CAPS,
                    FakeLLM({"assign": answer}), workers=1)
    assert placed == {"OBS-1": "authoring", "OBS-2": PLUMBING}
    assert "- plumbing:" not in prompts[1] and ids(prompts[1]) == ["OBS-1"]


def test_a_refusal_the_model_insists_is_plumbing_is_unassigned_not_hidden():
    llm = FakeLLM({"assign": lambda prompt: {"assignments": {i: PLUMBING for i in ids(prompt)}}})
    assert assign([obs("OBS-1", "validation")], CAPS, llm, workers=1) == {"OBS-1": UNASSIGNED}


def test_an_earlier_plumbing_placement_of_a_refusal_is_not_kept():
    llm = FakeLLM({"assign": lambda prompt: {"assignments": {i: "authoring" for i in ids(prompt)}}})
    placed = assign([obs("OBS-1", "permission")], CAPS, llm, workers=1, earlier={"OBS-1": PLUMBING})
    assert placed == {"OBS-1": "authoring"}


def test_the_kind_of_each_observation_is_shown_when_assigning():
    llm = FakeLLM({"assign": lambda prompt: {"assignments": {}}})
    assign([obs("OBS-1", "error_path")], CAPS, llm, workers=1)
    assert "OBS-1 | error_path | A step ordering" in llm.requests[0].prompt


def test_a_model_cannot_widen_plumbing_when_orienting():
    widened = {"capabilities": [{"id": "authoring", "name": "Authoring"},
                                {"id": "plumbing", "name": "Plumbing", "summary": "Validation details.",
                                 "includes": ["ordering input validation"]}]}
    caps = orient([obs("OBS-1", "error_path")], FakeLLM({"orient": lambda prompt: json.dumps(widened)}))
    plumbing = next(c for c in caps if c.id == PLUMBING)
    assert plumbing.includes == [] and "Validation details" not in plumbing.summary and caps[-1].id == PLUMBING
