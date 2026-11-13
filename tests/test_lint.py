"""Lint: deterministic checks on a result, `reqx validate`, and lint stored by every extraction."""
import json

from typer.testing import CliRunner

from reqx import Finding, validate
from reqx.host.cli import app
from reqx.modules.report.facade import ExtractionResult
from test_pipeline import run


def good(tmp_path):
    return run(tmp_path)


def codes(result, severity=None):
    return {f.code for f in validate(result).findings if severity in (None, f.severity)}


def edited(result, **changes):
    """A copy of the result's first requirement with changes, replacing it."""
    copy = result.model_copy(deep=True)
    copy.requirements[0] = copy.requirements[0].model_copy(update=changes)
    return copy


def test_a_good_result_has_no_findings(tmp_path):
    result = good(tmp_path)
    assert codes(result, "error") == set()
    assert codes(result) == set()


def test_lint_findings_are_stored_in_an_extraction_result(tmp_path):
    result = good(tmp_path)
    assert all(isinstance(f, Finding) for f in result.diagnostics.lint)
    assert result.diagnostics.lint == validate(result).findings
    assert ExtractionResult.model_validate_json(result.to_json()).diagnostics.lint == result.diagnostics.lint


def test_a_requirement_in_an_unknown_capability_is_an_error(tmp_path):
    result = good(tmp_path)
    assert "unknown_capability" in codes(edited(result, capability="nowhere"), "error")
    assert "unknown_capability" not in codes(result)


def test_a_requirement_without_evidence_is_an_error(tmp_path):
    assert "no_evidence" in codes(edited(good(tmp_path), evidence=[]), "error")


def test_citing_an_observation_that_does_not_exist_is_an_error(tmp_path):
    result = good(tmp_path)
    bad = edited(result, evidence=[result.requirements[0].evidence[0].model_copy(update={"observation": "OBS-nope"})])
    found = [f for f in validate(bad).findings if f.code == "unknown_observation"]
    assert found and found[0].severity == "error" and "OBS-nope" in found[0].ids


def test_two_requirements_with_one_id_is_an_error(tmp_path):
    result = good(tmp_path)
    result.requirements.append(result.requirements[0].model_copy())
    assert "duplicate_requirement_id" in codes(result, "error")


def test_evidence_that_disagrees_with_its_observation_is_an_error(tmp_path):
    result = good(tmp_path)
    evidence = result.requirements[0].evidence
    moved = [evidence[0].model_copy(update={"lines": (50, 51)}), *evidence[1:]]
    assert "evidence_mismatch" in codes(edited(result, evidence=moved), "error")
    renamed = [evidence[0].model_copy(update={"path": "src/other.py"}), *evidence[1:]]
    assert "evidence_mismatch" in codes(edited(result, evidence=renamed), "error")


def test_a_capability_without_requirements_is_a_warning_except_plumbing_and_unassigned(tmp_path):
    result = good(tmp_path)
    result.capabilities += [result.capabilities[0].model_copy(update={"id": "empty"}),
                            result.capabilities[0].model_copy(update={"id": "plumbing"}),
                            result.capabilities[0].model_copy(update={"id": "unassigned"})]
    found = [f for f in validate(result).findings if f.code == "capability_without_requirements"]
    assert [f.ids for f in found] == [["empty"]] and found[0].severity == "warning"


def test_two_statements_equal_after_case_and_spacing_are_a_warning(tmp_path):
    result = good(tmp_path)
    twin = result.requirements[0].model_copy(update={
        "id": "REQ-twin", "statement": "  a MANAGER can adjust   the stock of an item. "})
    result.requirements.append(twin)
    found = [f for f in validate(result).findings if f.code == "duplicate_statement"]
    assert len(found) == 1 and found[0].severity == "warning" and "REQ-twin" in found[0].ids
    other = result.requirements[0].model_copy(update={"id": "REQ-other", "statement": "Something quite different here."})
    result.requirements[-1] = other
    assert "duplicate_statement" not in codes(result)


def test_a_short_statement_is_a_warning(tmp_path):
    result = good(tmp_path)
    assert "short_statement" in codes(edited(result, statement="Adjust stock."), "warning")
    assert "short_statement" not in codes(result)


def test_a_statement_that_joins_obligations_is_a_warning(tmp_path):
    result = good(tmp_path)
    for text in ("The manager adjusts stock; the system logs it.", "The manager adjusts stock and also emails the owner.",
                 "A and then B and then C and then D are all done by the manager."):
        assert "compound_statement" in codes(edited(result, statement=text), "warning"), text
    assert "compound_statement" not in codes(edited(result, statement="The manager adjusts stock and logs it."))


def test_evidence_that_is_all_context_is_a_warning(tmp_path):
    result = good(tmp_path)
    evidence = [e.model_copy(update={"role": "context"}) for e in result.requirements[0].evidence]
    assert "context_only_evidence" in codes(edited(result, evidence=evidence), "warning")
    assert "context_only_evidence" not in codes(result)


def test_insufficient_or_conflicting_support_is_a_warning(tmp_path):
    result = good(tmp_path)
    for support in ("insufficient", "conflicting"):
        assert "weak_support" in codes(edited(result, support=support), "warning")
    assert "weak_support" not in codes(edited(result, support="direct"))


def write(tmp_path, result, name="result.json"):
    path = tmp_path / name
    path.write_text(result.to_json() if isinstance(result, ExtractionResult) else result)
    return path


def cli(path, *flags):
    return CliRunner().invoke(app, ["validate", str(path), *flags])


def test_validate_exits_zero_when_there_are_only_warnings_and_one_with_strict(tmp_path):
    (tmp_path / "a").mkdir()
    path = write(tmp_path, edited(good(tmp_path / "a"), statement="Adjust stock."))
    done = cli(path)
    assert done.exit_code == 0 and "warnings:" in done.output and "short_statement" in done.output
    assert done.output.splitlines()[-1] == "0 errors, 1 warnings"
    assert cli(path, "--strict").exit_code == 1


def test_validate_exits_one_on_errors_and_groups_them_first(tmp_path):
    path = write(tmp_path, edited(good(tmp_path), evidence=[]))
    done = cli(path)
    assert done.exit_code == 1
    assert done.output.index("errors:") < done.output.index("no_evidence")
    assert done.output.splitlines()[-1].startswith("1 errors")


def test_validate_exits_two_for_a_file_that_is_not_a_result(tmp_path):
    assert cli(write(tmp_path, '{"not": "a result"}', "junk.json")).exit_code == 2
    assert cli(write(tmp_path, "not json", "text.json")).exit_code == 2
    assert cli(tmp_path / "absent.json").exit_code == 2


def test_validate_json_prints_the_findings(tmp_path):
    path = write(tmp_path, edited(good(tmp_path), evidence=[]))
    done = cli(path, "--json")
    assert done.exit_code == 1
    assert {f["code"] for f in json.loads(done.output)["findings"]} >= {"no_evidence"}


def test_validate_accepts_a_result_or_a_path_in_the_library(tmp_path):
    result = good(tmp_path)
    assert validate(result) == validate(write(tmp_path, result))
