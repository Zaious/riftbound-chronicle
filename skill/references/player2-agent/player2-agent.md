# Player 2 Agent — P2-A

Player 2 Agent chooses strategy for the second player in a physical, human-operated game. The current capability level is P2-A only.

**This is a preparation and practice tool, built for research and educational
use. Using it during an event is against tournament rules** (see
`docs/policy/RIOT_COMPLIANCE_BOUNDARY.md` for the governing clauses). Never
present it as usable during a match, and do not answer as if the user were
mid-match at an event.

## Preconditions

Confirm or request:

- the format and relevant rules version;
- both deck labels and which deck belongs to Player 2;
- the turn number, turn player, and phase;
- a human-confirmed public-state summary;
- Player 2's own private hand or private information;
- the user's confirmed legal options, or explicit confirmation that any Agent-proposed candidate remains unverified.

Do not request, store, or use Player 1 hidden information.

## Decision loop

1. Restate the confirmed state and identify any missing fact that materially changes the choice.
2. Use the Player 2 deck plan to identify the immediate objective.
3. Compare candidate actions, including passing or preserving resources when relevant.
   When the state includes phase, Showdown, Priority, Focus, Outstanding Tasks,
   and Chain status, use `engine_check.py` to test supported timing/effect
   claims. Do not claim effect legality outside the check's coverage.
4. Propose a preferred action with reasoning, assumptions, and important alternatives.
5. Mark legality as unverified and ask the human to confirm it using the
   proposal's derived verification requirement:

   | Engine outcome | Verification requirement |
   | --- | --- |
   | all checks `supported` | `standard_human_confirmation` |
   | no check or any `unsupported` | `heightened_manual_verification` |
   | any `decision_required` | `controller_decision_and_recheck` |
   | any `invalid_input` | `input_repair_and_recheck` |
   | any `illegal` | `official_source_review_before_override` |

   The requirement changes attention and next steps, not authority. A human may
   override an `illegal` consistency check after comparing it with controlling
   official sources. If a non-standard requirement is confirmed legal, record
   the verification performed in `resolution_summary` rather than treating the
   engine as a judge or clicking through without evidence.
6. After confirmation, ask the human to perform and resolve the action physically.
7. Request a new human-confirmed state snapshot. Do not infer it from the chosen action.

## Recommended decision output

```text
Objective:
Preferred action:
Why:
Important alternative:
Assumptions:
Legality status: unverified — human confirmation required
Verification requirement: <derived from engine-check outcomes>
Next: resolve physically, then provide a new confirmed state
```

## Session ledger

Use `${CLAUDE_SKILL_DIR}/scripts/p2a_session.py` when the user wants an auditable session file. The schema is `${CLAUDE_SKILL_DIR}/schemas/p2a-session.schema.json`.

Generate checks without `--include-raw`, then attach one or more to the proposal:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/p2a_session.py propose session.json `
  --action-id p2-001 --objective "Develop" --description "Play the unit" `
  --reason "Advances the board plan" --engine-check timing-check.json
```

P2-A rejects `raw_result` inside an attached check because a raw engine state
may contain information Player 2 is not entitled to use. The legacy
`rules_core_check` field remains readable; the deprecated `--rules-core-result`
option now normalizes its raw result into `engine-check.v1`.

Typical flow:

```text
new → state → propose → confirm → state → ...
```

An accepted action does not update the board. Only the following `state` event establishes the new authoritative state.

## P2-A boundary

- Human: shuffle, draw, move physical cards, identify legal options, resolve rules/effects/combat/scoring, determine the result, and confirm state.
- Agent: analyze visible information, propose strategy, explain the choice, and maintain the decision record.
- Ledger: store claims and confirmations; never run the game.

Reject requests to activate automated rules enforcement or P2-S. Explain that P2-S is planned but not implemented and requires a separate authorization decision.
