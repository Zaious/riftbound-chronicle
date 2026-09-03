# Legal-action Phase-A fixtures

`fixtures.json` is **generated** by `skill/scripts/build_legal_action_fixtures.py`.
Every observation wraps a timing state from `check_rules_core.FIXTURES` and
every verdict comes from `legal_action.classify_candidates` calling the real
`rules_core.validate_timing`. Do not hand-edit; re-run the builder and commit
the diff. `check_legal_action.py` fails CI when the file is stale.

| Fixture | What it pins |
| --- | --- |
| `neutral_open_mixed` | `legal`, `illegal`, and `unsupported` (a requested cost check) in one query from a complete Neutral Open state |
| `neutral_closed_reaction_window` | a response window: Reaction legal, default play illegal with Core 807 cited |
| `prose_only_indeterminate` | no structured timing state → every candidate `indeterminate`, missing facts named |
| `pending_decision` | a listed pending decision → `decision_required`; an unlisted reference → `indeterminate` |
| `showdown_open_focus` | Focus-holder actions legal; a candidate for the other player is not classified as this one |
| `hindsight_without` / `hindsight_with` | same decision-time facts with and without `later_revealed` and `contradictory` sets — identical hashes and verdicts |

These assert nothing about Riftbound beyond what the timing kernel already
models. Nothing here is official, and nothing here enumerates.
