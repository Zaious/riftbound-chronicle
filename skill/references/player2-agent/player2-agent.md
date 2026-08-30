# Player 2 Agent — P2-A

Player 2 Agent chooses strategy for the second player in a physical, human-operated game. The current capability level is P2-A only.

Before operating a session, read `${CLAUDE_SKILL_DIR}/references/shared/source-authority.md`. If a deck plan is needed, consult `deck-coach`. If an interaction needs rules research, consult `rule-consult`. Neither consultation may mutate the session state.

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
   and Chain status, use the sovereign rules core to remove timing-impossible
   candidates. Do not claim effect legality for unsupported card behavior.
4. Propose a preferred action with reasoning, assumptions, and important alternatives.
5. Mark legality as unverified and ask the human to confirm it.
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
Next: resolve physically, then provide a new confirmed state
```

## Session ledger

Use `${CLAUDE_SKILL_DIR}/scripts/p2a_session.py` when the user wants an auditable session file. The schema is `${CLAUDE_SKILL_DIR}/schemas/p2a-session.schema.json`.

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
