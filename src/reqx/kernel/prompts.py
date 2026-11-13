"""The prompt templates, shipped with the package. PROMPT_VERSION changes whenever one does."""
from __future__ import annotations

from importlib import resources

PROMPT_VERSION = "2026-11-a"


def load(name: str) -> str:
    return resources.files("reqx.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
