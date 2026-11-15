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
- a guarantee a caller can rely on: work done in one transaction, a row locked against
  concurrent changes, a notification sent only once the change is saved

Record every entry point (a route, a view, a command handler) at least once, even one that only
hands the work on to other code: say what it accepts, what it refuses and what it hands on.

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
8. Keep every condition. When the code checks, filters or restricts by several things, the
   statement names all of them. "Auto-created issues with this text are deleted" is wrong when
   the code also requires the issue to have no photo: the statement must say so.
9. Read the lines around the ones you cite, and do not describe a line in a way its neighbours
   contradict. A field kept for compatibility next to a fuller one (a single `issue` beside a
   list of every `issues`), a default that is overwritten later, or a comment stating what the
   code is for all change what the cited line means.
10. Say only what the code does with a value. A value worked out but not shown being returned,
    saved, sent or displayed is not something anyone sees: do not say it is "shown" or that
    something "is named" it.
11. Say which operation a fact belongs to whenever the file has more than one that could fit,
    for example "When approving suggestions from the HQ page, ..." rather than "When approving
    suggestions, ...". Two views, pages or endpoints that do similar things are different
    operations, and a reader must be able to tell them apart from the statement alone.

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
