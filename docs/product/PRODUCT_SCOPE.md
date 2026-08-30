# Product Scope: Three Riftbound Assistant Systems

Status: development baseline
Date: 2026-08-24

Riftbound Chronicle is a portable knowledge and decision-support project with three distinct systems:

1. `deck-coach` teaches deck construction and how to pilot a finished list.
2. `rule-consult` explains rules and analyzes interactions with citations and calibrated uncertainty.
3. `player2-agent` acts as the strategic second player in a manually operated physical game.

The systems share card, rules, format, and evidence data. They do not share authority. A deck recommendation is not a ruling; a rules explanation is not a state transition; a Player 2 choice is not automatic rules enforcement.

A fourth system, `play-reviewer`, is planned for decision-time replay analysis.
It remains outside the active Skill router until the sovereign rules core can
reconstruct the bounded interaction and legal timing set with tested coverage.
See `../play-reviewer/PLAY_REVIEWER_PRODUCT_SPEC.md`.

## Product outcomes

### Deck Coach

Given a deck idea or list, produce:

- legality and environment checks;
- deck identity, engine, functional roles, curve, and substitutions;
- an evidence-aware deck primer;
- opening priorities, sequencing plans, fight-or-hold guidance, and common mistakes.

### Rule Consult

Given a rules question or concrete interaction, produce:

- the most likely answer;
- stated facts and assumptions;
- the applicable ruleset and source-precedence chain;
- citations and an explanation;
- a confidence level and escalation condition;
- a clear statement that the output is not an official tournament ruling.

Tournament procedure and penalties always remain subject to the event's Head Judge.

### Player 2 Agent

Given a human-confirmed game state and only the information Player 2 is entitled to know, produce:

- candidate strategic actions;
- a preferred action and rationale;
- the assumptions behind the choice;
- a request for human legality confirmation;
- an auditable decision record.

The initial deliverable is P2-A: assisted manual play. The human operates all physical cards and confirms every rule-dependent state transition.

## Shared sovereign rules layer

All modes may use a Chronicle-owned, versioned rules core for bounded timing
and permission reasoning. Version 1 derives the four Open/Closed and
Neutral/Showdown states, Action/Reaction permissions, Priority/Focus gates,
and the next HOT/FEPR procedure. It is executable support for Agent reasoning,
not a claim that arbitrary card effects or a complete game are implemented.

Official rules and scoped FAQs remain normative. A mismatch is a conformance
failure in the core. The public P2-A flow still gives the human authority over
physical operations, incomplete card-effect legality, and resulting state.

## Explicit non-goals for the current implementation

- No complete automated Riftbound card-effect or gameplay engine.
- No software-controlled shuffle, draw, phase progression, effect resolution, damage assignment, scoring, or win determination.
- No claim that a bounded timing-permission result is an authoritative or
  complete legal-action set for unsupported card behavior.
- No matchmaking, rank, ladder, or tournament bracket.
- No retained or published card/deck play rates, win rates, or matchup percentages.
- No claim that `rule-consult` is an official Riot or tournament judge.
- No implementation of P2-S.

## P2-S status

P2-S means a future automated simulator or reinforcement-learning environment that owns state, legal actions, and resolutions. It is documented only to prevent P2-A architecture from blocking a future authorized implementation.

Its status is:

```text
planned: true
implemented: false
included_in_public_runtime: false
activation_gate: written Riot approval plus a separate implementation decision
```

## Release layers

| Layer | Included now | Release rule |
|---|---|---|
| Portable skill | Three-mode router, knowledge, schemas, validation | Public repository |
| P2-A prototype | Human-confirmed session ledger and decision protocol | Prototype for review and application |
| Player-facing app | UI/API around the approved flow | Requires current Riot registration/approval decisions |
| P2-S | Automated state/rules/self-play | Not implemented without a new authorization decision |

## Development order

1. Establish the three-mode contracts and source authority.
2. Add shared schemas and deterministic validation.
3. Deliver the P2-A session-ledger vertical slice.
4. Add mode-specific evaluations.
5. Build a player-facing prototype around the same protocol.
6. Prepare the Riot application package from the working prototype.
