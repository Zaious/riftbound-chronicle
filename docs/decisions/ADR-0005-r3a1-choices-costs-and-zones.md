# ADR-0005 — R3-A1 choices, costs, zones, and linked results

Status: accepted

Date: 2026-09-03

Applies to: R3-A1, `effect_ir`, the atomic resolution coordinator,
`observation.v1`, card programs, traces, and decision artifacts

## Context

The Annie/Master Yi teaching pack contains twelve R3-A1 clauses across eleven
cards. Their primitive operations are small, but their correctness depends on
shared semantics: when choices are made, which choices target, what happens
when a target changes, how costs roll back, how linked instructions test prior
results, and how private looked-at cards enter an observation.

Implementing these rules card by card would create incompatible meanings for
the same words. C-13 therefore produced a clause ledger, 48 expectation-free
fixture drafts, and decision packets DP-01 through DP-11. This ADR resolves
those packets before executable programs are added.

The controlling baseline is Core Rules 2026-07-16 plus current card errata.
The 2025-10-16 Origins FAQ is retained locally as superseded historical
evidence because its own page directs readers to newer rules. It is not a
controlling override for this ADR.

## Decision

### 1. Selectors and targets (DP-01)

The card-program compiler declares a typed selector. Callers do not get to set
`targeted: true|false` to change the rules. Target status is part of the
compiled clause semantics derived from Core 355.7–355.10.

- Public objects chosen by one player to be affected are targets unless a
  listed exception applies.
- Objects mentioned only as a restriction, cost, trigger condition,
  replacement effect, or mandatory/non-choice are not targets.
- Choices from non-public zones are not targets and normally occur during
  resolution.
- A currently unique legal option does not stop an otherwise-targeted choice
  from being a target.

A required choice that has not yet been supplied is `decision_required` while
the transition is asking for it. It is `invalid_input` only when an artifact
claims the relevant stage is complete but omits or malforms that choice. A
well-formed supplied choice rejected by a supported selector is `illegal`.

### 2. One decision envelope, explicit stages (DP-02)

Introduce `engine-decisions.v1`, keyed to the same input and chain-item hashes
as the transition it completes. Each entry contains at least:

- `decision_id`;
- `stage`: `play_declaration`, `trigger_finalization`, or `resolution`;
- `kind` and `controller`;
- supplied selection or decision value;
- eligible options or the capability/provenance used to derive them;
- the input hash against which it was made.

Different stages do not receive incompatible schemas. Supplying a decision for
the wrong stage or input hash is `invalid_input`; a well-formed choice made by
the wrong controller is `illegal`; an unimplemented stage is `unsupported`.

Spell targets, destinations, and optional additional-cost intent are chosen at
play declaration. Targets and performance choices belonging to triggered
abilities are made when that triggered item is finalized where the rules
require it. Other choices are made during resolution.

Vision is explicit: the triggered ability is finalized, then Predict executes;
the recycle-or-keep decision occurs during resolution. It is not the optional
trigger-performance choice described by Core 402.1.

### 3. Mistargeting and linked causality (DP-03)

Targets are validated when chosen and revalidated at the instruction that uses
them. A target that changes to or from a non-board zone has a new object
identity even if the same physical card returns.

The chain item still resolves when targets become invalid. Trace outcomes are
typed:

- `skipped_illegal_target` when an instruction has no usable target;
- `applied_to_subset` when a multi-target instruction operates on the valid
  subset;
- `applied_full` when all required targets remain valid.

No replacement target is chosen during resolution unless current card text
explicitly instructs one.

Linked conditions are not all `if_applied`. They use typed result predicates.
In particular, Disintegrate's “If this kills it” requires a kill causally
attributed to that Deal action after its required Cleanup. Merely marking
damage, or merely executing the damage instruction, is insufficient. A
mistargeted damage instruction therefore cannot satisfy `caused_kill`.

### 4. Play-level atomic cost transaction (DP-04)

Playing a card is one atomic transaction across choices, cost calculation,
cost payment, legality checks, chain insertion, and the state committed by
those steps. A failure governed by Core 358.5 restores the pre-play state.

Costs use typed `cost_payment` records with an explicit cost context and a
receipt. A cost may reuse a primitive operation such as exhaust, but is not an
ordinary effect with only a `cost: true` flag. The receipt distinguishes:

- intent to pay an optional cost;
- the resulting payment events;
- replacement or reduction applied to those events;
- whether the rules consider the cost paid.

An unpayable supported cost is `illegal`; an unknown cost mechanic is
`unsupported`; malformed declarations are `invalid_input`; missing optional
cost intent at the play stage is `decision_required`.

### 5. Typed linked-result predicates (DP-05)

Instructions record completion as `full`, `partial`, or `none`, including
requested and actual counts where relevant. Branches use named predicates, not
one ambiguous negative dependency:

- `action_performed` / `action_not_performed`;
- `requested_count_not_reached`;
- `cost_paid` / `cost_not_paid`;
- `caused_kill`.

Mobilize's “If you can't” tests `actual_count < requested_count`; a partial
Channel satisfies the fallback. Meditation's “If you do” and “Otherwise” test
the optional-cost receipt, not whether the later draw instruction happened.
An unknown dependency id is `invalid_input`; a recognized but unavailable
predicate capability is `unsupported`.

### 6. Return, Recall, and Move are distinct events (DP-06)

Add distinct operations and event kinds:

- `return_to_hand`: place the card in its owner's hand, create a new tracked
  object identity, and drop temporary modifications as required for a
  non-board zone change;
- `recall`: relocate a permanent to its current controller's Base without a
  Move event; retain damage and statuses unless the source says otherwise;
- `move_board_object`: the existing board Move semantics.

Move-triggered abilities do not trigger from Recall or return-to-hand. The
destination is derived from rules and object ownership/control, not accepted as
an arbitrary caller-provided zone. Highlander performs heal, exhaust, then
Recall in printed order as one replacement result.

### 7. Look, Predict, and perspective (DP-07)

A look operation may create an own-private fact for the entitled player. That
fact records source zone, position, object/card identity when known, provenance,
and lifetime. It is never copied into another player's private facts.

Predict is a compound supported procedure only when the engine can:

1. inspect the available top card for the entitled player;
2. request the resolution-stage recycle decision;
3. recycle or preserve the card deterministically;
4. redact the identity from unauthorized observations.

Empty or short decks use “as many as possible” and are supported, not errors.
An opponent's predicted identity appearing in a Player 2 observation is
`invalid_input` as a perspective violation. Voluntary showing is not promoted
to public/revealed state without a separately recorded event.

### 8. Channel is its own operation (DP-08)

Add `channel_rune {player, count, entry_state}`. It consumes up to `count`
runes from the top of that player's Rune Deck, places them on the board, and
records requested and actual counts. `entry_state` is `ready` or `exhausted`.

Channel is a zone transfer, not a Move, and runes are not permanents. Existing
rune identity may be retained across this board-zone transition; no Move
trigger is emitted. An empty Rune Deck is a supported zero-result operation.

### 9. Versioning (DP-09)

- `riftbound-effect-program.v1` remains valid because the new operations and
  predicates are additive and old fields retain their meanings.
- The capability set and implementation identity change.
- `engine-decisions.v1` is a new schema.
- Effect state gains optional, capability-gated zone/object fields; old states
  remain valid for operations that do not need them.
- If implementation would change an existing field's meaning rather than add a
  new operation/predicate, it must stop and request a schema-major decision.

### 10. Failure vocabulary (DP-10)

| Outcome | Meaning in R3-A1 |
| --- | --- |
| `illegal` | A well-formed action or supplied choice is rejected by an implemented rule |
| `invalid_input` | State, program, decision, identity, stage, or hash is malformed/inconsistent |
| `unsupported` | The required mechanic or information model is not implemented |
| `decision_required` | A known decision owned by a known controller is required before retry |
| `supported` | The bounded transition completed, including a legal mistarget/no-effect resolution |

These outcomes describe engine execution. They are not official judge rulings.

### 11. Origins FAQ handling (DP-11)

The official Origins FAQ is captured as HTML in the ignored local rules store,
hashed in `rules.lock.json`, and indexed with provenance. It is marked
`superseded` by Core Rules 2026-07-16 and excluded from normal searches. An
explicit historical query may retrieve it to explain why a rule evolved.

Current R3-A1 executable claims cite the current Core baseline and applicable
errata. Historical FAQ text cannot raise coverage or override current Core.

## Implementation order

1. `engine-decisions.v1`, selector references, object identity, and zone state.
2. Atomic play/cost coordinator and cost receipts.
3. `return_to_hand`, `recall`, and `channel_rune` operations.
4. Typed linked-result predicates and causal Cleanup attribution.
5. Predict/private-fact adapter.
6. Convert C-13 fixture drafts to expected fixtures only as each capability
   lands; upgrade behavior clauses individually.

## Acceptance gates

Each capability requires positive, negative, missing-decision, mistarget,
rollback, stale-hash, perspective, deterministic-hash, and off-cwd coverage as
applicable. A card clause remains `unsupported` or `stale` until its complete
path and current-text hash pass. No deck-level support follows automatically.

## Rejected alternatives

- Card-specific branching in engine code.
- Treating every choice as a target.
- Treating Vision as a Core 402.1 optional triggered ability.
- Using `if_applied` to mean “caused a kill.”
- Treating cost payment as an ordinary effect outside the play transaction.
- Treating Recall or return-to-hand as Move.
- Letting historical FAQ text override a newer controlling Core baseline.
