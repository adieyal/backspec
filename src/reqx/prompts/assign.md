# Assign stage

At the end of this message are the capabilities of one software product, then a list of
observations about it. Each observation line is `OBS-id | statement`; `## path` lines say which
source file the following observations came from.

Assign every observation to exactly one capability id from the list: the one whose behaviour
the observation is evidence for. Judge by what the statement says, not by the file it came
from. Use `plumbing` only for internal mechanics no user or operator would notice.

## Output

Reply with a single JSON object, and nothing else, with one entry for every OBS id given and
no others. Copy the ids exactly.

```json
{"assignments": {"OBS-1a2b3c4d": "capability_id", "OBS-5e6f7a8b": "capability_id"}}
```
