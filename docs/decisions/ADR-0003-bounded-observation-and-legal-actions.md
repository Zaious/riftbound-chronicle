# ADR-0003 — Legal-action claims require bounded structured observations

Status: accepted

Date: 2026-09-02

Applies to: R4, P2-A candidate filtering, Match Analyst reconstruction, and the
future `legal_action` engine-check kind

## Context

P2-A currently receives a human-written public-state summary. Published legal
action systems normally enumerate from a complete simulator state. Treating a
prose summary as if it were complete would create the most dangerous possible
output: a confident list called “legal actions” that omitted actions the summary
did not mention.

Observation construction is therefore a prerequisite of legal-action work, not
background infrastructure that can be deferred until after the visible feature.

## Decision

R4 has two candidate-source modes and ships them in order.

### Phase A — user-supplied candidates

The caller supplies candidate actions. R4 classifies each independently within
the pinned capability set:

- `legal` — every required supported check passes;
- `illegal` — a supported rule rejects it;
- `indeterminate` — required facts are absent or ambiguous;
- `unsupported` — required engine semantics are not implemented;
- `decision_required` — an identified player/controller choice must be supplied
  before retry.

This phase never claims it found every action. It is useful immediately as a
recommendation mask for P2-A and as a response-window audit for Match Analyst.

### Phase B — engine-enumerated candidates

The engine may generate candidates only for action families whose generator,
costs, targets, timing, information boundary, and effect prerequisites all have
capability coverage. The result carries `complete_action_set: false` unless a
machine-checkable completeness proof covers every action family applicable to
that snapshot.

No consumer may turn “all generated candidates were checked” into “all legal
actions were generated.”

Phase B is an architecture decision, not a public-runtime authorization. Before
shipping it, re-check the applicable Riot product policy and preserve P2-A's
human legality authority; if that boundary disallows enumeration, Phase A
remains the active product surface.

## Observation contract

A future `observation.v1` must bind:

- perspective (`player1`, `player2`, `public_observer`, or
  `omniscient_replay`);
- source event/state sequence and component state hashes;
- confirmed public facts;
- perspective-owned private facts;
- inferred, later-revealed, unknown, and contradictory facts as separate sets;
- ruleset, format, region, card-data version, and capability set;
- completeness by field group, not one global boolean;
- provenance for every machine-structured fact.

Missing facts stay missing. A normalizer may propose a structured value from
prose, but it remains inferred until the human confirms it.

## Query and result contract

A future `action-query.v1` binds the observation hash, candidate-source mode,
acting player, requested action families, and supplied candidates. A future
`legal-action-result.v1` returns:

- one verdict per candidate;
- included/excluded/indeterminate reason codes;
- required capabilities and official locators;
- missing information and decisions;
- whether enumeration was attempted;
- `complete_action_set` plus the proof scope when true;
- deterministic query/result hashes.

The shared `engine-check.v1` may wrap the result as `legal_action_v1`; it does
not replace the detailed per-candidate artifact.

## Perspective and authority

- Player 2 queries cannot contain Player 1 private facts, including facts later
  revealed but unavailable at decision time.
- A candidate's observation hash and P2-A `state_seq` must match the confirmed
  state on which the recommendation was based.
- P2-A may rank only candidates whose verdict is usable for the intended scope;
  `indeterminate`, `unsupported`, and `decision_required` remain visible.
- The service is a bounded consistency checker. P2-A legality and physical state
  remain user-confirmed; Rule Consult's official sources remain authoritative.

## Completeness preflight

Before implementing Phase B, run the planned corpus check on real or synthetic
P2-A summaries. Measure which required observation fields can be extracted
unambiguously. If most summaries fail, improve the state-capture questions; do
not weaken completeness requirements to make enumeration appear successful.

## Acceptance gates

- complete and incomplete observation fixtures;
- hidden-information and hindsight adversarial fixtures;
- legal, illegal, indeterminate, unsupported, and decision-required candidates;
- deterministic ordering and hashes;
- explanation for every candidate outcome;
- an injected omitted-action-family test that makes any false
  `complete_action_set: true` fail;
- P2-A integration that preserves its human authority and verification ladder;
- Match Analyst integration that never converts an unknown window into a
  misplay.

## Consequences

Claude can implement observation/query/result schemas, fixtures, a Phase-A
classifier, and adversarial tests against this decision. Phase B remains gated
by actual action-family generators and completeness evidence.

## Rejected alternatives

- **Enumerate directly from free-form P2-A prose:** completeness cannot be
  established.
- **Return only legal/illegal:** conflates missing facts with unsupported rules.
- **Assume the generated list is complete:** omission becomes invisible.
- **Use omniscient post-game state for player decisions:** creates hidden-info
  and hindsight leakage.
