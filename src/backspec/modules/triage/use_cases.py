"""Triage every file from a preview, in parallel batches, and plan the audit of what it skips."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from backspec.kernel import prompts
from backspec.kernel.llm import LLMError, LLMPort, LLMRequest, ask
from backspec.kernel.text import short_hash
from backspec.modules.discovery.facade import SourceFile
from backspec.modules.triage.domain import (BATCH_FILES, BATCH_PREVIEW_LINES, PREVIEW_LINES, EarlierVerdict, TriageReply,
                                        Verdict, audit_sample, decide, merge_duplicate, pack, preview)


@dataclass
class TriageResult:
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)   # path -> why it has no verdict, so it is read
    audited: list[str] = field(default_factory=list)           # skipped files that are read anyway
    batches: int = 0
    reused_files: int = 0   # unchanged since the earlier run: verdict kept, not put to the model again

    @property
    def skipped(self) -> list[str]:
        return sorted(path for path, verdict in self.verdicts.items() if verdict.skipped)

    def to_read(self, files: list[SourceFile]) -> list[SourceFile]:
        """The files the observe stage reads: everything not skipped, plus the audit sample."""
        left_out = set(self.skipped) - set(self.audited)
        return [f for f in files if f.path not in left_out]


def fingerprint() -> str:
    """Changes whenever the way files are triaged does. Verdicts made another way are not reused."""
    return short_hash(prompts.load("triage"), BATCH_FILES, BATCH_PREVIEW_LINES, PREVIEW_LINES, "skip-only-sure-none")


def triage(files: list[SourceFile], llm: LLMPort, workers: int = 4, earlier: dict[str, EarlierVerdict] | None = None,
           audit: float = 0.0) -> TriageResult:
    result = TriageResult()
    by_path = {f.path: f for f in files}
    to_ask: list[SourceFile] = []
    for f in files:
        known = (earlier or {}).get(f.path)
        if known is not None and known.source_hash == f.source_hash:
            result.verdicts[f.path] = known.verdict
            result.reused_files += 1
        else:
            to_ask.append(f)
    batches = pack([(f.path, len(f.lines)) for f in to_ask])
    result.batches = len(batches)
    instructions = prompts.load("triage")

    def run(batch: list[str]) -> TriageReply | LLMError:
        body = "\n".join(preview(path, by_path[path].lines) for path in batch)
        try:
            return ask(llm, LLMRequest("triage", f"{instructions}\n\n# The batch\n\n{body}", "fast"), TriageReply)
        except LLMError as error:
            return error

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        replies = list(pool.map(run, batches))
    for batch, reply in zip(batches, replies):
        if isinstance(reply, LLMError):
            for path in batch:
                result.unresolved[path] = f"triage call failed: {str(reply)[:300]}"
            continue
        shown = set(batch)
        for raw in reply.files:
            if raw.path not in shown:
                continue
            verdict = decide(raw)
            old = result.verdicts.get(raw.path)
            result.verdicts[raw.path] = merge_duplicate(old, verdict) if old else verdict
        for path in batch:
            if path not in result.verdicts:
                result.unresolved[path] = "the triage reply did not mention this file"
    result.audited = audit_sample([(path, by_path[path].source_hash) for path in result.skipped], audit)
    return result
