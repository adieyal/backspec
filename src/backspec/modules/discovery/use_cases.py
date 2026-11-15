"""Walk the repository once and take a snapshot of every file that will be read."""
from __future__ import annotations

from backspec.modules.discovery.domain import Discovery, Left, SourceFile, excluded_by_pattern, followed, read_or_skip
from backspec.modules.discovery.ports import RepoPort


def discover(repo: RepoPort, include: list[str], exclude: list[str],
             default_excludes: bool = True, follow: list[str] | None = None) -> Discovery:
    """`follow` names files that are not selected but whose parts the selected files call may be
    read; they come back in `followed`, or in `left` with a reason if they cannot be read."""
    files: list[SourceFile] = []
    left: list[Left] = []
    follows: list[SourceFile] = []
    for path in repo.list_paths():
        reason = excluded_by_pattern(path, include, exclude, default_excludes)
        if reason == "not_included" and followed(path, follow or [], exclude, default_excludes):
            outcome = read_or_skip(path, repo.read(path))
            (follows if isinstance(outcome, SourceFile) else left).append(outcome)  # type: ignore[arg-type]
            continue
        if reason:
            left.append(Left(path, "excluded", reason))
            continue
        outcome = read_or_skip(path, repo.read(path))
        (files if isinstance(outcome, SourceFile) else left).append(outcome)  # type: ignore[arg-type]
    return Discovery(tuple(files), tuple(left), tuple(follows))
