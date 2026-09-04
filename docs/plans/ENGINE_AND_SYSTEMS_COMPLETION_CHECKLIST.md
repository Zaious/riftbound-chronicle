# Engine and Four-Systems Completion Checklist

Status: active implementation ledger

Baseline: Core Rules 2026-07-16; FAQ as of 2026-08-14

Last reconciled: 2026-09-02

This is the single completion ledger for Chronicle's sovereign rules engine and
four user-facing systems. A checked item means an implementation, contract, and
executable regression exist in the repository. A written design or prototype
alone does not count as implementation. A bounded checked item makes no claim
about mechanics outside the stated scope.

## Ownership labels

- **`[CLAUDE-READY]`** — bounded work with stable inputs, outputs, and acceptance
  tests. It can be handed to another AI without this conversation history.
- **`[CODEX-CONTEXT]`** — depends on the rules semantics, authority boundaries,
  schema history, or sequencing decisions developed in this thread. Codex
  should own the contract and final implementation.
- **`[JOINT]`** — Codex defines/finalizes the contract; Claude can implement a
  bounded subpackage, fixtures, data, documentation, or UI against it.

The label names the recommended implementation owner, not the only model
capable of doing the work. Prerequisites still apply. Completed items remain
unlabelled because ownership is relevant to remaining work.

## 0. Delivery order

- [x] Define the four-system product boundaries and ownership rules.
- [x] Build the first Chronicle-owned timing and typed-effect kernel.
- [x] Publish this reconciled completion checklist.
- [x] Establish the shared `engine-check.v1` result contract and runner.
- [x] Integrate `engine-check.v1` into Rule Consult artifact, CLI, validator,
  bilingual demo, and supported/abstaining regressions.
- [x] Integrate `engine-check.v1` into P2-A artifact, CLI, validator, calibrated
  verification flow, bilingual demo, and supported/abstaining regressions.
- [ ] `[JOINT]` Integrate behavior coverage and verified lines into Deck Coach.
- [ ] `[JOINT]` Build and validate a bounded R3 card-program pack.
- [ ] `[CODEX-CONTEXT]` Pass the R4 state-completeness and legal-action gates.
- [ ] `[JOINT]` Implement and route Match Analyst; routing remains
  `[CODEX-CONTEXT]`.

## 1. Shared evidence and source layer

Remaining source tooling is `[CLAUDE-READY]`; the card-program provenance
contract is `[JOINT]` because it must match R3 and `engine-check.v1`.

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
- [x] Read-only source refresh planner/capture/reporter with ignored output,
  registry immutability, public-DNS/redirect guards, and offline analysis.
- [ ] Human-reviewed official-source refresh and baseline-versioning workflow.
- [ ] Cross-language clause alignment and disagreement reporting.
- [ ] Card-text-to-effect-program provenance manifest shared by all systems.
- [ ] `[CLAUDE-READY; due 2026-10-23]` Re-run Tier 2 verification after the
  Radiance release, review all 53 Global Vendetta rows currently forecast to
  become stale, and update each row's evidence date or abstention status.

## 2. R1 — Timing, permissions, and Chain structure

Remaining engine semantics are `[CODEX-CONTEXT]`. Once a transition contract is
frozen, fixture expansion and official-example encoding become
`[CLAUDE-READY]`.

- [x] Accept ADR-0002 schema/ruleset/capability/implementation version policy
  and explicit migration contract.

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

Default ownership: `[JOINT]`. Codex specifies the semantic/state contract and
Claude may implement one bounded operation plus tests at a time.

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

Default ownership: `[CODEX-CONTEXT]`; these forms affect every later card
program and cannot be safely inferred from isolated examples.

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

Default ownership: `[CODEX-CONTEXT]`. Fixture/data expansion after a contract is
accepted is `[CLAUDE-READY]`.

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

Default ownership: `[CODEX-CONTEXT]`; independent UI or fixture work after each
procedure contract is `[CLAUDE-READY]`.

Dependency milestones are defined in
[ENGINE_CAPABILITY_MILESTONES.md](ENGINE_CAPABILITY_MILESTONES.md):

- [ ] **G1 — Showdown and Combat.** Complete the supported Showdown/Combat
  procedure and its state/trace contract.
- [ ] **G2 — Battlefield control, Conquer, and Scoring.** Complete control,
  point, and scoring semantics.
- [ ] **G3 — Victory and Terminal State.** Complete Victory Score, ties,
  simultaneous terminal events, Burn Out, terminal reasons, and reward adapter.

- [ ] Complete normal Cleanup steps 1–10a.
- [ ] Special, Combat, and End-of-Turn Cleanup additions.
- [ ] Attack declaration, attacker/defender designations, and legal defenders.
- [ ] Combat damage assignment, Tank/Backline conflicts, and simultaneous Deal.
- [ ] Showdown staging, opening, action cycle, resolution, and closure.
- [ ] Battlefield Contested/control transitions.
- [ ] Implement the Conquer/point/control components required by G2.
- [ ] Implement terminal detection, ties, Burn Out, and reward adapter required
  by G3.
- [ ] Complete turn start/main/ending phase transitions.
- [ ] Multi-player edge cases and Turn Order changes.

### Engine quality gates still required

Default ownership: `[JOINT]`. Test harnesses, golden fixture encoding, and
differential adapters are `[CLAUDE-READY]`; coverage definitions and version
migrations are `[CODEX-CONTEXT]`.

- [ ] State schema covering every mechanic in the bounded R3 pack without prose
  escape hatches.
- [ ] Property/fuzz tests for rollback, determinism, ordering, and recursion.
- [ ] Golden official examples encoded as conformance fixtures.
- [ ] Differential tests against independent implementations where semantics
  overlap, without giving those engines authority.
- [x] Version migration policy for state, program, trace, and decision schemas
  accepted in ADR-0002; migration tooling remains to implement.
- [x] Clause-level card behavior coverage manifest, not merely operation-name
  coverage.
- [x] Implement a capability manifest that identifies exact supported
  operations, procedures, clauses, exclusions, and implementation identity.

## 4. R3 — Bounded card-program packs

Default ownership: `[JOINT]`. ADR-0004 fixes global card semantics plus regional
overlays. Codex selects the first pack and accepts coverage; Claude can
collect/normalize card clauses and implement assigned cards.

- [x] Accept the global-core card-program plus regional-overlay architecture.
- [x] Select Annie and Master Yi Proving Grounds as Wave A; defer Lux/Garen to
  Wave B of the same global core pack.
- [ ] Verify the candidate fixed decklists against a physical Proving Grounds
  product or a second independent source.
- [ ] Define the first `taiwan-origins-v1` release/legality/localization overlay.
- [ ] Freeze applicable card text, errata, ruleset, global pack, and overlay.
- [x] Define `card-behavior-manifest.v1` using canonical rules identity,
  current-text hash, printing provenance, clause status, programs, and tests.
- [ ] Compile every relevant card clause into typed effects and conditions.
- [x] Label every selected Wave-A card and clause `unsupported` or `stale` in
  the R3-A0 draft; `full`/`partial` remain recommendations until tested programs exist.
- [ ] Attach an official locator to every implemented clause.
- [ ] Add positive, negative, replacement, timing, and impossible-action tests
  for every implemented card.
- [ ] Add cross-card fixtures for every deck's core lines.
- [ ] Reconcile those lines with Deck Coach primers and expert review.
- [ ] Publish machine-readable pack coverage and abstention reasons.
- [ ] Require pack-level conformance before P2-A or Match Analyst may claim
  executable support for that environment.

## 5. R4 — Observation, legal actions, and replay reconstruction

Default ownership: `[CODEX-CONTEXT]`. After schemas are frozen, corpus
normalization and adversarial fixtures become `[CLAUDE-READY]`.

- [x] Accept ADR-0003: structured observation is prerequisite; Phase A
  classifies user-supplied candidates; Phase B enumeration requires a
  completeness proof.

- [ ] Run the state-completeness pre-check on real P2-A `public_state` samples.
- [x] Define structured, perspective-safe observation schemas for Phase A.
- [x] Separate public, own-private, inferred, later-revealed, and unknown facts.
- [ ] Normalize complete and partial logs into stable source event ids.
- [ ] Reconstruct timing and supported effect state at every event.
- [x] Phase A: classify user-supplied candidates from supported structured state.
- [ ] Filter candidates by targets, costs, and effect prerequisites.
- [ ] Explain every included/excluded action and its coverage.
- [x] Abstain when the observation cannot support an unambiguous candidate verdict;
  Phase A still never claims a complete legal set.
- [ ] Phase B: generate candidates only for covered action families and keep
  `complete_action_set: false` without a machine-checkable completeness proof.
- [x] Prove Player 1 hidden information cannot enter Player 2's Phase-A query/results.
- [x] Add sourced fixtures for legal and illegal response windows within R1 coverage.
- [ ] Bind P2-A ranking to supported candidates without moving legality or
  physical-state authority away from the human.
- [ ] Measure confirmation latency/disagreement to detect rubber-stamping.

## 6. R5 — Evaluation, search, and learning research

Default ownership: `[JOINT]`. Deterministic runners, metrics, and corpus tooling
are `[CLAUDE-READY]`; policy objectives, information sets, and authorization
gates remain `[CODEX-CONTEXT]`.

- [ ] **R5-A:** deterministic batch runner for states, programs, decisions, and
  replays.
- [ ] **R5-A:** versioned replay corpus with train/eval separation and provenance.
- [x] **R5-A:** exact-locator fixture-exercise, unsupported-rate, and fixture-conformance
  metrics. These are not correctness or whole-rule-family coverage scores.
- [x] **R5-A:** abstention metrics split by missing state, unsupported mechanic, source
  conflict, stale data, and decision requirement.
- [ ] **R5-A:** policy evaluation separating legality, strategy, and outcome quality.
- [ ] **R5-A:** model/Skill/version primer battles and blinded expert preference tests.
- [ ] **R5-A:** Match-review correction loop into conformance fixtures.
- [ ] **R5-B:** bounded local search only after state ownership, R4 legal
  actions, deterministic transitions, and G3 terminal-state conformance.
- [ ] **R5-C:** P2-S/public simulation/RL remains outside the active roadmap
  until a separate authorization and product decision.

## 7. Shared `engine-check.v1` integration layer

- [x] One versioned envelope for timing-only, effect-only, combined resolution,
  cleanup, and bounded Phase-A legal-action checks.
- [x] Component input/result hashes plus engine/rules versions.
- [x] Distinct `supported`, `illegal`, `unsupported`, `decision_required`, and
  `invalid_input` outcomes with attributed causes.
- [x] Precise coverage, rule locators, trace summary, assumptions, and missing
  information.
- [x] Decision schema/id/options without embedding an authoritative choice.
- [x] Rejection of complete-game or complete-legality overclaims.
- [x] Dependency-free runner wrapping the existing pure engines.
- [x] Schema, validator, CLI examples, fixtures, and off-cwd regressions.
- [x] Optional raw state/trace so consumer artifacts can remain compact.
- [x] Consumer projection rules for all four systems.

## 8. Deck Coach

### Implemented

- [x] Routed Skill mode and product boundary.
- [x] Deterministic input, profile, recommendation mask, primer, evaluation, and
  primer-battle pipeline.
- [x] Environment/region/set legality and recommendation-mask reasons.
- [x] Eight roles and eight-section primer contract.
- [x] Evidence tiers, confidence, provenance, and abstention checks.
- [x] Executable cases and seven-dimension evaluation.
- [x] Format-scoped 2v2-only ban and collection-only recommendation-mask cases.
- [x] Optional card behavior manifest projection with copy-weighted clause
  coverage and automatic current-text staleness.
- [x] Bilingual behavior-coverage demo for all availability statuses and copy
  counts, with generated non-production fixtures and strategy-boundary guards.
- [x] Rift Atlas pasted-deck/URL provenance adapter.
- [x] Bilingual local demo with JSON/Markdown export and artifact import.

### Remaining

Default ownership: `[JOINT]`. Pipeline/evaluation/UI work is
`[CLAUDE-READY]` after Codex defines the behavior-coverage contract.

- [x] Consume `engine-check.v1` for verified timing/effect examples as
  rules-consistency evidence only; first wiring does not produce checks.
- [x] Rename `card_resolution_coverage` to `card_lookup_coverage` and state that
  it measures card-database name matching, not rules-engine coverage.
- [ ] `[JOINT]` Rename the separate top-level Deck Profile `resolution` block to
  an unambiguous lookup/matching term through an explicit `deck-profile.v1`
  compatibility or migration decision.
- [x] Consume a compatible active R3 card behavior manifest when supplied;
  default to explicitly unavailable until a production pack exists.
- [ ] Validate core loops, lines, mulligan rationale, and mistakes against
  executable card programs where supported.
- [ ] Separate heuristic roles from expert-confirmed deck identity.
- [ ] Expand expert cases across decks, regions, levels, and stale data.
- [ ] Add blinded player/expert preference results to the eval suite.
- [x] Expose unsupported/stale/uncovered behavior counts in output and demo
  without turning them into strategy claims.

## 9. Rule Consult

### Implemented

- [x] Routed Skill mode and unofficial/non-binding boundary.
- [x] Versioned artifact, CLI, validation, and finalization flow.
- [x] Source registry, bilingual retrieval, precedence, freshness, and masking.
- [x] Facts, assumptions, citations, confidence, and escalation contract.
- [x] Manual import of a bounded `rules_core` timing summary.
- [x] `engine_checks` artifact array, validator, import CLI, duplicate/overclaim
  guards, and legacy `core-check` normalization to `engine-check.v1`.
- [x] Executable consultation cases and bilingual local demo.

### Remaining

Default ownership: `[CODEX-CONTEXT]` for artifact migration and authority
semantics; fixtures and the engine-check viewer are `[CLAUDE-READY]` after that
migration lands.

- [ ] Run timing/effect/combined checks from one consultation command.
- [x] Present engine trace beside official passages without treating it as
  authority.
- [x] Render `decision_required` options neutrally in a read-only viewer.
- [x] Separate source uncertainty from engine coverage uncertainty.
- [x] Add sourced effect-layer and replacement-effect consultation fixtures.
- [ ] Add supported Combat-engine consultation fixtures and expert rulings;
  current source-only Combat questions do not satisfy this item.
- [x] Add an engine-check panel to demo and export.

## 10. Player 2 Agent

### Implemented

- [x] Routed P2-A mode and explicit P2-S negative capability.
- [x] Human-confirmed append-only session ledger.
- [x] Perspective boundary for public and Player 2 private information.
- [x] Separate confirmed-state, proposal, and confirmation events.
- [x] Manual import of a bounded `rules_core` timing summary.
- [x] `engine_checks` proposal evidence, outcome-derived verification burden,
  raw-result rejection, CLI import, and legacy raw-core normalization.
- [x] Bilingual read-only engine-check panel with all five verification states,
  documented human override, and post-confirmation snapshot requirement.
- [x] Protocol validator, regressions, CLI, and bilingual local demo.

### Remaining

Default ownership: `[CODEX-CONTEXT]` for observation, authority, candidate-mask,
and confirmation semantics; demo/UI work is `[CLAUDE-READY]` afterward.

- [ ] Build a structured observation adapter without inferring authority from
  prose.
- [ ] Use R4 legal candidates as a recommendation mask before ranking.
- [ ] Add a bounded policy/candidate ranker and expert scenario suite.
- [ ] Store opt-in sessions and measure confirmation latency/disagreement.
- [x] Add effect coverage and decision-required UI to the demo.
- [ ] Keep every physical state transition human-confirmed in P2-A.

## 11. Match Analyst

### Implemented specification

- [x] Whole-Match boundary rather than Combat-only naming.
- [x] One normalized timeline with Review and Commentary projections.
- [x] Perspective, hidden-information, hindsight, and uncertainty requirements.
- [x] Review classifications and commentary levels.
- [x] Artifact outlines and activation gates.

### Remaining implementation

Default ownership: `[JOINT]`. Codex owns normalization/reconstruction contracts,
review classifications, and activation. Claude may implement frozen schemas,
fixtures, projection formatting, and the demo.

- [ ] Add `match-analysis.v1`, `match-review.v1`, and
  `match-commentary.v1` schemas.
- [ ] Build deterministic log/replay normalization with source-event ids.
- [ ] Bind normalized events to `engine-check.v1` and R4 reconstruction.
- [ ] Implement observed/inferred/unknown/hindsight-only ledger.
- [ ] Implement decision-point and turning-point extraction.
- [ ] Implement Review with mandatory unsupported abstention.
- [ ] Implement Commentary over the same confirmed timeline.
- [ ] Prove Review and Commentary agree on confirmed state.
- [x] Add complete, partial, contradictory, and perspective-limited fixtures
  with independently re-derived contradiction/redaction boundaries.
- [ ] Obtain expert review of the first bounded replay corpus.
- [ ] Add runner, evaluation suite, and bilingual demo.
- [ ] Re-check the applicable Riot product boundary.
- [ ] Route Match Analyst only after every activation gate passes.

## 12. UI, packaging, and release

- [x] Consistent bilingual shell for Deck Coach, Rule Consult, and P2-A.
- [x] Local-only no-build demos with manual Agent bridge.
- [x] Shared navigation among the three active systems.
- [x] zh-Hant visible-copy coverage gate with explicit intentional-English
  allowlist and runtime-derived numbered-heading fallback.
- [x] Public repository excludes official PDFs and generated local index.
- [x] English, Traditional Chinese, and Korean README set.
- [x] CI and off-cwd portability checks for active scripts.
- [x] Three-language README connection tables with an artifact-derived CI gate
  that rejects both overstatement and understatement.
- [x] Shared engine-check viewer across the three active demos.
- [ ] Match Analyst demo and four-system navigation.
- [x] `[JOINT]` After each active system satisfies the six connection conditions,
  update English, Traditional Chinese, and Korean READMEs from “partial/planned”
  to the exact implemented connection scope.
- [x] `[CLAUDE-READY after the first migration]` Extend documentation CI to
  reject README connection claims that diverge from the system artifacts; the
  existing routed-mode sync check is not sufficient.
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

### Current connection audit

| System | Conditions passed | Status |
| --- | ---: | --- |
| Rule Consult | 6 / 6 | Connected to `engine-check.v1`; official sources remain authoritative |
| Deck Coach | 6 / 6 | Connected consume-only; engine evidence remains rules consistency, never strategy quality |
| Player 2 Agent P2-A | 6 / 6 | Connected with calibrated human verification; state and legality remain user-confirmed |
| Match Analyst | 0 / 6 | Not implemented or routed |

## 13. Delegation work packages

These packages translate the labels above into tasks that can be handed to
Claude without relying on the full conversation.

### Shared-working-tree protocol

Chronicle currently uses one shared working tree and one local `main`; therefore
delegated work uses a **no-commit handoff**, not an unpushed commit:

1. Codex confirms the working tree and records any pre-existing user changes.
2. Codex and Claude work serially, not concurrently, inside the delegated
   package's allowed files.
3. Claude does not stage, commit, push, reset, rebase, merge, or update the
   checklist.
4. Claude runs the package acceptance commands and returns their output plus
   `git diff -- <allowed paths>` and `git status --short`.
5. Claude stops if another process changes an allowed file or if unrelated
   uncommitted changes make attribution ambiguous.
6. Codex reviews the exact allowed-path diff, runs focused and complete suites,
   stages only accepted files, commits, updates this ledger, and pushes.

A feature branch/worktree may replace this protocol only after it has actually
been created and its base/ref recorded in the handoff. Merely saying “do not
push” does not isolate a commit on shared `main`.

### Ready to give Claude now

| ID | Package | Allowed scope | Acceptance evidence |
| --- | --- | --- | --- |
| C-01 — completed 2026-09-01 | Rename Deck Coach `card_resolution_coverage` to an unambiguous card-name/data-resolution term | Deck Coach pipeline, Rift Atlas bridge, tests, prototype labels, docs; no schema or rules-engine semantic change | Existing Deck Coach suite plus compatibility test; current field is internal, not schema-bound |
| C-02 — completed 2026-09-01 | Expand `engine-check.v1` CLI examples and fixtures | Examples/fixtures/tests only; no schema vocabulary or outcome changes | Document-derived executable commands, failure surface, links, and off-cwd pass |
| C-04 — completed 2026-09-01 | Encode additional existing official timing examples as R1 fixtures | Data/tests only, using already-supported transitions | Seven sourced cases plus baseline-linked provenance gate |
| C-05 — completed 2026-09-01 | Add property-style determinism and rollback tests for currently supported effect programs | Tests only; do not add mechanics or alter expected semantics | 240 generated programs across commit/reject/abstain paths plus cross-process hashes |
| C-06 — completed 2026-09-01 | Build source-registry refresh diff/report tooling | Read-only fetch/diff proposal; never auto-promote or overwrite baseline; reports stay under `skill/.local/refresh-reports/` | Offline fixtures, immutable registry, path guard, public DNS/redirect guard, no analysis socket |
| C-07 — completed 2026-09-01 | Expand Deck Coach expert/eval cases using existing contracts | Data, evidence ledger, and tests; no new scoring dimensions | 2v2-only ban and collection-only constraints, weak-primer discrimination, README count gate |
| C-08 — completed 2026-09-01 | Prepare Match Analyst example logs and uncertainty fixtures | Fixtures/docs only; no claim that the system is routed or implemented | Complete/partial/contradictory/perspective-safe fixtures with re-derived boundaries |
| C-09 — completed 2026-09-03 | Implement ADR-0002 capability-manifest schema, validator, fixtures, and engine-check binding | ADR-0002 accepted; do not change existing schema semantics | Exact capability/exclusion/build identity, stale/mismatch tests, off-cwd CLI |
| C-10 — completed 2026-09-03 | Implement ADR-0003 observation/action-query/result schemas and Phase-A adversarial fixtures | ADR-0003 accepted; no Phase-B completeness claim | Five candidate verdicts, perspective boundary, missing-fact abstention, deterministic ids |
| C-11 — completed 2026-09-03 | Build R5-A coverage and abstention report over existing fixtures | ADR-0002 capability vocabulary accepted | Deterministic report only; no search, policy-strength, or P2-S claim |
| C-12 — completed 2026-09-03 | Execute R3-A0 Annie/Master Yi clause inventory | Selection record accepted; no engine changes allowed | Verify current text/errata, stable clause ids, draft unsupported/stale labels plus non-authoritative future recommendations, source ledger; no production activation |

Former C-03 is intentionally moved to D-00. A schema-only viewer would be a
fixture harness, not evidence that any demo is connected; Rule Consult's first
real artifact migration should establish the presentation semantics first.

### Give Claude only after Codex lands a prerequisite contract

| ID | Package | Prerequisite owned by Codex | Claude deliverable |
| --- | --- | --- | --- |
| D-00 — completed 2026-09-01 | Reusable read-only engine-check viewer core | X-01 Rule Consult artifact migration and its source-vs-engine presentation rules — satisfied 2026-09-01 | Five outcomes, bilingual fail-closed renderer, authority/coverage display, no choices or mutation |
| D-01 — completed 2026-09-01 | Rule Consult engine-check panel and prototype | Rule Consult artifact/schema migration — satisfied 2026-09-01 | Bilingual rendering, fixture attach/export, confidence independence, UI regression |
| D-02 — completed 2026-09-01 | P2-A engine-check panel and verification-state UI | P2-A event/schema and verification-burden migration — satisfied 2026-09-01 | Bilingual shared viewer, five verification states, raw-result refusal, documented overrides, prototype regression |
| D-03 — completed 2026-09-02 | Deck behavior coverage display and primer evidence | R3 behavior-coverage manifest — contract/pipeline satisfied; production pack absent | Four status explanations, five copy counts, generated fixtures, bilingual display, strategy-boundary regressions |
| D-04 | Per-card R3 effect programs | Frozen pack, token registry, condition/choice contracts | Assigned card programs, clause locators, positive/negative tests |
| D-05 | Legal-action and perspective adversarial corpus | R4 observation/legal-action schemas | Hidden-info, missing-state, illegal-window, abstention fixtures |
| D-06 | Match Analyst schemas/runner projections | Normalized timeline and engine-binding contracts | Schema implementation, formatter, fixtures, no router activation |
| D-07 | Fourth demo and navigation | Match Analyst gates satisfied except final activation review | Bilingual demo matching the shared visual shell |

### Keep with Codex because this thread context matters

| ID | Work | Why context-sensitive |
| --- | --- | --- |
| X-01 — completed 2026-09-01 | Rule Consult migration from `rules_core_check` to `engine-check.v1` | Preserves source authority, consultation confidence, legacy reads, and compatibility |
| X-02 — completed 2026-09-01 | P2-A migration to `engine-check.v1` | Preserves human legality/state authority, rejects raw engine state, and calibrates verification without automation creep |
| X-03 — completed 2026-09-01 | Deck behavior-coverage contract | Separates card lookup, current-text clause programs, unsupported mechanics, tests, and strategy evidence |
| X-04 — governance completed 2026-09-02 | R1/R2 semantic expansion and schema versioning | ADR-0002 fixes version axes, composition, choices, feature acceptance, and migrations; mechanic implementations remain open |
| X-05 — selection completed 2026-09-03 | R3 pack selection and acceptance gate | ADR-0004 plus R3 selection fix Annie/Master Yi Wave A and Lux/Garen Wave B; physical list verification and pack activation remain open |
| X-06 — architecture completed 2026-09-02 | R4 observation and legal-action architecture | ADR-0003 fixes Phase A/B, information sets, completeness, hidden-data safety, and abstention |
| X-07 | Match Analyst normalization/review contract and router activation | Must keep Review/Commentary consistent and satisfy all gates |
| X-08 | Riot authorization interpretation and P2-S boundary | Product authority cannot be inferred from an isolated coding task |

## Claude handoff template

Every delegated package should include:

```text
Package ID and objective:
Allowed files/directories:
Files that must not change:
Frozen schemas/contracts to consume:
Required fixtures and acceptance commands:
Authority/compliance boundary:
Stop and report if:
  - a schema/version/outcome vocabulary must change;
  - official text conflicts with the frozen contract;
  - the task needs an unsupported engine mechanic;
  - unrelated or concurrent changes overlap the allowed files.
Do not stage, commit, push, reset, rebase, merge, or mark checklist items
complete. Return focused allowed-path diffs and acceptance output to Codex.
```

Codex reviews the diff, reruns the complete suite, decides whether the package
satisfies its checklist item, updates this ledger, and performs the final push.
