"""What a model call cost, and the rules for estimating it before and after.

A backend may report the tokens of its last call (`last_usage()`); when it does not, the
cost is estimated from characters. Estimates are always flagged as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CHARS_PER_TOKEN = 4

# Tokens reserved for a stage's reply before a call is sent, on top of the prompt's own estimate.
# These are allowances, not limits: a reply may be longer. They bound how far a run can overshoot.
OUTPUT_ALLOWANCE = {"observe": 3000, "orient": 1500, "assign": 3000, "synthesise": 3000,
                    "consolidate": 3000, "assess": 2000}
DEFAULT_OUTPUT_ALLOWANCE = 2000


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    estimated: bool = False
    cost_usd: float | None = None   # the backend's own figure for the call, when it gives one


def estimate_tokens(text: str) -> int:
    """Characters divided by four, rounded up."""
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_usage(prompt: str, reply: str) -> Usage:
    return Usage(estimate_tokens(prompt), estimate_tokens(reply), estimated=True)


def reservation(stage: str, prompt: str) -> int:
    """What a call is expected to cost, held against the budget until it returns."""
    return estimate_tokens(prompt) + OUTPUT_ALLOWANCE.get(stage, DEFAULT_OUTPUT_ALLOWANCE)


@dataclass
class Spend:
    """A snapshot of what a run has used so far. Cached replies count as calls to their stage's
    `cached`, never as tokens."""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False
    cost_usd: float | None = None
    budget_reached: bool = False
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)   # stage -> calls, cached, input_tokens, output_tokens
