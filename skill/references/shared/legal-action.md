# Bounded legal-action service (Phase A)

Status: implemented for caller-supplied candidates only. Decided in
[ADR-0003](../../../docs/decisions/ADR-0003-bounded-observation-and-legal-actions.md).

The service answers one narrow question: *for these candidate actions the
caller wrote down, what does the timing kernel say about each?* It never
generates candidates. Every result carries `enumeration_attempted: false` and
`complete_action_set: false` as constants, and a consumer may not turn "every
candidate I supplied was checked" into "every legal action was found".

## Three artifacts

| Artifact | Purpose |
| --- | --- |
| `observation.v1` | What is known, from whose perspective, how completely. Facts sit in six sets — `confirmed_public`, `own_private`, `inferred`, `later_revealed`, `unknown`, `contradictory` — and completeness is rated per field group, not as one boolean. |
| `action-query.v1` | The caller's candidates, bound to one `observation_hash`. Phase A has one `candidate_source_mode`: `user_supplied`. |
| `legal-action-result.v1` | One verdict per candidate with reason, official locators, what is missing, and any pending decision it depends on. |

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `legal` | every supported check passed |
| `illegal` | a supported rule rejects it, with the clause cited |
| `indeterminate` | a required fact is absent or ambiguous — always names what is missing |
| `unsupported` | the engine does not implement the semantics needed |
| `decision_required` | an identified controller choice must be supplied first |

A candidate's `action.checks` names what it wants verified (`timing`, `cost`,
`targets`, `effect_prerequisites`; default `timing`). Phase A implements
`timing` only — asking for any other check returns `unsupported` naming that
check, rather than a timing-only verdict that silently pretends the rest ran.

The classifier consults structured facts only. A candidate that arrives as prose,
or an observation without a complete structured `timing_state`, is
`indeterminate`. It does not read the human's summary and guess.

## Two boundaries, enforced structurally

**Perspective.** A `player2` observation or query is refused if any Player 1
private key appears anywhere in it — the same forbidden-key list P2-A uses.

**Hindsight.** `later_revealed` and `contradictory` facts are carried so Match
Analyst can record what was not known, but they never reach a verdict: the
observation hash and the result hash are identical with and without them.

## Runner

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/legal_action.py classify observation.json query.json `
  --output result.json

python ${CLAUDE_SKILL_DIR}/scripts/legal_action.py validate result.json
```

`classify` exits non-zero and writes nothing if the pair is invalid or the
query is bound to a different observation. Fixtures under
`data/legal_action_examples/` are generated from `check_rules_core.FIXTURES`
by `build_legal_action_fixtures.py`, and CI fails when they are stale.

## Into engine-check.v1

A result wraps as check kind `legal_action` with coverage `legal_action_v1`.
The envelope summarises — `supported`, `decision_required` when any candidate
is, `unsupported` when all are, `invalid_input` when the pair was refused — and
never adds an outcome the per-candidate artifact did not reach. Enumeration and
a complete action set are declared in its `unsupported_scope`.

## What P2-A may do with it

Rank only candidates whose verdict is `legal`. `indeterminate`, `unsupported`
and `decision_required` stay visible and un-ranked. Legality and physical state
remain human-confirmed; this is a consistency check, not an authority.
