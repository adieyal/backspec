# Orient stage

At the end of this message is a list of observations about one software product, grouped under
the source file each came from. Each line is `OBS-id | kind | statement`.

Propose the product capabilities these observations belong to. A capability is a feature area
as a user of the product would name it, for example "Password reset" or "Invoice export". It is
not a file, a layer or a technology. One source file can feed several capabilities, and one
capability usually draws on several files: server code, front-end code and tests.

## Rules

- Propose capabilities that together cover the observations. Let the number follow the amount of
  evidence: about one capability for every 25 to 40 observations, never fewer than 2 and never
  more than 18. A hundred observations is 3 or 4 capabilities, not 10.
- Make them distinct; no two should overlap heavily. If two would share most of their
  observations, they are one capability.
- Size them evenly where you can. Avoid one giant capability and avoid tiny ones.
- Do not propose `plumbing`. The program adds it, for internal mechanics no user, operator or
  calling system would notice. Input validation, refusals, errors and permission checks are
  never plumbing: put them in the capability whose operation they guard.
- Give each an `id` (lowercase letters and underscores), a `name` (2 to 5 words), a `summary`
  (one sentence saying what the user can do or see), and `includes` (3 to 6 short phrases
  naming the kinds of observation that belong there, so that observations can be assigned
  consistently).

## Output

Reply with a single JSON object, and nothing else, in this shape:

```json
{"capabilities": [{"id": "password_reset", "name": "Password reset",
                   "summary": "The user can ...", "includes": ["...", "..."]}]}
```
