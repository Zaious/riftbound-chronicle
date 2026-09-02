# Engine Capability Milestones

Status: accepted sequencing baseline

Date: 2026-09-02

This file names dependency milestones. It does not mark them implemented; the
completion checklist remains authoritative for delivery status.

## Foundation track

### E0 — Bounded timing/effect kernel (implemented)

Current four-state timing, Chain transitions, typed atomic effects, bounded
triggers/replacements/cleanup, engine-check integration, and behavior coverage.

### E1 — Choices, costs, and zone operations

Decision artifacts; Energy/Power and non-resource costs; look/reveal/search,
discard/banish/recycle/recall; open target groups; impossible-instruction rules.

### E2 — Card-play and object relationships

Full play lifecycle for cards/abilities/Hidden/Runes; attachments, Equipment,
Gear Units, token catalog, identity changes, last-known information, and linked
instruction grammar.

### E3 — Reactive and continuous semantics

Cross-object/delayed/counted triggers; duration expiry; continuous-effect
dependency/layers; complete replacement sequences and prevention allocation.

Each E milestone is delivered in smaller capability increments under ADR-0002;
this grouping is dependency order, not a request for one giant commit.

## Game-procedure track

### G1 — Showdown and Combat

Staging/opening/closing, attack declaration, attacker/defender designations,
legal defenders, damage assignment, Tank/Backline conflicts, simultaneous Deal,
and Combat cleanup.

Depends on the relevant E1/E2/E3 capabilities. Unlocks supported Combat
consultations and Match Analyst combat reconstruction.

### G2 — Battlefield control, Conquer, and Scoring

Contested/control transitions, hold/conquer procedures, points, scoring
replacement/trigger interactions, and multiplayer scoring order.

Depends on G1 where conquest follows Showdown/Combat and on scoring-related
effect capabilities.

### G3 — Victory and Terminal State

Victory Score, lead/tie requirements, simultaneous terminal events, Burn Out,
winner/draw/no-result reasons, deterministic terminal trace, and a reward
adapter that is explicitly downstream of the rules result.

G3 is the hard prerequisite for automated search/RL evaluation and complete
match-result validation. It is not a prerequisite for Deck Coach, Rule Consult,
or P2-A to provide bounded non-simulation value.

## R4/R5 relationship

- R4 Phase A candidate classification can begin after ADR-0003 and the relevant
  E capabilities.
- R4 Phase B complete enumeration waits for action-family generators and a
  completeness proof.
- R5-A deterministic runners, coverage/abstention metrics, and corpus tooling do
  not require Riot authorization.
- R5-B bounded local search waits for R4 and G3.
- R5-C P2-S/public simulation/RL remains outside the active roadmap until a
  separate authorization and product decision.
