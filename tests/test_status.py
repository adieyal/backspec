"""Staleness: which requirements rest on files that are no longer what was read."""
import json

from typer.testing import CliRunner

from backspec import status
from backspec.host.adapters.filesystem import DiskRepo
from backspec.host.cli import app
from test_pipeline import fake, repo


def saved(tmp_path):
    root = repo_in(tmp_path)
    result = run_at(root)
    path = tmp_path / "result.json"
    path.write_text(result.to_json())
    return root, result, path


def repo_in(tmp_path):
    (tmp_path / "repo").mkdir()
    return repo(tmp_path / "repo")


def run_at(root):
    from backspec import Config, extract
    return extract(root, Config(provider=fake(), use_cache=False))


def cli(path, root, *flags):
    return CliRunner().invoke(app, ["status", str(path), "--root", str(root), *flags])


def test_with_no_change_every_requirement_is_current_and_the_exit_code_is_zero(tmp_path):
    root, result, path = saved(tmp_path)
    report = status(result, root)
    assert report.counts == {"current": 1, "stale": 0, "source_missing": 0}
    assert report.changed_files == [] and report.missing_files == []
    done = cli(path, root)
    assert done.exit_code == 0 and done.output.startswith("1 current, 0 stale, 0 source_missing")


def test_editing_a_cited_file_makes_the_requirements_citing_it_stale_and_names_the_file(tmp_path):
    root, _, path = saved(tmp_path)
    (root / "src" / "policy.py").write_text("def can_adjust(user):\n    return True\n")
    report = status(path, root)
    assert report.changed_files == ["src/policy.py"] and report.missing_files == []
    assert [(r.status, r.changed, r.missing) for r in report.requirements] == [("stale", ["src/policy.py"], [])]
    done = cli(path, root)
    assert done.exit_code == 1
    assert "stale  REQ-" in done.output and "    changed  src/policy.py" in done.output


def test_deleting_a_cited_file_gives_source_missing(tmp_path):
    root, _, path = saved(tmp_path)
    (root / "src" / "service.py").unlink()
    report = status(path, root)
    assert report.missing_files == ["src/service.py"]
    assert report.requirements[0].status == "source_missing" and report.requirements[0].missing == ["src/service.py"]
    done = cli(path, root)
    assert done.exit_code == 1 and "source_missing  REQ-" in done.output and "    missing  src/service.py" in done.output


def test_a_file_that_is_no_longer_text_counts_as_missing(tmp_path):
    root, _, path = saved(tmp_path)
    (root / "src" / "policy.py").write_bytes(b"\xff\xfe\x00binary")
    assert status(path, root).missing_files == ["src/policy.py"]


def test_a_change_to_a_file_no_requirement_cites_changes_nothing(tmp_path):
    root, _, path = saved(tmp_path)
    (root / "src" / "util.py").write_text("def noop():\n    return 1\n")
    (root / "new.py").write_text("x = 1\n")
    report = status(path, root)
    assert report.counts == {"current": 1, "stale": 0, "source_missing": 0}
    assert report.changed_files == [] and cli(path, root).exit_code == 0


def test_json_output_parses_and_matches_the_library_report(tmp_path):
    root, _, path = saved(tmp_path)
    (root / "src" / "policy.py").write_text("changed\n")
    done = cli(path, root, "--json")
    assert done.exit_code == 1
    assert json.loads(done.output) == json.loads(status(path, root).model_dump_json())


def test_a_file_that_is_not_a_result_gives_exit_code_two(tmp_path):
    (tmp_path / "junk.json").write_text('{"not": "a result"}')
    assert cli(tmp_path / "junk.json", tmp_path).exit_code == 2
    (tmp_path / "text.json").write_text("not json")
    assert cli(tmp_path / "text.json", tmp_path).exit_code == 2
    assert cli(tmp_path / "absent.json", tmp_path).exit_code == 2


def test_reading_never_follows_a_path_outside_the_root(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "outside.txt").write_text("secret")
    (tmp_path / "root" / "link.txt").symlink_to(tmp_path / "outside.txt")
    disk = DiskRepo(tmp_path / "root")
    for path in ("../outside.txt", "link.txt", str(tmp_path / "outside.txt")):
        try:
            disk.read(path)
        except PermissionError:
            continue
        raise AssertionError(f"{path} was read")
