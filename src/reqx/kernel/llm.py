"""The one port every stage uses to reach a model, and the rule for reading its replies.

A stage builds a prompt, says which tier it needs and what shape the answer must have. The
pipeline, not the adapter, parses and validates the reply, and asks again when it is malformed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

Tier = Literal["fast", "strong"]
Reply = TypeVar("Reply", bound=BaseModel)


@dataclass(frozen=True)
class LLMRequest:
    stage: str
    prompt: str
    tier: Tier = "fast"


class LLMPort(Protocol):
    def complete(self, request: LLMRequest) -> str:
        """The model's reply as text. Raises LLMError when no reply could be had."""
        ...


class LLMError(Exception):
    """The model could not be reached, or never gave a reply in the required shape."""


def extract_json(text: str) -> object:
    """The JSON value in a reply, whether bare, fenced, or surrounded by a sentence or two."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def ask(llm: LLMPort, request: LLMRequest, shape: type[Reply], retries: int = 2) -> Reply:
    """Ask until the reply parses as `shape`, at most `retries` more times, telling the model
    what was wrong with its last attempt."""
    prompt = request.prompt
    problem = ""
    for _ in range(retries + 1):
        text = llm.complete(LLMRequest(request.stage, prompt, request.tier))
        try:
            return shape.model_validate(extract_json(text))
        except (json.JSONDecodeError, ValidationError) as error:
            problem = str(error)[:1500]
            prompt = (f"{request.prompt}\n\nYour previous reply could not be used:\n{problem}\n"
                      "Reply again with the JSON only, in exactly the shape asked for.")
    raise LLMError(f"{request.stage}: no usable reply after {retries + 1} attempts: {problem}")
