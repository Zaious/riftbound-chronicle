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
- [x] Full phase/turn state machine rather than caller-supplied phase facts.
  (C-38: setup → awaken → beginning → channel → draw → main → ending →
  the next player's turn as `turn_cycle.py` procedures with typed
  `turn_progress`, a Cleanup outstanding at every transition (319.2) and
  no discretionary action during 315; the First Turn Process read from the
  Mode of Play or explicit facts. Setup itself and the Match mode stay
  unsupported.)
- [ ] Complete Outstanding Task catalog and task-specific ordering rules.
  (C-38/C-39: `cleanup` and `scoring_step` tasks, the Scoring task waiting
  for the Beginning Step's chain, `run_cleanup` consuming the first
  Cleanup task; a general catalog remains.)
- [ ] Complete Showdown and Combat procedure state, not only timing labels.
  (C-26/C-30: one `combat` record on the timing state — staged, open,
  showdown_closed, damage_assigned, damage_dealt, cleanup_done,
  result_determined — plus `showdown.battlefield` and Focus passes that
  close a Combat Showdown; `next_procedure` reports `combat_step_pending`.
  C-33/C-34: `control_resolved`, `showdown.closing`, `staged_showdowns`;
  a Non-Combat Showdown every player passed reports
  `control_resolution_pending`.)
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
- [x] Permanent entry procedure: Units enter exhausted at the location chosen
  at play, Gear ready at the Base, new identity, not a Move (C-19; Core 359.2,
  143.4, 446.2).
- [x] Battlefield targets whose criteria-found affected objects are not
  targets; "all units at battlefields" targets nothing (C-20; Core 355.10.b/d).
- [x] Bonus Damage as a property of the Deal action: summed once from active
  sources, per affected object, before Prevent (C-20; Core 713–715, 437.1.a.1).
- [x] Discard from hand by the discarding player's private card_selection, as
  many as possible (C-22; Core 422).
- [x] Deflect as a mandatory any-domain Power additional cost, paid by the
  player's resource_allocation (C-23; Core 809, 356.2.a.2).
- [x] Granted one-turn, one-use replacement bound to an object's identity, and
  heal-all-damage (C-24; Core 370, 355.10.c, 124).

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
- [x] Play triggers on play completion and Move triggers on completed Moves,
  scheduled as chronological batches with trigger_order decisions (C-19, C-22;
  Core 419.4.a, 383.2.c).
- [x] Entry-state replacements: an object's own "I enter ready" and a this-turn
  effect over the controller's played units; conflicting results require the
  controller's replacement_order decision (C-21; Core 369.3).
- [x] Conditional passives evaluated on read (`effective_might`,
  `runes_at_least` over board runes), no dependency ordering (C-21; Core 364.3).
- [x] Ending Step trigger scheduling and Expiration Step (heal all, simultaneous
  this-turn expiry, empty pools) as two refusable procedures (C-21; Core 317).
- [x] Granted replacement variant next to source-backed ones, pruned on use,
  expiry, identity change, or the target leaving the board (C-24; ADR-0007 §12).

### Effect vocabulary still required

Default ownership: `[JOINT]`. Codex specifies the semantic/state contract and
Claude may implement one bounded operation plus tests at a time.

- [x] Generic choices: zero/one/up-to/exactly-N, divide, order, reveal
  selection, and affected-player decisions.
  (C-40, ADR-0011 §1–2: one typed `choice` specification — selection_kind,
  count, source, chooser, visibility, identity binding, enumerable cap — over
  the decision envelope, with `mode_selection` by stable option id and
  `card_ordering` for permutations; a private source is never listed in an
  engine result or check. Divide-among-targets and per-player simultaneous
  choices stay open: `each_player_choice` and `distinct_per_turn_choice` are
  declared unsupported.)
- [x] Typed costs: Energy, Power, exhaust, sacrifice/kill, discard, banish,
  return, and alternative/additional costs.
  (C-15: Energy, Power, exhaust, kill and mandatory/optional additional costs
  inside an atomic play transaction with receipts; C-23: any-domain Power
  (`power_any`) for Deflect; C-42, ADR-0011 §4: discard, recycle-from-trash,
  kill_this, recall_self and banish_self, [Repeat] as an optional additional
  cost, restricted Add resources, and cost modification as typed input with
  provenance; C-44, ADR-0012 §1: `cost_override` for "ignoring its base cost"
  and Flow-style replacements. XP, Buff and Empower costs are typed and
  refused as `xp_buff_costs`; the *sources* of cost modifications stay P4.)
- [x] Full card-play lifecycle for Units, Gear, Spells, Runes, Hidden, and
  abilities; `play_token` is not a substitute.
  (C-19: Units and Gear resolve by the permanent entry procedure with the
  location chosen at play and the open-Battlefield permission, 355.2; play
  triggers fire on play completion, 419.4.a; Spells since C-15, Runes via
  channel since C-16; C-42: activated abilities are chain items of kind
  `ability` with their source, [Add] included; C-44/C-45: typed play sources
  — hand, Champion Zone, trash with a granted permission, and facedown — with
  Ambush and the Hidden path. 421.4 and the Cleanup removal of hidden cards
  remain unsupported.)
- [x] Look, reveal, search, shuffle, randomize, discard, and banish operations.
  (C-22: discard as the player's private selection, 422; C-41: `look_at_top`,
  `reveal`, `put_back` by the player's `card_ordering`, `put_in_hand`,
  `draw_it`, multi-card `recycle` as one Game Action and `predict`, none of
  which Burn Out on a short deck, 431.1.c; C-43: `banish` and `burn`.
  Searching a deck and shuffling as a player action remain; randomization
  itself stays an external receipt, ADR-0010 §2.)
- [x] Recall as its own non-Move action and correct destination semantics.
  (C-16: `recall` to the current controller's Base, damage/exhaustion/modifiers
  retained, no Move trigger; Core 455–458.1.)
- [x] Countering Chain Items and counter-prevention interactions.
  (C-43, ADR-0011 §5: `counter` clears the effect-side entry and sends the
  card to its owner's trash — or hand — as a new object, records that it was
  not played and that no cost is refunded, and the resolution bridge removes
  the timing item in the same commit through `rules_core.remove_chain_item`;
  neither state commits when the timing chain does not carry it. "Can't be
  countered" is a P4 static and is refused by name.)
- [x] Attach, detach, Equip, Equipment, Gear Unit, Top-Most, and host changes.
  (C-46, ADR-0012 §4: `attached_to` names the Top-Most card and the other
  direction is derived; attaching takes the host's location and changes
  nothing else, 434.4–434.5.a; every attached card's Might Bonus modulates the
  host, 159.1; detaching derives its destination — the host's location, the
  host's last board location when it left for a non-board zone, and a
  Cleanup Recall record for a Gear left at a Battlefield, 435.4–435.4.b.
  Equip runs through the activation path. Nested attachments and Effect Text
  appending are declared unsupported.)
- [x] Buff/debuff objects and spend/remove/copy behavior beyond raw Might.
  (C-52, ADR-0013 §5: Empowered and Buffed as binary states with the rules'
  own idempotence — an already-Empowered object is a no-op with no second
  event, 441.1.c.1, and a Unit that already carries a Buff counter is chosen
  but not Buffed, 426.1.c — XP as a player value, and the three costs that
  spend them: spend_xp, spend_buff and disempower_self. A Level ability needs
  no new machinery: it is a continuous effect gated by `xp_at_least` that
  stops applying when the XP drops. C-53, ADR-0013 §6: copy as a Trait-layer
  effect over the traits the model carries.)
- [x] Channel and Rune-specific entry, ready/exhaust, and zone behavior.
  (C-16: `channel_rune` with entry state, partial completion per 430.3, new
  identity per 124.)
- [ ] Create/copy predefined tokens from a versioned token catalog.
  (C-48, ADR-0012 §6: `token-catalog.v1` with its schema, the promotion tool
  and its gate are in place, and `play_token` records the `token_id` it was
  compiled from; the catalogue ships **empty** because Codex's G-1 ruling on
  DP-67 makes every entry a manual promotion with an official text hash, the
  source cards and a reviewer/date record. The item stays open until tokens
  are actually reviewed. Copy is a typed request that fails closed,
  `copy_characteristics` — closed by C-53: copy is now a Trait-layer
  continuous effect over the modelled copyable traits, type and rules text,
  and a copy that would need a name, tag, printed cost or domain is refused
  by name rather than half-applied. The item stays open for the catalogue's
  own contents.)
- [ ] Score, conquer, hold, battlefield control, and Victory Score operations.
  (C-33..C-35, bounded slice per ADR-0009: control established after a
  Combat or a Non-Combat Showdown and lost in Cleanup; Conquer and Hold once
  per Battlefield per turn with the Final Point rule; Score triggers from
  modelled board sources; the victory condition reported as facts only.
  Still open: team scoring, Hidden (466.5.c), non-Conquer/Hold point
  sources, "activate" of named triggers, the Beginning Phase machine, the
  terminal state and Burn Out.)
- [ ] Burn Out and its complete loss/continuation semantics.
  (C-37: the Draw path — recycle by an external randomization receipt, the
  beneficiary's point, the empty-Trash sequence with the immediate victory
  from the second Burn Out and a score-derived bound, the terminal written
  by every Draw entry's two-state commit; Burn Out from non-Draw
  instructions (431.1.b) and the Predict / look / reveal exceptions remain.)

### Conditions, targets, and instruction grammar still required

Default ownership: `[CODEX-CONTEXT]`; these forms affect every later card
program and cannot be safely inferred from isolated examples.

- [ ] Open-ended target choice and target groups.
- [ ] Location-relative targets such as “here” and “another location.”
  (C-20: "at a battlefield" as a Battlefield target with criteria expansion,
  "here" as a location-scoped Bonus Damage source; C-22: "there" as the
  referent's current location. "another location" remains.)
- [ ] Last-known information and objects that change identity or zone.
  (C-14: object identity across non-board zone changes with selector
  revalidation; last-known information remains.)
- [x] Conditions over Might, damage, tags, domains, types, counts, and events.
  (C-21: "while you have N+ runes" as `runes_at_least`, 364.3; C-22: "the only
  unit you control there" as a named predicate; C-50, ADR-0013 §3:
  `condition.v1` as a typed AST — and/or/not over leaves for Might, keywords,
  Empowered, XP, Battlefield control, zone counts and controlled units — with
  one evaluator and a visibility boundary, so a condition that would need a
  private zone of anyone but the asking player is refused rather than
  answered. C-56 adds `same_location_as`, `might_less_than` and `object_kind`,
  which the Core's own replacement wording needs. Tags and domains are not
  modelled characteristics yet, so conditions over them stay refused.)
- [ ] General typed forms for “if,” “if you do,” “if this kills,” “then,”
  “then do this,” “for each,” “instead,” and “up to.”
  (C-15/C-17: “if you do” / “otherwise” via cost predicates, “if you can't”
  via requested_count_not_reached, “if this kills it, do this” via
  conditional reflexive triggers, “up to N” via bounded targets; C-22/C-24:
  “then” as sequence order with a named condition, “instead” for one granted
  next-death replacement; “for each” and the general forms remain.)
- [ ] Impossible-instruction continuation beyond the bounded linked gate.
- [ ] Simultaneous multi-object Move, Deal, Recycle, Kill, and token creation.
  (C-20: area Deal over criteria-found units, each with its own Bonus Damage,
  715.2; the rest remain.)
- [x] Player-targeted and uncontrolled-Battlefield replacement ordering.
  (C-56, ADR-0014 §3: the controller of the object being acted on orders the
  Replacement Effects that apply to that event, a player being acted on
  decides for itself, and an Uncontrolled Battlefield is the Current Turn
  Player's call.)

### Continuous effects, triggers, and replacement still required

Default ownership: `[CODEX-CONTEXT]`. Fixture/data expansion after a contract is
accepted is `[CLAUDE-READY]`.

- [x] Cross-object watchers and zone-dependent trigger eligibility.
  (C-19/C-21/C-22: play, end-of-turn and move triggers on the object itself,
  with the at_battlefield trigger condition; C-55, ADR-0014 §2: a watcher
  names the event kinds it reacts to and a scope — self, controller, location
  or any — and is matched against the semantic events of C-54, so one object
  reacts to another's. It stops at the same visibility boundary the conditions
  do: a watcher may react to the public fact that an opponent drew, but a
  condition on the card they drew is `watch_beyond_visibility`.)
- [x] Delayed triggers and duration-bound trigger registration.
  (C-55, ADR-0014 §2: a delayed trigger carries the source and target
  identities it was created with, the event or turn moment it waits for and
  the snapshot its instructions need. It fires once, and the binding is tested
  as the event saw it — a Unit dying still matches the binding made while it
  lived, a Unit that left and came back is a stranger and the trigger is
  dropped with its reason, 124. The end-of-turn ones fire in the real Ending
  Step alongside the printed triggers.)
- [x] First/Nth-time, once-per-turn, and per-object event counters.
  (C-55, ADR-0014 §2: a per-turn count keyed by the source's identity, the
  ability and the turn. An ability that has been performed its allowance does
  not trigger at all, 383.3.e, and a "you may" the controller declines at
  finalization was not performed, so it keeps its use, 383.3.e.2.b. The
  counters are pruned by the turn transition. C-56 gives Replacement Effects
  the same treatment under 372.)
- [ ] Instruction-level optional choices made during resolution.
- [x] Complete continuous-effect dependency/layer system.
  (C-49, ADR-0013 §1–2: six legacy representations collapsed into one
  canonical `continuous_effects[]`, and a real Core 476–480 engine over it —
  Trait, Ability and Arithmetic layers applied to a fixpoint, each effect
  applied once, dependency detected by trial application rather than declared,
  and a timestamp fallback where nothing depends on anything. The Core 479
  dependency example is a fixture: the dependency-aware order reads 6 where
  plain timestamp order reads 7. A dependency the engine cannot resolve is
  `layer_dependency_unresolved`, not a guess.)
- [ ] Duration expiry for this turn, next event, while/source-zone, and cleanup.
  (C-21: this-turn effects are active only for their stamped turn and expire
  at that turn's Expiration Step, 317.2.c; C-24: granted replacements follow
  the same active-turn boundary; C-49 adds `while_source_active`,
  `this_combat` and `until_detached` as first-class durations, with the source
  activity and the identity binding checked on every read and the dead ones
  pruned with their reason. Next-event and Cleanup durations remain.)
- [x] Multiple simultaneous replacement descriptors controlled by one player.
  (C-56, ADR-0014 §3: a batch with several descriptors used to fail closed and
  now resolves. A controller with more than one Replacement Effect in the
  batch orders its own sequences, and each Replacement Effect's controller
  orders the events of its own sequence.)
- [x] Different-controller simultaneous replacement execution in Turn Order.
  (C-56, ADR-0014 §3: the sequences of different controllers execute in Turn
  Order, and a batch that would need one without being given it fails closed
  as `turn_order_unknown` instead of guessing an order.)
- [x] Non-prevention replacement programs across simultaneous events.
  (C-56, ADR-0014 §3: `replace_with` runs inside a simultaneous batch, with
  `$affected` and `$source` so a replacement's instructions can say "it" and
  "me". `augment_with` and `reduce_damage` inside a simultaneous batch stay
  `batch_replacement_mode`.)
- [ ] Complete Core 373.2 uninterrupted sequence graph.
  (C-56, ADR-0014 §3: the sequence rules are implemented and pinned by the
  rulebook's own examples — 370.2's Zhonya's Hourglass pair, where both apply
  and the one that applied last dies, and 374's Soraka / Guardian Angel, where
  both orderings are reproduced because each sequence reads its qualifying set
  when it starts. A replacement's own actions run before any simultaneous
  unmodified event. What remains is the graph beyond the kill batch: the
  descriptor list is computed against the state the batch began in, so a
  Replacement Effect that only becomes applicable after another sequence is
  not in it.)
- [ ] `All` prevention, duration, and allocation choices.
- [ ] General Core 375 inheritance beyond the token subset.

### Game procedures still required

Default ownership: `[CODEX-CONTEXT]`; independent UI or fixture work after each
procedure contract is `[CLAUDE-READY]`.

Dependency milestones are defined in
[ENGINE_CAPABILITY_MILESTONES.md](ENGINE_CAPABILITY_MILESTONES.md):

- [ ] **G1 — Showdown and Combat.** Complete the supported Showdown/Combat
  procedure and its state/trace contract.
  (ADR-0008 fixes the R3-A3/G1 state, designation, assignment, Cleanup and
  closure contracts; C-26 through C-31 implement staging, opening,
  designations, Attack/Defend and Battlefield triggers, the Showdown close,
  Combat Damage assignment with previewed replacements, the simultaneous
  Deal, the Combat Cleanup, the result and the closure after control
  resolution (ADR-0009). Still open: start/end-of-combat effects,
  player-level Attack/Defend triggers, take-damage triggers, damage
  exemption sources, non-Prevent assignment replacements, Combats between
  more than two players.)
- [ ] **G2 — Battlefield control, Conquer, and Scoring.** Complete control,
  point, and scoring semantics.
  (ADR-0009 fixes the state, procedure and scoring contracts; C-33 through
  C-35 implement `battlefield_control.py`: atomic control resolution after
  a Combat or a Non-Combat Showdown, Conquer with the Final Point rule and
  its Burn Out rollback, typed Score triggers, staged Non-Combat Showdowns
  opened by the Turn Player's choice, the board Cleanup steps 323.6 /
  323.11 / 323.11.a, Hold as the Scoring Step, and `victory_check` facts.
  Still open: team scoring, Hidden, 323.7, non-Conquer/Hold point sources,
  383.4.g "activate", the Beginning Phase state machine.)
- [ ] **G3 — Victory and Terminal State.** Complete Victory Score, ties,
  simultaneous terminal events, Burn Out, terminal reasons, and reward adapter.
  (ADR-0010 fixes the contracts; C-36 through C-39 implement the bounded
  slice: the guarded `terminal` state with derived and declared reasons,
  ties that continue, Burn Out on Draw with randomization receipts and the
  terminal bridge, the Start of Turn state machine and turn transition, the
  atomic Cleanup with 322 iterations, and the read-only reward projection.
  Still open: non-Draw Burn Out, Setup, Match / Best-of and team modes,
  ready blockers, 323.7, the facedown reveal at game end, multi-player
  concession.)

- [ ] Complete normal Cleanup steps 1–10a.
  (C-26/C-31: step 2 designation synchronization, 3a/3b lethal Cleanup with
  Combat-Damage attribution, and steps 7–7a/10 as `stage_combat`; C-34:
  steps 4, 6, 8–8a and 9 as `run_board_cleanup`, `stage_showdown` and
  `open_showdown`; C-36/C-39: step 1 as `check_terminal` and the whole
  sequence 1–10a with the 322 follow-ups as one atomic `run_cleanup` that
  never pauses on the chain; step 5 (323.7) remains and fails the run
  closed whenever it applies.)
- [ ] Special, Combat, and End-of-Turn Cleanup additions.
  (C-21: the Ending Special Cleanup; C-31: the Combat Special Cleanup —
  heal all Units, Recall Attackers if Defenders remain.)
- [x] Attack declaration, attacker/defender designations, and legal defenders.
  (C-26: attacker = the player who applied Contested, defender the other
  participant, never guessed; designations on opening and by Cleanup; Core
  464.2.c, 323.2.)
- [ ] Combat damage assignment, Tank/Backline conflicts, and simultaneous Deal.
  (C-30/C-31, bounded implementation slice: `damage_assignment` decisions validated for
  465.2.c.3–c.9 with the official examples as goldens, Prevent values
  previewed and consumed once, receipts bound to the effect-state snapshot,
  Units as sources; damage-exemption sources (465.2.c.10) and non-Prevent
  assignment replacements remain unsupported, so Tank clauses stay partial.)
- [x] Showdown staging, opening, action cycle, resolution, and closure.
  (C-26/C-30/C-31: staging, opening with Focus, Focus passes closing a
  Combat Showdown, result and closure for Combats; C-34: Non-Combat
  Showdowns staged as a set, opened by the Turn Player's choice with Focus
  to the player who applied Contested, closed into control resolution.)
- [x] Battlefield Contested/control transitions.
  (C-19: `contested` / `contested_by` recorded on entering an uncontrolled
  Battlefield, 190.3.a.1; C-33/C-34: control established after a Combat
  or a Non-Combat Showdown, Uncontrolled after an emptied Combat, lost in
  the board Cleanup, Contested cleared / removed / re-applied per 466.5.a,
  323.11, 323.11.a; 466.5.c Hidden unsupported.)
- [x] Implement the Conquer/point/control components required by G2.
  (C-33/C-35: `points`, `scored_this_turn`, `mode`, `score_battlefield`,
  Conquer and Hold, Score triggers, `victory_check` facts; bounded per
  ADR-0009's coverage boundary.)
- [x] Implement terminal detection, ties, Burn Out, and reward adapter required
  by G3.
  (C-36/C-37, bounded: `check_terminal` / `declare_terminal`, the shared
  game-over guard, Burn Out on the Draw path with the terminal bridge,
  `reward_adapter.py` for two-player non-team games; non-Draw Burn Out and
  team / Match formats remain unsupported.)
- [x] Complete turn start/main/ending phase transitions.
  (C-21: `begin_ending_step` and `run_expiration_step` as two procedures,
  317; the Beginning and Main phases remain caller-supplied facts.)
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
  (C-18/C-25/C-32: the R3-A1, R3-A2 and R3-A3 batches — 34 cards, 38
  clauses full, 10 partial, 2 unsupported, 6 stale — in `r3a1_programs.json`;
  Legends are not engine objects, so Annie - Fiery and Master Yi - Wuju
  Bladesman stay partial; the Draw clauses derive full since C-37 modelled
  Burn Out on Draw (43 full, 5 partial); the Tank and mutual-damage clauses stay partial while damage
  exemption and non-Prevent replacement modes are unsupported; Vision stays
  unsupported; activation remains an ADR-0004 gate.)
- [x] Label every selected Wave-A card and clause `unsupported` or `stale` in
  the R3-A0 draft; `full`/`partial` remain recommendations until tested programs exist.
- [ ] Attach an official locator to every implemented clause.
- [ ] Add positive, negative, replacement, timing, and impossible-action tests
  for every implemented card.
- [ ] Add cross-card fixtures for every deck's core lines.
- [ ] Reconcile those lines with Deck Coach primers and expert review.
- [ ] Publish machine-readable pack coverage and abstention reasons.
  (C-18: `r3a1_behavior_manifest.json` derived from fixtures, still draft;
  pack-wide coverage awaits the later batches.)
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
| C-13 — completed 2026-09-03 | R3-A1 clause ledger, fixture drafts, decision packets | Inventory accepted | Per-clause Core locators, four drafts per clause without expected outcomes, eleven packets for X-09 |
| C-14 — completed 2026-09-04 | engine-decisions.v1, typed selectors, object identity, mistarget traces | ADR-0005 §1–3 | One decision envelope with stages; derived target status; identity across non-board zone changes; applied_full / applied_to_subset / skipped_illegal_target |
| C-15 — completed 2026-09-04 | Atomic play/cost transaction and cost receipts | ADR-0005 §4; Codex conditional review applied | play_transaction.py; riftbound-cost-receipt.v1 with unique payment events; shared chain_items; Add window (429.3); cost_paid / cost_not_paid predicates |
| C-16 — completed 2026-09-04 | return_to_hand, recall, channel_rune | ADR-0005 §6, §8; Codex Q1–Q3 | Three distinct zone events with their own trigger classes and identity rules |
| C-17 — completed 2026-09-04 | Typed linked-result predicates and caused_kill | ADR-0005 §5; Codex Q4 (b), Q5 | action_performed on the original action; requested_count_not_reached; conditional reflexive triggers built after Cleanup with 428.5.c attribution |
| C-18 — completed 2026-09-04 | R3-A1 card programs and derived behavior manifest | C-14..C-17 landed; Codex Q7, Q10 | r3a1_programs.json with cited fixtures; r3a1_programs.py derives a draft card-behavior-manifest.v1; Vision unsupported; stale cards stay stale |
| C-19 — completed 2026-09-05 | Permanent entry procedure, play triggers, open-Battlefield permission | ADR-0007 §1–3 | complete_permanent_play; entry_location chosen at play; contested_by without control; play triggers batch play:<item>; no Battlefield-control or Showdown claim |
| C-20 — completed 2026-09-05 | Battlefield targets with criteria expansion, Bonus Damage | ADR-0007 §4–5 | `affected.criteria` next to targets, affected units never targets; damage_modifiers summed once, per unit, before Prevent |
| C-21 — completed 2026-09-05 | Entry replacements, conditional passives, Ending and Expiration steps | ADR-0007 §6–8 | entry_replacements and turn_effects; effective_might with runes_at_least; begin_ending_step / run_expiration_step, Expiration refused before Ending triggers finish |
| C-22 — completed 2026-09-05 | Named instruction condition, Move triggers, private discard | ADR-0007 §9–10 | sole_controlled_unit_at_referent_location; move_triggers on move_board_object only; discard with card_selection, empty hand draws nothing, hand never listed |
| C-23 — completed 2026-09-05 | Deflect as any-domain Power with resource_allocation | ADR-0007 §11 | power_any mandatory additional cost per choice; one legal allocation paid, two or more asked; Add window first |
| C-24 — completed 2026-09-05 | Granted replacements | ADR-0007 §12 | grant_replacement / heal_all_damage; exactly one of source-backed or granted; not applicable after the target leaves and returns; expires with its turn; Highlander stays stale |
| C-25 — completed 2026-09-05 | R3-A2 card programs and re-derived manifest | C-19..C-24 landed | 19 R3-A2 clauses with passives, probes and play_entry fixtures; symbolic bindings, mirrored runs; stale cards carry programs without program_id; manifest draft |
| C-26 — bounded slice completed 2026-09-05 | Combat staging/opening, designations and trigger synchronization | ADR-0008 §1–3 | combat.py stage_combat / open_combat / sync_combat_designations over the timing/effect pair; location_selection for several staged Battlefields; contested_by is the attacker or the opening is unsupported; three controllers unsupported; Unit and Battlefield Attack/Defend triggers once per identity, attacker first; Cleanup step 2 before lethal. Not in this slice: start-of-combat effects and player-level Attack/Defend triggers |
| C-27 — completed 2026-09-05 | Battlefield Defend triggers and combat-relative characteristics | ADR-0008 §4–5 | Battlefield attack/defend triggers fire for the Battlefield's controller only; effective_might adds Shield while defending, attacking_or_defending_alone, friendly_unit_defends_alone auras, clamps negatives at 0; grant_keyword with keyword_modifiers bound to the Combat in progress |
| C-28 — completed 2026-09-05 | Atomic Standard Move and Ganking | ADR-0008 §6 | standard_move as a player action (validate_timing kind); simultaneous exhaust cost with confirmation; one destination; Base↔Battlefield routes; Battlefield→Battlefield only with active Ganking; relocation delegated to the Move operation |
| C-29 — completed 2026-09-05 | Active-Combat criteria and mutual Might damage | ADR-0008 §7 | affected.criteria.location active_combat under the bridge's Combat context, empty without a Combat, unsupported when the claimed Combat cannot be confirmed; mutual_damage_current_might snapshots both Mights and Deals at once with the Units as sources |
| C-30 — bounded slice completed 2026-09-05 | Combat Damage assignment and replacement preview receipts | ADR-0008 §8–9 | pass_focus closes the Combat Showdown; assign_combat_damage validates damage_assignment decisions against 465.2.c.3–c.9 (official examples as goldens), previews Prevent values only (other modes and 465.2.c.10 exemptions unsupported), auto-advances only for the sole legal assignment, records receipts bound to the effect-state snapshot |
| C-31 — completed 2026-09-05 | Simultaneous Combat Deal, Cleanup, result and closure boundary | ADR-0008 §10 | deal_combat_damage from snapshot-bound receipts with replacements consumed once; combat_cleanup in 323 order (designations, death triggers, kills attributed per object to the opposing side, heal, Recall, 324.2 follow-up); determine_combat_result after the chain empties; close_combat expires this-combat effects, stages the both-remain Combat again, and abstains as unsupported battlefield_control_resolution where 466.5 would change control |
| C-32 — completed 2026-09-05 | R3-A3 card programs and re-derived manifest | C-26..C-31 landed; ADR-0008 §11; Codex review-fix | 13 clauses / 12 cards with combat-scenario fixtures staged by the real procedures; 9 full, 4 partial (the Legend clause, the two Tank clauses, the mutual-damage clause); vanilla Units probed as intrinsic unit_combat; mirrored runs |
| C-33 — completed 2026-09-06 | Battlefield control resolution, Conquer scoring and Score triggers | ADR-0009 §1–2, §5–7, §11 | battlefield_control.resolve_battlefield_control atomic after a decided Combat (466.5, control_resolved); score_battlefield once per Battlefield per turn with the Final Point rule, draw-instead and unsupported burn_out rollback; Score triggers unit_here / controller / Battlefield; close_combat after control resolution; engine-check kind control_step |
| C-34 — completed 2026-09-06 | Non-Combat Showdowns and board Cleanup | ADR-0009 §3–4, §9 | stage_showdown rebuilds staged_showdowns; open_showdown with showdown_location and Focus to the applier before 323.13; pass_focus marks a Non-Combat Showdown closing; sole occupant hands over to control resolution, empty defers to 323.6, both present unsupported; run_board_cleanup for 323.6 / 323.11 / 323.11.a with an ongoing-only exemption |
| C-35 — completed 2026-09-06 | Scoring Step (Hold), victory facts, control_step scope and docs | ADR-0009 §8, §10, §12 | run_scoring_step Holds every controlled Battlefield not yet scored with no Final Point restriction, one trigger batch; victory_facts step reports threshold_met / strict_leader / tied_at_threshold without a winner; engine-check.md, rules-core.md, effect-ir.md |
| C-36 — completed 2026-09-06 | Terminal state, shared game-over guard and reward projection | ADR-0010 §3–4, §10 | terminal.check_terminal as Cleanup step 1 (strict leader ends, tie continues); declare_terminal records concession / external; one guard in the timing kernel and the two-state validators; frozen snapshot; reward_adapter.py read-only +1 / −1 / 0 |
| C-37 — completed 2026-09-06 | Burn Out on Draw, randomization receipts and the terminal bridge | ADR-0010 §2 | effect_ir.perform_draw with randomization-receipt.v1 and player_selection; the empty-Trash sequence wins immediately from the second Burn Out; every Draw entry (bridge, control transaction, scoring step, draw step) writes the terminal in its own commit; Draw clauses derive full |
| C-38 — completed 2026-09-06 | Start of Turn state machine, Mode of Play and turn transition | ADR-0010 §1, §6–9 | turn_cycle.py begin_turn / awaken / enter_beginning / channel / draw / enter_main with typed turn_progress and 319.2 Cleanup gating; First Turn Process from mode.id (duel, skirmish) or mode.first_turn; match and team modes unsupported |
| C-39 — completed 2026-09-06 | Atomic Cleanup orchestration with 322 iterations and G3 docs | ADR-0010 §5, §11 | run_cleanup runs 323 steps 1–10a on one working state, death triggers stay Pending, follow-up Cleanups iterate to a stable state, any decision or unsupported step commits nothing, 323.7 fails closed |
| C-40 — completed 2026-09-06 | Choice grammar, modal abilities and the new decision kinds | ADR-0011 §1–2, §6 | One typed `choice` specification over engine-decisions.v1; `mode_selection` by stable option id recorded on the chain entry; `card_ordering` for permutations; private options never listed in a result or an engine-check |
| C-41 — completed 2026-09-06 | Look, reveal, put back, recycle and Predict | ADR-0011 §3 | look_at_top / reveal marks that live only while a program runs (424.3.a), put_back by the player's card_ordering, put_in_hand / draw_it, multi-card recycle as one Game Action with the 416.5 order, Predict without Burn Out |
| C-42 — completed 2026-09-06 | Payment catalogue, activated abilities, Repeat and restricted resources | ADR-0011 §4 | discard / recycle_trash / kill_this / recall_self payments with receipt events; activated abilities as chain items of kind `ability`; [Repeat] executions with suffixed choices; restricted Add resources spent only on their named uses; cost modifications accepted only as evaluated typed input |
| C-43 — completed 2026-09-06 | Banish, Counter and [Burn N] | ADR-0011 §5 | banish (not a Kill, not a Discard); counter clearing the chain item on both sides in one commit via rules_core.remove_chain_item; burn, with a short deck refused as burn_out_non_draw rather than borrowing the Draw receipt |
| C-44 — completed 2026-09-06 | Play sources, cost overrides, Ambush and Unique | ADR-0012 §1–2 | Typed `source` (hand, Champion Zone, trash with a granted permission), `cost_override`, Ambush as a play permission with its timing; Unique recorded as the deck-construction constraint Core 825.3 makes it, never a play restriction |
| C-45 — completed 2026-09-06 | Facedown Zones, the Hide action and playing from Hidden | ADR-0012 §3 | Each Battlefield's Facedown Zone with its capacity; hide_card as a Discretionary Action with its own receipt use, so play-restricted resources cannot pay it; playing from Hidden the next turn with the base cost ignored and the 811.4 targeting restriction |
| C-46 — completed 2026-09-06 | Attachments, Top-Most and derived detach destinations | ADR-0012 §4 | attached_to with derived attachments, the Might Bonus on the Top-Most card, and one derivation for every host departure — killed, banished, returned, recycled or moved |
| C-47 — completed 2026-09-06 | Legends, the Champion Zone and the fail-closed copy request | ADR-0012 §5, §7 | `legend` objects that exist only in a Legend Zone or Banishment, passives that stay active from the Legend Zone, Board selectors that never reach a Legend; copy_object refuses rather than half-copying. Annie - Fiery and Master Yi - Wuju Bladesman derive full |
| C-48 — completed 2026-09-06 | The hand-promoted token catalogue | ADR-0012 §6 | token-catalog.v1 with its schema, promotion tool and gate; play_token records its token_id; the catalogue ships empty because nothing has been reviewed yet |

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
| D-04 — R3-A1/A2/A3 slices completed 2026-09-05 (C-18, C-25, C-32) | Per-card R3 effect programs | Frozen pack, token registry, condition/choice contracts — the Wave-A clauses are compiled; further batches need their own contracts | Assigned card programs, clause locators, positive/negative tests |
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
