"""The OpenAI Codex CLI as a model backend, using the login the user already has.

NOT VERIFIED: this adapter has never been run against the real `codex` CLI. It was written from
memory of the documented `codex exec` interface, and the `codex` binary was not available where
it was written. It is tested only against a fake `codex` shell script that follows the same
assumed interface. Every flag it passes is in `CODEX_FLAGS` below; check them against
`codex exec --help` before relying on it.

Each call is one non-interactive `codex exec` run in a read-only sandbox (it cannot change files),
started in an empty temporary directory, with the prompt on stdin. The model's final message is
written by Codex to a file we name, and that text is returned.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from backspec.kernel.llm import LLMError, LLMRequest

# UNVERIFIED: these flags are assumed from the documented `codex exec` interface and have not been
# run. `-` as the prompt is assumed to mean "read the prompt from stdin". The model flag
# (`--model NAME`) and the output flag (`--output-last-message FILE`) are added after these.
CODEX_FLAGS = ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "--color", "never"]
MODEL_FLAG = "--model"
OUTPUT_FLAG = "--output-last-message"
PROMPT_FROM_STDIN = "-"


class Codex:
    name = "codex"

    def __init__(self, fast: str | None = None, strong: str | None = None, timeout: int = 900):
        # No default model names are assumed: without one, Codex uses its own configured model.
        self.models = {"fast": fast, "strong": strong}
        self.timeout = timeout
        if shutil.which("codex") is None:
            raise LLMError("The `codex` command was not found. Install the Codex CLI and log in, "
                           "or choose another provider.")

    def label(self, tier: str) -> str:
        return f"{self.name}:{self.models[tier] or 'default'}"

    def command(self, tier: str, output: Path) -> list[str]:
        command = ["codex", *CODEX_FLAGS]
        if self.models[tier]:
            command += [MODEL_FLAG, self.models[tier]]
        return [*command, OUTPUT_FLAG, str(output), PROMPT_FROM_STDIN]

    def complete(self, request: LLMRequest) -> str:
        with tempfile.TemporaryDirectory(prefix="backspec-") as empty, \
                tempfile.TemporaryDirectory(prefix="backspec-out-") as out:
            output = Path(out) / "last-message.txt"
            try:
                done = subprocess.run(self.command(request.tier, output), input=request.prompt, capture_output=True,
                                      text=True, cwd=empty, timeout=self.timeout)
            except subprocess.TimeoutExpired as error:
                raise LLMError(f"{request.stage}: codex did not answer within {self.timeout}s") from error
            except FileNotFoundError as error:
                raise LLMError(f"{request.stage}: the `codex` command was not found") from error
            if done.returncode != 0:
                raise LLMError(f"{request.stage}: codex exited {done.returncode}: {(done.stderr or done.stdout)[:400]}")
            reply = output.read_text(encoding="utf-8") if output.is_file() else done.stdout
        if not reply.strip():
            raise LLMError(f"{request.stage}: codex gave an empty reply")
        return reply.strip()
