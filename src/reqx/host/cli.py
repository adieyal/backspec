"""The command line. It holds no logic: it turns flags into a Config and prints what comes back.
Results go to stdout or the output file; progress goes to stderr."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from reqx.host.composition import (CAPABILITIES_FILE, Config, default_previous, extract, load_result, orient,
                                   review_requirement, status, write_tree)
from reqx.kernel.llm import LLMError
from reqx.modules.capabilities.facade import CapabilitiesFileError
from reqx.modules.discovery.facade import DiscoveryFacade
from reqx.modules.report.facade import ExtractionResult, RenderOutput, formats, render
from reqx.modules.staleness.facade import summary
from reqx.modules.review.facade import UnknownRequirement

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Extract user requirements from a codebase, with verified citations.")


Include = Annotated[list[str], typer.Option("--include", help="Gitignore-style pattern to include. Repeatable.")]
Exclude = Annotated[list[str], typer.Option("--exclude", help="Gitignore-style pattern to exclude. Repeatable.")]
NoDefaultExcludes = Annotated[bool, typer.Option(help="Do not apply the built-in excludes.")]
ProviderOpt = Annotated[str, typer.Option("--provider", help="Model backend.")]
FastModel = Annotated[Optional[str], typer.Option(help="Model for observing, orienting and assigning.")]
Concurrency = Annotated[int, typer.Option(help="Parallel model calls.")]
CacheDir = Annotated[Optional[Path], typer.Option(help="Where to cache model replies.")]
NoCache = Annotated[bool, typer.Option(help="Do not read or write the cache.")]
Replay = Annotated[bool, typer.Option(help="Serve every call from the cache; fail on a miss.")]
CapabilitiesOpt = Annotated[Optional[Path], typer.Option(
    "--capabilities", help=f"The capabilities file. Default: {CAPABILITIES_FILE} under PATH.")]
MULTI_FILE = ("openspec",)   # formats that write a directory tree; `-o` is then required
ERRORS = (LLMError, OSError, ValueError)   # CapabilitiesFileError and a bad result file are ValueErrors


def _say(message: str) -> None:
    typer.echo(message, err=True)


def _emit(text: str, output: Optional[Path]) -> None:
    if output:
        output.write_text(text, encoding="utf-8")
        _say(f"written: {output}")
    else:
        typer.echo(text)


def _check_format(fmt: str, output: Optional[Path]) -> None:
    """Refuse an unknown format, or a multi-file format without a directory, before any work."""
    if fmt not in formats():
        raise typer.BadParameter(f"unknown format {fmt!r}; known formats: {', '.join(formats())}", param_hint="--format")
    if fmt in MULTI_FILE and output is None:
        raise typer.BadParameter(f"--format {fmt} writes several files; -o DIRECTORY is required", param_hint="-o")


def _emit_output(rendered: RenderOutput, output: Optional[Path]) -> None:
    if rendered.is_tree:
        paths = write_tree(rendered.files, output)  # type: ignore[arg-type]
        _say(f"written: {len(paths)} files under {output}")
    else:
        _emit(rendered.text or "", output)


@app.command("extract")
def extract_command(
    path: Path = typer.Argument(..., help="The repository or directory to read."),
    include: Include = [],
    exclude: Exclude = [],
    no_default_excludes: NoDefaultExcludes = False,
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Write the result here instead of stdout."),
    fmt: str = typer.Option("json", "--format", help="Output format: json, md, csv or openspec."),
    provider: ProviderOpt = "claude-code",
    model: Optional[str] = typer.Option(None, help="Model for synthesis and the support check."),
    fast_model: FastModel = None,
    no_assess_support: bool = typer.Option(False, help="Skip the support check."),
    concurrency: Concurrency = 4,
    cache_dir: CacheDir = None,
    no_cache: NoCache = False,
    replay: Replay = False,
    capabilities: CapabilitiesOpt = None,
    gate: bool = typer.Option(False, help="Write the capabilities file if there is none, then stop before "
                                          "assignment and synthesis."),
    dry_run: bool = typer.Option(False, help="List the files that would be read, and stop."),
    review: Optional[Path] = typer.Option(None, "--review", help="The review file. Default: reqx.review.yaml in PATH, if present."),
    no_reuse: bool = typer.Option(False, "--no-reuse", help="Read every file again, even those unchanged since "
                                  "the previous result."),
    previous: Optional[Path] = typer.Option(None, "--previous", help="An earlier JSON result whose ids to carry forward. "
                                            "Default: the -o file, if it already exists."),
    include_hidden: bool = typer.Option(False, "--include-hidden", help="csv: also list requirements rejected in review."),
    strict: Optional[bool] = typer.Option(None, "--strict/--no-strict", help="openspec: leave out requirements with "
                                          "no evidenced scenario (default: strict)."),
) -> None:
    """Run the pipeline on PATH."""
    _check_format(fmt, output)
    if dry_run:
        from reqx.host.adapters.filesystem import DiskRepo
        found = DiscoveryFacade(DiskRepo(path)).discover(include, exclude, not no_default_excludes)
        lines = sum(len(f.lines) for f in found.files)
        for source in found.files:
            typer.echo(f"read      {source.path}")
        for left in found.left:
            typer.echo(f"{left.state:9s} {left.path}  ({left.reason})")
        _say(f"{len(found.files)} files, {lines} lines to read; {len(found.left)} left out. "
             f"About {max(1, lines // 1300)} observe calls. Nothing was sent to a model.")
        raise typer.Exit(0)
    config = Config(include=include, exclude=exclude, default_excludes=not no_default_excludes,
                    assess_support=not no_assess_support, provider=provider, fast_model=fast_model,
                    strong_model=model, concurrency=concurrency, cache_dir=cache_dir,
                    use_cache=not no_cache, replay=replay, capabilities_file=capabilities, gate=gate,
                    review_file=review, previous=default_previous(previous, output, fmt), reuse=not no_reuse)
    try:
        result = extract(path, config, progress=_say)
    except ERRORS as error:
        _say(f"error: {error}")
        raise typer.Exit(2)
    _emit_output(render(result, fmt, include_hidden=include_hidden, strict=strict), output)
    _say(f"{len(result.requirements)} requirements; {result.run.calls} model calls, "
         f"{result.run.cached_calls} from cache; status {result.run.status}")
    if result.run.stopped_after:
        _say(f"stopped after {result.run.stopped_after}, as asked by --gate")
        raise typer.Exit(0)
    raise typer.Exit(0 if result.run.status == "complete" else 1)


@app.command("orient")
def orient_command(
    path: Path = typer.Argument(..., help="The repository or directory to read."),
    include: Include = [],
    exclude: Exclude = [],
    no_default_excludes: NoDefaultExcludes = False,
    provider: ProviderOpt = "claude-code",
    fast_model: FastModel = None,
    concurrency: Concurrency = 4,
    cache_dir: CacheDir = None,
    no_cache: NoCache = False,
    replay: Replay = False,
    capabilities: CapabilitiesOpt = None,
    force: bool = typer.Option(False, "--force", help="Replace the capabilities file if it exists."),
) -> None:
    """Propose the capabilities of PATH, write them to the capabilities file and stop."""
    config = Config(include=include, exclude=exclude, default_excludes=not no_default_excludes, provider=provider,
                    fast_model=fast_model, concurrency=concurrency, cache_dir=cache_dir, use_cache=not no_cache,
                    replay=replay, capabilities_file=capabilities)
    try:
        found = orient(path, config, progress=_say, force=force)
    except (*ERRORS, FileExistsError, ValueError) as error:
        _say(f"error: {error}")
        raise typer.Exit(2)
    for capability in found:
        typer.echo(f"{capability.id}: {capability.name}")


@app.command("render")
def render_command(
    file: Path = typer.Argument(..., help="A JSON result written by `reqx extract`."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="File to write; a directory for openspec."),
    fmt: str = typer.Option("md", "--format", help="Output format: json, md, csv or openspec."),
    technical: bool = typer.Option(False, help="Include technical-level requirements (md)."),
    include_hidden: bool = typer.Option(False, "--include-hidden", help="csv: also list requirements rejected in review."),
    strict: Optional[bool] = typer.Option(None, "--strict/--no-strict", help="openspec: leave out requirements with "
                                          "no evidenced scenario (default: strict)."),
) -> None:
    """Turn a saved JSON result into another format. No model is called."""
    _check_format(fmt, output)
    try:
        result = load_result(file)
        rendered = render(result, fmt, include_technical=technical, include_hidden=include_hidden, strict=strict)
        _emit_output(rendered, output)
    except (OSError, ValueError) as error:
        _say(f"error: {error}")
        raise typer.Exit(2)


@app.command("schema")
def schema_command() -> None:
    """Print the JSON Schema of the result."""
    typer.echo(json.dumps(ExtractionResult.model_json_schema(), indent=1))


@app.command("status")
def status_command(
    file: Path = typer.Argument(..., help="A JSON result written by `reqx extract`."),
    root: Path = typer.Option(Path("."), "--root", help="The repository the result was made from."),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """Show which requirements rest on files that have changed or gone. No model is called."""
    try:
        report = status(file, root)
    except (OSError, ValueError) as error:   # a pydantic ValidationError is a ValueError
        _say(f"error: {file} is not a valid result: {error}")
        raise typer.Exit(2)
    typer.echo(report.model_dump_json(indent=1) if as_json else summary(report))
    raise typer.Exit(0 if report.all_current else 1)


@app.command("review")
def review_command(
    file: Path = typer.Argument(..., help="A JSON result written by `reqx extract`."),
    requirement_id: str = typer.Argument(..., metavar="REQ-ID", help="The requirement to review."),
    confirm: bool = typer.Option(False, "--confirm", help="The requirement is right."),
    reject: bool = typer.Option(False, "--reject", help="The requirement is wrong; hide it."),
    statement: Optional[str] = typer.Option(None, "--statement", help="Replace the statement."),
    condition: list[str] = typer.Option([], "--condition", help="With --statement: a condition. Repeatable."),
    reviewer: Optional[str] = typer.Option(None, "--reviewer", help="Who decided. Default: the current user."),
    note: Optional[str] = typer.Option(None, "--note"),
    review: Optional[Path] = typer.Option(None, "--review", help="The review file. Default: reqx.review.yaml here."),
) -> None:
    """Record a decision about one requirement, to be applied by later runs."""
    try:
        typer.echo(review_requirement(file, requirement_id, confirm=confirm, reject=reject, statement=statement,
                                      conditions=condition, reviewer=reviewer, note=note, review_file=review))
    except UnknownRequirement:
        _say(f"error: {requirement_id} is not in {file}")
        raise typer.Exit(2)
    except (OSError, ValueError) as error:
        _say(f"error: {error}")
        raise typer.Exit(2)
