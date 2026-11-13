"""Where the adapters are chosen and handed to the modules. Nothing else in reqx knows which
model backend, file system or cache is in use."""
from __future__ import annotations

import datetime
import getpass
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from reqx.host.adapters.cache import CachedLLM
from reqx.host.adapters.capabilities_file import YamlCapabilitiesFile
from reqx.host.adapters.claude_code import ClaudeCode
from reqx.host.adapters.filesystem import DiskRepo
from reqx.host.adapters.review_yaml import YamlReviewStore
from reqx.kernel.llm import LLMError, LLMPort
from reqx.modules.capabilities.facade import CapabilitiesFacade, Capability
from reqx.modules.discovery.facade import DiscoveryFacade
from reqx.modules.evidence.facade import EvidenceFacade
from reqx.modules.extraction.facade import Progress, Settings, orient_only, run
from reqx.modules.report.facade import ExtractionResult, earlier_evidence
from reqx.modules.requirements.facade import RequirementsFacade
from reqx.modules.review.facade import ReviewFacade
from reqx.modules.staleness.facade import StalenessFacade, StatusReport


CAPABILITIES_FILE = "reqx.capabilities.yaml"
REVIEW_FILE = "reqx.review.yaml"


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
    capabilities_file: Path | None = None   # default: CAPABILITIES_FILE under the root
    gate: bool = False   # write the capabilities file if there is none, and stop before assignment
    review_file: Path | None = None   # default: reqx.review.yaml under the root, used only if it exists
    previous: Path | None = None      # a saved JSON result whose ids this run carries forward
    reuse: bool = True                # keep the previous result's observations for files that have not changed


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


def _wiring(path: str | Path, config: Config):
    root = Path(path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    inner, name = _provider(config)
    directory = (config.cache_dir or default_cache_dir(root)) if config.use_cache else None
    llm = CachedLLM(inner, directory, config.replay)
    settings = Settings(include=config.include, exclude=config.exclude, default_excludes=config.default_excludes,
                        assess_support=config.assess_support, gate=config.gate)
    store = YamlCapabilitiesFile(config.capabilities_file or root / CAPABILITIES_FILE)
    return root, name, llm, settings, store


def extract(path: str | Path, config: Config | None = None, progress: Progress = lambda _: None) -> ExtractionResult:
    """Read the code under `path` and return its requirements, observations and coverage.

    A capabilities file, if there is one, is used as it is. With `Config(gate=True)` the run stops
    once the capabilities are settled: requirements are empty, `run.status` is `partial` and
    `run.stopped_after` is `capabilities`."""
    config = config or Config()
    root, name, llm, settings, store = _wiring(path, config)
    review_path = config.review_file or root / REVIEW_FILE
    if config.review_file and not review_path.is_file():
        raise FileNotFoundError(f"review file not found: {review_path}")
    review_store = YamlReviewStore(review_path) if review_path.is_file() else None
    before = load_result(config.previous) if config.previous else None
    if config.previous and root in Path(config.previous).resolve().parents:
        # a result saved inside the repository is reqx's own output, never source to read
        settings.exclude = [*settings.exclude, "/" + Path(config.previous).resolve().relative_to(root).as_posix()]
    previous = before.requirements if before else None
    evidence = EvidenceFacade(llm, config.concurrency)
    earlier = earlier_evidence(before, evidence.fingerprint()) if before and config.reuse else None
    return run(root=root.name, provider=name, settings=settings,
               discovery=DiscoveryFacade(DiskRepo(root)),
               evidence=evidence,
               capabilities=CapabilitiesFacade(llm, config.concurrency, store),
               requirements=RequirementsFacade(llm, config.concurrency),
               usage=llm.usage, progress=progress, review=ReviewFacade(review_store), previous=previous,
               earlier=earlier)


def status(result: ExtractionResult | str | Path, root: str | Path = ".") -> StatusReport:
    """Which requirements in a result rest on files that are no longer what was read.
    `result` is an ExtractionResult or the path of a saved JSON result. No model is called."""
    if not isinstance(result, ExtractionResult):
        result = ExtractionResult.model_validate_json(Path(result).read_text(encoding="utf-8"))
    return StalenessFacade(DiskRepo(root)).check(result)


def orient(path: str | Path, config: Config | None = None, progress: Progress = lambda _: None,
           force: bool = False) -> list[Capability]:
    """Propose the capabilities of the code under `path` and write them to the capabilities file.
    Raises FileExistsError if the file exists, unless `force`."""
    config = config or Config()
    root, _, llm, settings, store = _wiring(path, config)
    return orient_only(settings, DiscoveryFacade(DiskRepo(root)), EvidenceFacade(llm, config.concurrency),
                       CapabilitiesFacade(llm, config.concurrency, store), force, progress)


def load_result(file: Path) -> ExtractionResult:
    """A saved JSON result."""
    return ExtractionResult.model_validate_json(Path(file).read_text(encoding="utf-8"))


def default_previous(previous: Path | None, output: Path | None, fmt: str = "json") -> Path | None:
    """The previous result: the one named, else the JSON output file if it already exists."""
    if previous is not None:
        return previous
    return output if output is not None and fmt == "json" and output.is_file() else None


def review_requirement(file: Path, requirement_id: str, *, confirm: bool = False, reject: bool = False,
                       statement: str | None = None, conditions: list[str] | None = None,
                       reviewer: str | None = None, note: str | None = None,
                       review_file: Path | None = None) -> str:
    """Record a decision about one requirement of a saved result, and say what was written.
    Raises UnknownRequirement for an id the result does not have, ValueError for a bad request."""
    if confirm + reject + (statement is not None) != 1:
        raise ValueError("give exactly one of --confirm, --reject or --statement")
    if conditions and statement is None:
        raise ValueError("--condition goes with --statement")
    decision = "confirm" if confirm else "reject" if reject else "edit"
    path = review_file or Path(REVIEW_FILE)
    if not reviewer:
        try:
            reviewer = getpass.getuser()
        except Exception:
            reviewer = "unknown"
    ReviewFacade(YamlReviewStore(path)).record(
        load_result(file).requirements, requirement_id, decision,  # type: ignore[arg-type]
        statement=statement, conditions=(conditions or []) if statement is not None else None,
        reviewer=reviewer, date=datetime.date.today().isoformat(), note=note)
    return f"{requirement_id}: {decision} by {reviewer} written to {path}"
