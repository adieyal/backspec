"""A model backend for tests: each stage is answered by a function you supply."""
from __future__ import annotations

import json
import threading
from typing import Callable

from backspec.kernel.llm import LLMError, LLMRequest
from backspec.kernel.usage import Usage

Answer = Callable[[str], object]
Reporter = Callable[[LLMRequest, str], "Usage | None"]


class FakeLLM:
    name = "fake"

    def __init__(self, answers: dict[str, Answer]):
        self.answers = answers
        self.requests: list[LLMRequest] = []
        self.report: Reporter | None = None   # set to make the fake report usage, as a real backend does
        self._local = threading.local()

    def last_usage(self) -> Usage | None:
        return getattr(self._local, "usage", None)

    def label(self, tier: str) -> str:
        return f"fake:{tier}"

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        self._local.usage = None
        if request.stage not in self.answers:
            raise LLMError(f"{request.stage}: the fake has no answer for this stage")
        reply = self.answers[request.stage](request.prompt)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        if self.report:
            self._local.usage = self.report(request, text)
        return text
