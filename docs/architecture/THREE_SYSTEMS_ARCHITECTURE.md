# Three-Systems Architecture

Status: accepted baseline
Date: 2026-08-24

This document describes the three currently active modes. The planned fourth
mode, Play Reviewer, is specified separately and is not routed until its
rules-core activation gates pass.

## Design principle

The project is one portable Skill with three operating modes, not three unrelated assistants and not one undifferentiated coach.

```text
               shared sovereign knowledge + rules core
 cards · rules · executable timing · formats · provenance · freshness
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     deck-coach     rule-consult   player2-agent
      recommends      explains       chooses
          │              │              │
       no ruling    no state write   human confirms
```

## Dependency direction

```text
apps / agent hosts
        ↓
mode contracts and P2-A protocol
        ↓
skill references, schemas, data, and validators
```

The portable `skill/` folder must not depend on a particular web app, private deployment path, model provider, or future reinforcement-learning framework.

It also must not depend on a third-party fan engine for its rules semantics.
Chronicle owns the common state/timing contract and executable conformance
cases. External simulators may inform the design or be compared against it, but
they do not define truth or availability. See
`SOVEREIGN_RULES_LAYER.md`.

The three no-build pages under `prototype/` are reference clients of these contracts, not alternate authorities. They use a manual copy/paste Agent bridge and in-tab memory only:

- `deck-coach` exports `deck-coach-session.v1`;
- `rule-consult` exports `rule-consultation.v1`;
- `p2a` exports `p2a-session.v1`.

Opening Rule Consult from P2-A is deliberately navigation-only. It cannot inspect or mutate the P2-A ledger.

## Mode boundaries

### `deck-coach`

Owns deck analysis and strategic education. It may consume general rules knowledge, but does not settle disputed rulings. Live move selection belongs to `player2-agent`.

### `rule-consult`

Owns rules research and explanation. It returns analysis, citations, confidence, and escalation. It never mutates the P2-A session state. A user may copy a conclusion into a human-confirmed state update, but that is a new human action.

### `player2-agent`

Owns Player 2 strategy. It can consult the other modes, but the final output is a proposed player decision. It must not convert a rules explanation into an automatic game event.

## Shared authority metadata

Every stateful P2-A artifact carries:

```text
mode: player2-agent
automation_level: P2-A
state_authority: user_confirmed
legality_authority: user_confirmed
p2s_enabled: false
```

Every knowledge-bearing output should carry, when relevant:

- card-data version;
- ruleset and tournament-rules version;
- format and region;
- ban/errata freshness date;
- source identifiers;
- model or policy version;
- confidence and unresolved assumptions.

## Information boundary

The acting Player 2 Agent may receive:

- all public game information;
- Player 2's own private information;
- public pre-game information such as Legends and an open decklist when applicable.

It must not receive Player 1's hidden hand, deck order, or other private information. A physical operator who knows both hands must still enter only the information Player 2 is entitled to use.

## State transition rule

A P2-A decision has three separate records:

1. `state_confirmed`: the human's description of the current state.
2. `action_proposed`: the Agent's strategic recommendation, explicitly unverified for legality and bound to the latest confirmed state's sequence number.
3. `action_confirmed`: the human accepts or rejects legality and physically resolves it.

The resulting position is not inferred. It becomes authoritative only through the next `state_confirmed` record.

This separation is an implementation invariant, not wording in a disclaimer.

## Future extensibility without P2-S implementation

P2-A uses free-form, human-authored public state summaries instead of a complete machine-resolvable game graph. A future adapter may introduce structured observations and legal-action masks, but no such adapter is loaded, called, or shipped now.

The only P2-S accommodation in current code is a negative capability flag (`p2s_enabled: false`) and validation that rejects engine-derived authority.
