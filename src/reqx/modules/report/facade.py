"""The report, as the rest of reqx sees it."""
from __future__ import annotations

from reqx.modules.report.domain import FileCoverage, RenderOutput
from reqx.modules.report.dto import Coverage, Diagnostics, ExtractionResult, Run
from reqx.modules.report.renderers import UnknownFormat, formats, render
from reqx.modules.report.use_cases import build_coverage, earlier_evidence, to_markdown

__all__ = ["Coverage", "Diagnostics", "ExtractionResult", "FileCoverage", "RenderOutput", "Run", "UnknownFormat",
           "build_coverage", "earlier_evidence", "formats", "render", "to_markdown"]
