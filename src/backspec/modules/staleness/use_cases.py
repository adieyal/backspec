"""Compare a saved result with the repository as it is now."""
from __future__ import annotations

from backspec.modules.report.facade import ExtractionResult
from backspec.modules.staleness.domain import (FileState, RequirementStatus, StatusReport, classify_file,
                                           classify_requirement, hash_of)
from backspec.modules.staleness.ports import RepoPort


def _current_hash(repo: RepoPort, path: str) -> str | None:
    try:
        return hash_of(repo.read(path))
    except (OSError, ValueError):
        return None


def check(result: ExtractionResult, repo: RepoPort) -> StatusReport:
    recorded: dict[str, str] = {}
    for observation in sorted(result.observations, key=lambda o: (o.path, o.id)):
        recorded.setdefault(observation.path, observation.source_hash)
    states: dict[str, FileState] = {
        path: classify_file(recorded[path], _current_hash(repo, path)) for path in sorted(recorded)}

    items: list[RequirementStatus] = []
    for requirement in result.requirements:
        cited = sorted({e.path for e in requirement.evidence})
        # evidence that names a path no observation recorded cannot be confirmed: it counts as changed
        mine = {path: states.get(path, "changed") for path in cited}
        items.append(RequirementStatus(
            id=requirement.id, capability=requirement.capability, statement=requirement.statement,
            status=classify_requirement(mine),
            changed=[p for p, s in mine.items() if s == "changed"],
            missing=[p for p, s in mine.items() if s == "missing"]))
    items.sort(key=lambda r: (r.capability, r.id))
    counts = {name: sum(1 for r in items if r.status == name) for name in ("current", "stale", "source_missing")}
    return StatusReport(counts=counts,
                        changed_files=[p for p, s in states.items() if s == "changed"],
                        missing_files=[p for p, s in states.items() if s == "missing"],
                        requirements=items)
