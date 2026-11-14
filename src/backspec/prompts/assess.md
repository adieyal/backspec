# Assess-support stage

You are checking requirements against the code they cite. You did not write them. Be strict.

The requirements come at the end of this message, one block each. A block starts with `##### REQ-id`, then the
STATEMENT (and CONDITIONS if any), then one or more pieces of evidence. Each piece of evidence
shows numbered code lines; the lines marked `>` are the cited ones and the others are
surrounding context.

For each requirement, judge the whole statement, including every condition, against all of its
evidence taken together:

- `direct`: the evidence shows the complete behaviour as stated. Every part of the statement
  and every condition can be pointed to in the shown code.
- `partial`: the evidence shows the main behaviour, but some part of the statement or a
  condition is not shown. Name the missing part.
- `insufficient`: the evidence is related but does not show the behaviour, or shows only that
  something exists.
- `conflicting`: the shown code disagrees with the statement. Say how.

A statement that says more than the shown code shows is `partial`, not `direct`. Code that only
shows a function, field or type exists is `insufficient` for a claim about behaviour. A test
counts as evidence of behaviour.

Do not use outside knowledge of the product. Judge only from the shown lines.

Reply with a single JSON object, and nothing else, in this shape, with one entry per requirement:

```json
{"verdicts": [{"id": "REQ-1a2b3c4d", "support": "partial",
               "note": "one short sentence; for anything but direct, exactly what is not shown, with the line number you rely on"}]}
```
