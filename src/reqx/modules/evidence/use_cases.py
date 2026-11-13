"""Observe: read every file in numbered batches and keep only what verifies."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from reqx.kernel import prompts
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from reqx.modules.discovery.facade import SourceFile
from reqx.modules.evidence.domain import (Chunk, NothingFound, Observation, ObserveReply, Rejected,
                                          pack, render, split_file, verify)

BATCH_LINES = 1300


@dataclass
class ObservationSet:
    observations: list[Observation] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    nothing: list[NothingFound] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # path -> why its batch failed
    batches: int = 0


def observe(files: list[SourceFile], llm: LLMPort, workers: int = 4,
            batch_lines: int = BATCH_LINES) -> ObservationSet:
    file_lines = {f.path: f.lines for f in files}
    hashes = {f.path: f.source_hash for f in files}
    chunks = [chunk for f in files for chunk in split_file(f.path, f.lines, batch_lines)]
    batches = pack(chunks, batch_lines)
    instructions = prompts.load("observe")

    def run(batch: list[Chunk]) -> ObserveReply | LLMError:
        try:
            return ask(llm, LLMRequest("observe", f"{instructions}\n\n# The batch\n\n{render(batch)}", "fast"), ObserveReply)
        except LLMError as error:
            return error

    result = ObservationSet(batches=len(batches))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, batches))
    seen: set[str] = set()
    for batch, reply in zip(batches, replies):
        shown = {chunk.path for chunk in batch}
        if isinstance(reply, LLMError):
            for path in shown:
                result.failed[path] = str(reply)[:300]
            continue
        result.nothing += [entry for entry in reply.none if entry.path in shown]
        for raw in reply.observations:
            checked = verify(raw, shown, file_lines, hashes)
            if isinstance(checked, Rejected):
                result.rejected.append(checked)
            elif checked.id not in seen:
                seen.add(checked.id)
                result.observations.append(checked)
    return result
