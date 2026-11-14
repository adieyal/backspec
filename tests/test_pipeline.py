"""The whole pipeline against a fake model: what backspec guarantees whatever the model says."""
import json
import re

from typer.testing import CliRunner

from backspec import Config, ExtractionResult, extract, to_markdown
from backspec.host.adapters.fake import FakeLLM
from backspec.host.cli import app

POLICY = "def can_adjust(user):\n    return user.role == 'manager'\n"
SERVICE = "def adjust(item, delta):\n    if item.quantity + delta < 0:\n        raise NegativeStock()\n    item.quantity += delta\n"


def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "policy.py").write_text(POLICY)
    (tmp_path / "src" / "service.py").write_text(SERVICE)
    (tmp_path / "src" / "util.py").write_text("def noop():\n    pass\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00")
    return tmp_path


def observe(prompt):
    return {"observations": [
        {"path": "src/policy.py", "lines": [1, 2], "quote": "return user.role == 'manager'", "kind": "permission",
         "statement": "Only a manager may adjust stock."},
        {"path": "src/service.py", "lines": [2, 3], "quote": "raise NegativeStock()", "kind": "validation",
         "statement": "An adjustment that would make stock negative is refused."},
        {"path": "src/service.py", "lines": [9, 9], "quote": "this line is not in the file", "kind": "rule",
         "statement": "An invented fact."},
        {"path": "src/secret.py", "lines": [1, 1], "quote": "password = 1", "kind": "rule", "statement": "Not shown."},
    ], "none": [{"path": "src/util.py", "reason": "a helper with no behaviour"}]}


def orient(prompt):
    return {"capabilities": [{"id": "stock", "name": "Stock adjustment", "summary": "Correct stock by hand."}]}


def assign(prompt):
    return {"assignments": {obs_id: "stock" for obs_id in re.findall(r"^(OBS-\w+) \|", prompt, re.M)}}


def synthesise(prompt):
    ids = re.findall(r"^(OBS-\w+) \|", prompt, re.M)
    return {"requirements": [
        {"statement": "A manager can adjust the stock of an item.", "conditions": ["The result is not negative."],
         "level": "user", "evidence": [{"observation": i, "role": "establishes"} for i in ids]},
        {"statement": "The system emails the owner.", "evidence": [{"observation": "OBS-invented", "role": "establishes"}]},
    ], "open_questions": ["Is the adjustment logged?"]}


def assess(prompt):
    return {"verdicts": [{"id": i, "support": "partial", "note": "The link between the check and the route is not shown."}
                         for i in re.findall(r"^##### (REQ-\w+)", prompt, re.M)]}


def triage(prompt):
    """Every file is of low relevance, so triage settles and skips nothing."""
    return {"files": [{"path": path, "role": "other", "relevance": "low", "sure": True}
                      for path in re.findall(r"^=== FILE: (\S+)", prompt, re.M)]}


def fake():
    return FakeLLM({"triage": triage, "observe": observe, "orient": orient, "assign": assign,
                    "synthesise": synthesise, "assess": assess})


def run(tmp_path, llm=None, **changes):
    return extract(repo(tmp_path), Config(provider=llm or fake(), use_cache=False, **changes))


def test_only_observations_whose_citations_verify_are_kept(tmp_path):
    result = run(tmp_path)
    assert {o.statement for o in result.observations} == {
        "Only a manager may adjust stock.", "An adjustment that would make stock negative is refused."}
    assert {r.reason for r in result.diagnostics.rejected} == {"quote not found", "path was not shown to the model"}


def test_a_requirement_cites_only_real_observations_and_its_evidence_is_copied(tmp_path):
    result = run(tmp_path)
    assert [r.statement for r in result.requirements] == ["A manager can adjust the stock of an item."]
    requirement = result.requirements[0]
    known = {o.id: o for o in result.observations}
    for evidence in requirement.evidence:
        assert (evidence.path, evidence.lines, evidence.quote) == (
            known[evidence.observation].path, known[evidence.observation].lines, known[evidence.observation].quote)
    assert requirement.scope == "cross_file"
    assert requirement.support == "partial" and "not shown" in requirement.support_note


def test_every_file_is_in_exactly_one_state(tmp_path):
    result = run(tmp_path)
    states = {f.path: f.state for f in result.coverage.files}
    assert states == {"logo.png": "excluded", "src/policy.py": "extracted", "src/service.py": "extracted",
                      "src/util.py": "no_requirements"}
    assert sum(result.coverage.summary.values()) == 4
    assert result.run.status == "complete"


def test_without_the_support_check_requirements_are_not_assessed(tmp_path):
    assert run(tmp_path, assess_support=False).requirements[0].support == "not_assessed"


def test_evidence_that_only_shows_existence_cannot_be_rated_direct(tmp_path):
    def context_only(prompt):
        reply = synthesise(prompt)
        for evidence in reply["requirements"][0]["evidence"]:
            evidence["role"] = "context"
        return reply
    llm = FakeLLM({"observe": observe, "orient": orient, "assign": assign, "synthesise": context_only,
                   "assess": lambda p: {"verdicts": [{"id": i, "support": "direct"} for i in re.findall(r"##### (REQ-\w+)", p)]}})
    assert run(tmp_path, llm).requirements[0].support == "insufficient"


def test_a_failed_stage_makes_the_run_partial_and_names_the_files(tmp_path):
    llm = FakeLLM({"orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess})
    result = run(tmp_path, llm)
    assert result.run.status == "partial" and result.requirements == []
    assert {f.state for f in result.coverage.files if f.path.startswith("src/")} == {"failed"}


def test_a_malformed_reply_is_asked_for_again(tmp_path):
    attempts = []

    def flaky(prompt):
        attempts.append(prompt)
        return "not json at all" if len(attempts) == 1 else json.dumps(observe(prompt))
    llm = FakeLLM({"observe": flaky, "orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess})
    assert len(run(tmp_path, llm).observations) == 2
    assert "could not be used" in attempts[1]


def test_the_model_is_shown_real_line_numbers(tmp_path):
    llm = fake()
    run(tmp_path, llm)
    prompt = next(r.prompt for r in llm.requests if r.stage == "observe")
    assert "=== FILE: src/service.py (lines 1-5) ===" in prompt and "    3|         raise NegativeStock()" in prompt


def test_a_second_run_is_served_from_the_cache_and_replay_fails_on_a_miss(tmp_path):
    (tmp_path / "repo").mkdir()
    root, cache = repo(tmp_path / "repo"), tmp_path / "cache"
    first = extract(root, Config(provider=fake(), cache_dir=cache))
    second = extract(root, Config(provider=fake(), cache_dir=cache, replay=True))
    assert first.run.calls == 6 and second.run.calls == 0 and second.run.cached_calls == 6
    assert second.requirements == first.requirements
    (root / "src" / "service.py").write_text(SERVICE + "# changed\n")
    assert extract(root, Config(provider=fake(), cache_dir=cache, replay=True)).run.status == "partial"


def test_the_result_round_trips_through_json_and_renders(tmp_path):
    result = run(tmp_path)
    again = ExtractionResult.model_validate_json(result.to_json())
    assert again == result
    text = to_markdown(again)
    assert "## Stock adjustment" in text and "`src/policy.py:1-2`" in text and "Open question: Is the adjustment logged?" in text


def test_dry_run_lists_files_and_calls_no_model(tmp_path):
    done = CliRunner().invoke(app, ["extract", str(repo(tmp_path)), "--dry-run", "--provider", "none"])
    assert done.exit_code == 0 and "read      src/policy.py" in done.output and "excluded  logo.png" in done.output


def test_changing_one_stages_prompt_leaves_the_other_stages_cached(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    root, cache = repo(tmp_path / "repo"), tmp_path / "cache"
    extract(root, Config(provider=fake(), cache_dir=cache))
    from backspec.kernel import prompts
    real = prompts.load
    monkeypatch.setattr(prompts, "load", lambda name: real(name) + ("\nBe brief." if name == "synthesise" else ""))
    second = extract(root, Config(provider=fake(), cache_dir=cache))
    assert second.run.calls == 1 and second.run.cached_calls == 5
