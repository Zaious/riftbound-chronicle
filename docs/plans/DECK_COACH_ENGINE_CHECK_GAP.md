# Deck Coach ↔ `engine-check.v1`: gap analysis and test list

Status: design accepted by
[ADR-0006](../decisions/ADR-0006-deck-coach-engine-evidence-intake.md) — no
schema or runtime implementation yet. Written 2026-09-03 for the Codex/Claude
split.

## Where Deck Coach stands

`check_readme_connection_claims.py` derives the six connection conditions from
artifacts, not from prose. For Deck Coach every one is false today:

| Condition | How the audit derives it | Deck Coach now |
| --- | --- | --- |
| `artifact_accepts_engine_check` | the session schema references `engine-check.schema.json` | `deck-coach-session.schema.json` has no `engine_checks` field |
| `runner_produces_or_imports` | the runner source contains `build_engine_check` and `engine_checks` | `deck_coach_pipeline.py` never touches either |
| `validator_rejects_overclaim` | the validator accepts a real `supported` check, refuses an overstated coverage, refuses a malformed check | no validator entry point exists (`spec["validate"] is None`) |
| `ui_renders_outcomes` | the prototype page loads `engine-check-view.js` and calls `mount` | `prototype/deck-coach/` renders behavior coverage only |
| `regressions_cover_supported_and_abstaining` | a check script exercises both a supported and an abstaining check through the artifact | `check_deck_coach.py` / `check_deck_coach_prototype.py` cover coverage display only |
| `authority_boundary_preserved` | a boundary constant survives consuming a check | no engine-facing authority constant exists (`spec["boundary"] is None`) |

Deck Coach therefore "displays behavior coverage" (D-03) but does not *consume
engine evidence*. That is the priority wiring item Codex named.

## What Deck Coach would consume, and what it must not conclude

Deck Coach's questions are construction and piloting. The engine can answer a
narrow subset of them, and the wiring has to keep that subset visible:

| Deck Coach claim | Engine evidence that can back it | Kind |
| --- | --- | --- |
| "this Reaction can be played in response to X" | timing check on a representative state | `timing`, `legal_action` (Phase A) |
| "this card's clause N executes as written" | effect check against its card program | `effect` — only once R3-A1+ programs exist |
| "these two units die simultaneously; you choose the order" | cleanup check → `decision_required` | `cleanup` |
| "this line is strong / this matchup is favourable" | **nothing** | must stay `strategy_evidence: not_established_by_engine_coverage` |

The last row is the boundary constant. Deck Coach already carries
`strategy_evidence: not_established_by_engine_coverage` in
`deck-behavior-coverage.v1`; the engine-check wiring must leave it in place
after a check is attached. That is the authority test.

## Accepted shape

**Session artifact.** Add an optional `engine_checks` array to
`deck-coach-session.v1`, each item a full `engine-check.v1` — the same pattern
`rule-consultation.v1` and `p2a-session.v1` use, so the shared viewer and the
shared validator apply unchanged. Optional, so existing sessions stay valid
(ADR-0002 row 1). When present it is paired with
`engine_evidence_scope: rules_consistency_only`.

**Runner.** `deck_coach.py engine-check <session> --check <engine-check.json>`
mirroring `rule_consult.py engine-check`: validate the check with
`validate_engine_check`, refuse if invalid, append. The first wiring is
**consume-only**. Producing a timing check later requires an explicit structured
scenario; primer prose is never converted into an invented game state.

**Authority constant.** A Deck Coach constant
`ENGINE_EVIDENCE_SCOPE = "rules_consistency_only"` recorded on the session
when the first check is attached, plus the existing
`strategy_evidence: not_established_by_engine_coverage` on coverage. The audit
condition becomes: after attaching any check, both survive unchanged.

**Prototype.** Mount the shared `engine-check-view.js` under the coverage
panel, read-only, all five outcomes — the D-00 core already renders them.

**Nothing here changes:** primer generation, diagnosis, the coverage
projection, or any schema semantics. No engine op. No strategy inference from
engine outcomes.

## Test list (each is an injected failure the gate must catch)

1. Session with a real `supported` timing check attached → validates.
2. Same session with the check's `coverage.complete_game` flipped true →
   rejected with a coverage error.
3. Malformed check (missing `authority`) → rejected.
4. Attaching a check must not change `primer`, `diagnosis`, or
   `strategy_evidence` — hash the three before and after.
5. A check with outcome `unsupported` attached → session valid, and the
   coverage panel still says `not_established_by_engine_coverage`.
6. `decision_required` cleanup check attached → the session must not carry
   `cleanup_decisions` or `replacement_event_order` (the consultation presents
   the choice; Deck Coach does not make it — same rule as Rule Consult).
7. Prototype renders all five outcomes from `engine-check-fixtures.js` with
   no control that resolves a decision (reuse `check_engine_check_view`'s
   read-only invariant).
8. `check_readme_connection_claims.py` derives `deck-coach 6/6` from
   artifacts alone; READMEs are then updated to say so, not before.
9. Off-cwd: the `engine-check` subcommand works from `$TEMP` by absolute path
   and writes nothing on failure.

## Codex decisions (accepted 2026-09-03)

- `engine_checks` is an optional array on `deck-coach-session.v1`.
- `engine_evidence_scope: rules_consistency_only` lives on the session and is
  required whenever `engine_checks` is present; behavior coverage retains its
  separate strategy-evidence constant.
- The first wiring only consumes validated checks. It does not produce timing
  checks from primer claims.
