# Synthesise stage

You are given the verified observations for one capability of a software product. Each
observation is one fact that a single source file establishes, already checked against the
code. Your job is to turn them into requirements: complete behaviours of the product, as a
user or operator would state them.

The capability's name and summary come at the end of this message, followed by the
observations. Each observation is one block:

    OBS-id | kind | path:first-last | in name
      statement
      quote: a line copied from the code

`in name` is the function or method the observation sits in. It is missing when the program
could not tell.

## What a requirement is

- One behaviour that could be tested on its own. Split anything that joins several.
- Stated at the level of the product, not the code: "The developer can ...", "The system ...",
  "Grounded ...". No function, class or variable names.
- Complete: say who or what acts, what happens, and under which conditions. A behaviour that
  matters is usually spread over several observations from several files: the server code, the
  front end and the tests. Combine them into one requirement and list all of them as evidence.
- Many observations describe the same behaviour from different files. Merge them. Do not
  write one requirement per observation.
- Do not merge different operations. Observations from different functions, views or
  endpoints that do similar things (two pages that list procedures, two ways of approving a
  change) are different operations unless they show the same behaviour. When the behaviour
  differs between them (a different permission check, sort order, title or message), write one
  requirement per operation and say which operation each is. A condition seen in one operation
  must never be stated for another.

## Rules

1. Use only what the observations say. Do not add reasons, guarantees or outcomes that no
   observation states. Do not drop a condition an observation states either: a requirement
   that leaves one out claims more than the code does.
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
   It is fine to leave trivia unused, but not a refusal, an error, a permission check or a
   change that is saved: each of those belongs in some requirement. Aim for roughly one
   requirement for every five to ten observations, usually between 5 and 20 in all. These
   numbers never justify joining different operations or unrelated behaviours into one
   statement: a requirement that strings several behaviours together with "and" and ";" is
   too coarse, and should be split.

## Scenarios

A requirement may carry `scenarios`: concrete cases written as given / when / then. Add one
only where an observation shows that concrete case. That is usually an observation of kind
`test_case` (a test with a given input and an expected result), or a documented example.

- Each scenario has a `name`, `given` (the starting state), `when` (the action or input) and
  `then` (the observable result). All four must be filled in, from what the observations say.
- Each scenario lists the ids of the observations that show it, copied exactly, in the same
  way as a requirement. A scenario that cites no real observation is discarded, and so is one
  with a part left empty.
- Never invent a scenario to fill the field, and never turn a rule into an example that no
  observation shows. Most requirements will have no scenarios, and that is correct: leave
  `scenarios` empty or leave it out.

## Output

Reply with a single JSON object, and nothing else, in this shape:

```json
{
  "requirements": [
    {
      "statement": "The developer can ...",
      "conditions": ["..."],
      "level": "user",
      "evidence": [{"observation": "OBS-1a2b3c", "role": "establishes"}],
      "scenarios": [
        {
          "name": "A short name for the case",
          "given": "...",
          "when": "...",
          "then": "...",
          "evidence": [{"observation": "OBS-4d5e6f", "role": "establishes"}]
        }
      ]
    }
  ],
  "open_questions": ["..."]
}
```
