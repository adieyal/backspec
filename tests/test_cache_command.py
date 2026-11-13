"""`reqx cache info` and `reqx cache clear`."""
from typer.testing import CliRunner

from reqx import Config, extract
from reqx.host.cli import app
from reqx.host.composition import default_cache_dir
from test_pipeline import fake, repo

HEX = "0123456789abcdef0123456789abcdef"


def cached_repo(tmp_path):
    (tmp_path / "repo").mkdir()
    root, cache = repo(tmp_path / "repo"), tmp_path / "cache"
    extract(root, Config(provider=fake(), cache_dir=cache))
    return root, cache


def cli(*args):
    return CliRunner().invoke(app, ["cache", *args])


def test_info_counts_cached_replies_per_stage_and_their_size(tmp_path):
    root, cache = cached_repo(tmp_path)
    done = cli("info", str(root), "--cache-dir", str(cache))
    assert done.exit_code == 0
    for stage in ("assess", "assign", "observe", "orient", "synthesise"):
        assert f"  {stage}: 1\n" in done.output
    size = sum(f.stat().st_size for f in cache.iterdir())
    assert f"cache directory: {cache}" in done.output and f"6 cached replies, {size} bytes" in done.output


def test_info_defaults_to_the_cache_of_the_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "repo").mkdir()
    root = repo(tmp_path / "repo")
    extract(root, Config(provider=fake()))
    done = cli("info", str(root))
    assert f"cache directory: {default_cache_dir(root.resolve())}" in done.output and "6 cached replies" in done.output


def test_info_on_a_missing_cache_reports_zero(tmp_path):
    done = cli("info", str(tmp_path), "--cache-dir", str(tmp_path / "none"))
    assert done.exit_code == 0 and "0 cached replies, 0 bytes" in done.output


def test_clear_without_yes_deletes_nothing_and_says_what_it_would_delete(tmp_path):
    root, cache = cached_repo(tmp_path)
    done = cli("clear", str(root), "--cache-dir", str(cache))
    assert done.exit_code == 0 and "would delete 6 cached replies" in done.output and "--yes" in done.output
    assert len(list(cache.iterdir())) == 6


def test_clear_with_yes_deletes_the_cache_files_and_only_those(tmp_path):
    root, cache = cached_repo(tmp_path)
    other = tmp_path / "other.json"
    other.write_text("keep")
    done = cli("clear", str(root), "--cache-dir", str(cache), "--yes")
    assert done.exit_code == 0 and "deleting 6 cached replies" in done.output
    assert list(cache.iterdir()) == [] and cache.is_dir() and other.read_text() == "keep" and root.is_dir()
    assert "0 cached replies" in cli("info", str(root), "--cache-dir", str(cache)).output


def test_a_directory_that_is_not_a_cache_is_refused_and_left_alone(tmp_path):
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "notes.txt").write_text("mine")
    (folder / f"observe-{HEX}.json").write_text("{}")
    for command in (("info",), ("clear", "--yes")):
        done = cli(*command, str(tmp_path), "--cache-dir", str(folder))
        assert done.exit_code == 2 and "does not look like a reqx cache" in done.output
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt", f"observe-{HEX}.json"]


def test_a_subdirectory_or_a_symlink_makes_a_directory_not_a_cache(tmp_path):
    folder = tmp_path / "c"
    (folder / "sub").mkdir(parents=True)
    assert cli("clear", "--yes", str(tmp_path), "--cache-dir", str(folder)).exit_code == 2
    (folder / "sub").rmdir()
    target = tmp_path / "target.json"
    target.write_text("keep")
    (folder / f"observe-{HEX}.json").symlink_to(target)
    assert cli("clear", "--yes", str(tmp_path), "--cache-dir", str(folder)).exit_code == 2
    assert target.read_text() == "keep"
