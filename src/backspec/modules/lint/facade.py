"""Lint, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.modules.lint.domain import Finding, Linted, LintReport, Severity, summary
from backspec.modules.lint.use_cases import lint, lint_findings

__all__ = ["Finding", "Linted", "LintReport", "Severity", "lint", "lint_findings", "summary"]
