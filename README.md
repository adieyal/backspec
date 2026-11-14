# backspec

Reads a codebase and writes down the user requirements it implements, as structured JSON.
Every requirement cites the lines it rests on. Every citation is checked in code. Every file
is accounted for.

backspec proposes candidate requirements. It is not a system of record, and a requirement it writes
is a reading of the code, not proof that the product behaves that way.

## Use

```bash
pip install -e .
```

```bash
backspec extract ./repo --dry-run
```

```bash
backspec extract ./repo --include "src/**" --exclude "**/migrations/**" -o reqs.json
```

To check the grouping before the expensive stages run, propose the capabilities first. This
writes `backspec.capabilities.yaml` at the root of the repository, which you can edit.
`backspec extract` then uses the file and skips the orient call, on this and every later run.

```bash
backspec orient ./repo          # writes ./repo/backspec.capabilities.yaml; --force replaces it
backspec extract ./repo         # uses the file; --capabilities PATH picks another
backspec extract ./repo --gate  # orient if there is no file, write it, and stop
```

A file that breaks the rules (unique ids of lowercase letters, digits and underscores; a name
for each) is refused with every problem listed. `plumbing` is added if it is missing. Which
observation belongs to which capability is not stored; it is redone on each run. A gated run
returns no requirements, with `run.status` `partial` and `run.stopped_after` `capabilities`.

A run reports its tokens (`run.input_tokens`, `run.output_tokens`, and `run.usage_by_stage`).
A backend that reports usage is used as it is; otherwise tokens are estimated as characters / 4
and `run.tokens_estimated` is true. Cached replies count as zero tokens. `--dry-run` prints an
estimate of the tokens the observe stage would read. `--max-tokens N` is a soft budget: a call is
not sent if the tokens already used, plus those reserved for calls in flight, plus its own
estimated cost would pass N. The run is then `partial` with `run.budget_reached` true, and exits 1.
A run can overshoot N by the amount the calls in flight turned out dearer than estimated.

```bash
backspec extract ./repo --max-tokens 400000
```

```bash
backspec render reqs.json -o REQUIREMENTS.md
backspec render reqs.json --format csv -o reqs.csv            # one row per requirement and evidence pair
backspec render reqs.json --format openspec -o spec/          # a directory; -o is required
backspec render reqs.json --format html -o reqs.html --title "My shop"   # one page, opens offline
backspec extract ./repo --format csv -o reqs.csv
```

Formats: `json`, `md` (default for `render`), `csv`, `html` and `openspec`; an unknown name is refused with
the list. `csv` adds `--include-hidden` (a `hidden` column). `openspec` writes
`specs/<capability>/spec.md`, `NOT_EXPORTED.md` and `README.md`. Only requirements with support
`direct` or `partial` are exported, and, with `--strict` (the default), only those with a scenario.
A scenario comes only from a test or example in the code and cites it; backspec never writes one to fill
a gap. `--no-strict` keeps a requirement with no scenario and marks it as having none. A format is
a function in `modules/report/renderers.py`, added to `RENDERERS`.

```bash
backspec status reqs.json --root ./repo
```

`status` compares a saved result with the files on disk and lists the requirements whose cited
files have changed (`stale`) or gone (`source_missing`). It calls no model. Exit code 0 when
everything is current, 1 otherwise, 2 for a file that is not a result. `--json` prints the
report as JSON; in Python, `backspec.status(result_or_path, root)` returns it.

```bash
backspec validate reqs.json            # lint: exit 0 clean (warnings allowed), 1 errors, 2 not a result
backspec validate reqs.json --strict   # warnings count as errors; --json prints the findings
backspec coverage reqs.json            # files per state, unused observations, files worth a look; --all, --json
backspec cache info ./repo             # the cache folder, replies per stage, size; --cache-dir PATH
backspec cache clear ./repo --yes      # without --yes, only reports what it would delete
```

`validate` checks a saved result against the schema, then runs deterministic checks: errors for
a citation that points at nothing, an unknown capability or a duplicate id, warnings for vague,
compound or weakly supported requirements. Every extraction runs the same checks and stores the
findings in `diagnostics.lint`. In Python, `backspec.validate(result_or_path)` returns the report.
`coverage` reads only the saved result. `cache clear` deletes only files named
`<stage>-<hex>.json` and refuses a folder that holds anything else.

Requirement ids last between runs: a run carries them forward from the previous result by how
much the cited code overlaps, so rewording a statement keeps its id. `-o` names the previous
result when that file already exists, or give `--previous FILE`. Record a decision, and the next
run applies it. The entry goes in `backspec.review.yaml` (or `--review PATH`).

```bash
backspec review reqs.json REQ-1a2b3c4d --confirm --reviewer ana
backspec review reqs.json REQ-1a2b3c4d --statement "Managers may adjust stock." --condition "Never below zero."
backspec review reqs.json REQ-1a2b3c4d --reject --note "Not a requirement"
backspec extract ./repo -o reqs.json
```

A rejected requirement is hidden and counted in `diagnostics.review`. If the cited code changed
since the decision, it comes back as `needs_review`. Entries that match nothing are listed as stale.

```python
from backspec import Config, extract

result = extract("./repo", Config(include=["src/**"]))
for requirement in result.requirements:
    print(requirement.id, requirement.support, requirement.statement)
```

```python
from backspec import orient

for capability in orient("./repo"):   # writes the capabilities file
    print(capability.id, capability.name)
```

The default model backend is the Claude Code CLI, using the login you already have. It must be
installed. `--provider codex` uses the Codex CLI instead (`codex exec`, read-only sandbox, prompt on
stdin). **That adapter has not been run against the real Codex CLI**: it was written from the
documented interface and tested only against a fake `codex` script; its flags are listed in
`src/backspec/host/adapters/codex.py` and should be checked first. To use anything else, pass an object with a `complete(request) -> str` method as
`Config(provider=...)`.

A model does not describe the same file the same way twice, so backspec asks it only about what
is new. When a previous result is available (`--previous FILE`, or the `-o` file if it already
exists):

- a file that has not changed keeps the observations that result made of it and is not read again,
  and keeps its triage verdict and is not triaged again;
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
2. **Triage.** A fast model looks at each file's path, size and first 40 lines and gives its
   role, how likely it is to hold behaviour a user would notice, and whether it is sure. The
   program skips a file only when the relevance is `none` and the model is sure; anything else,
   including a file the model did not answer for, is read. A skipped file is `triaged_out`, with
   its role as the reason. A fraction of the skipped files (`--triage-audit`, default 0.1, at
   least 5 and at most 50) is read anyway, chosen by hash so the choice is the same every run;
   `coverage.triage_audit` says how many of them held a verified observation, with a 95 percent
   confidence interval for the miss rate. `--no-triage` reads everything.
3. **Observe.** Show a model every line of each file to be read, each with its real line number,
   and collect single facts with a line range and a verbatim quote.
4. **Verify.** Keep an observation only if its quote is really in the file. No model is involved.
5. **Orient and assign.** Propose capabilities (or read them from the capabilities file), then place each observation in one. Grouping is
   by observation, not by file.
6. **Synthesise.** Write requirements per capability. A requirement names observations by id
   and the program copies their locations, so a model never writes a citation at this step.
7. **Assess support.** A second call judges whether the cited lines establish the statement:
   `direct`, `partial`, `insufficient` or `conflicting`.
8. **Report.** Requirements, observations, a state and reason for every file, and what was
   rejected along the way.

Triaging, observing, orienting and assigning use a fast model. Synthesis and the support check use a
strong one.

## What it guarantees, and what it does not

Guaranteed, whatever the model says:

- Every citation in the output resolves to real lines in the file as it was read.
- Every file under the root is in exactly one state: `excluded`, `skipped`, `triaged_out`,
  `extracted`, `no_requirements`, `candidates_rejected` or `failed`.
- A requirement whose evidence only shows that something exists is never rated above
  `insufficient`.
- A run in which any stage failed is marked `partial`.

Not guaranteed:

- That a requirement is true. The support verdict is a model's judgement.
- That all requirements were found. File coverage is not completeness.
- That cited code is reachable. backspec reads code and does not run it.

## Optional syntax support

backspec needs no parser. If `tree-sitter-language-pack` is installed (`pip install "backspec[treesitter]"`),
files in Python, JavaScript, TypeScript, TSX, Go, Java, Ruby, Rust, C# and PHP are analysed with it:

- a large file is cut between top-level functions and classes, not inside one;
- each observation, and the evidence copied from it, names the innermost function, method or class
  that holds its whole line range (`symbol`, set in code); the Markdown shows it as
  `path:10-14` (Shop.buy);
- `coverage.files[].analysis` says `syntax` or `text` for each file, and `run.syntax_files` and
  `run.text_files` count them.

Without the package, for another language, or when parsing fails, a file is read as text, as
before. `backspec extract --text-only` (`Config(syntax=False)`) does that even when it is installed.
Observations made one way are not reused by a run made the other way.

## Layout

One module per capability under `src/backspec/modules/`, each with a `domain.py`, `use_cases.py`
and a small `facade.py`, plus `ports.py` where it needs the outside world. Adapters and wiring
live in `src/backspec/host/`. The import rules are enforced by `tests/test_architecture.py`.

```bash
python3 -m pytest -q
```

## The HTML report

`--format html` writes one self-contained page that loads nothing from the network. It shows little
at a time: the overview lists the capabilities and a search box; a capability lists its
requirements as single sentences; a requirement opens to its conditions, scenarios and cited lines.
"To review" holds the requirements below direct support and, folded away, open questions, lint
findings and failures. "Coverage" lists the files by state, folded, with the run's details.

The template is `src/backspec/templates/report.html`. Its look follows `DESIGN.md` at the root of this
repository (the ThoughtStream design system from designmd.ai); the heading font, Libre Baskerville
(OFL), is embedded in the page.

## Not verified

The Codex adapter has never been run against the real `codex` CLI. Requirement precision has not
been checked by a person. See the spec.

## Licence

MIT; see `LICENSE`. The HTML report embeds the Libre Baskerville font, which is under the SIL Open
Font Licence (`src/backspec/templates/libre-baskerville-OFL.txt`).
