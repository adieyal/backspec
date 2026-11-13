# Consolidate stage

You are given the requirements already written for one capability of a software product. Each
has an id, a statement, its conditions, and the ids of the observations it cites. Many of them
are too fine: the same behaviour written several times, or one behaviour cut into pieces.
Your job is to say which requirements are the same behaviour and should become one.

## What to merge

Merge requirements that:

- state one rule or behaviour, and differ only in a message, a reason string, a status name,
  an enum value, a field or a file;
- are one rule cut into its cases (one per status, one per reason, one per kind of input):
  write the rule once and put the cases in its conditions;
- show the same behaviour from different places (the check, the screen, the report, the test).

Do not merge requirements that a reviewer would test separately, or that have different actors
or different outcomes. When in doubt, leave it out. A requirement you do not mention is kept
unchanged.

## How to write a merged requirement

- `statement`: one complete statement of the rule, at the level of the product. Use only what
  the merged statements say. Do not add reasons or outcomes they do not state.
- `conditions`: the conditions of the merged requirements, joined and without repeats. Keep
  the cases that distinguish the rule's variants.
- `level`: `user`, `system` or `technical`, as for the requirements merged.
- `merge`: the ids of the requirements this one replaces, copied exactly. At least two. A
  requirement id may appear in only one group. Do not invent ids.

You do not write citations. The program takes the evidence of the merged requirements.

## Output

Reply with a single JSON object, and nothing else:

```json
{
  "groups": [
    {
      "statement": "The system ...",
      "conditions": ["..."],
      "level": "system",
      "merge": ["REQ-1a2b3c", "REQ-4d5e6f"]
    }
  ]
}
```

If nothing should be merged, reply `{"groups": []}`.
