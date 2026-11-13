"""A model backend for tests: each stage is answered by a function you supply."""
from __future__ import annotations

import json
from typing import Callable

from reqx.kernel.llm import LLMError, LLMRequest

Answer = Callable[[str], object]


class FakeLLM:
    name = "fake"

    def __init__(self, answers: dict[str, Answer]):
        self.answers = answers
        self.requests: list[LLMRequest] = []

    def label(self, tier: str) -> str:
        return f"fake:{tier}"

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if request.stage not in self.answers:
            raise LLMError(f"{request.stage}: the fake has no answer for this stage")
        reply = self.answers[request.stage](request.prompt)
        return reply if isinstance(reply, str) else json.dumps(reply)
