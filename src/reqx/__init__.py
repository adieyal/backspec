"""reqx: extract user requirements from a codebase, with verified citations.

    from reqx import Config, extract
    result = extract("./repo", Config(include=["src/**"]))
    for requirement in result.requirements:
        print(requirement.id, requirement.support, requirement.statement)
"""
from reqx.host.composition import Config, extract, orient, status, validate
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest
from reqx.modules.capabilities.facade import Capability
from reqx.modules.lint.facade import Finding, LintReport
from reqx.modules.report.facade import ExtractionResult, to_markdown
from reqx.modules.staleness.facade import StatusReport

__all__ = ["Capability", "Config", "ExtractionResult", "Finding", "LLMError", "LLMPort", "LLMRequest", "LintReport",
           "StatusReport", "extract", "orient", "status", "to_markdown", "validate"]
