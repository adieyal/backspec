"""The report, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.modules.report.domain import CoverageReport, FileCoverage, RenderOutput, coverage_text
from reqx.modules.report.dto import Coverage, Diagnostics, ExtractionResult, Run
from reqx.modules.report.renderers import UnknownFormat, formats, render
from reqx.modules.report.use_cases import build_coverage, coverage_report, earlier_evidence, to_markdown

__all__ = ["Coverage", "CoverageReport", "Diagnostics", "ExtractionResult", "FileCoverage", "RenderOutput", "Run",
           "UnknownFormat", "build_coverage", "coverage_report", "coverage_text", "earlier_evidence", "formats",
           "render", "to_markdown"]
