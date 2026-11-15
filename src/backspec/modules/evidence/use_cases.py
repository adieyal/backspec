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
                                          unobserved, verify, windows)
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
    unobserved: dict[str, list[str]] = field(default_factory=dict)   # path -> functions still without an observation after a second look
    read_in_part: dict[str, int] = field(default_factory=dict)   # path -> lines shown, for a file of which only given parts were read


def fingerprint(batch_lines: int = BATCH_LINES, syntax: bool = False) -> str:
    """Changes whenever the way files are observed does, syntax support on or off included.
    Earlier observations made another way are not reused."""
    parts = [prompts.load("observe"), prompts.load("second_look"), batch_lines, "ids-by-cited-text"]
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
            earlier: dict[str, Earlier] | None = None, syntax: SyntaxPort | None = None,
            parts: dict[str, list[tuple[int, int]]] | None = None) -> ObservationSet:
    """`parts` names files of which only the given line ranges are read (path -> ranges). Their
    observations must lie inside those ranges, and only functions inside them get a second look.
    Earlier observations of such a file are not reused: the parts may differ from run to run."""
    parts = parts or {}
    symbols = {f.path: _symbols(syntax, f) for f in files}
    file_lines = {f.path: f.lines for f in files}
    hashes = {f.path: f.source_hash for f in files}
    result = ObservationSet(analysis={path: "text" if found is None else "syntax" for path, found in symbols.items()})
    seen: set[str] = set()
    to_read = []
    partial: list[Chunk] = []
    changes = {}
    shown_parts: list[Chunk] = []
    for f in files:
        if f.path in parts:
            for first, last in parts[f.path]:
                for start in range(first, last + 1, batch_lines):
                    end = min(last, start + batch_lines - 1)
                    shown_parts.append(Chunk(f.path, start, tuple(f.lines[start - 1:end])))
            result.read_in_part[f.path] = sum(b - a + 1 for a, b in parts[f.path])
            continue
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
    chunks = [chunk for f in to_read for chunk in split_file(f.path, f.lines, batch_lines, symbols[f.path])] + partial + shown_parts
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
    _keep(batches, replies, result, seen, file_lines, hashes, changes, parts)
    # A file read in part gets a second look only at the functions inside the parts that were read.
    looked = {**symbols, **{path: [s for s in symbols.get(path) or [] if _inside(parts[path], s.first_line, s.last_line)]
                            for path in parts if symbols.get(path) is not None}}
    _second_look([*to_read, *(f for f in files if f.path in parts)], looked, result, seen, file_lines, hashes, llm,
                 workers, batch_lines, parts)
    # Where an observation sits is worked out here, from the file as it is now, for new, carried and
    # reused observations alike: code may have moved between symbols since an earlier run.
    result.observations = [
        o.model_copy(update={"symbol": symbol}) if (symbol := enclosing_symbol(symbols.get(o.path), *o.lines)) != o.symbol else o
        for o in result.observations]
    return result


def _inside(ranges: list[tuple[int, int]], first: int, last: int) -> bool:
    return any(a <= first and last <= b for a, b in ranges)


def _outside_parts(checked: Observation, parts: dict[str, list[tuple[int, int]]]) -> Rejected | None:
    """For a file read in part, an observation whose lines are not within what was shown is refused:
    its quote was found, but somewhere the model was not shown."""
    if checked.path in parts and not _inside(parts[checked.path], *checked.lines):
        return Rejected(path=checked.path, lines=list(checked.lines), quote=checked.quote, statement=checked.statement,
                        reason="outside the parts of the file that were shown")
    return None


def _keep(batches: list[list[Chunk]], replies: list, result: ObservationSet, seen: set[str],
          file_lines: dict[str, list[str]], hashes: dict[str, str], changes: dict,
          parts: dict[str, list[tuple[int, int]]]) -> None:
    """Verify what each batch's reply says and keep what holds; record the rest."""
    for batch, reply in zip(batches, replies):
        shown = {chunk.path for chunk in batch}
        if isinstance(reply, LLMError):
            for path in shown:
                result.failed[path] = str(reply)[:300]
            continue
        result.nothing += [entry for entry in reply.none if entry.path in shown]
        for raw in reply.observations:
            checked = verify(raw, shown, file_lines, hashes)
            if not isinstance(checked, Rejected):
                checked = _outside_parts(checked, parts) or checked
            if isinstance(checked, Rejected):
                result.rejected.append(checked)
            elif checked.path in changes and not changes[checked.path].touches(*checked.lines):
                # Read only as context for a change. What the earlier run said of these lines stands.
                result.outside_change += 1
            elif checked.id not in seen:
                seen.add(checked.id)
                result.observations.append(checked)


def _second_look(files: list[SourceFile], symbols: dict[str, list[Symbol] | None], result: ObservationSet,
                 seen: set[str], file_lines: dict[str, list[str]], hashes: dict[str, str], llm: LLMPort,
                 workers: int, batch_lines: int, parts: dict[str, list[tuple[int, int]]]) -> None:
    """Show a model again each function that a full reading recorded nothing in. Whatever is still
    without an observation afterwards is recorded by name, never passed over silently.

    Only files read in full and whose batch did not fail are looked at, and not a file the model
    said holds nothing worth recording."""
    nothing = {entry.path for entry in result.nothing}
    missed: dict[str, list[Symbol]] = {}
    for f in files:
        if f.path in result.failed or symbols.get(f.path) is None:
            continue
        cited = [o.lines for o in result.observations if o.path == f.path]
        if not cited and f.path in nothing:
            continue
        found = unobserved(symbols[f.path], cited)
        if found:
            missed[f.path] = found
    if not missed:
        return
    chunks = [Chunk(path, s.first_line, tuple(file_lines[path][s.first_line - 1:s.last_line]))
              for path, found in missed.items() for s in found]
    batches = pack(chunks, batch_lines)
    result.batches += len(batches)
    instructions = f"{prompts.load('observe')}\n\n{prompts.load('second_look')}"

    def run(batch: list[Chunk]) -> ObserveReply | LLMError:
        try:
            return ask(llm, LLMRequest("second_look", f"{instructions}\n\n# The batch\n\n{render(batch)}", "fast"), ObserveReply)
        except LLMError as error:
            return error

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, batches))
    for batch, reply in zip(batches, replies):
        if isinstance(reply, LLMError):
            continue   # the functions stay unobserved, and are recorded below
        shown = {chunk.path for chunk in batch}
        for raw in reply.observations:
            checked = verify(raw, shown, file_lines, hashes)
            if not isinstance(checked, Rejected):
                checked = _outside_parts(checked, parts) or checked
            if isinstance(checked, Rejected):
                result.rejected.append(checked)
            elif checked.id not in seen:
                seen.add(checked.id)
                result.observations.append(checked)
    for path, found in missed.items():
        cited = [o.lines for o in result.observations if o.path == path]
        still = [s.name for s in found if not any(a <= s.last_line and s.first_line <= b for a, b in cited)]
        if still:
            result.unobserved[path] = still
