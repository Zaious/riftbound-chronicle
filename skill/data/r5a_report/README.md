# R5-A coverage and abstention report

`report.json` is **generated** by `skill/scripts/r5a_report.py build`. It runs
every existing executable fixture through the real engines and wraps each in
`engine-check.v1`, so its counts are the engine's counts, not a description of
them. `check_r5a_report.py` fails CI when the file is stale or when any of the
report's refusals is missing. Re-run the build and commit the diff; do not
edit by hand.

What it measures:

| Section | Source |
| --- | --- |
| `engine_checks` | outcome per check kind, and the overall abstention rate |
| `fixture_conformance.rules_core` | the 21 timing cases matched their stored expectations; this is regression consistency, not proof that the expectations are correct |
| `locator_exercise` | exact locator strings cited by executed fixtures ÷ exact locator strings declared by the capability manifest |
| `abstention` | five buckets — missing state, unsupported mechanic, source conflict, stale data, decision required — each listing which fixtures landed there |
| `legal_action_verdicts` | the five Phase-A verdicts, counted over the legal-action fixtures |

What it refuses, as constants that fail validation if flipped: search, policy
strength, P2-S, matchup rates, complete game, complete legality. This is R5's
measurement tier and nothing above it. A number here says how much of the
engine's own declared locator list its fixtures exercise by exact-string
identity. It does not say that a cited rule-family range is completely
implemented, that a stored expectation is correct, or how any deck or player
performs.
