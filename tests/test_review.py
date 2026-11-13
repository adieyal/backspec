"""Durable ids and the review file: what survives from one run to the next."""
import re

import yaml
from typer.testing import CliRunner

from reqx import Config, extract
from reqx.host.adapters.fake import FakeLLM
from reqx.host.cli import app
from reqx.modules.review.domain import Known, ReviewEntry, anchors_of, carry_ids

POLICY = "def can_adjust(user):\n    return user.role == 'manager'\n"
SERVICE = "def adjust(item, delta):\n    if item.quantity + delta < 0:\n        raise NegativeStock()\n    item.quantity += delta\n"


def repo(root):
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "policy.py").write_text(POLICY)
    (root / "src" / "service.py").write_text(SERVICE)
    return root


def llm(statement="A manager can adjust the stock of an item.", only=None):
    def observe(prompt):
        return {"observations": [
            {"path": "src/policy.py", "lines": [1, 2], "quote": "return user.role == 'manager'", "kind": "permission",
             "statement": "Only a manager may adjust stock."},
            {"path": "src/service.py", "lines": [2, 3], "quote": "raise NegativeStock()", "kind": "validation",
             "statement": "A negative result is refused."}]}

    def synth(prompt):
        ids = re.findall(r"^(OBS-\w+) \|", prompt, re.M)
        return {"requirements": [{"statement": statement, "conditions": ["Not negative."],
                                  "evidence": [{"observation": i, "role": "establishes"} for i in ids]}]}
    return FakeLLM({
        "observe": observe,
        "orient": lambda p: {"capabilities": [{"id": "stock", "name": "Stock", "summary": "Stock."}]},
        "assign": lambda p: {"assignments": {i: "stock" for i in re.findall(r"^(OBS-\w+) \|", p, re.M)}},
        "synthesise": synth,
        "assess": lambda p: {"verdicts": []}})


def run(root, statement="A manager can adjust the stock of an item.", **config):
    return extract(root, Config(provider=llm(statement), use_cache=False, **config))


def first_run(tmp_path, statement="A manager can adjust the stock of an item."):
    root = repo(tmp_path / "repo") if (tmp_path / "repo").exists() else repo(_mk(tmp_path / "repo"))
    result = run(root, statement)
    saved = tmp_path / "first.json"
    saved.write_text(result.to_json())
    return root, result, saved


def _mk(path):
    path.mkdir()
    return path


def write_entries(root, entries):
    (root / "reqx.review.yaml").write_text(yaml.safe_dump({"entries": entries}))


def entry(requirement, decision, **fields):
    anchors = sorted(anchors_of((e.path, e.quote) for e in requirement.evidence))
    return {"id": requirement.id, "decision": decision, "reviewer": "ana", "date": "2026-01-01",
            "anchors": [list(a) for a in anchors], **fields}


# domain

def known(id_, pairs, reviewed=False):
    return Known(id_, frozenset(pairs), reviewed)


def a(*names):
    return [("f.py", n) for n in names]


def test_a_reworded_requirement_with_the_same_evidence_keeps_its_id():
    result = carry_ids([("REQ-new", frozenset(a("x", "y")))], [known("REQ-old", a("x", "y"))])
    assert result[0].id == "REQ-old" and result[0].carried


def test_a_requirement_that_gained_one_piece_of_evidence_out_of_three_still_matches():
    result = carry_ids([("REQ-new", frozenset(a("x", "y", "z", "w")))], [known("REQ-old", a("x", "y", "z"))])
    assert result[0].id == "REQ-old"   # 3 shared of 4 in the union


def test_quotes_are_compared_with_whitespace_squashed():
    assert anchors_of([("f.py", "a  b\n c")]) == anchors_of([("f.py", "a b c")])


def test_an_ambiguous_split_keeps_new_ids_and_flags_when_the_previous_one_was_reviewed():
    new = [("REQ-1", frozenset(a("x", "y"))), ("REQ-2", frozenset(a("x", "y")))]
    result = carry_ids(new, [known("REQ-old", a("x", "y"), reviewed=True)])
    assert [c.id for c in result] == ["REQ-1", "REQ-2"]
    assert all(c.ambiguous_reviewed and not c.carried for c in result)
    unreviewed = carry_ids(new, [known("REQ-old", a("x", "y"))])
    assert not any(c.ambiguous_reviewed for c in unreviewed)


def test_no_two_requirements_share_an_id():
    new = [("REQ-old", frozenset(a("p", "q"))), ("REQ-old", frozenset(a("p", "q"))), ("REQ-b", frozenset(a("x", "y")))]
    result = carry_ids(new, [known("REQ-b", a("p", "q")), known("REQ-c", a("x", "y"))])
    ids = [c.id for c in result]
    assert len(set(ids)) == len(ids)


def test_a_new_requirement_cannot_steal_an_id_that_another_carries():
    new = [("REQ-b", frozenset(a("z", "w"))), ("REQ-n", frozenset(a("x", "y")))]
    result = carry_ids(new, [known("REQ-b", a("x", "y"))])
    assert result[1].id == "REQ-b" and result[0].id != "REQ-b"


# use cases

def test_a_second_run_with_a_reworded_statement_keeps_the_id_from_the_first(tmp_path):
    root, first, saved = first_run(tmp_path)
    second = run(root, "Managers may correct stock levels.", previous=saved)
    assert second.requirements[0].statement == "Managers may correct stock levels."
    assert second.requirements[0].id == first.requirements[0].id
    assert second.diagnostics.review.carried == 1 and second.diagnostics.review.new == 0


def test_without_a_previous_result_or_a_review_file_nothing_changes(tmp_path):
    root, first, _ = first_run(tmp_path)
    assert first.diagnostics.review is None and first.requirements[0].review == "unreviewed"


def test_confirm_marks_the_requirement_confirmed(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [entry(first.requirements[0], "confirm")])
    result = run(root, previous=saved)
    assert result.requirements[0].review == "confirmed" and result.diagnostics.review.confirmed == 1


def test_edit_replaces_statement_and_conditions_and_keeps_the_id(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [entry(first.requirements[0], "edit", statement="Only managers adjust stock.",
                               conditions=["Never below zero."])])
    result = run(root, "Something else entirely.", previous=saved)
    requirement = result.requirements[0]
    assert (requirement.statement, requirement.conditions, requirement.review) == (
        "Only managers adjust stock.", ["Never below zero."], "edited")
    assert requirement.id == first.requirements[0].id and result.diagnostics.review.edited == 1


def test_reject_hides_the_requirement_and_counts_it(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [entry(first.requirements[0], "reject")])
    result = run(root, previous=saved)
    assert result.requirements == [] and result.diagnostics.review.rejected_hidden == 1


def test_a_rejected_requirement_stays_hidden_on_the_run_after_even_when_reworded(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [entry(first.requirements[0], "reject")])
    hidden = run(root, previous=saved)
    saved.write_text(hidden.to_json())
    again = run(root, "Reworded again.", previous=saved)
    assert again.requirements == [] and again.diagnostics.review.rejected_hidden == 1
    assert again.diagnostics.review.stale_entries == []


def test_a_rejected_requirement_whose_evidence_changed_comes_back_as_needs_review(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [entry(first.requirements[0], "reject")])
    (root / "src" / "service.py").write_text(SERVICE.replace("raise NegativeStock()", "raise  NegativeStock( )"))
    changed = FakeLLM({**llm().answers, "observe": lambda p: {"observations": [
        {"path": "src/policy.py", "lines": [1, 2], "quote": "return user.role == 'manager'", "kind": "permission",
         "statement": "Only a manager may adjust stock."},
        {"path": "src/service.py", "lines": [2, 3], "quote": "raise  NegativeStock( )", "kind": "validation",
         "statement": "A negative result is refused."}]}})
    result = extract(root, Config(provider=changed, use_cache=False, previous=saved))
    assert [r.review for r in result.requirements] == ["needs_review"]
    assert result.requirements[0].id == first.requirements[0].id
    assert result.diagnostics.review.needs_review == 1 and result.diagnostics.review.rejected_hidden == 0


def test_an_entry_for_an_unknown_requirement_is_reported_stale_and_kept(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [{"id": "REQ-gone", "decision": "confirm", "reviewer": "ana", "date": "2026-01-01",
                          "anchors": [["gone.py", "nothing"]]}])
    result = run(root, previous=saved)
    assert result.diagnostics.review.stale_entries == ["REQ-gone"]
    assert "REQ-gone" in (root / "reqx.review.yaml").read_text()


def test_the_review_command_writes_an_entry_that_the_next_run_applies(tmp_path):
    root, first, saved = first_run(tmp_path)
    requirement = first.requirements[0]
    review_file = tmp_path / "mine.yaml"
    runner = CliRunner()
    done = runner.invoke(app, ["review", str(saved), requirement.id, "--statement", "Managers only.",
                               "--condition", "Not negative.", "--reviewer", "ana", "--note", "ok",
                               "--review", str(review_file)])
    assert done.exit_code == 0 and requirement.id in done.output and len(done.output.strip().splitlines()) == 1
    written = yaml.safe_load(review_file.read_text())["entries"][0]
    assert written["decision"] == "edit" and written["reviewer"] == "ana" and written["note"] == "ok"
    assert written["anchors"] and written["conditions"] == ["Not negative."]
    result = run(root, "Reworded.", previous=saved, review_file=review_file)
    assert (result.requirements[0].statement, result.requirements[0].review) == ("Managers only.", "edited")
    # replacing the entry keeps one per id
    runner.invoke(app, ["review", str(saved), requirement.id, "--confirm", "--review", str(review_file)])
    assert len(yaml.safe_load(review_file.read_text())["entries"]) == 1


def test_the_review_command_rejects_an_unknown_id_and_a_bad_combination(tmp_path):
    root, first, saved = first_run(tmp_path)
    runner = CliRunner()
    unknown = runner.invoke(app, ["review", str(saved), "REQ-nope", "--confirm", "--review", str(tmp_path / "r.yaml")])
    assert unknown.exit_code == 2 and not (tmp_path / "r.yaml").exists()
    both = runner.invoke(app, ["review", str(saved), first.requirements[0].id, "--confirm", "--reject"])
    assert both.exit_code == 2


def test_the_default_review_file_under_the_root_is_used_when_it_exists(tmp_path):
    root, first, saved = first_run(tmp_path)
    write_entries(root, [entry(first.requirements[0], "confirm")])
    assert run(root).requirements[0].review == "confirmed"      # no previous result needed


def test_an_existing_json_output_file_is_the_previous_result_unless_one_is_named(tmp_path):
    from reqx.host.composition import default_previous
    out = tmp_path / "reqs.json"
    assert default_previous(None, out) is None
    out.write_text("{}")
    assert default_previous(None, out) == out
    assert default_previous(None, out, "md") is None
    assert default_previous(tmp_path / "p.json", out) == tmp_path / "p.json"
