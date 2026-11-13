"""Triage: a cheap first look at each file, deciding which are worth reading in full.

The rule is here, not in the prompt. A file is skipped only when the model says its relevance is
`none` and says it is sure. Everything else is read: low relevance, unsure, a file the reply did
not mention, a batch whose call failed. Triage is conservative by construction.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from pydantic import BaseModel, Field

from reqx.kernel.text import numbered

ROLES = ("ui", "api", "domain", "test", "docs", "infra", "config", "generated", "data", "other")
RELEVANCE = ("high", "medium", "low", "none")

PREVIEW_LINES = 40         # lines of each file the model sees
BATCH_FILES = 60           # files per call ...
BATCH_PREVIEW_LINES = 2500  # ... or preview lines per call, whichever comes first

AUDIT_MIN = 5
AUDIT_MAX = 50
DEFAULT_AUDIT = 0.1


class RawVerdict(BaseModel):
    """One file's verdict as the model gave it. Anything missing counts against skipping."""
    path: str
    role: str = "other"
    relevance: str = ""
    sure: bool = False


class TriageReply(BaseModel):
    files: list[RawVerdict] = Field(default_factory=list)


@dataclass(frozen=True)
class Verdict:
    role: str
    relevance: str
    skipped: bool


@dataclass(frozen=True)
class EarlierVerdict:
    """What an earlier run decided about one file, as the file was then."""
    source_hash: str
    verdict: Verdict


def is_skipped(relevance: str, sure: bool) -> bool:
    """The whole rule: skip only a file that is surely of no relevance."""
    return relevance == "none" and sure is True


def decide(raw: RawVerdict) -> Verdict:
    role = raw.role.strip().lower()
    relevance = raw.relevance.strip().lower()
    return Verdict(role=role if role in ROLES else "other",
                   relevance=relevance if relevance in RELEVANCE else "unknown",
                   skipped=is_skipped(relevance, raw.sure))


def merge_duplicate(first: Verdict, second: Verdict) -> Verdict:
    """A path the model answered twice is skipped only if both answers skip it."""
    return Verdict(role=first.role, relevance=first.relevance, skipped=first.skipped and second.skipped)


def preview(path: str, lines: list[str]) -> str:
    shown = lines[:PREVIEW_LINES]
    cut = f", first {len(shown)} shown" if len(shown) < len(lines) else ""
    header = f"=== FILE: {path} ({len(lines)} lines{cut}) ==="
    return "\n".join([header, *numbered(shown, 1), ""])


def pack(sizes: list[tuple[str, int]]) -> list[list[str]]:
    """Paths grouped into batches of at most BATCH_FILES files and BATCH_PREVIEW_LINES preview
    lines, in order. `sizes` is (path, number of lines in the file)."""
    batches: list[list[str]] = []
    current: list[str] = []
    used = 0
    for path, size in sizes:
        shown = min(size, PREVIEW_LINES)
        if current and (len(current) >= BATCH_FILES or used + shown > BATCH_PREVIEW_LINES):
            batches.append(current)
            current, used = [], 0
        current.append(path)
        used += shown
    if current:
        batches.append(current)
    return batches


def audit_size(skipped: int, fraction: float) -> int:
    """How many skipped files the audit reads. 0 turns it off, 1.0 or more reads them all;
    otherwise a fraction, at least AUDIT_MIN and at most AUDIT_MAX, or all if fewer than AUDIT_MIN."""
    if skipped == 0 or fraction <= 0:
        return 0
    if fraction >= 1 or skipped < AUDIT_MIN:
        return skipped
    return min(skipped, max(AUDIT_MIN, min(AUDIT_MAX, math.ceil(skipped * fraction))))


def audit_sample(skipped: list[tuple[str, str]], fraction: float) -> list[str]:
    """The paths of the skipped files to read anyway. `skipped` is (path, source hash). Chosen
    by sorting on the sha256 of the source hash, so the same files are chosen every run."""
    ranked = sorted(skipped, key=lambda s: (hashlib.sha256(s[1].encode()).hexdigest(), s[0]))
    return sorted(path for path, _ in ranked[:audit_size(len(skipped), fraction)])


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def _bisect(f, target: float) -> float:
    """The p in [0, 1] where the decreasing function f(p) crosses target."""
    low, high = 0.0, 1.0
    for _ in range(80):
        middle = (low + high) / 2
        if f(middle) > target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def clopper_pearson(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float] | None:
    """The exact binomial confidence interval for a rate, or None when there were no trials."""
    if trials <= 0:
        return None
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between 0 and trials")
    tail = (1 - confidence) / 2
    lower = 0.0
    if successes > 0:
        # P(X >= k | p) rises with p; the lower bound is where it reaches `tail`
        lower = _bisect(lambda p: -(1 - _binomial_cdf(successes - 1, trials, p)), -tail)
    upper = 1.0 if successes == trials else _bisect(lambda p: _binomial_cdf(successes, trials, p), tail)
    return lower, upper
