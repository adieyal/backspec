"""The consolidation pass: the program merges what the model says is one behaviour, and loses nothing."""
import re

from backspec.host.adapters.fake import FakeLLM
from backspec.modules.capabilities.facade import Capability
from backspec.modules.evidence.facade import Observation
from backspec.modules.requirements import use_cases
from backspec.modules.requirements.facade import RequirementsFacade

CAP = Capability(id="stock", name="Stock", summary="Stock rules.")


def observations(count):
    return [Observation(id=f"OBS-{n:03d}", statement=f"fact {n}", kind="rule", path=f"src/f{n // 12}.py",
                        lines=(n + 1, n + 2), quote=f"line {n}", source_hash="h", verified="exact")
            for n in range(count)]


def synth_with(count):
    """One requirement per observation, so the count is under the test's control."""
    def answer(prompt):
        ids = re.findall(r"^(OBS-\w+) \|", prompt, re.M)
        return {"requirements": [{"statement": f"Requirement {i}.", "evidence": [{"observation": i}]} for i in ids[:count]]}
    return answer


def run(consolidate, observed=36, made=13, llm_answers=None):
    answers = {"synthesise": synth_with(made)}
    if consolidate is not None:
        answers["consolidate"] = consolidate
    llm = FakeLLM(answers)
    obs = observations(observed)
    result = RequirementsFacade(llm).synthesise([CAP], {"stock": obs})
    return result, llm, {o.id: o for o in obs}


def ids_of(result):
    return {r.statement: r.id for r in result.requirements}


def reply_for(first, groups_of):
    """A consolidate answer built from the requirement ids in the prompt, by statement."""
    def answer(prompt):
        ids = dict((s, i) for i, s in re.findall(r"^(REQ-\w+) \| \w+\n  statement: (.*)$", prompt, re.M))
        return {"groups": [{"statement": g["statement"], "conditions": g.get("conditions", []), "level": "system",
                            "merge": [ids.get(m, m) for m in g["merge"]]} for g in groups_of]}
    return answer


def test_merged_evidence_is_the_union_copied_from_the_observations():
    groups = [{"statement": "The system refuses a bad adjustment.", "conditions": ["stock is low"],
               "merge": ["Requirement OBS-000.", "Requirement OBS-001.", "Requirement OBS-012."]}]
    result, llm, known = run(reply_for(None, groups))
    merged = next(r for r in result.requirements if r.statement == "The system refuses a bad adjustment.")
    assert [e.observation for e in merged.evidence] == ["OBS-000", "OBS-001", "OBS-012"]
    for e in merged.evidence:
        assert (e.path, e.lines, e.quote) == (known[e.observation].path, known[e.observation].lines, known[e.observation].quote)
    assert merged.scope == "cross_file" and merged.level == "system" and merged.conditions == ["stock is low"]
    assert merged.merged_from == ["Requirement OBS-000.", "Requirement OBS-001.", "Requirement OBS-012."]
    from backspec.kernel.text import short_hash
    assert merged.id == "REQ-" + short_hash("stock", merged.statement)
    assert len(result.requirements) == 13 - 2 and result.unconsolidated == {}
    assert [r.stage for r in llm.requests].count("consolidate") == 1
    assert next(r for r in llm.requests if r.stage == "consolidate").tier == "strong"


def test_a_requirement_the_reply_does_not_mention_is_kept_unchanged():
    groups = [{"statement": "Merged.", "merge": ["Requirement OBS-000.", "Requirement OBS-001."]}]
    result, _, _ = run(reply_for(None, groups))
    kept = [r for r in result.requirements if r.statement.startswith("Requirement OBS-")]
    assert len(kept) == 11 and all(r.merged_from == [] for r in kept)
    assert "Requirement OBS-005." in {r.statement for r in kept}


def test_an_unknown_id_in_a_group_is_ignored():
    groups = [{"statement": "Merged.", "merge": ["Requirement OBS-000.", "REQ-nope", "Requirement OBS-001."]},
              {"statement": "Alone.", "merge": ["REQ-nope", "Requirement OBS-002."]}]
    result, _, _ = run(reply_for(None, groups))
    merged = next(r for r in result.requirements if r.statement == "Merged.")
    assert [e.observation for e in merged.evidence] == ["OBS-000", "OBS-001"]
    assert "Alone." not in {r.statement for r in result.requirements}
    assert "Requirement OBS-002." in {r.statement for r in result.requirements}


def test_a_requirement_named_in_two_groups_goes_to_the_first():
    groups = [{"statement": "First.", "merge": ["Requirement OBS-000.", "Requirement OBS-001."]},
              {"statement": "Second.", "merge": ["Requirement OBS-001.", "Requirement OBS-002.", "Requirement OBS-003."]}]
    result, _, _ = run(reply_for(None, groups))
    by_statement = {r.statement: r for r in result.requirements}
    assert [e.observation for e in by_statement["First."].evidence] == ["OBS-000", "OBS-001"]
    assert [e.observation for e in by_statement["Second."].evidence] == ["OBS-002", "OBS-003"]


def test_a_failed_consolidate_call_keeps_the_originals_and_is_recorded():
    result, _, _ = run(consolidate=None)
    assert len(result.requirements) == 13 and all(r.merged_from == [] for r in result.requirements)
    assert set(result.unconsolidated) == {"stock"} and "consolidate" in result.unconsolidated["stock"]


def test_a_small_capability_under_the_threshold_is_not_consolidated():
    result, llm, _ = run(reply_for(None, []), observed=6, made=3)
    assert len(result.requirements) == 3 and "consolidate" not in [r.stage for r in llm.requests]


def test_a_capability_synthesised_in_several_batches_is_consolidated(monkeypatch):
    monkeypatch.setattr(use_cases, "SYNTH_BATCH", 2)
    result, llm, _ = run(reply_for(None, []), observed=4, made=2)
    assert len(result.requirements) == 4 and [r.stage for r in llm.requests].count("consolidate") == 1
