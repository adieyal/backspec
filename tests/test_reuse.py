"""An unchanged file keeps the observations an earlier run made of it."""
from test_pipeline import SERVICE, assess, assign, fake, observe, orient, repo, synthesise

from reqx import Config, extract
from reqx.host.adapters.fake import FakeLLM


def saved(tmp_path, result):
    path = tmp_path / "previous.json"
    path.write_text(result.to_json())
    return path


def stages(llm):
    return [request.stage for request in llm.requests]


def test_unchanged_files_are_not_read_again_and_keep_their_observation_ids(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    llm = fake()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    assert "observe" not in stages(llm)
    assert [o.id for o in second.observations] == [o.id for o in first.observations]
    assert second.run.reused_files == 3 and first.run.reused_files == 0
    states = {f.path: f.state for f in second.coverage.files}
    assert states.pop("previous.json") == "excluded"   # the saved result itself is never read as source
    assert states == {f.path: f.state for f in first.coverage.files}


def test_a_model_that_answers_differently_the_second_time_changes_nothing_for_unchanged_files(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))

    def different(prompt):
        reply = observe(prompt)
        reply["observations"] = reply["observations"][:1]
        reply["observations"][0]["statement"] = "Worded another way."
        return reply
    llm = FakeLLM({"observe": different, "orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess})
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    assert [r.id for r in second.requirements] == [r.id for r in first.requirements]
    assert second.diagnostics.review.carried == len(first.requirements)


def test_only_a_changed_file_is_read_again(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    (root / "src" / "service.py").write_text(SERVICE + "\n# a new comment\n")
    llm = fake()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    prompt = next(r.prompt for r in llm.requests if r.stage == "observe")
    assert "=== FILE: src/service.py" in prompt and "=== FILE: src/policy.py" not in prompt
    assert second.run.reused_files == 2
    assert {o.path for o in second.observations} == {"src/policy.py", "src/service.py"}


def test_observations_made_another_way_are_not_reused(tmp_path, monkeypatch):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    from reqx.kernel import prompts
    real = prompts.load
    monkeypatch.setattr(prompts, "load", lambda name: real(name) + ("\nLook harder." if name == "observe" else ""))
    llm = fake()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    assert "observe" in stages(llm) and second.run.reused_files == 0


def test_reuse_can_be_turned_off(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    llm = fake()
    extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first), reuse=False))
    assert "observe" in stages(llm)


def test_a_previous_result_saved_inside_the_repository_is_not_read_as_source(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    inside = root / "reqs.json"
    inside.write_text(first.to_json())
    second = extract(root, Config(provider=fake(), use_cache=False, previous=inside))
    states = {f.path: (f.state, f.reason) for f in second.coverage.files}
    assert states["reqs.json"] == ("excluded", "exclude_pattern")
    assert second.run.reused_files == 3


def reworded(prompt):
    reply = synthesise(prompt)
    reply["requirements"][0]["statement"] = "Managers may correct stock levels."
    return reply


def rewording_llm():
    return FakeLLM({"observe": observe, "orient": orient, "assign": assign, "synthesise": reworded, "assess": assess})


def test_a_run_with_nothing_changed_calls_no_model_and_returns_the_same_requirements(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    llm = rewording_llm()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    assert stages(llm) == []
    assert [(r.id, r.statement, r.support) for r in second.requirements] == [
        (r.id, r.statement, r.support) for r in first.requirements]
    assert second.run.reused_capabilities == ["stock"] and second.run.capabilities_source == "previous"
    assert second.diagnostics.open_questions == first.diagnostics.open_questions


def test_a_capability_whose_evidence_changed_is_written_again(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    (root / "src" / "service.py").write_text(SERVICE + "\n# a new comment\n")
    llm = rewording_llm()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    assert "synthesise" in stages(llm) and "orient" not in stages(llm)
    assert second.run.reused_capabilities == []
    assert second.requirements[0].statement == "Managers may correct stock levels."
    assert second.requirements[0].id == first.requirements[0].id   # the id is still carried by its evidence


def test_requirements_written_another_way_are_not_reused(tmp_path, monkeypatch):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    from reqx.kernel import prompts
    real = prompts.load
    monkeypatch.setattr(prompts, "load", lambda name: real(name) + ("\nBe brief." if name == "synthesise" else ""))
    llm = rewording_llm()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    assert stages(llm) == ["synthesise", "assess"] and second.run.reused_capabilities == []


def test_a_rejected_requirement_is_kept_aside_and_stays_hidden_on_the_next_run(tmp_path):
    from reqx.host.composition import review_requirement
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    before = saved(tmp_path, first)
    review_file = tmp_path / "review.yaml"
    review_requirement(before, first.requirements[0].id, reject=True, reviewer="ana", review_file=review_file)
    second = extract(root, Config(provider=fake(), use_cache=False, previous=before, review_file=review_file))
    assert second.requirements == [] and [r.id for r in second.hidden] == [first.requirements[0].id]
    before.write_text(second.to_json())
    llm = fake()
    third = extract(root, Config(provider=llm, use_cache=False, previous=before, review_file=review_file))
    assert stages(llm) == [] and third.requirements == []
    assert [r.id for r in third.hidden] == [first.requirements[0].id]
    assert third.diagnostics.review.stale_entries == [] and third.diagnostics.review.rejected_hidden == 1


def test_an_observation_placed_before_is_not_put_to_the_model_again(tmp_path):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False))
    (root / "src" / "extra.py").write_text("def limit():\n    return 5\n")

    def observe_extra(prompt):
        return {"observations": [{"path": "src/extra.py", "lines": [1, 2], "quote": "return 5", "kind": "rule",
                                  "statement": "The limit is five."}]}
    llm = FakeLLM({"observe": observe_extra, "orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess})
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved(tmp_path, first)))
    asked = next(r.prompt for r in llm.requests if r.stage == "assign")
    listed = asked.split("# The observations")[1]
    assert listed.count("OBS-") == 1 and "The limit is five." in listed   # only the new observation is asked about
    assert len(second.assignments) == len(first.assignments) + 1
