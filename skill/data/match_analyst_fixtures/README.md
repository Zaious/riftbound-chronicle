# Match Analyst example logs and uncertainty fixtures

Match Analyst is **specified, not implemented, and not routed**. See
[`../../../docs/match-analyst/MATCH_ANALYST_PRODUCT_SPEC.md`](../../../docs/match-analyst/MATCH_ANALYST_PRODUCT_SPEC.md),
including its activation gate. Nothing in this directory says the system exists;
these are the logs a future implementation will be held to, written first so the
hard cases are fixed before anything can be tuned to pass them.

[`../../scripts/check_match_analyst_fixtures.py`](../../scripts/check_match_analyst_fixtures.py)
validates them, and fails if `SKILL.md` starts routing the mode.

| Fixture | Kind | What it defends against |
| --- | --- | --- |
| `complete-showdown.json` | `complete` | A system that labels everything uncertain. Without a log where nothing is missing, the other three are passed by abstaining always. |
| `partial-observer.json` | `partial` | Reconstructing a missing Chain order or a player's unseen options and presenting it as observed. Every gap here looks recoverable, which is what makes it a trap. |
| `contradictory-record.json` | `contradictory` | Choosing the branch that reads better. Two recorders disagree about whether a unit died and about who held Priority; one account is false and the log cannot say which. |
| `perspective-safe-hidden.json` | `perspective_safe` | Two separate leaks: using what the player could not see, and grading a decision by what the reveal showed afterwards. Excluding only opponent-private events stops the first and lets the second straight through. |

## Shape

`riftbound-match-log-fixture.v1` is the shape **these fixtures** use. It is not
`match-analysis.v1`, and it is deliberately not a file in `skill/schemas/`:
defining the artifact contract is implementation work gated behind R2/R4, and a
schema sitting in the schemas directory would read as a commitment nobody has
made. Each event carries turn, phase, four-state label, Priority, Focus,
Outstanding Tasks, and Chain, plus `visibility`
(`public` / `private:<player>` / `revealed_later`) and one of the spec's four
certainty labels.

Each fixture ends in `expected_analysis_boundary` — the obligations an analysis
of that log must respect, in machine-checkable form: which events it may not
use, which it may not use *before* a given decision, which decisions it cannot
grade, and which claims are off-limits. That block is the actual test material;
the events exist to make it concrete.

## What the check re-derives rather than trusts

A fixture that labels itself contradictory must contain a contradiction the
checker finds on its own, from the events. A fixture that declares an event
unusable must have labelled it genuinely unreadable from the stated perspective.
Card names are verified against the bundled card database, rules vocabulary
against the four states and the spec's labels, and the ruleset against the
executable baseline. A label the checker takes on faith is a label that can
quietly become false.

## Provenance

Every log is synthetic and marked `is_real_match: false`. Card names, card text
behaviour, and battlefields are real, so the logs are recognisable as Riftbound;
the matches never happened and must never be presented as a record of anyone's
game. No win rate, play rate, matchup percentage, or ranking is computed here or
derivable from a single match.
