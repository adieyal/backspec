"""The capabilities file: the owner's correction of the capability list, used on every later run."""
import re

import pytest
import yaml
from typer.testing import CliRunner

from reqx import Config, extract, orient
from reqx.host.adapters.fake import FakeLLM
from reqx.host.cli import app
from reqx.modules.capabilities.facade import CapabilitiesFileError
from test_pipeline import assess, assign, observe, orient as orient_answer, repo, synthesise

FILE = "reqx.capabilities.yaml"


def fake(**override):
    answers = {"observe": observe, "orient": orient_answer, "assign": assign, "synthesise": synthesise,
               "assess": assess}
    return FakeLLM({**answers, **override})


def stages(llm):
    return [r.stage for r in llm.requests]


def write(root, text):
    (root / FILE).write_text(text, encoding="utf-8")


def go(root, llm, **changes):
    if not (root / "src").exists():
        repo(root)
    return extract(root, Config(provider=llm, use_cache=False, **changes))


def test_an_existing_file_is_used_and_orient_is_not_called(tmp_path):
    write(tmp_path, "- id: billing\n  name: Billing\n  summary: Charge people.\n")
    llm = fake(assign=lambda p: {"assignments": {i: "billing" for i in re.findall(r"^(OBS-\w+) \|", p, re.M)}})
    result = go(tmp_path, llm)
    assert "orient" not in stages(llm) and "assign" in stages(llm)
    assert result.run.capabilities_source == "file"
    assert [c.id for c in result.capabilities] == ["billing", "plumbing"]
    assert {r.capability for r in result.requirements} == {"billing"}


def test_a_missing_file_means_orient_is_called_and_no_file_is_written(tmp_path):
    llm = fake()
    result = go(tmp_path, llm)
    assert stages(llm).count("orient") == 1
    assert result.run.capabilities_source == "oriented" and result.run.stopped_after is None
    assert not (tmp_path / FILE).exists()


def test_the_gate_writes_the_file_and_stops_before_assign_and_synthesise(tmp_path):
    llm = fake()
    result = go(tmp_path, llm, gate=True)
    assert (tmp_path / FILE).is_file()
    assert not {"assign", "synthesise", "assess"} & set(stages(llm))
    assert result.requirements == [] and result.run.status == "partial" and result.run.stopped_after == "capabilities"
    assert [c.id for c in result.capabilities] == ["stock", "plumbing"] and result.observations


def test_the_gate_with_an_existing_file_only_stops_and_leaves_it_alone(tmp_path):
    text = "- id: billing\n  name: Billing\n"
    write(tmp_path, text)
    llm = fake()
    result = go(tmp_path, llm, gate=True)
    assert (tmp_path / FILE).read_text() == text
    assert {"orient", "assign", "synthesise"}.isdisjoint(stages(llm))
    assert result.run.capabilities_source == "file" and result.run.stopped_after == "capabilities"


def test_an_invalid_file_is_refused_naming_the_file_and_every_problem(tmp_path):
    write(tmp_path, "- id: Stock Level\n  name: Stock\n- id: dup\n  name: One\n- id: dup\n  name: ''\n")
    llm = fake()
    with pytest.raises(CapabilitiesFileError) as error:
        go(tmp_path, llm)
    message = str(error.value)
    assert str(tmp_path / FILE) in message
    assert "'Stock Level'" in message and "used more than once" in message and "name must not be empty" in message
    assert llm.requests == []


def test_a_file_that_is_not_yaml_is_refused_naming_the_file(tmp_path):
    write(tmp_path, "- id: [unclosed\n")
    with pytest.raises(CapabilitiesFileError, match="reqx.capabilities.yaml is not valid YAML"):
        go(tmp_path, fake())


def test_plumbing_is_added_when_the_file_lacks_it(tmp_path):
    write(tmp_path, "- id: billing\n  name: Billing\n")
    result = go(tmp_path, fake(), gate=True)
    assert [c.id for c in result.capabilities] == ["billing", "plumbing"]


def test_the_written_file_loads_back_to_the_same_capabilities(tmp_path):
    result = go(tmp_path, fake(), gate=True)
    text = (tmp_path / FILE).read_text()
    assert text.startswith("#") and "reqx extract" in text
    again = go(tmp_path, fake(), gate=True)
    assert again.capabilities == result.capabilities and again.run.capabilities_source == "file"
    assert [c["id"] for c in yaml.safe_load(text)] == ["stock", "plumbing"]


def test_library_orient_writes_the_file_and_refuses_to_overwrite_without_force(tmp_path):
    root = repo(tmp_path)
    llm = fake()
    found = orient(root, Config(provider=llm, use_cache=False))
    assert [c.id for c in found] == ["stock", "plumbing"] and (root / FILE).is_file()
    assert set(stages(llm)) == {"observe", "orient"}
    with pytest.raises(FileExistsError):
        orient(root, Config(provider=llm, use_cache=False))
    assert len(orient(root, Config(provider=llm, use_cache=False), force=True)) == 2


@pytest.fixture
def cli(monkeypatch):
    """The command line, with the model backend replaced by the fake."""
    llm = fake()
    monkeypatch.setattr("reqx.host.composition._provider", lambda config: (llm, "fake"))
    return lambda *args: CliRunner().invoke(app, [*args, "--no-cache"]), llm


def test_the_orient_command_refuses_to_overwrite_without_force(tmp_path, cli):
    invoke, llm = cli
    root = repo(tmp_path)
    write(root, "- id: mine\n  name: Mine\n")
    done = invoke("orient", str(root))
    assert done.exit_code == 2 and "--force" in done.output
    assert (root / FILE).read_text() == "- id: mine\n  name: Mine\n" and llm.requests == []
    forced = invoke("orient", str(root), "--force")
    assert forced.exit_code == 0 and "stock: Stock adjustment" in forced.output
    assert [c["id"] for c in yaml.safe_load((root / FILE).read_text())] == ["stock", "plumbing"]


def test_the_orient_command_lists_capabilities_on_stdout_and_the_file_on_stderr(tmp_path, cli):
    invoke, _ = cli
    root = repo(tmp_path)
    done = invoke("orient", str(root))
    assert done.exit_code == 0 and (root / FILE).is_file()
    assert done.stdout.splitlines() == ["stock: Stock adjustment", "plumbing: Internal mechanics"]
    assert str(root / FILE) in done.stderr


def test_extract_reports_an_invalid_file_on_the_command_line(tmp_path, cli):
    invoke, _ = cli
    root = repo(tmp_path)
    write(root, "- id: BAD\n  name: x\n")
    done = invoke("extract", str(root))
    assert done.exit_code == 2 and "reqx.capabilities.yaml is not usable" in done.output and "'BAD'" in done.output


def test_extract_with_gate_on_the_command_line_stops_cleanly(tmp_path, cli):
    invoke, llm = cli
    root = repo(tmp_path)
    done = invoke("extract", str(root), "--gate")
    assert done.exit_code == 0 and "stopped after capabilities" in done.stderr
    assert (root / FILE).is_file() and "assign" not in stages(llm)
