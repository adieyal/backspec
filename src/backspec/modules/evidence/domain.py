"""Observations: single facts a file establishes, each tied to lines that are checked in code.

An observation is evidence. It is not a requirement. A citation is accepted only when its quote
is really in the file: inside the cited lines (exact), or in exactly one other place, to which
the range is then moved (repaired). Anything else is rejected and recorded.
"""
from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from backspec.kernel.text import numbered, short_hash, squash

Kind = Literal["entry_point", "permission", "validation", "state_change", "rule", "display",
               "error_path", "test_case", "doc_claim", "other"]


@dataclass(frozen=True)
class Symbol:
    """A named definition in a file. Lines are 1-based and inclusive. `name` is qualified by the
    symbols around it (`Class.method`)."""
    name: str
    kind: Literal["function", "method", "class", "other"]
    first_line: int
    last_line: int


@dataclass(frozen=True)
class Chunk:
    """A run of lines from one file, with the real number of its first line."""
    path: str
    first: int
    lines: tuple[str, ...]

    @property
    def last(self) -> int:
        return self.first + len(self.lines) - 1


class RawObservation(BaseModel):
    """An observation as the model gave it, before any check."""
    path: str = ""
    lines: list[int] = Field(default_factory=list)
    quote: str = ""
    kind: str = "other"
    statement: str = ""


class NothingFound(BaseModel):
    path: str
    reason: str = ""


class ObserveReply(BaseModel):
    observations: list[RawObservation] = Field(default_factory=list)
    none: list[NothingFound] = Field(default_factory=list)


class Observation(BaseModel):
    id: str
    statement: str
    kind: str
    path: str
    lines: tuple[int, int]
    quote: str
    source_hash: str
    verified: Literal["exact", "repaired"]
    symbol: str | None = None   # innermost symbol holding the whole range; set in code, never by a model


@dataclass(frozen=True)
class Earlier:
    """What an earlier run established about one file: the file as it was read then, and the
    observations that verified. An unchanged file need not be read again."""
    source_hash: str
    observations: tuple["Observation", ...]
    nothing_reason: str | None = None
    line_digest: str = ""   # the file line by line, to find what changed since; empty if not recorded


class Rejected(BaseModel):
    path: str
    lines: list[int]
    quote: str
    statement: str
    reason: str


def split_file(path: str, lines: list[str], limit: int, symbols: list[Symbol] | None = None) -> list[Chunk]:
    """A file as chunks of at most `limit` lines. With `symbols`, a cut falls between top-level
    symbols, never inside one, whenever that fits within the limit. Otherwise (and for a single
    symbol larger than the limit) it is at a blank line before top-level code where one is near."""
    cuts = _symbol_cuts(lines, symbols) if symbols else []
    chunks, start = [], 0
    while start < len(lines):
        end = min(start + limit, len(lines))
        if end < len(lines):
            fits = [cut for cut in cuts if start < cut <= end]
            if fits:
                end = max(fits)
            else:
                end = _text_cut(lines, start, end, limit)
        chunks.append(Chunk(path, start + 1, tuple(lines[start:end])))
        start = end
    return chunks


def _text_cut(lines: list[str], start: int, end: int, limit: int) -> int:
    for cut in range(end, max(start + limit // 2, end - 150), -1):
        if not lines[cut - 1].strip() and not lines[cut].startswith((" ", "\t")):
            return cut
    return end


def _symbol_cuts(lines: list[str], symbols: list[Symbol]) -> list[int]:
    """Line numbers after which a chunk may end: just after a top-level symbol, or just before one
    (taking the comment lines directly above it along with it)."""
    top: list[Symbol] = []
    for symbol in sorted(symbols, key=lambda s: (s.first_line, -s.last_line)):
        if not top or symbol.first_line > top[-1].last_line:
            top.append(symbol)
    cuts: set[int] = set()
    previous_end = 0
    for symbol in top:
        cut = symbol.first_line - 1
        while cut > previous_end and cut <= len(lines) and lines[cut - 1].strip():
            cut -= 1
        cuts.add(cut)
        cuts.add(symbol.last_line)
        previous_end = symbol.last_line
    return sorted(c for c in cuts if 0 < c < len(lines))


def enclosing_symbol(symbols: list[Symbol] | None, first: int, last: int) -> str | None:
    """The qualified name of the innermost symbol that contains the whole range, or None."""
    best: Symbol | None = None
    for symbol in symbols or []:
        if symbol.first_line <= first and last <= symbol.last_line:
            if best is None or (symbol.last_line - symbol.first_line, -symbol.name.count(".")) < \
                    (best.last_line - best.first_line, -best.name.count(".")):
                best = symbol
    return best.name if best else None


MIN_SYMBOL_LINES = 3   # a function shorter than this is not worth a second look


def unobserved(symbols: list[Symbol] | None, cited: list[tuple[int, int]]) -> list[Symbol]:
    """The functions and methods no observation touches, outermost first: those not inside another
    function, of at least MIN_SYMBOL_LINES lines. An entry point that only delegates is still
    behaviour (what it accepts, what it refuses, what it hands on), so a reading that recorded
    nothing in it has probably missed something."""
    callables = [s for s in symbols or [] if s.kind in ("function", "method")]
    out = []
    for symbol in callables:
        nested = any(o is not symbol and o.first_line <= symbol.first_line and symbol.last_line <= o.last_line
                     and (o.first_line, -o.last_line) != (symbol.first_line, -symbol.last_line) for o in callables)
        if nested or symbol.last_line - symbol.first_line + 1 < MIN_SYMBOL_LINES:
            continue
        if not any(a <= symbol.last_line and symbol.first_line <= b for a, b in cited):
            out.append(symbol)
    return sorted(out, key=lambda s: s.first_line)


def pack(chunks: list[Chunk], limit: int) -> list[list[Chunk]]:
    """Chunks grouped into batches of at most `limit` lines, in order."""
    batches: list[list[Chunk]] = []
    current: list[Chunk] = []
    size = 0
    for chunk in chunks:
        if current and size + len(chunk.lines) > limit:
            batches.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(chunk.lines)
    if current:
        batches.append(current)
    return batches


def render(batch: list[Chunk]) -> str:
    """A batch as the model sees it: a header per file, then every line with its real number."""
    out: list[str] = []
    for chunk in batch:
        out.append(f"=== FILE: {chunk.path} (lines {chunk.first}-{chunk.last}) ===")
        out += numbered(list(chunk.lines), chunk.first)
        out.append("")
    return "\n".join(out)


DIGEST_WIDTH = 6      # characters of digest kept for each line
CONTEXT_AROUND_CHANGE = 30


def observation_id(path: str, cited_lines: list[str], statement: str) -> str:
    """An id that depends on the cited text, not on where it sits. Moving the code keeps the id;
    changing the cited lines changes it."""
    return "OBS-" + short_hash(path, squash("\n".join(cited_lines)), statement.strip())


def line_digest(lines: list[str]) -> str:
    """The file as one short digest per line, enough to tell later which lines changed."""
    return "".join(hashlib.sha1(squash(line).encode()).hexdigest()[:DIGEST_WIDTH] for line in lines)


@dataclass(frozen=True)
class Change:
    """How a file differs from the one an earlier run read. `kept` are runs of lines that are the
    same, as (old first line, new first line, length). `changed` are the new or altered line
    ranges in the file as it is now."""
    kept: tuple[tuple[int, int, int], ...]
    changed: tuple[tuple[int, int], ...]

    def moved(self, first: int, last: int) -> tuple[int, int] | None:
        """Where an old line range is now, if every line of it is unchanged."""
        for old, new, length in self.kept:
            if old <= first and last < old + length:
                return first - old + new, last - old + new
        return None

    def touches(self, first: int, last: int) -> bool:
        return any(a <= last and first <= b for a, b in self.changed)


def compare(old_digest: str, new_lines: list[str]) -> Change:
    old = [old_digest[i:i + DIGEST_WIDTH] for i in range(0, len(old_digest), DIGEST_WIDTH)]
    digest = line_digest(new_lines)
    new = [digest[i:i + DIGEST_WIDTH] for i in range(0, len(digest), DIGEST_WIDTH)]
    kept, changed = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "equal":
            kept.append((i1 + 1, j1 + 1, i2 - i1))
        elif j2 > j1:
            changed.append((j1 + 1, j2))
    return Change(tuple(kept), tuple(changed))


def windows(changed: tuple[tuple[int, int], ...], total: int, context: int = CONTEXT_AROUND_CHANGE) -> list[tuple[int, int]]:
    """The line ranges to show a model: each change with context either side, overlaps merged."""
    out: list[list[int]] = []
    for first, last in changed:
        a, b = max(1, first - context), min(total, last + context)
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def carried(observation: "Observation", change: Change, source_hash: str) -> "Observation | None":
    """An earlier observation as it stands in the changed file, or None if its lines changed."""
    where = change.moved(*observation.lines)
    if where is None:
        return None
    return observation.model_copy(update={"lines": where, "source_hash": source_hash})


def _clean(quote: str) -> str:
    """A quote without the `  123| ` prefix a model sometimes copies along with the line."""
    return squash(re.sub(r"^\s*\d+\|\s?", "", quote))


def verify(raw: RawObservation, shown: set[str], file_lines: dict[str, list[str]],
           source_hashes: dict[str, str]) -> Observation | Rejected:
    """Check one observation against the files the model was shown."""
    def reject(reason: str) -> Rejected:
        return Rejected(path=raw.path, lines=raw.lines, quote=raw.quote, statement=raw.statement, reason=reason)

    if raw.path not in shown:
        return reject("path was not shown to the model")
    if not raw.statement.strip():
        return reject("no statement")
    quote = _clean(raw.quote)
    if len(quote) < 4:
        return reject("no usable quote")
    lines = file_lines[raw.path]
    span = raw.lines if len(raw.lines) == 2 and 1 <= raw.lines[0] <= raw.lines[1] <= len(lines) else None
    verdict: Literal["exact", "repaired"]
    if span and quote in squash("\n".join(lines[span[0] - 1:span[1]])):
        verdict, where = "exact", (span[0], span[1])
    else:
        hits = [number for number, line in enumerate(lines, 1) if quote in squash(line)]
        if len(hits) != 1:
            return reject("quote not found" if not hits else "quote found more than once")
        width = min(span[1] - span[0], 30) if span else 0
        first = max(1, hits[0] - width // 2)
        verdict, where = "repaired", (first, min(len(lines), first + width))
    return Observation(
        id=observation_id(raw.path, lines[where[0] - 1:where[1]], raw.statement),
        statement=raw.statement.strip(), kind=raw.kind, path=raw.path, lines=where,
        quote=_clean(raw.quote), source_hash=source_hashes[raw.path], verified=verdict)
