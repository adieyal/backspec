"""Token usage and the soft budget, against a fake model that may or may not report usage."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from reqx import Config, LLMError, LLMRequest, extract
from reqx.host import cli
from reqx.host.adapters.cache import CachedLLM
from reqx.host.adapters.fake import FakeLLM
from reqx.kernel.usage import Usage, reservation
from test_pipeline import assess, assign, fake, observe, orient, repo, synthesise

STAGES = {"observe", "orient", "assign", "synthesise", "assess"}


def reporting(llm=None, tokens_in=100, tokens_out=10):
    llm = llm or fake()
    llm.report = lambda request, reply: Usage(tokens_in, tokens_out)
    return llm


def fresh_repo(tmp_path):
    """The fixture repository in a new folder, so a test can run it more than once."""
    folder = tmp_path / f"repo{len(list(tmp_path.iterdir()))}"
    folder.mkdir()
    return repo(folder)


def run(tmp_path, llm, **changes):
    return extract(fresh_repo(tmp_path), Config(provider=llm, use_cache=False, **changes))


def reservations(tmp_path):
    """What each stage would reserve in a normal run of the fixture repository."""
    llm = fake()
    run(tmp_path, llm)
    return {r.stage: reservation(r.stage, r.prompt) for r in llm.requests}


def test_totals_add_up_across_stages_and_cached_replies_count_zero(tmp_path):
    (tmp_path / "repo").mkdir()
    root, cache = repo(tmp_path / "repo"), tmp_path / "cache"
    first = extract(root, Config(provider=reporting(), cache_dir=cache))
    assert (first.run.input_tokens, first.run.output_tokens) == (500, 50)
    assert sum(u.input_tokens for u in first.run.usage_by_stage.values()) == 500
    assert sum(u.output_tokens for u in first.run.usage_by_stage.values()) == 50
    second = extract(root, Config(provider=reporting(), cache_dir=cache))
    assert (second.run.calls, second.run.cached_calls) == (0, 5)
    assert (second.run.input_tokens, second.run.output_tokens) == (0, 0)
    assert all(u.calls == 0 and u.cached == 1 and u.input_tokens == 0 for u in second.run.usage_by_stage.values())
    # a mix: only the synthesise prompt changed, so four stages are cached and one is paid for
    from reqx.kernel import prompts
    real = prompts.load
    prompts.load = lambda name: real(name) + ("\nBe brief." if name == "synthesise" else "")
    try:
        third = extract(root, Config(provider=reporting(), cache_dir=cache))
    finally:
        prompts.load = real
    assert (third.run.calls, third.run.cached_calls, third.run.input_tokens) == (1, 4, 100)
    assert third.run.usage_by_stage["synthesise"].calls == 1 and third.run.usage_by_stage["observe"].cached == 1


def test_the_per_stage_table_has_the_stages_that_ran(tmp_path):
    result = run(tmp_path, reporting())
    assert set(result.run.usage_by_stage) == STAGES
    assert all(u.calls == 1 and u.cached == 0 for u in result.run.usage_by_stage.values())
    assert run(tmp_path, reporting(), assess_support=False).run.usage_by_stage.keys() == STAGES - {"assess"}


def test_tokens_are_estimated_and_flagged_when_the_backend_reports_nothing(tmp_path):
    llm = fake()
    result = run(tmp_path, llm)
    assert result.run.tokens_estimated
    prompts_chars = sum(len(r.prompt) for r in llm.requests)
    assert result.run.input_tokens == sum((len(r.prompt) + 3) // 4 for r in llm.requests)
    assert result.run.input_tokens >= prompts_chars // 4 and result.run.output_tokens > 0


def test_a_backend_that_reports_usage_is_not_flagged_as_estimated(tmp_path):
    result = run(tmp_path, reporting())
    assert not result.run.tokens_estimated and result.run.cost_usd is None


def test_a_reported_cost_is_summed(tmp_path):
    llm = fake()
    llm.report = lambda request, reply: Usage(1, 1, cost_usd=0.5)
    assert run(tmp_path, llm).run.cost_usd == pytest.approx(2.5)


def test_a_budget_smaller_than_the_first_call_sends_nothing(tmp_path):
    llm = fake()
    result = run(tmp_path, llm, max_tokens=100)
    assert llm.requests == []
    assert result.run.status == "partial" and result.run.budget_reached
    assert result.run.calls == 0 and result.requirements == [] and result.observations == []
    assert {f.state for f in result.coverage.files if f.path.startswith("src/")} == {"failed"}
    assert all("budget" in f.reason for f in result.coverage.files if f.state == "failed")


def test_a_budget_that_allows_observe_but_not_orient_keeps_the_observations(tmp_path):
    needs = reservations(tmp_path)
    # the observe call uses up the whole budget, so the next call is refused
    result = run(tmp_path, reporting(tokens_in=needs["observe"], tokens_out=0), max_tokens=needs["observe"])
    assert len(result.observations) == 2 and result.requirements == []
    assert result.run.status == "partial" and result.run.budget_reached
    assert "budget" in result.diagnostics.failed_stages["orient"]
    assert set(result.run.usage_by_stage) == {"observe"}


def test_a_budget_that_allows_observe_but_not_synthesis_keeps_the_observations(tmp_path):
    needs = reservations(tmp_path)
    budget = max(needs["observe"], 110 + needs["orient"], 220 + needs["assign"])
    assert 330 + needs["synthesise"] > budget   # the fixture's numbers must leave synthesis out
    result = run(tmp_path, reporting(), max_tokens=budget)
    assert len(result.observations) == 2 and result.requirements == []
    assert result.run.status == "partial" and result.run.budget_reached
    assert "budget" in result.diagnostics.failed_capabilities["stock"]
    assert set(result.run.usage_by_stage) == {"observe", "orient", "assign"}


def test_a_run_without_a_budget_or_within_one_is_not_budget_stopped(tmp_path):
    assert not run(tmp_path, reporting()).run.budget_reached
    result = run(tmp_path, reporting(), max_tokens=10_000_000)
    assert result.run.status == "complete" and not result.run.budget_reached


def test_a_run_entirely_from_cache_passes_under_a_budget_of_one_token(tmp_path):
    (tmp_path / "repo").mkdir()
    root, cache = repo(tmp_path / "repo"), tmp_path / "cache"
    extract(root, Config(provider=fake(), cache_dir=cache))
    again = extract(root, Config(provider=fake(), cache_dir=cache, replay=True, max_tokens=1))
    assert again.run.status == "complete" and not again.run.budget_reached
    assert again.run.cached_calls == 5 and again.run.input_tokens == 0


def test_a_reservation_is_released_when_a_call_fails():
    failing = [True]

    def answer(prompt):
        if failing[0]:
            raise LLMError("observe: the model fell over")
        return "{}"
    llm = CachedLLM(FakeLLM({"observe": answer}), None, max_tokens=reservation("observe", "hello"))
    request = LLMRequest("observe", "hello")
    for _ in range(3):   # each failure would leave the budget short if its reservation were kept
        with pytest.raises(LLMError, match="fell over"):
            llm.complete(request)
    failing[0] = False
    assert llm.complete(request) == "{}"
    assert not llm.budget_reached and llm.spend().by_stage["observe"]["calls"] == 1


def test_a_call_over_the_budget_is_refused_with_a_message_that_says_so():
    llm = CachedLLM(FakeLLM({"observe": lambda p: "{}"}), None, max_tokens=10)
    with pytest.raises(LLMError, match="token budget reached"):
        llm.complete(LLMRequest("observe", "hello"))
    assert llm.budget_reached and llm.calls == 0


def test_usage_is_read_in_the_thread_that_made_the_call():
    inner = FakeLLM({"observe": lambda p: (time.sleep(0.01), "{}")[1]})
    inner.report = lambda request, reply: Usage(len(request.prompt), 0)
    llm = CachedLLM(inner, None)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda n: llm.complete(LLMRequest("observe", "x" * (n + 1))), range(40)))
    assert llm.spend().input_tokens == sum(range(1, 41)) and not llm.spend().estimated


def test_parallel_calls_overshoot_the_budget_by_no_more_than_the_documented_bound():
    workers, calls, budget = 8, 60, 20_000
    prompt = "x" * 400
    held = reservation("observe", prompt)
    extra = 150   # each reply costs this much more than was reserved
    inner = FakeLLM({"observe": lambda p: (time.sleep(0.01), "{}")[1]})
    inner.report = lambda request, reply: Usage(held - 3000 + 0, 3000 + extra)
    llm = CachedLLM(inner, None, max_tokens=budget)
    refused, lock = [], threading.Lock()

    def call(_):
        try:
            llm.complete(LLMRequest("observe", prompt))
        except LLMError:
            with lock:
                refused.append(1)
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(call, range(calls)))
    spent = llm.spend().input_tokens + llm.spend().output_tokens
    assert refused and llm.calls + len(refused) == calls and llm.budget_reached
    assert spent <= budget + workers * extra          # the bound: calls in flight x their estimation error
    assert spent > budget - held                      # and the budget was used, not left idle


def test_the_command_line_says_so_when_the_budget_was_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "extract", lambda path, config, progress: extract(
        path, replace(config, provider=fake(), use_cache=False), progress))
    done = CliRunner().invoke(cli.app, ["extract", str(repo(tmp_path)), "--max-tokens", "100"])
    assert done.exit_code == 1
    assert "token budget reached: 0 tokens used (limit 100)" in done.output


def test_the_final_line_shows_the_token_totals_and_marks_estimates(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "extract", lambda path, config, progress: extract(
        path, replace(config, provider=fake(), use_cache=False), progress))
    done = CliRunner().invoke(cli.app, ["extract", str(repo(tmp_path))])
    assert done.exit_code == 0 and "tokens in" in done.output and "(estimated)" in done.output


def test_the_dry_run_estimates_the_tokens_of_the_files_to_read(tmp_path):
    root = repo(tmp_path)
    done = CliRunner().invoke(cli.app, ["extract", str(root), "--dry-run"])
    chars = sum(len((root / "src" / name).read_text()) for name in ("policy.py", "service.py", "util.py"))
    assert done.exit_code == 0 and f"about {chars // 4} tokens to read" in done.output


def test_the_claude_code_envelope_is_read_as_input_including_cache_fields():
    from reqx.host.adapters.claude_code import _usage
    envelope = {"total_cost_usd": 0.00026, "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1311,
                                                    "cache_read_input_tokens": 5, "output_tokens": 9}}
    assert _usage(envelope) == Usage(1318, 9, False, 0.00026)
    assert _usage({"usage": {"output_tokens": 3}}) == Usage(0, 3, False, None)
    assert _usage({"result": "x"}) is None
