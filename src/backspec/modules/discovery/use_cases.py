"""Walk the repository once and take a snapshot of every file that will be read."""
from __future__ import annotations

from backspec.modules.discovery.domain import Discovery, Left, SourceFile, excluded_by_pattern, read_or_skip
from backspec.modules.discovery.ports import RepoPort


def discover(repo: RepoPort, include: list[str], exclude: list[str],
             default_excludes: bool = True) -> Discovery:
    files: list[SourceFile] = []
    left: list[Left] = []
    for path in repo.list_paths():
        reason = excluded_by_pattern(path, include, exclude, default_excludes)
        if reason:
            left.append(Left(path, "excluded", reason))
            continue
        outcome = read_or_skip(path, repo.read(path))
        (files if isinstance(outcome, SourceFile) else left).append(outcome)  # type: ignore[arg-type]
    return Discovery(tuple(files), tuple(left))
