# Synthesise stage

You are given the verified observations for one capability of a software product. Each
observation is one fact that a single source file establishes, already checked against the
code. Your job is to turn them into requirements: complete behaviours of the product, as a
user or operator would state them.

The capability's name and summary come at the end of this message, followed by the
observations. Each observation is one block:

    OBS-id | kind | path:first-last
      statement
      quote: a line copied from the code

## What a requirement is

- One behaviour that could be tested on its own. Split anything that joins several.
- Stated at the level of the product, not the code: "The developer can ...", "The system ...",
  "Grounded ...". No function, class or variable names.
- Complete: say who or what acts, what happens, and under which conditions. A behaviour that
  matters is usually spread over several observations from several files: the server code, the
  front end and the tests. Combine them into one requirement and list all of them as evidence.
- Many observations describe the same behaviour from different files. Merge them. Do not
  write one requirement per observation.

## Rules

1. Use only what the observations say. Do not add reasons, guarantees or outcomes that no
   observation states.
2. Every requirement lists the ids of the observations it rests on, copied exactly. You cannot
   cite anything else. An id you invent or alter makes the requirement invalid.
3. Give each cited observation a role:
   - `establishes`: it shows part of the behaviour itself: the check, the rule, the change,
     what is displayed, or a test demonstrating it.
   - `context`: it only shows that something exists, such as a route or a field.
4. `conditions` lists what the behaviour depends on: a state, a limit, a setting. Leave it
   empty when there is none.
5. `level` is `user` when a person using the product can see or do it, `system` when it is a
   rule the product enforces behind the scenes, `technical` for internal mechanics.
6. If the observations suggest a behaviour but leave a gap you would have to guess at, do not
   guess. Add a line to `open_questions`.
7. Consolidate hard. Write the fewest requirements that still cover what the capability does.
   One requirement is one rule with all its conditions, citing every observation that shows it.
   This is too fine, and you must not do it:
   - one requirement per message string, status message or reason string: write the rule that
     produces them once, and list the cases in `conditions`;
   - one requirement per enum value, status or option: that is one rule with several cases;
   - one requirement per file that shows the same behaviour: the server, the front end, the
     report and the test are one requirement with several pieces of evidence;
   - a requirement that only restates another from its test, or only adds a detail of wording.
   The right grain is what a product owner would list as "what this capability does". Before
   you answer, read your list again and merge any two that a reviewer would test together.
   It is fine to leave trivia unused. Aim for roughly one requirement for every five to ten
   observations, usually between 5 and 20 in all, and never more than one for every three
   observations.

## Output

Reply with a single JSON object, and nothing else, in this shape:

```json
{
  "requirements": [
    {
      "statement": "The developer can ...",
      "conditions": ["..."],
      "level": "user",
      "evidence": [{"observation": "OBS-1a2b3c", "role": "establishes"}]
    }
  ],
  "open_questions": ["..."]
}
```
