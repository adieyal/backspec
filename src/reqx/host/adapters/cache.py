"""A cache in front of any model backend, and a count of the calls made.

The key is a hash of the complete input: the model's label, the prompt version and the whole
prompt. Anything that changes what the model sees changes the key.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from reqx.kernel.llm import LLMError, LLMPort, LLMRequest
from reqx.kernel.prompts import PROMPT_VERSION


class CachedLLM:
    def __init__(self, inner: LLMPort, directory: Path | None, replay: bool = False):
        self.inner = inner
        self.directory = directory
        self.replay = replay
        self.calls = 0
        self.cached = 0
        self._lock = threading.Lock()
        if directory:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _label(self, tier: str) -> str:
        label = getattr(self.inner, "label", None)
        return label(tier) if callable(label) else f"{type(self.inner).__name__}:{tier}"

    def complete(self, request: LLMRequest) -> str:
        key = hashlib.sha256("\0".join([self._label(request.tier), PROMPT_VERSION, request.prompt]).encode()).hexdigest()
        path = self.directory / f"{request.stage}-{key[:32]}.json" if self.directory else None
        if path and path.exists():
            with self._lock:
                self.cached += 1
            return json.loads(path.read_text(encoding="utf-8"))["reply"]
        if self.replay:
            raise LLMError(f"{request.stage}: replay mode and no cached reply for this call")
        reply = self.inner.complete(request)
        with self._lock:
            self.calls += 1
        if path:
            path.write_text(json.dumps({"stage": request.stage, "model": self._label(request.tier), "reply": reply}),
                            encoding="utf-8")
        return reply

    def usage(self) -> tuple[int, int]:
        return self.calls, self.cached
