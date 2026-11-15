"""Plan which parts of the followed files to read: parse, then follow the calls."""
from __future__ import annotations

from backspec.modules.discovery.facade import SourceFile
from backspec.modules.reach.domain import (DEFAULT_DEPTH, Call, Definition, FollowedFile, FollowReport, innermost,
                                           reach, report)
from backspec.modules.reach.ports import CallsPort

NO_PARSER = "following calls needs tree-sitter (the `treesitter` extra), and it is not in use"


def _parse(syntax: CallsPort, file: SourceFile) -> tuple[list[Definition], list[Call]] | str:
    """The definitions and calls of a file, or why they could not be had."""
    try:
        symbols = syntax.symbols(file.path, file.text)
        calls = syntax.calls(file.path, file.text)
        properties = syntax.properties(file.path, file.text) or set()
    except Exception as error:   # a parser that fails is recorded, never fatal
        return f"could not be parsed: {error}"[:200]
    if symbols is None or calls is None:
        return "could not be parsed (no grammar for this language, or a parse failure)"
    return [Definition(file.path, s.name, s.kind, s.first_line, s.last_line, s.first_line in properties)
            for s in symbols], calls


def plan(seeds: list[SourceFile], followed: list[SourceFile], syntax: CallsPort | None, patterns: list[str],
         depth: int = DEFAULT_DEPTH) -> FollowReport:
    lengths = {f.path: len(f.lines) for f in followed}
    if syntax is None:
        return FollowReport(patterns=patterns, depth=depth, unavailable=NO_PARSER,
                            files=[FollowedFile(path=p, lines=n, reason=NO_PARSER) for p, n in sorted(lengths.items())])
    seed_calls: list[tuple[Call, str]] = []
    for f in seeds:
        parsed = _parse(syntax, f)
        if isinstance(parsed, str):
            continue   # a selected file that cannot be parsed is read as text; it just calls nothing here
        definitions, calls = parsed
        seed_calls += [(c, f"{f.path}:{innermost(definitions, c.line) or '(module)'}") for c in calls]
    definitions: list[Definition] = []
    calls: dict[str, list[Call]] = {}
    unparsed: dict[str, str] = {}
    for f in followed:
        parsed = _parse(syntax, f)
        if isinstance(parsed, str):
            unparsed[f.path] = parsed
            continue
        definitions += parsed[0]
        calls[f.path] = parsed[1]
    reached, skipped, ambiguous = reach(seed_calls, definitions, calls, depth)
    return report(patterns, depth, lengths, reached, skipped, ambiguous, unparsed)
