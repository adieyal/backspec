"""Observe: read every file in numbered batches and keep only what verifies.

A model does not give the same observations twice for the same file. So a file that has not
changed since an earlier run keeps that run's observations, and only new or changed files are
read. Everything built on observations, requirement ids included, is then stable between runs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from reqx.kernel import prompts
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from reqx.modules.discovery.facade import SourceFile
from reqx.kernel.text import short_hash
from reqx.modules.evidence.domain import (Chunk, Earlier, NothingFound, Observation, ObserveReply, Rejected,
                                          pack, render, split_file, verify)

BATCH_LINES = 1300


@dataclass
class ObservationSet:
    observations: list[Observation] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    nothing: list[NothingFound] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # path -> why its batch failed
    batches: int = 0
    reused_files: int = 0   # unchanged since the earlier run, so not read again


def fingerprint(batch_lines: int = BATCH_LINES) -> str:
    """Changes whenever the way files are observed does. Earlier observations made another way
    are not reused."""
    return short_hash(prompts.load("observe"), batch_lines)


def observe(files: list[SourceFile], llm: LLMPort, workers: int = 4, batch_lines: int = BATCH_LINES,
            earlier: dict[str, Earlier] | None = None) -> ObservationSet:
    file_lines = {f.path: f.lines for f in files}
    hashes = {f.path: f.source_hash for f in files}
    result = ObservationSet()
    seen: set[str] = set()
    to_read = []
    for f in files:
        known = (earlier or {}).get(f.path)
        if known is None or known.source_hash != f.source_hash:
            to_read.append(f)
            continue
        result.reused_files += 1
        for observation in known.observations:
            if observation.source_hash == f.source_hash and observation.id not in seen:
                seen.add(observation.id)
                result.observations.append(observation)
        if known.nothing_reason is not None and not known.observations:
            result.nothing.append(NothingFound(path=f.path, reason=known.nothing_reason))
    chunks = [chunk for f in to_read for chunk in split_file(f.path, f.lines, batch_lines)]
    batches = pack(chunks, batch_lines)
    result.batches = len(batches)
    instructions = prompts.load("observe")

    def run(batch: list[Chunk]) -> ObserveReply | LLMError:
        try:
            return ask(llm, LLMRequest("observe", f"{instructions}\n\n# The batch\n\n{render(batch)}", "fast"), ObserveReply)
        except LLMError as error:
            return error

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, batches))
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
