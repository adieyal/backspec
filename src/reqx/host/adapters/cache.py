"""A cache in front of any model backend, a count of the calls made, and the token budget.

Tokens: after a call the wrapper asks the backend for `last_usage()` (backends keep it per
thread, so the read is correct when calls run in parallel) and falls back to an estimate. With
a budget, a call is sent only if tokens spent + tokens reserved by calls in flight + its own
reservation fit; the reservation is replaced by the actual cost when the call returns, or just
released when it fails. A run can therefore overshoot by at most the amount by which the calls in
flight when the last call was admitted turned out dearer than their reservations.

The key is a hash of the complete input: the model's label and the whole prompt, instructions
included. Anything that changes what the model sees changes the key, and nothing else does: a
change to one stage's prompt leaves the other stages' cached replies in use.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from reqx.kernel.llm import LLMError, LLMPort, LLMRequest
from reqx.kernel.usage import Spend, Usage, estimate_usage, reservation


class CachedLLM:
    def __init__(self, inner: LLMPort, directory: Path | None, replay: bool = False,
                 max_tokens: int | None = None):
        self.inner = inner
        self.directory = directory
        self.replay = replay
        self.calls = 0
        self.cached = 0
        self.max_tokens = max_tokens
        self.budget_reached = False
        self._spent = 0       # tokens used by finished calls
        self._reserved = 0    # tokens held for calls in flight
        self._input = 0
        self._output = 0
        self._estimated = False
        self._cost: float | None = None
        self._stages: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()
        if directory:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _label(self, tier: str) -> str:
        label = getattr(self.inner, "label", None)
        return label(tier) if callable(label) else f"{type(self.inner).__name__}:{tier}"

    def complete(self, request: LLMRequest) -> str:
        key = hashlib.sha256("\0".join([self._label(request.tier), request.prompt]).encode()).hexdigest()
        path = self.directory / f"{request.stage}-{key[:32]}.json" if self.directory else None
        if path and path.exists():
            with self._lock:
                self.cached += 1
                self._stage(request.stage)["cached"] += 1
            return json.loads(path.read_text(encoding="utf-8"))["reply"]
        if self.replay:
            raise LLMError(f"{request.stage}: replay mode and no cached reply for this call")
        held = reservation(request.stage, request.prompt)
        with self._lock:
            if self.max_tokens is not None and self._spent + self._reserved + held > self.max_tokens:
                self.budget_reached = True
                raise LLMError(f"{request.stage}: token budget reached ({self._spent} of {self.max_tokens} "
                               f"tokens used, {self._reserved} reserved); the call was not sent")
            self._reserved += held
        try:
            reply = self.inner.complete(request)
            reported = getattr(self.inner, "last_usage", None)
            used = (reported() if callable(reported) else None) or estimate_usage(request.prompt, reply)
        finally:
            with self._lock:
                self._reserved -= held
        with self._lock:
            self.calls += 1
            self._record(request.stage, used)
        if path:
            path.write_text(json.dumps({"stage": request.stage, "model": self._label(request.tier), "reply": reply}),
                            encoding="utf-8")
        return reply

    def _stage(self, stage: str) -> dict[str, int]:
        return self._stages.setdefault(stage, {"calls": 0, "cached": 0, "input_tokens": 0, "output_tokens": 0})

    def _record(self, stage: str, used: Usage) -> None:
        self._spent += used.input_tokens + used.output_tokens
        self._input += used.input_tokens
        self._output += used.output_tokens
        self._estimated = self._estimated or used.estimated
        if used.cost_usd is not None:
            self._cost = (self._cost or 0.0) + used.cost_usd
        entry = self._stage(stage)
        entry["calls"] += 1
        entry["input_tokens"] += used.input_tokens
        entry["output_tokens"] += used.output_tokens

    def spend(self) -> Spend:
        with self._lock:
            return Spend(self._input, self._output, self._estimated, self._cost, self.budget_reached,
                         {stage: dict(entry) for stage, entry in self._stages.items()})

    def usage(self) -> tuple[int, int]:
        return self.calls, self.cached
