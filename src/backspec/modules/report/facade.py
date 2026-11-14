"""The report, as the rest of backspec sees it."""
from __future__ import annotations

from backspec.modules.report.domain import CoverageReport, FileCoverage, RenderOutput, coverage_text
from backspec.modules.report.dto import Coverage, Diagnostics, ExtractionResult, Run, StageUsage
from backspec.modules.report.renderers import UnknownFormat, formats, render
from backspec.modules.report.use_cases import build_coverage, coverage_report, earlier_evidence, earlier_triage, to_markdown

__all__ = ["Coverage", "CoverageReport", "Diagnostics", "ExtractionResult", "FileCoverage", "RenderOutput", "Run", "StageUsage",
           "UnknownFormat", "build_coverage", "coverage_report", "coverage_text", "earlier_evidence", "earlier_triage", "formats",
           "render", "to_markdown"]
