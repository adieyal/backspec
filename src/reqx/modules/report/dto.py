"""The result of a run: the one document reqx writes. JSON is its canonical form."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from reqx.modules.capabilities.facade import Capability
from reqx.modules.evidence.facade import Observation, Rejected
from reqx.modules.report.domain import FileCoverage
from reqx.modules.requirements.facade import Requirement
from reqx.modules.review.facade import ReviewSummary

SCHEMA_VERSION = "0.1"


class Run(BaseModel):
    status: Literal["complete", "partial"]
    tool_version: str
    prompt_version: str
    provider: str
    root: str
    calls: int = 0
    cached_calls: int = 0


class Coverage(BaseModel):
    summary: dict[str, int]
    files: list[FileCoverage]
    unused_observations: dict[str, int] = Field(default_factory=dict)   # capability -> count


class Diagnostics(BaseModel):
    rejected: list[Rejected] = Field(default_factory=list)
    failed_capabilities: dict[str, str] = Field(default_factory=dict)
    open_questions: dict[str, list[str]] = Field(default_factory=dict)
    review: ReviewSummary | None = None   # set when ids were carried forward or a review file applied


class ExtractionResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run: Run
    capabilities: list[Capability]
    requirements: list[Requirement]
    observations: list[Observation]
    assignments: dict[str, str] = Field(default_factory=dict)   # observation id -> capability id
    coverage: Coverage
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    def to_json(self) -> str:
        return self.model_dump_json(indent=1)
