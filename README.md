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

```bash
reqx render reqs.json -o REQUIREMENTS.md
```

```python
from reqx import Config, extract

result = extract("./repo", Config(include=["src/**"]))
for requirement in result.requirements:
    print(requirement.id, requirement.support, requirement.statement)
```

The default model backend is the Claude Code CLI, using the login you already have. It must be
installed. To use anything else, pass an object with a `complete(request) -> str` method as
`Config(provider=...)`.

## How it works

1. **Discover.** List the files, apply the include and exclude patterns, take one snapshot of
   each file that will be read.
2. **Observe.** Show a model every line, each with its real line number, and collect single
   facts with a line range and a verbatim quote.
3. **Verify.** Keep an observation only if its quote is really in the file. No model is involved.
4. **Orient and assign.** Propose capabilities, then place each observation in one. Grouping is
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

Triage, the editable capabilities file, the review file and durable ids, staleness, the
triage audit, tree-sitter, a Codex adapter, token budgets, and every renderer other than
Markdown. See the spec.
