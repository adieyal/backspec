"""Run the checks on a result."""
from __future__ import annotations

from backspec.modules.lint.domain import Finding, Linted, LintReport, check


def lint(result: Linted) -> LintReport:
    return LintReport(findings=check(result))


def lint_findings(result: Linted) -> list[Finding]:
    """The findings for a run. Lint is an aid: whatever goes wrong inside it never fails a run."""
    try:
        return check(result)
    except Exception:
        return []
