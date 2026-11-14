"""backspec: extract user requirements from a codebase, with verified citations.

    from backspec import Config, extract
    result = extract("./repo", Config(include=["src/**"]))
    for requirement in result.requirements:
        print(requirement.id, requirement.support, requirement.statement)
"""
from backspec.host.composition import Config, extract, orient, status, validate
from backspec.kernel.llm import LLMError, LLMPort, LLMRequest
from backspec.modules.capabilities.facade import Capability
from backspec.modules.lint.facade import Finding, LintReport
from backspec.modules.report.facade import ExtractionResult, to_markdown
from backspec.modules.staleness.facade import StatusReport

__all__ = ["Capability", "Config", "ExtractionResult", "Finding", "LLMError", "LLMPort", "LLMRequest", "LintReport",
           "StatusReport", "extract", "orient", "status", "to_markdown", "validate"]
