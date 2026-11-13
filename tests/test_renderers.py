"""Output formats and scenarios: what reqx writes for spreadsheets and spec tools."""
import csv
import io
import re

import pytest
from typer.testing import CliRunner

from reqx import Config, ExtractionResult, extract, to_markdown
from reqx.host.adapters.fake import FakeLLM
from reqx.host.cli import app
from reqx.modules.report.domain import requirement_title, with_shall
from reqx.modules.report.facade import UnknownFormat, formats, render
from reqx.modules.requirements.domain import (MergeGroup, RawScenario, CitedObservation, Requirement, Scenario,
                                              Evidence, build_scenarios, merge_requirements)
from tests.test_pipeline import assign, observe, orient, repo

VERDICTS = {
    "Managers adjust stock, but never below zero.": ("partial", "The route is not shown."),
    "Stock must never go negative.": ("direct", ""),
    "The system SHALL log every adjustment.": ("insufficient", "Only a log call exists."),
    "Adjustments are limited to one per day.": ("conflicting", "The code allows several."),
}


def synthesise(prompt):
    ids = re.findall(r"^(OBS-\w+) \|", prompt, re.M)
    cite = lambda *i: [{"observation": x, "role": "establishes"} for x in i]
    return {"requirements": [
        {"statement": "Managers adjust stock, but never below zero.", "conditions": ["a, b", "line\none"],
         "evidence": cite(*ids), "scenarios": [
             {"name": "Refused below zero", "given": "stock is 1", "when": "a manager removes 2",
              "then": "the adjustment is refused", "evidence": cite(ids[1])},
             {"name": "Invented", "given": "g", "when": "w", "then": "t", "evidence": cite("OBS-invented")},
             {"name": "Missing a part", "given": "g", "when": "w", "then": " ", "evidence": cite(ids[0])}]},
        {"statement": "Stock must never go negative.", "evidence": cite(ids[1])},
        {"statement": "The system SHALL log every adjustment.", "evidence": cite(ids[0])},
        {"statement": "Adjustments are limited to one per day.", "evidence": cite(ids[0])},
    ]}


def assess(prompt):
    out = []
    for rid, statement in re.findall(r"^##### (REQ-\w+)\nSTATEMENT: (.*)$", prompt, re.M):
        support, note = VERDICTS[statement]
        out.append({"id": rid, "support": support, "note": note})
    return {"verdicts": out}


@pytest.fixture
def result(tmp_path):
    llm = FakeLLM({"observe": observe, "orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess})
    return extract(repo(tmp_path), Config(provider=llm, use_cache=False))


def by_statement(result, start):
    return next(r for r in result.requirements if r.statement.startswith(start))


def test_a_scenario_citing_real_observations_is_kept_with_copied_evidence(result):
    scenario = by_statement(result, "Managers").scenarios[0]
    known = {o.id: o for o in result.observations}
    assert scenario.name == "Refused below zero" and scenario.then == "the adjustment is refused"
    (evidence,) = scenario.evidence
    assert (evidence.path, evidence.lines, evidence.quote) == (
        known[evidence.observation].path, known[evidence.observation].lines, known[evidence.observation].quote)


def test_a_scenario_with_an_invented_id_or_a_missing_part_is_dropped_and_counted(result):
    assert [s.name for s in by_statement(result, "Managers").scenarios] == ["Refused below zero"]
    assert result.diagnostics.dropped_scenarios == 2


def test_scenarios_survive_a_json_round_trip_and_older_results_load_without_them(result):
    again = ExtractionResult.model_validate_json(result.to_json())
    assert again == result
    assert Requirement(id="R", capability="c", statement="s", scope="local", evidence=[]).scenarios == []


def test_build_scenarios_counts_each_drop():
    class Obs:
        id, kind, path, lines, statement, quote = "OBS-1", "test_case", "a.py", (1, 2), "s", "q"
    raws = [RawScenario(name="n", given="g", when="w", then="t", evidence=[CitedObservation(observation="OBS-1")]),
            RawScenario(name="n2", given="g", when="w", then="t", evidence=[]),
            RawScenario(name="n3", given=None, when="w", then="t", evidence=[CitedObservation(observation="OBS-1")])]
    kept, dropped = build_scenarios(raws, {"OBS-1": Obs()})
    assert [s.name for s in kept] == ["n"] and dropped == 2


def test_a_merged_requirement_keeps_the_union_of_scenarios_without_repeats():
    ev = [Evidence(observation="OBS-1", role="establishes", path="a.py", lines=(1, 1), quote="q")]
    one = Scenario(name="Same", given="g", when="w", then="t", evidence=ev)
    other = Scenario(name="Other", given="g2", when="w2", then="t2", evidence=ev)

    def req(i, scenarios):
        return Requirement(id=i, capability="c", statement=i, scope="local", evidence=ev, scenarios=scenarios)
    merged = merge_requirements([req("A", [one]), req("B", [one.model_copy(), other])],
                                [MergeGroup(statement="Both", merge=["A", "B"])])
    assert len(merged) == 1 and [s.name for s in merged[0].scenarios] == ["Same", "Other"]


def test_csv_has_one_row_per_evidence_pair_and_parses_back(result):
    text = render(result, "csv").text
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert list(rows[0]) == ["requirement_id", "capability", "statement", "conditions", "level", "support", "review",
                             "scope", "evidence_role", "path", "first_line", "last_line", "quote"]
    assert len(rows) == sum(len(r.evidence) for r in result.requirements)
    first = by_statement(result, "Managers")
    mine = [r for r in rows if r["requirement_id"] == first.id]
    assert len(mine) == len(first.evidence) == 2
    assert {r["path"] for r in mine} == {"src/policy.py", "src/service.py"}
    assert mine[0]["statement"] == "Managers adjust stock, but never below zero."   # comma survives
    assert mine[0]["conditions"] == "a, b | line\none"                               # comma and newline survive
    assert "hidden" not in rows[0]


def test_csv_includes_hidden_requirements_only_when_asked(result):
    hidden = result.requirements[0]
    result = result.model_copy(update={"requirements": result.requirements[1:], "hidden": [hidden]})
    assert hidden.id not in render(result, "csv").text
    rows = list(csv.DictReader(io.StringIO(render(result, "csv", include_hidden=True).text, newline="")))
    assert {r["requirement_id"]: r["hidden"] for r in rows}[hidden.id] == "true"
    assert "false" in {r["hidden"] for r in rows}


def tree(result, **options):
    return render(result, "openspec", **options).files


def test_openspec_strict_leaves_a_requirement_without_scenario_out_and_lists_it(result):
    files = tree(result)
    spec = files["specs/stock/spec.md"]
    assert "# Stock adjustment Specification" in spec and "## Purpose" in spec and "## Requirements" in spec
    assert "Stock must never go negative" not in spec
    not_exported = files["NOT_EXPORTED.md"]
    assert "no evidenced scenario" in not_exported and "Stock must never go negative." in not_exported


def test_openspec_writes_requirement_blocks_with_evidence_and_scenarios(result):
    spec = tree(result)["specs/stock/spec.md"]
    assert "### Requirement: Managers adjust stock" in spec
    assert "The system SHALL ensure: Managers adjust stock, but never below zero." in spec
    assert re.search(r"^Evidence: src/policy.py:1-2, src/service.py:2-3$", spec, re.M)
    assert "#### Scenario: Refused below zero" in spec
    assert "- **GIVEN** stock is 1" in spec and "- **WHEN** a manager removes 2" in spec
    assert "- **THEN** the adjustment is refused" in spec


def test_openspec_non_strict_includes_it_with_the_marker_and_no_made_up_scenario(result):
    spec = tree(result, strict=False)["specs/stock/spec.md"]
    block = next(b for b in spec.split("### Requirement: ") if b.startswith("Stock must never go negative"))
    assert "> No scenario: reqx found no test or example that shows this case." in block
    assert "GIVEN" not in block and "Scenario:" not in block


def test_insufficient_and_conflicting_requirements_are_not_exported(result):
    for strict in (True, False):
        files = tree(result, strict=strict)
        assert "log every adjustment" not in files["specs/stock/spec.md"]
        assert "one per day" not in files["specs/stock/spec.md"]
        assert "Only a log call exists." in files["NOT_EXPORTED.md"]
        assert "The code allows several." in files["NOT_EXPORTED.md"]


def test_openspec_readme_counts_what_was_and_was_not_exported(result):
    readme = tree(result)["README.md"]
    assert "Exported: 1 requirements in 1 specs." in readme and "Not exported: 3 requirements" in readme
    assert "1 with no evidenced scenario" in readme and "specs/stock/spec.md" in readme


def test_the_shall_rule():
    assert with_shall("The system SHALL log it.") == "The system SHALL log it."
    assert with_shall("Stock MUST stay positive.") == "Stock MUST stay positive."
    assert with_shall("Stock must stay positive.") == "Stock MUST stay positive."
    assert with_shall("A manager can adjust stock.") == "The system SHALL ensure: A manager can adjust stock."


def test_title_is_the_first_clause_short_and_without_trailing_punctuation():
    assert requirement_title("A manager can adjust stock, but never below zero.") == "A manager can adjust stock"
    assert requirement_title("The system refuses it.") == "The system refuses it"
    long = requirement_title("The developer can configure the notification channel used for every kind of alert "
                             "raised by the monitoring service")
    assert len(long) <= 60 and not long.endswith(" ") and long.startswith("The developer can configure")
    assert requirement_title("Stock is checked: it cannot go negative.") == "Stock is checked"


def test_an_unknown_format_is_refused_with_the_known_ones(result, tmp_path):
    with pytest.raises(UnknownFormat) as error:
        render(result, "docx")
    assert all(name in str(error.value) for name in formats())
    saved = tmp_path / "r.json"
    saved.write_text(result.to_json())
    done = CliRunner().invoke(app, ["render", str(saved), "--format", "docx"])
    assert done.exit_code != 0 and "openspec" in done.output


def test_render_openspec_without_an_output_directory_is_an_error(result, tmp_path):
    saved = tmp_path / "r.json"
    saved.write_text(result.to_json())
    done = CliRunner().invoke(app, ["render", str(saved), "--format", "openspec"])
    assert done.exit_code != 0 and "-o" in done.output


def test_render_openspec_writes_the_tree_and_csv_writes_a_file(result, tmp_path):
    saved = tmp_path / "r.json"
    saved.write_text(result.to_json())
    out = tmp_path / "spec"
    done = CliRunner().invoke(app, ["render", str(saved), "--format", "openspec", "-o", str(out)])
    assert done.exit_code == 0, done.output
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} == {
        "specs/stock/spec.md", "NOT_EXPORTED.md", "README.md"}
    table = tmp_path / "r.csv"
    assert CliRunner().invoke(app, ["render", str(saved), "--format", "csv", "-o", str(table)]).exit_code == 0
    assert table.read_text().startswith("requirement_id,capability,")


def test_extract_refuses_openspec_without_a_directory_before_calling_a_model(tmp_path):
    done = CliRunner().invoke(app, ["extract", str(repo(tmp_path)), "--format", "openspec", "--provider", "none"])
    assert done.exit_code != 0 and "-o" in done.output


def test_markdown_shows_scenarios_under_their_requirement(result):
    text = to_markdown(result)
    assert "    - Scenario: Refused below zero" in text
    assert "        - Given: stock is 1" in text and "        - Then: the adjustment is refused" in text
    assert text.count("Scenario:") == 1
    assert render(result, "md").text == text and render(result, "json").text == result.to_json()


def test_a_reused_requirement_has_its_scenario_evidence_refreshed():
    from reqx.modules.extraction.use_cases import _refreshed

    class Now:
        path, lines, quote = "src/new.py", (7, 8), "moved"
    old = Evidence(observation="OBS-1", role="establishes", path="src/old.py", lines=(1, 2), quote="moved")
    requirement = Requirement(id="R", capability="c", statement="s", scope="local", evidence=[old], scenarios=[
        Scenario(name="n", given="g", when="w", then="t", evidence=[old])])
    kept = _refreshed(requirement, {"OBS-1": Now()})
    assert kept.scenarios[0].evidence[0].path == "src/new.py" and kept.scenarios[0].evidence[0].lines == (7, 8)
