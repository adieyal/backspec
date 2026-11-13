"""The result of a run: the one document reqx writes. JSON is its canonical form."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from reqx.modules.capabilities.facade import Capability
from reqx.modules.evidence.facade import Observation, Rejected
from reqx.modules.lint.facade import Finding
from reqx.modules.report.domain import FileCoverage
from reqx.modules.requirements.facade import Requirement
from reqx.modules.review.facade import ReviewSummary

SCHEMA_VERSION = "0.1"


class StageUsage(BaseModel):
    calls: int = 0    # replies the model produced
    cached: int = 0   # replies served from the cache: they cost nothing
    input_tokens: int = 0
    output_tokens: int = 0


class Run(BaseModel):
    status: Literal["complete", "partial"]
    tool_version: str
    prompt_version: str
    provider: str
    root: str
    calls: int = 0
    cached_calls: int = 0
    capabilities_source: Literal["file", "oriented", "previous"] = "oriented"
    observe_fingerprint: str = ""   # how files were observed; a later run reuses observations only if it matches
    reused_files: int = 0           # files unchanged since the previous result, not read again
    partly_read_files: int = 0      # files changed since the previous result: only the changed parts were read
    syntax_files: int = 0           # files read with symbols from a parser
    text_files: int = 0             # files read as plain text
    synthesis_fingerprint: str = ""  # how requirements were written and judged
    reused_capabilities: list[str] = Field(default_factory=list)   # evidence unchanged, requirements kept
    stopped_after: Literal["capabilities"] | None = None   # set when a gated run stopped early
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_estimated: bool = False   # true if any call's tokens were estimated, not reported
    cost_usd: float | None = None    # the backend's own cost figure, summed, when it reports one
    usage_by_stage: dict[str, StageUsage] = Field(default_factory=dict)
    budget_reached: bool = False     # a call was not sent because the token budget was reached


class Coverage(BaseModel):
    summary: dict[str, int]
    files: list[FileCoverage]
    unused_observations: dict[str, int] = Field(default_factory=dict)   # capability -> count


class Diagnostics(BaseModel):
    rejected: list[Rejected] = Field(default_factory=list)
    failed_capabilities: dict[str, str] = Field(default_factory=dict)
    unconsolidated: dict[str, str] = Field(default_factory=dict)   # capability -> why its merge pass failed
    dropped_scenarios: int = 0   # scenarios the model wrote that were left out (incomplete or uncited)
    open_questions: dict[str, list[str]] = Field(default_factory=dict)
    review: ReviewSummary | None = None   # set when ids were carried forward or a review file applied
    lint: list[Finding] = Field(default_factory=list)   # deterministic checks on the finished result
    failed_stages: dict[str, str] = Field(default_factory=dict)   # a stage the whole run depends on -> why it failed


class ExtractionResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run: Run
    capabilities: list[Capability]
    requirements: list[Requirement]
    hidden: list[Requirement] = Field(default_factory=list)   # rejected in review: kept here, left out of the catalogue
    observations: list[Observation]
    assignments: dict[str, str] = Field(default_factory=dict)   # observation id -> capability id
    coverage: Coverage
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    def to_json(self) -> str:
        return self.model_dump_json(indent=1)
