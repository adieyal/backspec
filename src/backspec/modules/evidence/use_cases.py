"""Observe: read every file in numbered batches and keep only what verifies.

A model does not give the same observations twice for the same file. So a file that has not
changed since an earlier run keeps that run's observations, and only new or changed files are
read. Everything built on observations, requirement ids included, is then stable between runs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from backspec.kernel import prompts
from backspec.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from backspec.modules.discovery.facade import SourceFile
from backspec.kernel.text import short_hash
from backspec.modules.evidence.domain import (Chunk, Earlier, NothingFound, Observation, ObserveReply, Rejected,
                                          Symbol, carried, compare, enclosing_symbol, pack, render, split_file,
                                          verify, windows)
from backspec.modules.evidence.ports import SyntaxPort

BATCH_LINES = 1300


@dataclass
class ObservationSet:
    observations: list[Observation] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    nothing: list[NothingFound] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # path -> why its batch failed
    batches: int = 0
    reused_files: int = 0   # unchanged since the earlier run, so not read again
    partly_read_files: int = 0   # changed since the earlier run: only the changed parts were read
    outside_change: int = 0      # observations a model made of unchanged lines while reading a change; not kept
    analysis: dict[str, str] = field(default_factory=dict)   # path -> "syntax" or "text": how the file was analysed


def fingerprint(batch_lines: int = BATCH_LINES, syntax: bool = False) -> str:
    """Changes whenever the way files are observed does, syntax support on or off included.
    Earlier observations made another way are not reused."""
    parts = [prompts.load("observe"), batch_lines, "ids-by-cited-text"]
    return short_hash(*parts, "syntax") if syntax else short_hash(*parts)


def _symbols(syntax: SyntaxPort | None, file: SourceFile) -> list[Symbol] | None:
    """The symbols of a file, or None: no parser, no grammar, or a parser that failed."""
    if syntax is None:
        return None
    try:
        return syntax.symbols(file.path, file.text)
    except Exception:
        return None


def observe(files: list[SourceFile], llm: LLMPort, workers: int = 4, batch_lines: int = BATCH_LINES,
            earlier: dict[str, Earlier] | None = None, syntax: SyntaxPort | None = None) -> ObservationSet:
    symbols = {f.path: _symbols(syntax, f) for f in files}
    file_lines = {f.path: f.lines for f in files}
    hashes = {f.path: f.source_hash for f in files}
    result = ObservationSet(analysis={path: "text" if found is None else "syntax" for path, found in symbols.items()})
    seen: set[str] = set()
    to_read = []
    partial: list[Chunk] = []
    changes = {}
    for f in files:
        known = (earlier or {}).get(f.path)
        if known is None:
            to_read.append(f)
            continue
        if known.source_hash != f.source_hash:
            if not known.line_digest:
                to_read.append(f)
                continue
            # Changed since the earlier run. Observations whose lines are untouched stay, moved to
            # where those lines are now; only the changed parts, with context, are read again.
            change = compare(known.line_digest, f.lines)
            result.partly_read_files += 1
            for observation in known.observations:
                still = carried(observation, change, f.source_hash)
                if still is not None and still.id not in seen:
                    seen.add(still.id)
                    result.observations.append(still)
            for first, last in windows(change.changed, len(f.lines)):
                partial.append(Chunk(f.path, first, tuple(f.lines[first - 1:last])))
            changes[f.path] = change
            continue
        result.reused_files += 1
        for observation in known.observations:
            if observation.source_hash == f.source_hash and observation.id not in seen:
                seen.add(observation.id)
                result.observations.append(observation)
        if known.nothing_reason is not None and not known.observations:
            result.nothing.append(NothingFound(path=f.path, reason=known.nothing_reason))
    chunks = [chunk for f in to_read for chunk in split_file(f.path, f.lines, batch_lines, symbols[f.path])] + partial
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
            elif checked.path in changes and not changes[checked.path].touches(*checked.lines):
                # Read only as context for a change. What the earlier run said of these lines stands.
                result.outside_change += 1
            elif checked.id not in seen:
                seen.add(checked.id)
                result.observations.append(checked)
    # Where an observation sits is worked out here, from the file as it is now, for new, carried and
    # reused observations alike: code may have moved between symbols since an earlier run.
    result.observations = [
        o.model_copy(update={"symbol": symbol}) if (symbol := enclosing_symbol(symbols.get(o.path), *o.lines)) != o.symbol else o
        for o in result.observations]
    return result
