"""reqx: extract user requirements from a codebase, with verified citations.

    from reqx import Config, extract
    result = extract("./repo", Config(include=["src/**"]))
    for requirement in result.requirements:
        print(requirement.id, requirement.support, requirement.statement)
"""
from reqx.host.composition import Config, extract, status
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest
from reqx.modules.report.facade import ExtractionResult, to_markdown
from reqx.modules.staleness.facade import StatusReport

__all__ = ["Config", "ExtractionResult", "LLMError", "LLMPort", "LLMRequest", "StatusReport", "extract", "status", "to_markdown"]
