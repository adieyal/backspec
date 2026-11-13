"""Where the adapters are chosen and handed to the modules. Nothing else in reqx knows which
model backend, file system or cache is in use."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from reqx.host.adapters.cache import CachedLLM
from reqx.host.adapters.claude_code import ClaudeCode
from reqx.host.adapters.filesystem import DiskRepo
from reqx.kernel.llm import LLMError, LLMPort
from reqx.modules.capabilities.facade import CapabilitiesFacade
from reqx.modules.discovery.facade import DiscoveryFacade
from reqx.modules.evidence.facade import EvidenceFacade
from reqx.modules.extraction.facade import Progress, Settings, run
from reqx.modules.report.facade import ExtractionResult
from reqx.modules.requirements.facade import RequirementsFacade
from reqx.modules.staleness.facade import StalenessFacade, StatusReport


@dataclass
class Config:
    """Everything a run can be told. The command line and the library take the same fields."""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    default_excludes: bool = True
    assess_support: bool = True
    provider: str | LLMPort = "claude-code"
    fast_model: str | None = None
    strong_model: str | None = None
    concurrency: int = 4
    cache_dir: Path | None = None
    use_cache: bool = True
    replay: bool = False


def default_cache_dir(root: Path) -> Path:
    """A folder per repository under the user's cache directory, never inside the repository."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "reqx" / hashlib.sha256(str(root).encode()).hexdigest()[:16]


def _provider(config: Config) -> tuple[LLMPort, str]:
    if not isinstance(config.provider, str):
        return config.provider, getattr(config.provider, "name", type(config.provider).__name__)
    if config.provider == "claude-code":
        return ClaudeCode(config.fast_model, config.strong_model), "claude-code"
    raise LLMError(f"Unknown provider {config.provider!r}. This version ships `claude-code`; "
                   "pass a provider object to use another.")


def extract(path: str | Path, config: Config | None = None, progress: Progress = lambda _: None) -> ExtractionResult:
    """Read the code under `path` and return its requirements, observations and coverage."""
    config = config or Config()
    root = Path(path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    inner, name = _provider(config)
    directory = (config.cache_dir or default_cache_dir(root)) if config.use_cache else None
    llm = CachedLLM(inner, directory, config.replay)
    settings = Settings(include=config.include, exclude=config.exclude,
                        default_excludes=config.default_excludes, assess_support=config.assess_support)
    return run(root=root.name, provider=name, settings=settings,
               discovery=DiscoveryFacade(DiskRepo(root)),
               evidence=EvidenceFacade(llm, config.concurrency),
               capabilities=CapabilitiesFacade(llm, config.concurrency),
               requirements=RequirementsFacade(llm, config.concurrency),
               usage=llm.usage, progress=progress)


def status(result: ExtractionResult | str | Path, root: str | Path = ".") -> StatusReport:
    """Which requirements in a result rest on files that are no longer what was read.
    `result` is an ExtractionResult or the path of a saved JSON result. No model is called."""
    if not isinstance(result, ExtractionResult):
        result = ExtractionResult.model_validate_json(Path(result).read_text(encoding="utf-8"))
    return StalenessFacade(DiskRepo(root)).check(result)
