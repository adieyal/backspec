# reqx

Reads a codebase and writes down the user requirements it implements, as structured JSON.
Every requirement cites the lines it rests on. Every citation is checked in code. Every file
is accounted for.

reqx proposes candidate requirements. It is not a system of record, and a requirement it writes
is a reading of the code, not proof that the product behaves that way.

## Use

```bash
pip install -e .
```

```bash
reqx extract ./repo --dry-run
```

```bash
reqx extract ./repo --include "src/**" --exclude "**/migrations/**" -o reqs.json
```

To check the grouping before the expensive stages run, propose the capabilities first. This
writes `reqx.capabilities.yaml` at the root of the repository, which you can edit.
`reqx extract` then uses the file and skips the orient call, on this and every later run.

```bash
reqx orient ./repo          # writes ./repo/reqx.capabilities.yaml; --force replaces it
reqx extract ./repo         # uses the file; --capabilities PATH picks another
reqx extract ./repo --gate  # orient if there is no file, write it, and stop
```

A file that breaks the rules (unique ids of lowercase letters, digits and underscores; a name
for each) is refused with every problem listed. `plumbing` is added if it is missing. Which
observation belongs to which capability is not stored; it is redone on each run. A gated run
returns no requirements, with `run.status` `partial` and `run.stopped_after` `capabilities`.

```bash
reqx render reqs.json -o REQUIREMENTS.md
reqx render reqs.json --format csv -o reqs.csv            # one row per requirement and evidence pair
reqx render reqs.json --format openspec -o spec/          # a directory; -o is required
reqx extract ./repo --format csv -o reqs.csv
```

Formats: `json`, `md` (default for `render`), `csv` and `openspec`; an unknown name is refused with
the list. `csv` adds `--include-hidden` (a `hidden` column). `openspec` writes
`specs/<capability>/spec.md`, `NOT_EXPORTED.md` and `README.md`. Only requirements with support
`direct` or `partial` are exported, and, with `--strict` (the default), only those with a scenario.
A scenario comes only from a test or example in the code and cites it; reqx never writes one to fill
a gap. `--no-strict` keeps a requirement with no scenario and marks it as having none. A format is
a function in `modules/report/renderers.py`, added to `RENDERERS`.

```bash
reqx status reqs.json --root ./repo
```

`status` compares a saved result with the files on disk and lists the requirements whose cited
files have changed (`stale`) or gone (`source_missing`). It calls no model. Exit code 0 when
everything is current, 1 otherwise, 2 for a file that is not a result. `--json` prints the
report as JSON; in Python, `reqx.status(result_or_path, root)` returns it.

Requirement ids last between runs: a run carries them forward from the previous result by how
much the cited code overlaps, so rewording a statement keeps its id. `-o` names the previous
result when that file already exists, or give `--previous FILE`. Record a decision, and the next
run applies it. The entry goes in `reqx.review.yaml` (or `--review PATH`).

```bash
reqx review reqs.json REQ-1a2b3c4d --confirm --reviewer ana
reqx review reqs.json REQ-1a2b3c4d --statement "Managers may adjust stock." --condition "Never below zero."
reqx review reqs.json REQ-1a2b3c4d --reject --note "Not a requirement"
reqx extract ./repo -o reqs.json
```

A rejected requirement is hidden and counted in `diagnostics.review`. If the cited code changed
since the decision, it comes back as `needs_review`. Entries that match nothing are listed as stale.

```python
from reqx import Config, extract

result = extract("./repo", Config(include=["src/**"]))
for requirement in result.requirements:
    print(requirement.id, requirement.support, requirement.statement)
```

```python
from reqx import orient

for capability in orient("./repo"):   # writes the capabilities file
    print(capability.id, capability.name)
```

The default model backend is the Claude Code CLI, using the login you already have. It must be
installed. To use anything else, pass an object with a `complete(request) -> str` method as
`Config(provider=...)`.

A model does not describe the same file the same way twice, so reqx asks it only about what
is new. When a previous result is available (`--previous FILE`, or the `-o` file if it already
exists):

- a file that has not changed keeps the observations that result made of it and is not read again;
- in a file that has changed, only the changed lines are read again, with some context; an
  observation whose cited lines are untouched stays, and its citation moves with the code;
- the capabilities are the previous ones, unless there is a capabilities file;
- an observation already placed in a capability stays there;
- a capability whose observations are all the same keeps its requirements and their support verdicts.

A run with nothing changed calls no model and returns the same requirements. An edit rewrites
only the capabilities whose cited code it touched. Anything made with a
different prompt is not reused, and `--no-reuse` starts from nothing.

A requirement rejected in review is left out of `requirements` and kept under `hidden`.

## How it works

1. **Discover.** List the files, apply the include and exclude patterns, take one snapshot of
   each file that will be read.
2. **Observe.** Show a model every line, each with its real line number, and collect single
   facts with a line range and a verbatim quote.
3. **Verify.** Keep an observation only if its quote is really in the file. No model is involved.
4. **Orient and assign.** Propose capabilities (or read them from the capabilities file), then place each observation in one. Grouping is
   by observation, not by file.
5. **Synthesise.** Write requirements per capability. A requirement names observations by id
   and the program copies their locations, so a model never writes a citation at this step.
6. **Assess support.** A second call judges whether the cited lines establish the statement:
   `direct`, `partial`, `insufficient` or `conflicting`.
7. **Report.** Requirements, observations, a state and reason for every file, and what was
   rejected along the way.

Observing, orienting and assigning use a fast model. Synthesis and the support check use a
strong one.

## What it guarantees, and what it does not

Guaranteed, whatever the model says:

- Every citation in the output resolves to real lines in the file as it was read.
- Every file under the root is in exactly one state: `excluded`, `skipped`, `extracted`,
  `no_requirements`, `candidates_rejected` or `failed`.
- A requirement whose evidence only shows that something exists is never rated above
  `insufficient`.
- A run in which any stage failed is marked `partial`.

Not guaranteed:

- That a requirement is true. The support verdict is a model's judgement.
- That all requirements were found. File coverage is not completeness.
- That cited code is reachable. reqx reads code and does not run it.

## Layout

One module per capability under `src/reqx/modules/`, each with a `domain.py`, `use_cases.py`
and a small `facade.py`, plus `ports.py` where it needs the outside world. Adapters and wiring
live in `src/reqx/host/`. The import rules are enforced by `tests/test_architecture.py`.

```bash
python3 -m pytest -q
```

## Not built yet

Triage, the
triage audit, tree-sitter, a Codex adapter, token budgets, and the HTML renderer. See the spec.
