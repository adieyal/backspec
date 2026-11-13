"""The Codex adapter, against a fake `codex` script. The real CLI has never been run."""
import json
import os
import stat

import pytest

from reqx import Config, extract
from reqx.host.adapters.codex import CODEX_FLAGS, Codex
from reqx.host.composition import _provider
from reqx.kernel.llm import LLMError, LLMRequest
from test_pipeline import repo

SCRIPT = """#!/bin/sh
# a stand-in for `codex exec`: records how it was called, writes a reply where --output-last-message says
log="$FAKE_CODEX_LOG"
pwd > "$log.cwd"
ls -A > "$log.ls"
printf '%s\\n' "$@" > "$log.args"
cat > "$log.stdin"
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then out="$2"; fi
  shift
done
if [ -n "$FAKE_CODEX_FAIL" ]; then echo "boom: not logged in" >&2; exit 3; fi
if [ -n "$FAKE_CODEX_STDOUT_ONLY" ]; then echo '{"from": "stdout"}'; exit 0; fi
echo '{"reply": "ok"}' > "$out"
echo "progress noise on stdout is ignored when the file is written"
"""


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "codex"
    script.write_text(SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "log"))
    return tmp_path / "log"


def read(log, suffix):
    return open(f"{log}.{suffix}", encoding="utf-8").read()


def test_the_prompt_goes_on_stdin_and_the_final_message_file_is_returned(fake_codex):
    reply = Codex().complete(LLMRequest("observe", "PROMPT TEXT\nline two"))
    assert reply == '{"reply": "ok"}'
    assert read(fake_codex, "stdin") == "PROMPT TEXT\nline two"


def test_it_runs_read_only_in_an_empty_temporary_directory(fake_codex, tmp_path):
    Codex().complete(LLMRequest("observe", "p"))
    args = read(fake_codex, "args").split("\n")
    assert args[:len(CODEX_FLAGS)] == CODEX_FLAGS and args[args.index("--sandbox") + 1] == "read-only"
    assert args[-2] == "-"   # the prompt is read from stdin
    cwd = read(fake_codex, "cwd").strip()
    assert cwd != str(tmp_path) and not os.path.exists(cwd)   # a temporary directory, removed afterwards
    assert read(fake_codex, "ls") == ""                       # and it was empty


def test_a_model_name_is_passed_only_when_one_was_given(fake_codex):
    Codex().complete(LLMRequest("observe", "p", "fast"))
    assert "--model" not in read(fake_codex, "args")
    Codex(fast="small", strong="big").complete(LLMRequest("synthesise", "p", "strong"))
    args = read(fake_codex, "args").split("\n")
    assert args[args.index("--model") + 1] == "big"
    assert Codex(fast="small").label("fast") == "codex:small" and Codex().label("strong") == "codex:default"


def test_without_a_message_file_the_standard_output_is_used(fake_codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_STDOUT_ONLY", "1")
    assert json.loads(Codex().complete(LLMRequest("observe", "p"))) == {"from": "stdout"}


def test_a_non_zero_exit_is_an_llm_error_with_the_stage_and_the_message(fake_codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
    with pytest.raises(LLMError, match=r"observe: codex exited 3: boom: not logged in"):
        Codex().complete(LLMRequest("observe", "p"))


def test_a_missing_binary_is_an_llm_error_when_the_adapter_is_made(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(LLMError, match="`codex` command was not found"):
        Codex()
    with pytest.raises(LLMError, match="`codex` command was not found"):
        _provider(Config(provider="codex"))


def test_the_binary_disappearing_after_start_is_an_llm_error_too(fake_codex, monkeypatch, tmp_path):
    adapter = Codex()
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(LLMError, match="was not found"):
        adapter.complete(LLMRequest("observe", "p"))


def test_the_provider_name_selects_the_adapter(fake_codex):
    inner, name = _provider(Config(provider="codex", fast_model="a", strong_model="b"))
    assert name == "codex" and isinstance(inner, Codex) and inner.models == {"fast": "a", "strong": "b"}


def test_an_extraction_can_run_through_the_adapter(fake_codex, tmp_path):
    (tmp_path / "r").mkdir()
    result = extract(repo(tmp_path / "r"), Config(provider="codex", use_cache=False, assess_support=False))
    # the fake always answers {"reply": "ok"}: an empty reply for every stage, so nothing is found
    assert result.run.provider == "codex" and result.observations == [] and result.requirements == []
