"""Which parts of the followed files the selected files reach, by the names they call.

The selected files are read in full. A followed file is read only where it defines something
that the selected code calls, directly or through calls already followed, up to a depth.

Calls are matched to definitions by name alone, so this is an approximation. Names so common
that a match would mean nothing (`save`, `get`, `filter` ...) are never followed, nor is a name
defined more than MAX_DEFINITIONS times in the followed files. Both are recorded, as is every
name followed to more than one definition. Nothing is passed over silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

# Names that say nothing about which definition is meant: Python and Django built-ins and
# container, string, queryset and model methods that every model shares.
GENERIC_NAMES = frozenset("""
save get filter exclude all create delete update objects first last exists values values_list count
append extend insert pop remove clear copy items keys setdefault format strip lstrip rstrip split join
replace lower upper startswith endswith encode decode get_or_create update_or_create bulk_create
bulk_update order_by distinct select_related prefetch_related annotate aggregate only defer using none
refresh_from_db full_clean clean clean_fields validate_unique add set sort sorted reverse reversed
len str int float bool list dict tuple isinstance issubclass getattr setattr hasattr super print range
enumerate zip map min max sum any all abs round open next iter type id repr hash vars dir callable
json loads dumps dump load now today date datetime timedelta strftime strptime isoformat astimezone
localtime make_aware is_aware log debug info warning error exception critical render redirect reverse
get_object_or_404 HttpResponse JsonResponse Http404 Q F Count Sum Max Min Avg Exists OuterRef Subquery
__init__ __str__ __repr__ __eq__ __hash__ send emit run call apply execute process handle read write
close flush to_dict as_dict serialize validate is_valid cleaned_data
""".split())

MAX_DEFINITIONS = 3   # a name defined more often than this in the followed files is not followed
DEFAULT_DEPTH = 2
CALLABLE = ("function", "method")


@dataclass(frozen=True)
class Definition:
    """A function, method or class in a file. Lines are 1-based and inclusive; `name` is
    qualified (`Class.method`)."""
    path: str
    name: str
    kind: str
    first: int
    last: int
    attribute: bool = False   # read or set as an attribute, without a call (a Python @property and its setter)

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Call:
    """A name called on a line: `foo(...)` and `x.foo(...)` are both `foo`. With `called` false,
    an attribute used without a call (`x.foo`, `x.foo = 1`), which can only reach a property."""
    name: str
    line: int
    called: bool = True


class ReachedSymbol(BaseModel):
    path: str
    symbol: str
    lines: tuple[int, int]
    depth: int                       # 1: called from a selected file; 2: from a symbol reached at depth 1 ...
    called_as: str
    called_from: list[str] = Field(default_factory=list)   # "path:symbol" of each caller that reached it


class SkippedName(BaseModel):
    name: str
    reason: Literal["generic", "ambiguous"]
    definitions: int                 # how many times the followed files define it
    called_from: list[str] = Field(default_factory=list)


class AmbiguousName(BaseModel):
    """A name followed to more than one definition: which was meant cannot be told by name."""
    name: str
    definitions: list[str]


class FollowedFile(BaseModel):
    path: str
    lines: int                       # length of the file
    lines_read: int = 0              # lines shown to a model
    ranges: list[tuple[int, int]] = Field(default_factory=list)
    symbols: int = 0                 # symbols reached in it
    reason: str = ""                 # why nothing of it was read, when nothing was


class FollowReport(BaseModel):
    """What following calls into other files did: what it read, and what it would not follow."""
    patterns: list[str] = Field(default_factory=list)
    depth: int = DEFAULT_DEPTH
    files: list[FollowedFile] = Field(default_factory=list)
    reached: list[ReachedSymbol] = Field(default_factory=list)
    skipped: list[SkippedName] = Field(default_factory=list)
    ambiguous: list[AmbiguousName] = Field(default_factory=list)
    unavailable: str = ""            # why nothing could be followed at all (no parser)

    def ranges(self) -> dict[str, list[tuple[int, int]]]:
        """Path -> the line ranges to read, for every followed file of which something is read."""
        return {f.path: f.ranges for f in self.files if f.ranges}


def innermost(definitions: list[Definition], line: int) -> str | None:
    best: Definition | None = None
    for d in definitions:
        if d.first <= line <= d.last and (best is None or d.last - d.first < best.last - best.first):
            best = d
    return best.name if best else None


def merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for first, last in sorted(ranges):
        if out and first <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], last)
        else:
            out.append([first, last])
    return [(a, b) for a, b in out]


def reach(seed_calls: list[tuple[Call, str]], definitions: list[Definition], calls: dict[str, list[Call]],
          depth: int = DEFAULT_DEPTH, generic: frozenset[str] = GENERIC_NAMES,
          max_definitions: int = MAX_DEFINITIONS) -> tuple[list[ReachedSymbol], list[SkippedName], list[AmbiguousName]]:
    """Follow calls from the selected code into the followed files.

    `seed_calls` are the calls in the selected files, each with "path:symbol" of where it is.
    `definitions` and `calls` are those of the followed files. A call reaches every function or
    method of that name; a call of a class name reaches that class's `__init__`, if it has one.
    A class's other methods are reached only when they are called themselves. An attribute used
    without a call reaches only definitions read as attributes (properties)."""
    by_name: dict[str, list[Definition]] = {}
    for d in definitions:
        by_name.setdefault(d.short, []).append(d)
    classes = {d.name for d in definitions if d.kind == "class"}

    def targets(call: Call) -> list[Definition]:
        name = call.name
        if not call.called:
            return [d for d in by_name.get(name, []) if d.kind in CALLABLE and d.attribute]
        found = [d for d in by_name.get(name, []) if d.kind in CALLABLE]
        constructors = [d for d in by_name.get("__init__", [])
                        if d.kind in CALLABLE and d.name.rsplit(".", 1)[0] in classes
                        and d.name.rsplit(".", 1)[0].rsplit(".", 1)[-1] == name]
        return found + constructors

    reached: dict[tuple[str, str, int], ReachedSymbol] = {}
    skipped: dict[str, SkippedName] = {}
    ambiguous: dict[str, AmbiguousName] = {}
    frontier = seed_calls
    for level in range(1, depth + 1):
        new: list[Definition] = []
        for call, origin in frontier:
            found = targets(call)
            if not found:
                continue   # defined nowhere in the followed files: nothing to follow, nothing to record
            distinct = sorted({f"{d.path}:{d.name}" for d in found})   # a property and its setter are one
            if call.name in generic or len(distinct) > max_definitions:
                entry = skipped.setdefault(call.name, SkippedName(
                    name=call.name, reason="generic" if call.name in generic else "ambiguous", definitions=len(distinct)))
                if origin not in entry.called_from:
                    entry.called_from.append(origin)
                continue
            if len(distinct) > 1:
                ambiguous.setdefault(call.name, AmbiguousName(name=call.name, definitions=distinct))
            for d in found:
                key = (d.path, d.name, d.first)
                if key in reached:
                    if origin not in reached[key].called_from:
                        reached[key].called_from.append(origin)
                    continue
                reached[key] = ReachedSymbol(path=d.path, symbol=d.name, lines=(d.first, d.last), depth=level,
                                             called_as=call.name, called_from=[origin])
                new.append(d)
        frontier = [(c, f"{d.path}:{d.name}") for d in new for c in calls.get(d.path, []) if d.first <= c.line <= d.last]
    return (sorted(reached.values(), key=lambda r: (r.path, r.lines)),
            sorted(skipped.values(), key=lambda s: s.name), sorted(ambiguous.values(), key=lambda a: a.name))


def report(patterns: list[str], depth: int, followed: dict[str, int], reached: list[ReachedSymbol],
           skipped: list[SkippedName], ambiguous: list[AmbiguousName], unparsed: dict[str, str]) -> FollowReport:
    """The report, with the ranges to read per followed file. `followed` is path -> its length."""
    files = []
    for path, total in sorted(followed.items()):
        mine = [r for r in reached if r.path == path]
        ranges = merge([r.lines for r in mine])
        reason = unparsed.get(path, "" if ranges else "nothing the selected files call is defined here")
        files.append(FollowedFile(path=path, lines=total, ranges=ranges, symbols=len(mine),
                                  lines_read=sum(b - a + 1 for a, b in ranges), reason=reason))
    return FollowReport(patterns=patterns, depth=depth, files=files, reached=reached, skipped=skipped, ambiguous=ambiguous)
