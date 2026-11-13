# Working on reqx

reqx reads a codebase and writes down the requirements it implements, with citations that are
checked in code. Read `README.md` first.

- One module per capability under `src/reqx/modules/<capability>/`: `domain.py` (rules and
  models, no I/O), `ports.py` (what it needs from outside, as Protocols), `use_cases.py`, and a
  small `facade.py`. Models that combine several modules go in `dto.py`.
- A domain imports only `reqx.kernel` and its own domain. A module reaches another module only
  through that module's `facade`. Nothing under `modules/` or `kernel/` imports `reqx.host`.
- Adapters (file system, model backends, cache, YAML files) and wiring live in `src/reqx/host/`.
  `host/cli.py` holds no logic: it turns flags into a `Config` and prints what comes back.
- The program drives and the model only reads and writes statements. Anything that can be
  checked or computed in code is, never asked of a model. A model never writes a citation that
  the program could copy.
- Nothing is dropped silently. What is rejected, skipped, unmatched or failed is recorded in the
  result with its reason.
- Tests live flat in `tests/` as `test_*.py` and run against `reqx.host.adapters.fake.FakeLLM`.
  Name a test for the behaviour it shows.
- Change `PROMPT_VERSION` in `src/reqx/kernel/prompts.py` whenever a prompt changes.
- Run `python3 -m pytest -q` before you finish. It must pass, including `tests/test_architecture.py`.
