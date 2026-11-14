"""The renderers: pure functions from a result to text. They write no files; the host does.

To add a format, write `def render_x(result, **options) -> RenderOutput`, add it to RENDERERS,
and give it a line in the README. A renderer takes every option the command line can pass and
ignores the ones that do not concern it.
"""
from __future__ import annotations

import base64
import collections
import csv
import io
import json
import re
from pathlib import PurePath
from typing import Callable

from backspec.kernel import templates
from backspec.modules.report.domain import RenderOutput, one_line, requirement_title, with_shall
from backspec.modules.report.dto import ExtractionResult
from backspec.modules.report.use_cases import to_markdown
from backspec.modules.requirements.facade import Requirement

Renderer = Callable[..., RenderOutput]


class UnknownFormat(ValueError):
    pass


def render_json(result: ExtractionResult, **options) -> RenderOutput:
    return RenderOutput(text=result.to_json())


def render_markdown(result: ExtractionResult, include_technical: bool = False, **options) -> RenderOutput:
    return RenderOutput(text=to_markdown(result, include_technical=include_technical))


CSV_COLUMNS = ["requirement_id", "capability", "statement", "conditions", "level", "support", "review", "scope",
               "evidence_role", "path", "first_line", "last_line", "quote"]


def render_csv(result: ExtractionResult, include_hidden: bool = False, **options) -> RenderOutput:
    """One row per requirement and evidence pair. Hidden requirements only on request, marked in
    a `hidden` column."""
    columns = [*CSV_COLUMNS, "hidden"] if include_hidden else CSV_COLUMNS
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    rows = [(r, False) for r in result.requirements]
    if include_hidden:
        rows += [(r, True) for r in result.hidden]
    for r, hidden in rows:
        for e in r.evidence:
            row = [r.id, r.capability, r.statement, " | ".join(r.conditions), r.level, r.support, r.review, r.scope,
                   e.role, e.path, e.lines[0], e.lines[1], e.quote]
            writer.writerow([*row, "true" if hidden else "false"] if include_hidden else row)
    return RenderOutput(text=buffer.getvalue())


EXPORTED_SUPPORT = ("direct", "partial")
NO_SCENARIO = "no evidenced scenario"
NO_SCENARIO_MARKER = "> No scenario: backspec found no test or example that shows this case."


def _evidence_line(r: Requirement) -> str:
    cites = dict.fromkeys(f"{e.path}:{e.lines[0]}-{e.lines[1]}" for e in r.evidence)
    return "Evidence: " + ", ".join(cites)


def _not_exported_reason(r: Requirement, strict: bool) -> str | None:
    if r.support not in EXPORTED_SUPPORT:
        what = "was not assessed" if r.support == "not_assessed" else f"is {r.support}"
        return f"support {what}" + (f": {one_line(r.support_note)}" if r.support_note else "")
    if strict and not r.scenarios:
        return NO_SCENARIO
    return None


def _spec_file(name: str, summary: str, requirements: list[Requirement]) -> str:
    out = [f"# {one_line(name)} Specification", "", "## Purpose", "", one_line(summary) or one_line(name), "",
           "## Requirements", ""]
    titles: collections.Counter[str] = collections.Counter()
    for r in requirements:
        title = requirement_title(r.statement)
        titles[title.lower()] += 1
        if titles[title.lower()] > 1:   # a spec keeps one block per title
            title = f"{title} ({titles[title.lower()]})"
        out += [f"### Requirement: {title}", "", with_shall(r.statement), "", _evidence_line(r), ""]
        if not r.scenarios:
            out += [NO_SCENARIO_MARKER, ""]
        for s in r.scenarios:
            out += [f"#### Scenario: {one_line(s.name)}", f"- **GIVEN** {one_line(s.given)}",
                    f"- **WHEN** {one_line(s.when)}", f"- **THEN** {one_line(s.then)}", ""]
    return "\n".join(out)


def _safe_id(capability_id: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", capability_id.lower()).strip("_") or "capability"


def render_openspec(result: ExtractionResult, strict: bool | None = None, **options) -> RenderOutput:
    """A tree: specs/<capability>/spec.md per capability, NOT_EXPORTED.md and README.md at the
    root. Strict (the default) leaves out a requirement with no scenario; backspec never writes one."""
    strict = True if strict is None else strict
    names = {c.id: c for c in result.capabilities}
    exported: dict[str, list[Requirement]] = collections.defaultdict(list)
    left_out: list[tuple[Requirement, str]] = []
    for r in result.requirements:
        reason = _not_exported_reason(r, strict)
        if reason is None:
            exported[r.capability].append(r)
        else:
            left_out.append((r, reason))
    files: dict[str, str] = {}
    paths: dict[str, str] = {}
    for cid, requirements in exported.items():
        capability = names.get(cid)
        path = f"specs/{_safe_id(cid)}/spec.md"
        paths[cid] = path
        files[path] = _spec_file(capability.name if capability else cid, capability.summary if capability else "",
                                 requirements)

    def entry(r: Requirement, reason: str) -> str:
        return f"- `{r.id}` ({r.capability}): {one_line(r.statement)}\n  Reason: {reason}"

    out = ["# Requirements not exported", ""]
    if not left_out:
        out += ["Every requirement was exported.", ""]
    groups: dict[str, list[tuple[Requirement, str]]] = collections.defaultdict(list)
    for r, reason in left_out:
        groups[NO_SCENARIO if reason == NO_SCENARIO else "support below direct or partial"].append((r, reason))
    for title, items in groups.items():
        out += [f"## Not exported: {title}", ""] + [entry(r, reason) for r, reason in items] + [""]
    files["NOT_EXPORTED.md"] = "\n".join(out)

    reasons = collections.Counter(NO_SCENARIO if reason == NO_SCENARIO else reason.split(":")[0]
                                  for _, reason in left_out)
    count = sum(len(v) for v in exported.values())
    readme = ["# OpenSpec export", "",
              f"Written by backspec from a result with {len(result.requirements)} requirements "
              f"({'strict' if strict else 'non-strict'} mode).", "",
              f"- Exported: {count} requirements in {len(exported)} specs.",
              f"- Not exported: {len(left_out)} requirements; see `NOT_EXPORTED.md`."]
    readme += [f"    - {n} with {reason}" for reason, n in sorted(reasons.items())]
    if result.hidden:
        readme.append(f"- {len(result.hidden)} requirements rejected in review are never exported.")
    readme += ["", "Only requirements whose support is `direct` or `partial` are exported. backspec never writes a "
               "scenario of its own: a scenario here comes from a test or example in the code, with its evidence.",
               ("In strict mode a requirement with no evidenced scenario is left out."
                if strict else
                "In non-strict mode a requirement with no scenario is included and marked as having none."), "",
               "## Specs", ""]
    for cid, path in paths.items():
        capability = names.get(cid)
        readme.append(f"- `{path}`: {capability.name if capability else cid}, {len(exported[cid])} requirements")
    if not paths:
        readme.append("- none")
    readme.append("")
    files["README.md"] = "\n".join(readme)
    return RenderOutput(files=files)


BODY_MARK = "<!--BACKSPEC_BODY-->"
PAGE = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '{head}</head>\n<body>\n{body}</body>\n</html>\n')


def page_data(result: ExtractionResult, title: str) -> dict:
    """What the page draws from: the result without the parts only a later run needs."""
    data = result.model_dump(mode="json", exclude={"assignments": True, "observations": True,
                                                   "coverage": {"files": {"__all__": {"line_digest", "source_hash"}}}})
    data["title"] = title
    data["observations"] = [o.id for o in result.observations]
    data["observations_by_id"] = {o.id: o.statement for o in result.observations}
    return data


def render_html(result: ExtractionResult, title: str | None = None, fragment: bool = False, **options) -> RenderOutput:
    """One self-contained page: the capabilities, each requirement with its evidence, what needs a
    second look, and coverage.
    It loads nothing from the network. `fragment` leaves out the document wrapper, for a host
    that supplies its own."""
    name = title or PurePath(result.run.root).name or "This codebase"
    # "<" never appears raw in the embedded data, so nothing in a result can close the script element
    data = json.dumps(page_data(result, name), ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    template = templates.load("report.html").replace("__BACKSPEC_TITLE__", _escape(f"{name} requirements"))
    template = re.sub(r"__BACKSPEC_FONT:([a-z0-9.-]+)__",
                      lambda m: base64.b64encode(templates.load_bytes(m.group(1))).decode("ascii"), template)
    template = template.replace("__BACKSPEC_DATA__", data)
    if fragment:
        return RenderOutput(text=template.replace(BODY_MARK + "\n", ""))
    head, body = template.split(BODY_MARK + "\n", 1)
    return RenderOutput(text=PAGE.format(head=head, body=body))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


RENDERERS: dict[str, Renderer] = {
    "json": render_json,
    "md": render_markdown,
    "csv": render_csv,
    "openspec": render_openspec,
    "html": render_html,
}


def formats() -> list[str]:
    return list(RENDERERS)


def render(result: ExtractionResult, fmt: str, **options) -> RenderOutput:
    """The result in the named format. Unknown names are refused with the known ones."""
    renderer = RENDERERS.get(fmt)
    if renderer is None:
        raise UnknownFormat(f"unknown format {fmt!r}; known formats: {', '.join(RENDERERS)}")
    return renderer(result, **options)
