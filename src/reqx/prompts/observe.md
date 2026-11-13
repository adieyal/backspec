# Observe stage

You are given one batch of source files from a software product, at the end of this message. Every line starts with its
real line number, then `|`, then the line. Your job is to record what these files establish
about the product's behaviour. You are collecting evidence. You are not writing requirements.

## What to record

Go through each file and write one observation for each distinct thing it establishes that a
user, operator or calling system could notice. Look in particular for:

- what an entry point accepts and does: a route, a command, a UI action
- a permission or access check
- a validation, a limit, a refusal, and the error given
- a state change: what is saved, changed or deleted
- a rule for deciding something: a status, a category, an ordering
- what a test shows the product doing in a concrete case
- what is displayed to the user and when

Skip pure plumbing: imports, logging, formatting helpers, type declarations with no rule in
them. If a file holds nothing worth recording, list it under `none` with a short reason.

## Rules

1. One observation is one fact. Split anything that joins several.
2. State only what these lines show. Do not guess at behaviour in code you cannot see.
3. `lines` is the first and last line number of the code the observation rests on. Copy the
   numbers printed at the start of the lines. Never count lines yourself. Keep the range tight:
   usually under 30 lines.
4. `quote` is a short piece of text copied exactly, character for character, from one line
   inside that range. Leave out the line number and the `|`. Pick a distinctive line, not a
   blank or a lone bracket.
5. `path` is the file path exactly as printed in the `=== FILE:` header above the lines.
6. `kind` is one of: `entry_point`, `permission`, `validation`, `state_change`, `rule`,
   `display`, `error_path`, `test_case`, `doc_claim`, `other`.
7. Write each `statement` as one plain sentence about the product, for example "A rule whose
   test fails is given the status Broken." Do not mention function or variable names unless
   the user would see them.

## Output

Reply with a single JSON object, and nothing else, in this shape:

```json
{
  "observations": [
    {"path": "pkg/file.py", "lines": [120, 134], "quote": "if result.failed:", "kind": "rule",
     "statement": "A rule whose test fails is given the status Broken."}
  ],
  "none": [{"path": "pkg/other.py", "reason": "type declarations only"}]
}
```
