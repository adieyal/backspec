# Triage stage

You are given a batch of files from a software product, at the end of this message. For each
file you see its path, its size in lines, and its first lines, each with its real line number.
You are not reading the files in full. This is a quick first look, to decide which files are
worth reading closely for behaviour that a user or operator would notice.

## What to say about each file

- `role`: what the file is, one of `ui`, `api`, `domain`, `test`, `docs`, `infra`, `config`,
  `generated`, `data`, `other`.
- `relevance`: how likely the file holds behaviour a user or operator would notice (screens,
  routes, commands, permissions, validation, rules, state changes, what tests show the product
  doing, claims in documentation). One of `high`, `medium`, `low`, `none`.
- `sure`: `true` only if the preview is enough for you to be confident of the relevance. If the
  preview is cut off and the rest could hold something different, or the file is unusual, say
  `false`.

## Rules

1. Answer for every file in the batch, with `path` exactly as printed in the `=== FILE:` header.
2. Use `none` only for a file that plainly holds no behaviour: lock files, build and tool
   configuration, generated code, fixtures and vendored or bulk data. When in doubt, use `low`
   or `sure: false`. A file you are not sure about is read in full anyway; a file wrongly
   dismissed is lost.
3. Judge from what you see. Do not guess at what the rest of the file might hold.

## Output

Reply with JSON only, in this shape:

```json
{"files": [{"path": "src/app.py", "role": "api", "relevance": "high", "sure": true}]}
```
