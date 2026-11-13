"""reqx: extract user requirements from a codebase, with verified citations.

    from reqx import Config, extract
    result = extract("./repo", Config(include=["src/**"]))
    for requirement in result.requirements:
        print(requirement.id, requirement.support, requirement.statement)
"""
from reqx.host.composition import Config, extract, orient
from reqx.kernel.llm import LLMError, LLMPort, LLMRequest
from reqx.modules.capabilities.facade import Capability
from reqx.modules.report.facade import ExtractionResult, to_markdown

__all__ = ["Capability", "Config", "ExtractionResult", "LLMError", "LLMPort", "LLMRequest", "extract", "orient", "to_markdown"]
