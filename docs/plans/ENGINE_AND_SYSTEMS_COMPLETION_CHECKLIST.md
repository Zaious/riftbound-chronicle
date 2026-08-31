# Engine and Four-Systems Completion Checklist

Status: active implementation ledger

Baseline: Core Rules 2026-07-16; FAQ as of 2026-08-14

Last reconciled: 2026-09-01

This is the single completion ledger for Chronicle's sovereign rules engine and
four user-facing systems. A checked item means an implementation, contract, and
executable regression exist in the repository. A written design or prototype
alone does not count as implementation. A bounded checked item makes no claim
about mechanics outside the stated scope.

## 0. Delivery order

- [x] Define the four-system product boundaries and ownership rules.
- [x] Build the first Chronicle-owned timing and typed-effect kernel.
- [x] Publish this reconciled completion checklist.
- [ ] Establish the shared `engine-check.v1` result contract and runner.
- [ ] Integrate `engine-check.v1` into Rule Consult.
- [ ] Integrate `engine-check.v1` into Player 2 Agent P2-A.
- [ ] Integrate behavior coverage and verified lines into Deck Coach.
- [ ] Build and validate a bounded R3 card-program pack.
- [ ] Pass the R4 state-completeness and legal-action gates.
- [ ] Implement and route Match Analyst.

## 1. Shared evidence and source layer

- [x] Versioned source registry with `locale`, `region`, `document_class`,
  `status`, and `superseded_by`.
- [x] Official-source precedence and controlling-language policy.
- [x] Opt-in local English Core/Tournament Rules bootstrap.
- [x] Optional Simplified Chinese rules/FAQ/errata bootstrap group.
- [x] Ignored local PDF storage and download lock with hashes.
- [x] Page-addressable bilingual SQLite rules index.
- [x] Default masking of superseded sources.
- [x] Bundled card snapshot and errata overlay with provenance/freshness checks.
- [x] Format/region/set-pool environment registry for Deck Coach.
- [ ] Human-reviewed official-source refresh and baseline-versioning workflow.
- [ ] Cross-language clause alignment and disagreement reporting.
- [ ] Card-text-to-effect-program provenance manifest shared by all systems.

## 2. R1 — Timing, permissions, and Chain structure

- [x] Four-state model: Neutral/Showdown × Open/Closed.
- [x] Action/Reaction permission gates.
- [x] Priority and Focus ownership checks.
- [x] HOT/FEPR next-procedure classification.
- [x] Add a typed Pending Chain Item.
- [x] Finalize the oldest Pending Item.
- [x] Resolve/remove exactly the newest Finalized Item.
- [x] Unit/Gear/Add immediate-resolution classification.
- [x] Priority passing and all-player pass detection.
- [x] Focus movement/retention when a Chain empties.
- [x] Trigger/Add Focus-pass exceptions.
- [x] Optional-at-finalize trigger decision.
- [x] Chronological trigger batches and Turn Player/Turn Order controller blocks.
- [x] Effect-program binding for triggered items.
- [x] Deterministic state hashes, transition traces, and official locators.
- [x] Canonical fixtures and executable conformance cases.
- [ ] Full phase/turn state machine rather than caller-supplied phase facts.
- [ ] Complete Outstanding Task catalog and task-specific ordering rules.
- [ ] Complete Showdown and Combat procedure state, not only timing labels.
- [ ] Official conformance corpus covering every R1 clause and adverse ordering
  combination.

## 3. R2 — Typed effects and resolution

### Implemented atomic vocabulary

- [x] Draw when the known Main Deck contains enough cards.
- [x] Recycle one known object.
- [x] Move a board object between supported Base/Battlefield locations.
- [x] Add a typed Might modifier.
- [x] Deal and heal positive damage values.
- [x] Ready and exhaust supported board objects.
- [x] Add Energy or domain-labelled Power.
- [x] Kill supported Unit/Gear permanents; tokens cease to exist off-board.
- [x] Play explicitly identified Unit/Gear tokens with type-correct entry state.
- [x] Typed target snapshots and supported target revalidation.
- [x] Bounded linked `if_applied` instructions.
- [x] Atomic timing/effect resolution bridge with rollback.

### Implemented triggers, replacement, and cleanup slices

- [x] Typed self-death trigger capture and Pending scheduling.
- [x] Reflexive trigger emission with chronological batches.
- [x] Exact-event `prevent_event`, optional choice, and finite uses.
- [x] Recursive `replace_with` with once-per-event recursion protection.
- [x] Finite Damage Prevention Values and partial Deal semantics.
- [x] Core 370.1.b.1 `augment_with` (“same event plus”).
- [x] Bounded Core 375 token-entry/Temporary modifier inheritance.
- [x] Lethal-damage cleanup with repeated Core 322 passes.
- [x] One-descriptor simultaneous Kill prevention sequence.
- [x] Core 370.4 source-leaves-simultaneously behavior for that sequence.
- [x] Versioned cleanup decision artifact and atomic resubmission path.

### Effect vocabulary still required

- [ ] Generic choices: zero/one/up-to/exactly-N, divide, order, reveal
  selection, and affected-player decisions.
- [ ] Typed costs: Energy, Power, exhaust, sacrifice/kill, discard, banish,
  return, and alternative/additional costs.
- [ ] Full card-play lifecycle for Units, Gear, Spells, Runes, Hidden, and
  abilities; `play_token` is not a substitute.
- [ ] Look, reveal, search, shuffle, randomize, discard, and banish operations.
- [ ] Recall as its own non-Move action and correct destination semantics.
- [ ] Countering Chain Items and counter-prevention interactions.
- [ ] Attach, detach, Equip, Equipment, Gear Unit, Top-Most, and host changes.
- [ ] Buff/debuff objects and spend/remove/copy behavior beyond raw Might.
- [ ] Channel and Rune-specific entry, ready/exhaust, and zone behavior.
- [ ] Create/copy predefined tokens from a versioned token catalog.
- [ ] Score, conquer, hold, battlefield control, and Victory Score operations.
- [ ] Burn Out and its complete loss/continuation semantics.

### Conditions, targets, and instruction grammar still required

- [ ] Open-ended target choice and target groups.
- [ ] Location-relative targets such as “here” and “another location.”
- [ ] Last-known information and objects that change identity or zone.
- [ ] Conditions over Might, damage, tags, domains, types, counts, and events.
- [ ] General typed forms for “if,” “if you do,” “if this kills,” “then,”
  “then do this,” “for each,” “instead,” and “up to.”
- [ ] Impossible-instruction continuation beyond the bounded linked gate.
- [ ] Simultaneous multi-object Move, Deal, Recycle, Kill, and token creation.
- [ ] Player-targeted and uncontrolled-Battlefield replacement ordering.

### Continuous effects, triggers, and replacement still required

- [ ] Cross-object watchers and zone-dependent trigger eligibility.
- [ ] Delayed triggers and duration-bound trigger registration.
- [ ] First/Nth-time, once-per-turn, and per-object event counters.
- [ ] Instruction-level optional choices made during resolution.
- [ ] Complete continuous-effect dependency/layer system.
- [ ] Duration expiry for this turn, next event, while/source-zone, and cleanup.
- [ ] Multiple simultaneous replacement descriptors controlled by one player.
- [ ] Different-controller simultaneous replacement execution in Turn Order.
- [ ] Non-prevention replacement programs across simultaneous events.
- [ ] Complete Core 373.2 uninterrupted sequence graph.
- [ ] `All` prevention, duration, and allocation choices.
- [ ] General Core 375 inheritance beyond the token subset.

### Game procedures still required

- [ ] Complete normal Cleanup steps 1–10a.
- [ ] Special, Combat, and End-of-Turn Cleanup additions.
- [ ] Attack declaration, attacker/defender designations, and legal defenders.
- [ ] Combat damage assignment, Tank/Backline conflicts, and simultaneous Deal.
- [ ] Showdown staging, opening, action cycle, resolution, and closure.
- [ ] Battlefield Contested/control transitions.
- [ ] Conquer resolution, scoring, ties, and win determination.
- [ ] Complete turn start/main/ending phase transitions.
- [ ] Multi-player edge cases and Turn Order changes.

### Engine quality gates still required

- [ ] State schema covering every mechanic in the bounded R3 pack without prose
  escape hatches.
- [ ] Property/fuzz tests for rollback, determinism, ordering, and recursion.
- [ ] Golden official examples encoded as conformance fixtures.
- [ ] Differential tests against independent implementations where semantics
  overlap, without giving those engines authority.
- [ ] Version migration policy for state, program, trace, and decision schemas.
- [ ] Clause-level coverage manifest, not merely operation-name coverage.

## 4. R3 — Bounded card-program packs

- [ ] Select two to four linear Origins/Taiwan decks and their Battlefields.
- [ ] Freeze applicable card text, errata, ruleset, format, and region.
- [ ] Define a registry keyed by stable card/printing identity.
- [ ] Compile every relevant card clause into typed effects and conditions.
- [ ] Label each card `full`, `partial`, `unsupported`, or `stale`.
- [ ] Attach an official locator to every implemented clause.
- [ ] Add positive, negative, replacement, timing, and impossible-action tests
  for every implemented card.
- [ ] Add cross-card fixtures for every deck's core lines.
- [ ] Reconcile those lines with Deck Coach primers and expert review.
- [ ] Publish machine-readable pack coverage and abstention reasons.
- [ ] Require pack-level conformance before P2-A or Match Analyst may claim
  executable support for that environment.

## 5. R4 — Observation, legal actions, and replay reconstruction

- [ ] Run the state-completeness pre-check on real P2-A `public_state` samples.
- [ ] Define structured, perspective-safe observation schemas.
- [ ] Separate public, own-private, inferred, later-revealed, and unknown facts.
- [ ] Normalize complete and partial logs into stable source event ids.
- [ ] Reconstruct timing and supported effect state at every event.
- [ ] Enumerate timing-legal candidates from supported structured state.
- [ ] Filter candidates by targets, costs, and effect prerequisites.
- [ ] Explain every included/excluded action and its coverage.
- [ ] Abstain when the observation cannot support an unambiguous legal set.
- [ ] Prove Player 1 hidden information cannot enter Player 2's action set.
- [ ] Add official fixtures for legal and illegal response windows.
- [ ] Bind P2-A ranking to supported candidates without moving legality or
  physical-state authority away from the human.
- [ ] Measure confirmation latency/disagreement to detect rubber-stamping.

## 6. R5 — Evaluation, search, and learning research

- [ ] Deterministic batch runner for states, programs, decisions, and replays.
- [ ] Versioned replay corpus with train/eval separation and provenance.
- [ ] Clause-level engine coverage, unsupported-rate, and conformance metrics.
- [ ] Abstention metrics split by missing state, unsupported mechanic, source
  conflict, stale data, and decision requirement.
- [ ] Policy evaluation separating legality, strategy, and outcome quality.
- [ ] Model/Skill/version primer battles and blinded expert preference tests.
- [ ] Match-review correction loop into conformance fixtures.
- [ ] Search/MCTS/RL only after state ownership, legal actions, deterministic
  transitions, and Riot authorization are separately satisfied.
- [ ] P2-S remains excluded from public runtime until its written gate passes.

## 7. Shared `engine-check.v1` integration layer

- [ ] One versioned envelope for timing-only, effect-only, combined resolution,
  cleanup, and future legal-action checks.
- [ ] Component input/result hashes plus engine/rules versions.
- [ ] Distinct `supported`, `illegal`, `unsupported`, `decision_required`, and
  `invalid_input` outcomes with attributed causes.
- [ ] Precise coverage, rule locators, trace summary, assumptions, and missing
  information.
- [ ] Decision schema/id/options without embedding an authoritative choice.
- [ ] Rejection of complete-game or complete-legality overclaims.
- [ ] Dependency-free runner wrapping the existing pure engines.
- [ ] Schema, validator, CLI examples, fixtures, and off-cwd regressions.
- [ ] Optional raw state/trace so consumer artifacts can remain compact.
- [ ] Consumer projection rules for all four systems.

## 8. Deck Coach

### Implemented

- [x] Routed Skill mode and product boundary.
- [x] Deterministic input, profile, recommendation mask, primer, evaluation, and
  primer-battle pipeline.
- [x] Environment/region/set legality and recommendation-mask reasons.
- [x] Eight roles and eight-section primer contract.
- [x] Evidence tiers, confidence, provenance, and abstention checks.
- [x] Executable cases and seven-dimension evaluation.
- [x] Rift Atlas pasted-deck/URL provenance adapter.
- [x] Bilingual local demo with JSON/Markdown export and artifact import.

### Remaining

- [ ] Consume `engine-check.v1` for verified timing/effect examples.
- [ ] Rename card-name “resolution coverage” so it cannot be confused with
  rules-engine coverage.
- [ ] Consume the R3 card behavior coverage manifest.
- [ ] Validate core loops, lines, mulligan rationale, and mistakes against
  executable card programs where supported.
- [ ] Separate heuristic roles from expert-confirmed deck identity.
- [ ] Expand expert cases across decks, regions, levels, and stale data.
- [ ] Add blinded player/expert preference results to the eval suite.
- [ ] Expose unsupported interaction coverage in output and demo.

## 9. Rule Consult

### Implemented

- [x] Routed Skill mode and unofficial/non-binding boundary.
- [x] Versioned artifact, CLI, validation, and finalization flow.
- [x] Source registry, bilingual retrieval, precedence, freshness, and masking.
- [x] Facts, assumptions, citations, confidence, and escalation contract.
- [x] Manual import of a bounded `rules_core` timing summary.
- [x] Executable consultation cases and bilingual local demo.

### Remaining

- [ ] Consume `engine-check.v1` instead of timing-only `rules_core_check`.
- [ ] Run timing/effect/combined checks from one consultation command.
- [ ] Present engine trace beside official passages without treating it as
  authority.
- [ ] Render `decision_required` options neutrally.
- [ ] Separate source uncertainty from engine coverage uncertainty.
- [ ] Add effect/replacement/combat fixtures and expert rulings.
- [ ] Add an engine-check panel to demo and export.

## 10. Player 2 Agent

### Implemented

- [x] Routed P2-A mode and explicit P2-S negative capability.
- [x] Human-confirmed append-only session ledger.
- [x] Perspective boundary for public and Player 2 private information.
- [x] Separate confirmed-state, proposal, and confirmation events.
- [x] Manual import of a bounded `rules_core` timing summary.
- [x] Protocol validator, regressions, CLI, and bilingual local demo.

### Remaining

- [ ] Consume `engine-check.v1` for timing/effect/combined coverage.
- [ ] Differentiate verification burden by supported/unsupported/decision state.
- [ ] Build a structured observation adapter without inferring authority from
  prose.
- [ ] Use R4 legal candidates as a recommendation mask before ranking.
- [ ] Add a bounded policy/candidate ranker and expert scenario suite.
- [ ] Store opt-in sessions and measure confirmation latency/disagreement.
- [ ] Add effect coverage and decision-required UI to the demo.
- [ ] Keep every physical state transition human-confirmed in P2-A.

## 11. Match Analyst

### Implemented specification

- [x] Whole-Match boundary rather than Combat-only naming.
- [x] One normalized timeline with Review and Commentary projections.
- [x] Perspective, hidden-information, hindsight, and uncertainty requirements.
- [x] Review classifications and commentary levels.
- [x] Artifact outlines and activation gates.

### Remaining implementation

- [ ] Add `match-analysis.v1`, `match-review.v1`, and
  `match-commentary.v1` schemas.
- [ ] Build deterministic log/replay normalization with source-event ids.
- [ ] Bind normalized events to `engine-check.v1` and R4 reconstruction.
- [ ] Implement observed/inferred/unknown/hindsight-only ledger.
- [ ] Implement decision-point and turning-point extraction.
- [ ] Implement Review with mandatory unsupported abstention.
- [ ] Implement Commentary over the same confirmed timeline.
- [ ] Prove Review and Commentary agree on confirmed state.
- [ ] Add complete, partial, contradictory, and perspective-limited fixtures.
- [ ] Obtain expert review of the first bounded replay corpus.
- [ ] Add runner, evaluation suite, and bilingual demo.
- [ ] Re-check the applicable Riot product boundary.
- [ ] Route Match Analyst only after every activation gate passes.

## 12. UI, packaging, and release

- [x] Consistent bilingual shell for Deck Coach, Rule Consult, and P2-A.
- [x] Local-only no-build demos with manual Agent bridge.
- [x] Shared navigation among the three active systems.
- [x] Public repository excludes official PDFs and generated local index.
- [x] English, Traditional Chinese, and Korean README set.
- [x] CI and off-cwd portability checks for active scripts.
- [ ] Shared engine-check viewer across the three active demos.
- [ ] Match Analyst demo and four-system navigation.
- [ ] One bounded end-to-end example spanning Deck Coach → P2-A → Rule Consult
  → Match Analyst.
- [ ] Release report generated from this checklist and executable evidence.

## Definition of “engine connected to a system”

A system is not connected merely because its instructions mention the rules
core. It is connected only when all six conditions are checked:

- [ ] Its machine-readable artifact accepts `engine-check.v1`.
- [ ] Its runner can produce or import the check without hand-editing JSON.
- [ ] Its validator rejects malformed, overstated, or mismatched coverage.
- [ ] Its UI/output renders supported, unsupported, and decision-required states.
- [ ] Its regressions include one supported and one abstaining end-to-end case.
- [ ] It preserves its authority boundary after consuming the check.

Until these pass independently for a system, documentation must describe the
connection as partial or planned.
