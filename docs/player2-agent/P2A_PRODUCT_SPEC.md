# Player 2 Agent: P2-A Product Specification

Status: implementation target
Date: 2026-08-24

## Purpose

P2-A lets one human operate two physical Riftbound decks while an Agent supplies Player 2's strategic choices. The software assists state recording and decision-making; the human remains responsible for physical operations, legality, and resolution.

## Primary user flow

1. The user creates a session and names both decks.
2. The user records the current phase, public board summary, and Player 2's private hand.
3. The Agent reviews only Player 2-visible information.
4. The Agent records one or more proposed actions with strategic reasons and assumptions.
5. The user confirms or rejects the selected action's legality.
6. The user performs the physical action and resolves all effects.
7. The user records the resulting position as a new confirmed state.
8. The cycle repeats until the physical game ends.

## Functional requirements

### Session

- Unique session identifier and timestamps.
- Format, ruleset version, deck labels, and participant roles.
- Fixed P2-A authority metadata.
- Append-only ordered event ledger.

### State snapshot

- Turn number, turn player, and phase as human-entered labels.
- Public-state summary.
- Player 2 private-hand summary.
- Optional notes and source/version metadata.
- Human confirmation identity.

The prototype deliberately does not parse these fields into rule-enforceable objects.

### Action proposal

- Stable action identifier.
- Reference to the confirmed state on which the proposal was based.
- Description, strategic reason, assumptions, and alternatives considered.
- `legality_status: unverified` at creation.
- Zero or more compact `engine-check.v1` envelopes without raw engine state.
- A deterministic verification requirement derived from the check outcomes;
  this calibrates human attention but does not change legality authority.
- No state mutation.

### Human confirmation

- Reference to an existing proposal.
- Legal or rejected decision.
- Human confirmer.
- Optional physical-resolution summary.
- Explicit marker that the resulting state still requires a new human snapshot.

### Audit and portability

- Human-readable JSON session file.
- Deterministic offline validator.
- No external Python dependencies.
- Works when invoked outside the repository by absolute path.

## Safety and policy invariants

- `automation_level` must equal `P2-A`.
- `p2s_enabled` must be `false`.
- `state_authority` and `legality_authority` must be `user_confirmed`.
- Player 1 hidden information is not stored.
- A proposal cannot be presented as already legal.
- A supported engine check cannot replace human confirmation; an illegal check
  can be overridden only as a recorded human judgment against official sources.
- A legal confirmation under any non-standard verification requirement must
  include a non-empty human verification summary.
- Raw engine results are rejected at the P2-A information boundary.
- An action confirmation cannot produce an authoritative derived state.
- The next authoritative state must be a separate human-confirmed snapshot.
- The public implementation contains no randomizer, card resolver, phase engine, scoring engine, or winner evaluator.

## Prototype acceptance criteria

- Create and validate a new P2-A session.
- Record a human-confirmed state.
- Record an Agent proposal.
- Preserve supported, unsupported, decision-required, invalid-input, and illegal
  checks with distinct verification requirements.
- Confirm or reject the proposal as a human.
- Reject malformed sessions and any session claiming engine-derived authority or P2-S activation.
- Preserve a complete event trail suitable for a product demo and Riot review.
- Provide a no-build visual flow that creates, displays, and exports the same ledger contract without adding rule automation.

## Deliberately deferred

- A graphical card-table renderer; the current UI is a workflow prototype rather than a digital tabletop.
- Card image rendering.
- Authentication and RSO.
- Network synchronization.
- Voice input.
- Complete structured card zones.
- Automated legality or resolution.
- Model hosting and reinforcement-learning inference.
