# ADR-0007 — R3-A2 play lifecycle, conditions, continuous effects, and turn expiry

- Status: Accepted (Codex rulings on DP-12–DP-24, 2026-09-05)
- Scope: the `R3-A2-play-conditions-continuous` capability batch — 19 clauses
  on 19 Wave-A cards — and the engine contracts they need. Builds on
  ADR-0002 (versioning), ADR-0004 (packs), ADR-0005 (choices, costs, zones).
- Not decided here: Battlefield control transfer, Showdown, Combat, Beginning
  Phase, counters, continuous-effect dependency layers.

## Context

R3-A1 gave the engine typed selectors, decisions, an atomic play transaction,
zone events, linked predicates, and eleven card programs. The next batch of
Wave-A clauses needs permanents to actually enter the board, "When you play
me" and "When I move" triggers, area effects, Bonus Damage, entry-state and
conditional passives, "this turn" expiry with an Ending Step, discard with a
private choice, Deflect, and effect-created replacements. Each of those has a
reading the rules fix and a reading that would be convenient; this ADR
records the fixed ones.

## Decision

### 1. Permanent entry is an explicit procedure (DP-12)

`complete_permanent_play` replaces the spell path for Unit and Gear chain
items: the card leaves the chain (a Non-Board Zone, Core 328) and gets a new
identity on entering the board (124); entry replacements apply — default
Unit exhausted (143.4, 359.2.c), Non-Unit Gear ready (359.2.d), then
enter-ready replacements; the Unit enters the `entry_location` chosen at
play and stored on the shared chain entry, Gear enters the controller's Base;
only then is the play complete and "When you play me" evaluated; then a
board-entry Cleanup (319.6). Entering a Battlefield the controller does not
control records `contested: true` and `contested_by: <controller>`
(190.3.a.1) and nothing more: control transfer, Showdown and Combat are later
procedures. A location or chain binding that does not exist is
`invalid_input`; one that exists but fails 355.2 without permission is
`illegal`.

### 2. "When you play me" triggers on play completion (DP-13)

`play_triggers` on an object fire when the act of playing completes by the
card's resolution (419.4.a), never merely on an enter-board event; a card
whose resolution is prevented does not trigger (419.4.a.1 — counters stay
`unsupported: counter`). Triggers from one play-completion event share one
batch; same-controller collisions reuse the `trigger_order` decision; targets
and choices are made at trigger finalization (355.5.b); scheduling respects
HOT and Outstanding Tasks and never interleaves the resolving item.

### 3. Open-Battlefield permission (DP-14)

`play_permissions: ["open_battlefield"]` is a compiled ability active in the
zones the card can be played from (366.2). `entry_location` is validated at
the 355.2 choice: own Base, a Battlefield the controller controls, or — with
the permission — an open Battlefield (unoccupied and uncontrolled,
170.11.c). A later change to the Battlefield does not reopen the choice: the
permanent enters the chosen location (359.2.c) and, if not controlled by its
controller, records `contested_by`. No Battlefield-control or Showdown claim
follows.

### 4. Battlefield targets and area effects are two layers (DP-15)

"All units at a battlefield" targets the Battlefield (355.10.b), which has a
bindable identity, is chosen at play and revalidated at resolution. The
units are `affected_objects` found by criteria at resolution: not targets,
not subject to Deflect or untargetability. The trace shows the targeted
battlefield, the dynamically affected non-target objects, and the criteria
with its snapshot hash. "All units at battlefields" targets nothing and
expands over every Battlefield. Choosing a Battlefield that does not exist or
is not legal is `illegal`; a state missing a Battlefield or identity it
should have is `invalid_input`; a Battlefield target that vanished or changed
identity before resolution leaves the spell resolving with that instruction
`skipped_illegal_target`.

### 5. Bonus Damage is a property of the Deal action (DP-16)

`damage_modifiers` on the state carry amount (positive integer), scope
(`controller_sources` keyed to the spell's or ability's controller, or
`location` judged by the affected unit's current Battlefield), and source.
Order: confirm the Deal action happens and its base damage is non-zero
(715.4); collect every active Bonus; sum once (714); add once to a single
target or separately to each affected target (715.1–715.2); replacement,
Prevent and `reduce_damage` see the total including Bonus (437.1.a.1). A
Battlefield source such as Void Gate is not pruned by the "source must be on
the board" rule. An inactive source simply does not apply; an unknown scope
is `unsupported`.

### 6. `enter_board` is a replaceable event (DP-17)

Units default to exhausted; Master Yi Honed is a mandatory self replacement
to ready (369.3); Confront creates a `turn_effect` making the controller's
units played later this turn enter ready. Mutually exclusive entry
replacements needing a controller's choice reuse the replacement
order/choice decisions — never a fixed priority. Entry replacements carry
stable ids (or receive a deterministic id at compilation) so the existing
`replacement_order` envelope can name the complete order. The trace records
the default state, the replacements applied, and the final entry state.

### 7. "You have N runes" and conditional passives (DP-18)

Counts every Rune the player controls on the Board — Base or any Board
Location, ready or exhausted — and nothing in Non-Board Zones; teammates'
runes do not count ("you", not "friendly"). `current_might(obj)` keeps its
contract; a new context-aware `effective_might(state, object_id)` applies
conditional passives and every rules path that needs them uses it. Mutually
dependent or cyclic continuous effects stay `unsupported:
continuous_dependency`.

### 8. Ending Step and Expiration Step are two procedures (DP-19)

`begin_ending_step` enters the Ending Phase, evaluates and schedules "At the
end of your turn" triggers, and waits for those Chain Items, HOT and
Outstanding Tasks. `run_expiration_step` runs only with the Ending Step
handled, the Chain empty and no Outstanding Tasks: one Ending Special
Cleanup — 3c heal all Units, 3d every `this turn` effect of this turn
expires simultaneously, 3e every player's Energy and Power pool empties.
Follow-up Cleanups are normal Cleanups (324.2), never a repeated Special
Cleanup. Effects carry a `turn_id` so another turn's effects are never
cleared or treated as active in the current turn. Wrong phase, non-empty
Chain or Tasks → `illegal`; unknown
turn-effect kind → `unsupported`. The next player's Beginning Phase is not
implemented and no complete turn transition is claimed.

### 9. Instruction conditions are named predicates (DP-20)

En Garde's "if it is the only unit you control there" is
`predicate: {kind: "sole_controlled_unit_at_referent_location", effect_id}`:
at resolution, read the earlier instruction's legal referent; none → skip;
"there" is the referent's current location; count the units the effect's
controller controls there (teammates excluded); exactly one and it is the
referent. Not holding is `skipped_linked_dependency / completion: none`, not
`illegal`; an unknown condition kind is `unsupported`.

### 10. Move triggers, Discard, and private choices (DP-21)

Only a successful `move_board_object` raises Move triggers; Recall, return to
hand, and board entry do not. `discard {player, count}` moves hand → owner's
trash with a new identity, is not a target, and discards as many as possible
when short (422.4). The choice is a new decision kind `card_selection`
(stage resolution, controller = the discarding player, value = hand object
ids with their selection identities), confined to that player's own-private
observation and decision artifacts. When the whole hand must go and only one
set is legal the engine proceeds; otherwise `decision_required`. Unknown or
stale identities, or a choice without complete identity bindings, are
`invalid_input`; a well-formed choice outside the
player's hand, or another player's choice, is `illegal`. "Discard 1, then
draw 1" is an action-performed linked gate: nothing discarded → no draw; a
partial discard that happened → draw.

### 11. Deflect and any-domain Power (DP-22)

After targets are fixed and before cost determination, each time an
opposing-team spell or ability chooses an object with Deflect adds a
mandatory `power_any` cost equal to the summed Deflect values (809.1.c–d,
809.2); affected-by-criteria units do not trigger it. Payment is a
`resource_allocation` decision whose value is the complete allocation
(`{"fury": 1, "calm": 1}`): the sum equals the Power due, no domain exceeds
the confirmed pool; one legal allocation proceeds, several are
`decision_required` (engine-check `cost_choice`), and the engine never spends
domains in an arbitrary order. The Add window is settled first; a short pool
after it is `illegal`. A non-positive Deflect value is `invalid_input`.

### 12. Effect-created replacements (DP-23)

`grant_replacement` creates a *granted* replacement variant bound to the
target object id and its identity at grant time, `uses_remaining: 1`,
`duration: this_turn`, a `turn_id`, and `granted_by`; source-backed
replacements keep their `source_object`, and the validator requires exactly
one of the two forms. A granted replacement is removed after use, on expiry,
when the target's identity changes, or when the target stops being an
applicable board object. It participates in the existing order/choice
decisions. Highlander stays stale; its program exists without a program_id.

### 13. Versioning and vocabulary (DP-24)

Everything here is optional fields, new operations, new procedures, and new
predicate/decision kinds with unchanged meaning for existing fields: same
schema majors, new capability set and implementation identity. Vocabulary:
decisions `card_selection`, `resource_allocation`; predicate
`sole_controlled_unit_at_referent_location`; procedures
`begin_ending_step`, `run_expiration_step`; evaluator `effective_might`;
battlefield `contested` + `contested_by`; granted replacement as its own
variant. Any change to an existing field's requiredness, an existing
outcome's meaning, an existing function's semantics, or a replay result
stops for a schema-major / migration decision.

## Implementation order

1. C-19 permanent entry, play triggers, open-Battlefield permission.
2. C-20 Battlefield targets with criteria expansion, Bonus Damage.
3. C-21 enter ready, conditional passives, Ending and Expiration steps.
4. C-22 named instruction conditions, Move triggers, discard with
   `card_selection`.
5. C-23 Deflect with `power_any` and `resource_allocation`.
6. C-24 `grant_replacement` (Highlander stays stale).
7. C-25 the R3-A2 card programs with symbolic bindings and mirrored runs;
   manifest re-derived.

`draw` remains partial while Burn Out is outside Effect IR v1. A passing
fail-closed empty-deck fixture proves safe abstention, not full behavioral
coverage; every active Draw clause names `burn_out` until that procedure is
implemented.

## Acceptance gates

Each batch: one commit, full and off-cwd gates, capability manifest and R5-A
report regenerated. In addition: C-19 claims no Battlefield control or
Showdown; C-20 never marks area-affected units as targets; C-21 proves
Expiration is refused before Ending triggers finish; C-22 proves an
empty-handed Traveling Merchant does not draw and that a private selection
never reaches the opponent's observation; C-23 proves two legal Power
allocations are not auto-chosen; C-24 proves a granted replacement no longer
applies after its target leaves and returns; C-25 keeps symbolic bindings
and mirrored runs. The four stale cards (Annie Dark Child, Void Gate,
Highlander, Disintegrate) may carry programs but get no program_id, no
test_ids, and no manifest promotion. Every card or clause status describes
only the derived clause in the draft manifest — never a deck or a game.

## Rejected alternatives

- Reusing the spell path (effects → trash → Cleanup) for permanents.
- A bare `contested: true` without the contesting controller.
- Renaming C-14's target expansion for area effects, which would make
  affected units targets.
- Bonus Damage as a second Deal, or applied before deciding whether damage
  is dealt at all.
- A fixed priority among entry replacements.
- One `end_turn` procedure mixing Ending triggers and expiration.
- A generic `predicate: {kind: "condition", condition: {...}}`.
- Reusing `target_selection` for hand choices.
- Storing a single chosen domain for `power_any`.
- Making `source_object` optional on every replacement.
