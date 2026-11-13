"""The command line. It holds no logic: it turns flags into a Config and prints what comes back.
Results go to stdout or the output file; progress goes to stderr."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from reqx.host.composition import Config, default_previous, extract, load_result, review_requirement
from reqx.kernel.llm import LLMError
from reqx.modules.discovery.facade import DiscoveryFacade
from reqx.modules.report.facade import ExtractionResult, to_markdown
from reqx.modules.review.facade import UnknownRequirement

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Extract user requirements from a codebase, with verified citations.")


def _say(message: str) -> None:
    typer.echo(message, err=True)


def _emit(text: str, output: Optional[Path]) -> None:
    if output:
        output.write_text(text, encoding="utf-8")
        _say(f"written: {output}")
    else:
        typer.echo(text)


@app.command("extract")
def extract_command(
    path: Path = typer.Argument(..., help="The repository or directory to read."),
    include: list[str] = typer.Option([], "--include", help="Gitignore-style pattern to include. Repeatable."),
    exclude: list[str] = typer.Option([], "--exclude", help="Gitignore-style pattern to exclude. Repeatable."),
    no_default_excludes: bool = typer.Option(False, help="Do not apply the built-in excludes."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Write the result here instead of stdout."),
    fmt: str = typer.Option("json", "--format", help="json or md."),
    provider: str = typer.Option("claude-code", help="Model backend."),
    model: Optional[str] = typer.Option(None, help="Model for synthesis and the support check."),
    fast_model: Optional[str] = typer.Option(None, help="Model for observing, orienting and assigning."),
    no_assess_support: bool = typer.Option(False, help="Skip the support check."),
    concurrency: int = typer.Option(4, help="Parallel model calls."),
    cache_dir: Optional[Path] = typer.Option(None, help="Where to cache model replies."),
    no_cache: bool = typer.Option(False, help="Do not read or write the cache."),
    replay: bool = typer.Option(False, help="Serve every call from the cache; fail on a miss."),
    dry_run: bool = typer.Option(False, help="List the files that would be read, and stop."),
    review: Optional[Path] = typer.Option(None, "--review", help="The review file. Default: reqx.review.yaml in PATH, if present."),
    previous: Optional[Path] = typer.Option(None, "--previous", help="An earlier JSON result whose ids to carry forward. "
                                            "Default: the -o file, if it already exists."),
) -> None:
    """Run the pipeline on PATH."""
    if fmt not in ("json", "md"):
        raise typer.BadParameter("--format must be json or md")
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
                    use_cache=not no_cache, replay=replay, review_file=review,
                    previous=default_previous(previous, output, fmt))
    try:
        result = extract(path, config, progress=_say)
    except (LLMError, NotADirectoryError, OSError, ValueError) as error:
        _say(f"error: {error}")
        raise typer.Exit(2)
    _emit(result.to_json() if fmt == "json" else to_markdown(result), output)
    _say(f"{len(result.requirements)} requirements; {result.run.calls} model calls, "
         f"{result.run.cached_calls} from cache; status {result.run.status}")
    raise typer.Exit(0 if result.run.status == "complete" else 1)


@app.command("render")
def render_command(
    file: Path = typer.Argument(..., help="A JSON result written by `reqx extract`."),
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
    technical: bool = typer.Option(False, help="Include technical-level requirements."),
) -> None:
    """Turn a saved JSON result into Markdown. No model is called."""
    result = load_result(file)
    _emit(to_markdown(result, include_technical=technical), output)


@app.command("schema")
def schema_command() -> None:
    """Print the JSON Schema of the result."""
    typer.echo(json.dumps(ExtractionResult.model_json_schema(), indent=1))


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
