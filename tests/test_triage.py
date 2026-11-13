"""Triage: a cheap first look that skips files surely of no relevance, and an audit of what it skips."""
import re

import pytest
from typer.testing import CliRunner

from reqx import Config, extract
from reqx.host import cli
from reqx.host.adapters.fake import FakeLLM
from reqx.modules.triage.domain import (AUDIT_MAX, AUDIT_MIN, BATCH_FILES, PREVIEW_LINES, audit_sample, audit_size,
                                        clopper_pearson, is_skipped, pack, preview)
from test_pipeline import assess, assign, observe, orient, synthesise

POLICY = "def can_adjust(user):\n    return user.role == 'manager'\n"
SERVICE = "def adjust(item, delta):\n    if item.quantity + delta < 0:\n        raise NegativeStock()\n    item.quantity += delta\n"


def repo(tmp_path, extra=()):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "policy.py").write_text(POLICY)
    (tmp_path / "src" / "service.py").write_text(SERVICE)
    (tmp_path / "src" / "util.py").write_text("def noop():\n    pass\n")
    (tmp_path / "data.txt").write_text("1,2,3\n4,5,6\n")
    for name in extra:
        (tmp_path / "src" / name).write_text(f"x = '{name}'\n")
    return tmp_path


def triage_with(verdicts, default=None):
    """A triage answer. `verdicts` maps path -> (role, relevance, sure); a path left out is not mentioned
    unless there is a `default`."""
    def answer(prompt):
        files = []
        for path in re.findall(r"^=== FILE: (\S+)", prompt, re.M):
            verdict = verdicts.get(path, default)
            if verdict:
                files.append({"path": path, "role": verdict[0], "relevance": verdict[1], "sure": verdict[2]})
        return {"files": files}
    return answer


def fake(triage=None, observer=observe):
    answers = {"observe": observer, "orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess}
    if triage is not None:
        answers["triage"] = triage
    return FakeLLM(answers)


def states(result):
    return {f.path: f.state for f in result.coverage.files}


def run(root, llm, **changes):
    changes.setdefault("triage_audit", 0)
    return extract(root, Config(provider=llm, use_cache=False, **changes))


def observed_paths(llm):
    return {path for r in llm.requests if r.stage == "observe" for path in re.findall(r"^=== FILE: (\S+)", r.prompt, re.M)}


def saved(tmp_path, result):
    path = tmp_path / "previous.json"
    path.write_text(result.to_json())
    return path


# the rule

def test_only_a_sure_none_is_skipped():
    assert is_skipped("none", True)
    assert not is_skipped("none", False)
    assert not any(is_skipped(r, s) for r in ("high", "medium", "low", "unknown", "") for s in (True, False))


def test_a_sure_none_is_not_read_and_is_triaged_out_with_its_role(tmp_path):
    llm = fake(triage_with({"data.txt": ("data", "none", True)}, default=("domain", "high", True)))
    result = run(repo(tmp_path), llm)
    assert states(result)["data.txt"] == "triaged_out"
    covered = next(f for f in result.coverage.files if f.path == "data.txt")
    assert covered.reason == "data" and covered.triage_role == "data" and covered.triage_skipped
    assert covered.source_hash and not covered.line_digest and not covered.observations
    assert "data.txt" not in observed_paths(llm)
    assert result.run.status == "complete"


def test_an_unsure_none_a_low_and_an_unmentioned_file_are_all_read(tmp_path):
    root = repo(tmp_path, extra=["left_out.py"])
    llm = fake(triage_with({"data.txt": ("data", "none", False), "src/util.py": ("other", "low", True),
                            "src/policy.py": ("domain", "high", True), "src/service.py": ("domain", "none", True)}))
    result = run(root, llm)
    assert observed_paths(llm) == {"data.txt", "src/util.py", "src/policy.py", "src/left_out.py"}
    assert states(result)["src/service.py"] == "triaged_out"
    assert result.diagnostics.triage_unresolved == {"src/left_out.py": "the triage reply did not mention this file"}


def test_a_failed_triage_call_means_every_file_is_read_and_is_recorded(tmp_path):
    llm = fake()   # no triage answer: the call fails
    result = run(repo(tmp_path), llm)
    assert observed_paths(llm) == {"data.txt", "src/policy.py", "src/service.py", "src/util.py"}
    assert "triaged_out" not in states(result).values()
    assert set(result.diagnostics.triage_unresolved) == observed_paths(llm)
    assert all("triage call failed" in why for why in result.diagnostics.triage_unresolved.values())
    assert result.run.status == "complete"


def test_a_garbled_role_or_relevance_never_causes_a_skip(tmp_path):
    llm = fake(triage_with({"data.txt": ("banana", "nothing", True)}, default=("domain", "high", True)))
    result = run(repo(tmp_path), llm)
    covered = next(f for f in result.coverage.files if f.path == "data.txt")
    assert covered.state != "triaged_out" and covered.triage_role == "other" and covered.triage_relevance == "unknown"


def test_the_model_sees_the_path_size_and_first_forty_numbered_lines(tmp_path):
    root = repo(tmp_path)
    (root / "src" / "long.py").write_text("\n".join(f"line{n}" for n in range(1, 101)))
    llm = fake(triage_with({}, default=("domain", "high", True)))
    run(root, llm)
    prompt = next(r.prompt for r in llm.requests if r.stage == "triage")
    assert "=== FILE: src/long.py (100 lines, first 40 shown) ===" in prompt
    assert "   40| line40" in prompt and "line41" not in prompt
    assert "=== FILE: src/util.py (3 lines) ===" in prompt
    assert next(r.tier for r in llm.requests if r.stage == "triage") == "fast"


def test_batches_are_about_sixty_files_or_twenty_five_hundred_preview_lines():
    assert [len(b) for b in pack([(f"f{n}", 5) for n in range(130)])] == [BATCH_FILES, BATCH_FILES, 10]
    assert len(pack([(f"f{n}", 1000) for n in range(100)])) == 2   # 40 preview lines each: 62 would fit; 60 files is the limit
    assert [len(b) for b in pack([(f"f{n}", 1000) for n in range(61)])] == [60, 1]
    assert preview("a.py", ["x"] * 3).startswith("=== FILE: a.py (3 lines) ===")
    assert PREVIEW_LINES == 40


# the audit

def hashes(n):
    return [(f"f{i:03d}.py", f"sha256:{i}") for i in range(n)]


def test_the_audit_sample_is_deterministic_and_does_not_depend_on_order():
    first = audit_sample(hashes(100), 0.1)
    assert first == audit_sample(list(reversed(hashes(100))), 0.1)
    assert len(first) == 10 and first == sorted(first)
    assert set(audit_sample(hashes(100), 0.1)) <= set(audit_sample(hashes(100), 0.3))   # a larger sample extends it


def test_the_audit_reads_at_least_five_at_most_fifty_and_all_when_fewer_than_five():
    assert audit_size(3, 0.1) == 3 and audit_size(4, 0.1) == 4
    assert audit_size(20, 0.1) == AUDIT_MIN == 5 and audit_size(5, 0.1) == 5
    assert audit_size(200, 0.1) == 20
    assert audit_size(1000, 0.1) == AUDIT_MAX == 50
    assert audit_size(1000, 0.9) == 50
    assert audit_size(0, 0.5) == 0


def test_an_audit_of_zero_is_off_and_of_one_reads_everything_skipped():
    assert audit_sample(hashes(10), 0) == []
    assert len(audit_sample(hashes(300), 1.0)) == 300


def audited_repo(tmp_path):
    return repo(tmp_path), triage_with({"src/policy.py": ("domain", "none", True), "src/util.py": ("other", "none", True)},
                                       default=("domain", "high", True))


def test_an_audited_file_with_a_verified_observation_is_not_triaged_out_and_counts_as_yielded(tmp_path):
    root, triage = audited_repo(tmp_path)
    llm = fake(triage)
    result = run(root, llm, triage_audit=1.0)
    assert {"src/policy.py", "src/util.py"} <= observed_paths(llm)
    assert states(result)["src/policy.py"] == "extracted"
    assert states(result)["src/util.py"] == "triaged_out"   # audited, yielded nothing
    policy = next(f for f in result.coverage.files if f.path == "src/policy.py")
    assert policy.found_by_audit and policy.triage_audited and policy.triage_skipped and policy.line_digest
    audit = result.coverage.triage_audit
    assert (audit.skipped, audit.audited, audit.yielded, audit.yielded_paths) == (2, 2, 1, ["src/policy.py"])
    low, high = audit.miss_rate_interval
    assert 0 < low < 0.5 < high < 1
    assert "Only a manager may adjust stock." in {o.statement for o in result.observations}


def test_without_an_audit_nothing_skipped_is_read_and_the_interval_is_null(tmp_path):
    root, triage = audited_repo(tmp_path)
    llm = fake(triage)
    result = run(root, llm, triage_audit=0)
    assert {"src/policy.py", "src/util.py"}.isdisjoint(observed_paths(llm))
    audit = result.coverage.triage_audit
    assert (audit.skipped, audit.audited, audit.yielded, audit.miss_rate_interval) == (2, 0, 0, None)
    assert result.coverage.summary["triaged_out"] == 2


def test_the_default_audit_reads_every_skipped_file_when_fewer_than_five_were_skipped(tmp_path):
    root, triage = audited_repo(tmp_path)
    result = extract(root, Config(provider=fake(triage), use_cache=False))
    assert result.coverage.triage_audit.audited == 2


def test_a_failed_audit_read_is_listed_and_not_counted(tmp_path):
    root, triage = audited_repo(tmp_path)
    result = run(root, fake(triage, observer=lambda prompt: "not json"), triage_audit=1.0)
    audit = result.coverage.triage_audit
    assert audit.audited == 0 and sorted(audit.failed_paths) == ["src/policy.py", "src/util.py"]
    assert states(result)["src/policy.py"] == "failed" and result.run.status == "partial"


def test_the_interval_for_no_misses_in_eight_has_an_upper_bound_near_037_and_none_for_zero_audited():
    low, high = clopper_pearson(0, 8)
    assert low == 0.0 and high == pytest.approx(0.3694, abs=0.001)
    assert clopper_pearson(0, 0) is None
    low, high = clopper_pearson(1, 10)
    assert (low, high) == (pytest.approx(0.0025, abs=0.0005), pytest.approx(0.4450, abs=0.001))
    assert clopper_pearson(8, 8) == (pytest.approx(0.6306, abs=0.001), 1.0)


# reuse

def test_an_unchanged_file_keeps_its_verdict_and_is_not_triaged_again(tmp_path):
    root, triage = audited_repo(tmp_path)
    first = run(root, fake(triage))
    llm = fake(triage)
    second = run(root, llm, previous=saved(tmp_path, first))
    assert [r.stage for r in llm.requests] == []
    assert states(second) == {**states(first), "previous.json": "excluded"}
    assert second.run.triage_fingerprint == first.run.triage_fingerprint != ""
    assert second.coverage.triage_audit == first.coverage.triage_audit


def test_an_audited_file_that_yielded_nothing_is_not_read_again_when_unchanged(tmp_path):
    root, triage = audited_repo(tmp_path)
    first = run(root, fake(triage), triage_audit=1.0)
    llm = fake(triage)
    second = run(root, llm, triage_audit=1.0, previous=saved(tmp_path, first))
    assert [r.stage for r in llm.requests] == []
    assert second.coverage.triage_audit == first.coverage.triage_audit


def test_a_changed_file_is_triaged_again_and_the_unchanged_ones_are_not(tmp_path):
    root, triage = audited_repo(tmp_path)
    first = run(root, fake(triage))
    (root / "src" / "util.py").write_text("def noop():\n    return 1\n")
    seen = []

    def spy(prompt):
        seen.extend(re.findall(r"^=== FILE: (\S+)", prompt, re.M))
        return triage_with({}, default=("domain", "high", True))(prompt)
    llm = fake(spy)
    second = run(root, llm, previous=saved(tmp_path, first))
    assert seen == ["src/util.py"]
    assert states(second)["src/util.py"] != "triaged_out" and states(second)["src/policy.py"] == "triaged_out"


def test_verdicts_made_with_another_prompt_are_not_reused(tmp_path, monkeypatch):
    root, triage = audited_repo(tmp_path)
    first = run(root, fake(triage))
    from reqx.kernel import prompts
    real = prompts.load
    monkeypatch.setattr(prompts, "load", lambda name: real(name) + ("\nLook harder." if name == "triage" else ""))
    llm = fake(triage)
    second = run(root, llm, previous=saved(tmp_path, first))
    assert "triage" in [r.stage for r in llm.requests]
    assert second.run.triage_fingerprint != first.run.triage_fingerprint


def test_a_file_with_no_verdict_is_triaged_again_next_time(tmp_path):
    root = repo(tmp_path)
    first = run(root, fake())   # triage failed
    llm = fake(triage_with({"data.txt": ("data", "none", True)}, default=("domain", "high", True)))
    second = run(root, llm, previous=saved(tmp_path, first))
    assert states(second)["data.txt"] == "triaged_out"


# switching it off

def test_no_triage_reads_every_file_and_makes_no_triage_call(tmp_path):
    root, triage = audited_repo(tmp_path)
    llm = fake(triage)
    result = run(root, llm, triage=False)
    assert "triage" not in [r.stage for r in llm.requests]
    assert observed_paths(llm) == {"data.txt", "src/policy.py", "src/service.py", "src/util.py"}
    assert "triaged_out" not in states(result).values()
    assert result.coverage.triage_audit is None and result.run.triage_fingerprint == ""


def test_the_flags_become_config_fields(tmp_path, monkeypatch):
    seen = []

    def capture(path, config, progress=None):
        seen.append(config)
        raise cli.LLMError("stop here")
    monkeypatch.setattr(cli, "extract", capture)
    runner = CliRunner()
    runner.invoke(cli.app, ["extract", str(tmp_path)])
    runner.invoke(cli.app, ["extract", str(tmp_path), "--no-triage", "--triage-audit", "0.25"])
    assert (seen[0].triage, seen[0].triage_audit) == (True, 0.1)
    assert (seen[1].triage, seen[1].triage_audit) == (False, 0.25)
    assert runner.invoke(cli.app, ["extract", str(tmp_path), "--triage-audit", "1.5"]).exit_code != 0
