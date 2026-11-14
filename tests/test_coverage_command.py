"""`backspec coverage`: what happened to each file of a saved result, with no model call."""
import json

from typer.testing import CliRunner

from backspec import Config, extract
from backspec.host.cli import app
from backspec.modules.report.facade import FileCoverage, coverage_report
from test_pipeline import fake, repo


def result_with_big_file(tmp_path):
    root = repo(tmp_path)
    (root / "src" / "big.py").write_text("".join(f"x{i} = {i}\n" for i in range(100)))
    return extract(root, Config(provider=fake(), use_cache=False))


def saved(tmp_path, result):
    path = tmp_path / "result.json"
    path.write_text(result.to_json())
    return path


def cli(path, *flags):
    return CliRunner().invoke(app, ["coverage", str(path), *flags])


def test_the_line_count_of_each_file_that_was_read_is_stored(tmp_path):
    lines = {f.path: f.lines for f in result_with_big_file(tmp_path).coverage.files}
    assert lines["src/big.py"] == 100 and lines["src/policy.py"] == 2 and lines["logo.png"] == 0


def test_the_report_counts_files_per_state_and_leaves_excluded_files_out_of_the_lists(tmp_path):
    report = coverage_report(result_with_big_file(tmp_path))
    assert report.counts == {"excluded": 1, "extracted": 2, "no_requirements": 2}
    assert set(report.files) == {"extracted", "no_requirements"}
    assert [f.path for f in report.files["no_requirements"]] == ["src/big.py", "src/util.py"]
    assert report.files["no_requirements"][1].reason == "a helper with no behaviour"


def test_a_long_file_with_no_observation_is_worth_a_look_and_a_short_one_is_not(tmp_path):
    report = coverage_report(result_with_big_file(tmp_path))
    assert [f.path for f in report.worth_a_look] == ["src/big.py"]


def test_a_long_file_that_no_requirement_cites_is_worth_a_look(tmp_path):
    result = result_with_big_file(tmp_path)
    for entry in result.coverage.files:
        if entry.path == "src/service.py":
            entry.lines, entry.cited_by = 120, 0
        if entry.path == "src/policy.py":
            entry.lines, entry.cited_by = 120, 1   # cited: not listed
    assert [f.path for f in coverage_report(result).worth_a_look] == ["src/big.py", "src/service.py"]


def test_a_file_that_was_not_read_is_never_worth_a_look(tmp_path):
    result = result_with_big_file(tmp_path)
    result.coverage.files.append(FileCoverage(path="huge.txt", state="skipped", reason="too large", lines=500))
    assert "huge.txt" not in [f.path for f in coverage_report(result).worth_a_look]


def test_unused_observations_are_reported_per_capability(tmp_path):
    result = result_with_big_file(tmp_path)
    result.coverage.unused_observations = {"stock": 3}
    assert coverage_report(result).unused_observations == {"stock": 3}
    assert "  stock: 3" in cli(saved(tmp_path, result)).output


def test_the_command_prints_states_reasons_and_the_worth_a_look_list_and_calls_no_model(tmp_path):
    done = cli(saved(tmp_path, result_with_big_file(tmp_path)))
    assert done.exit_code == 0
    assert done.output.startswith("files per state: 1 excluded, 2 extracted, 2 no_requirements")
    assert "no_requirements (2):" in done.output and "  src/util.py  (a helper with no behaviour)" in done.output
    assert "excluded (" not in done.output and "logo.png" not in done.output
    assert "worth a look" in done.output and "  src/big.py  (100 lines, 0 observations, cited by 0)" in done.output


def test_long_lists_are_truncated_to_30_lines_unless_all(tmp_path):
    result = result_with_big_file(tmp_path)
    result.coverage.files += [FileCoverage(path=f"gen/f{i:03d}.py", state="skipped", reason="generated")
                              for i in range(45)]
    path = saved(tmp_path, result)
    short, full = cli(path).output, cli(path, "--all").output
    assert short.count("gen/f") == 30 and "... and 15 more" in short
    assert full.count("gen/f") == 45 and "more (--all" not in full


def test_json_output_is_the_report(tmp_path):
    result = result_with_big_file(tmp_path)
    done = cli(saved(tmp_path, result), "--json")
    assert json.loads(done.output) == json.loads(coverage_report(result).model_dump_json())


def test_a_file_that_is_not_a_result_gives_exit_code_two(tmp_path):
    (tmp_path / "junk.json").write_text("{}")
    assert cli(tmp_path / "junk.json").exit_code == 2
    assert cli(tmp_path / "absent.json").exit_code == 2
