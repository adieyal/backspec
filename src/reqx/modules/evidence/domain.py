"""Observations: single facts a file establishes, each tied to lines that are checked in code.

An observation is evidence. It is not a requirement. A citation is accepted only when its quote
is really in the file: inside the cited lines (exact), or in exactly one other place, to which
the range is then moved (repaired). Anything else is rejected and recorded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from reqx.kernel.text import numbered, short_hash, squash

Kind = Literal["entry_point", "permission", "validation", "state_change", "rule", "display",
               "error_path", "test_case", "doc_claim", "other"]


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


@dataclass(frozen=True)
class Earlier:
    """What an earlier run established about one file: the file as it was read then, and the
    observations that verified. An unchanged file need not be read again."""
    source_hash: str
    observations: tuple["Observation", ...]
    nothing_reason: str | None = None


class Rejected(BaseModel):
    path: str
    lines: list[int]
    quote: str
    statement: str
    reason: str


def split_file(path: str, lines: list[str], limit: int) -> list[Chunk]:
    """A file as chunks of at most `limit` lines, cut at a blank line before top-level code
    where one is near, so that a function is not cut in half."""
    chunks, start = [], 0
    while start < len(lines):
        end = min(start + limit, len(lines))
        if end < len(lines):
            for cut in range(end, max(start + limit // 2, end - 150), -1):
                if not lines[cut - 1].strip() and not lines[cut].startswith((" ", "\t")):
                    end = cut
                    break
        chunks.append(Chunk(path, start + 1, tuple(lines[start:end])))
        start = end
    return chunks


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
        id="OBS-" + short_hash(source_hashes[raw.path], where, raw.statement),
        statement=raw.statement.strip(), kind=raw.kind, path=raw.path, lines=where,
        quote=_clean(raw.quote), source_hash=source_hashes[raw.path], verified=verdict)
