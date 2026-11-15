# Assign stage

At the end of this message are the capabilities of one software product, then a list of
observations about it. Each observation line is `OBS-id | kind | statement`; `## path` lines say which
source file the following observations came from.

Assign every observation to exactly one capability id from the list: the one whose behaviour
the observation is evidence for. Judge by what the statement says, not by the file it came
from. Use `plumbing` only for internal mechanics no user, operator or calling system would
notice. A refusal, an error a caller gets back, a permission check, input validation, a change
that is saved, or anything shown is never plumbing, however technical it reads: place it with
the capability whose operation it belongs to. Observations of kind `entry_point`, `permission`,
`validation`, `state_change`, `error_path`, `display` and `test_case` placed in `plumbing` are
asked about again.

## Output

Reply with a single JSON object, and nothing else, with one entry for every OBS id given and
no others. Copy the ids exactly.

```json
{"assignments": {"OBS-1a2b3c4d": "capability_id", "OBS-5e6f7a8b": "capability_id"}}
```
