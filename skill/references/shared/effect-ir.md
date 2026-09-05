# Chronicle Typed Effect IR

Read this reference when implementing or evaluating a card instruction. The R2
effect IR is Chronicle-owned executable semantics. It complements the timing
core: `rules_core.py` determines when and what procedure occurs;
`effect_ir.py` applies only supported, already-resolved atomic instructions.

## Invariants

- No card-name conditionals exist in the interpreter.
- A card definition may only compose typed operations.
- Every operation produces a rule-grounded before/after trace.
- State and program versions must match the executable rules baseline.
- Unknown operations, Burn Out, malformed locations, or unsupported mechanics
  fail closed with `committed: false`.
- The interpreter never falls back to model prose or partial guessed behavior.
- Official rules remain normative; a mismatch is a conformance failure.
- Applying a program never mutates the state it was given, produces the same
  result byte for byte on the same input, and either commits every effect or
  returns no state at all. `check_effect_ir_properties.py` asserts these over
  generated programs, including that hashes do not vary with interpreter run
  state — a hash that depends on dict ordering is stable on one machine and
  wrong everywhere else.

## Supported R2 v1 operations

| Operation | Scope | Official locator |
| --- | --- | --- |
| `draw` | draw known available cards from the top of Main Deck | Core 413 |
| `recycle_one` | recycle one known object to its owner's corresponding deck | Core 416 |
| `move_board_object` | move one known object between Base/Battlefield locations; a Base destination may be `player_relation: object_controller` (each moved unit's own controller's Base, 355.4.a) | Core 420, 445 |
| `modify_might` | append a typed Might modifier with source and duration | Core 135.2.e.3, 477 |
| `deal_damage` | mark positive damage on one unit/object | Core 417 |
| `heal_damage` | clear up to a specified amount of marked damage | Core 418 |
| `ready` | ready a supported board object; already ready is a no-op | Core 415 |
| `exhaust` | exhaust a supported board object; already exhausted is a no-op | Core 414 |
| `add_resource` | add Energy or domain-labelled Power | Core 429 |
| `play_token` | create one explicitly identified Unit/Gear token at a Base or Battlefield; Units default exhausted and Gear ready | Core 143.4, 149.1, 184–186, 349, 375 |
| `kill` | kill a supported Unit/Gear permanent with typed self-death trigger capture and replacement handling | Core 428 |
| `return_to_hand` | return a board object or a card in its owner's trash to its owner's hand as a new object with nothing of the old one; not a Move; a token ceases to exist | Core 124, 124.1, 446.2, 186.1 |
| `recall` | relocate a board object to its current controller's Base keeping damage, exhaustion and modifiers; not a Move, so Move triggers never fire; already there is a no-op | Core 455, 456.1, 458.1 |
| `grant_turn_effect` | record a 'this turn' effect for the controller (entry state for units played this turn), expiring at the Expiration Step | Core 369.3, 317.2.c |
| `discard` | the player moves `count` cards from hand to trash by a private card_selection decision; short hands discard what they have (Core 422.4); not a target | Core 422.1, 422.1.a, 422.4, 124 |
| `grant_replacement` | create a granted replacement bound to a board object's identity, once, for this turn ($granted_target binds inside its replacement_effects) | Core 370, 355.10.c, 124, 317.2.c |
| `heal_all_damage` | clear all marked damage on one object; already clean is a no-op | Core 418 |
| `grant_keyword` | grant Shield X / Tank / Ganking / Backline to a Unit on the board for this combat or this turn, bound to its identity | Core 814.2, 466.7.c, 317.2.c, 124 |
| `mutual_damage_current_might` | two chosen Units deal their current rules-facing Might to each other as one simultaneous action, the Units being the sources; one illegal Unit skips the pair | Core 417.1.d, 417.6.b.3–417.6.b.4, 143.2.b |
| `channel_rune` | put the top runes of a player's Rune Deck on the board in the stated entry state, as many as possible when short; new objects | Core 430.1, 430.2.a, 430.3, 124 |

Return, Recall and Move are three events with three trigger classes; the
engine never derives one from another (DP-06). This version deliberately
excludes Burn Out, simultaneous multi-card recycle, the full Cleanup procedure, open-ended target choice and target
groups, countering, attachments, unrestricted replacement modification inheritance,
layers, cross-object triggers,
scoring, and open-ended token construction. Those require additional state and ordering
contracts; they are not simulated by approximation.

## Replacement event framework

R2 currently supports typed `prevent_event` replacements for an exact effect
operation and optional affected object/controller relation. Replacement
descriptors preserve source, controller, optionality, and remaining uses.

- A replacement is evaluated before the event occurs.
- Optional replacement use requires an explicit apply/decline choice.
- Declining does not consume a use.
- When several replacements apply, the affected object's controller must supply
  a complete unique order.
- The first applied prevention replaces the event with nothing, records
  `replaced_prevented`, consumes its use when finite, and prevents linked
  `if_applied` instructions.
- A replacement is not re-applied after its remaining uses reach zero.

`reduce_damage` implements a finite Prevent Value for `deal_damage`. The value
is reduced by the amount actually prevented. If all damage is prevented, no
Deal event occurs and linked `if_applied` instructions are skipped. If only part
is prevented, the remaining positive Damage is recursively presented to other
Replacement Effects and, if dealt, satisfies the linked action. A depleted
Prevent Value is removed from active state.

### Recursive `replace_with`

`replace_with` removes the original event and executes a nested typed effect
program. The applied replacement is temporarily unavailable to its own child
events, enforcing the once-per-event rule; other active replacements may apply
recursively. Recursion is capped, and any unsupported child prevents the whole
outer program from committing.

If the replacement source leaves the board during its nested program, its
descriptor is not restored. Because the original action did not occur, a linked
`if_applied` instruction remains skipped. Nested trigger descriptors retain a
replacement-prefixed chronological batch.

### “Same event plus” augmentation

`augment_with` implements the bounded Core 370.1.b.1 form that preserves the
original event and then performs an additional typed effect program. The
original event keeps the original program's controller and source; the added
program uses the replacement descriptor's controller and source. Other active
replacement effects may apply recursively to either part.

Linked `if_applied` instructions depend only on whether the original event
actually occurred. The added program still executes when another replacement
prevents or replaces that original event, but its successful execution does not
make the original event count as applied. A finite augmentation consumes one
use, and its descriptor is restored only while its source remains on the board.

### Bounded modifier inheritance

`play_token` carries a typed `event_modifiers` envelope. The current Core 375
slice supports only `entry_state` (`ready` or `exhausted`) and the
`temporary` result keyword. When a token-play event is replaced by one or more
token-play child events, every compatible child inherits those modifiers and
records `modifier_inheritance.rule: Core 375` in its trace.

A modifier that cannot apply to the replacement event is ignored: token entry
state is not attached to a replacement `draw`, matching the official rule's
example. If a child declares a contradictory value for the same supported
modifier, execution fails closed because this slice does not invent a
precedence rule. Other keywords, post-entry linked actions, copy semantics,
token text, attachments, and modifiers for other event families remain outside
the executable contract.

Player-targeted events, uncontrolled Battlefield ordering, general
simultaneous-event replacement sequences, `All` prevention and duration expiry,
broader modification inheritance, and replacement sequences spanning several
simultaneous events are not supported yet. They fail closed rather than being
approximated.

### Bounded simultaneous Kill sequences

`apply_simultaneous_kill_batch` implements the first Core 370.4 and 373 slice
for a simultaneous group of typed Kill events. Each event remains distinct. A
single applicable `prevent_event` descriptor may qualify for one or more events;
when it qualifies for several, its controller must provide a complete unique
`replacement_event_order`. Applied prevention traces precede every unmodified
Kill trace, even when the replacement source is one of the permanents leaving
in that simultaneous group.

Finite uses are consumed in the declared event order. If that consumption
changes state while a lethal Unit remains, `perform_lethal_cleanup` repeats the
cleanup under Core 322. An unlimited prevention that changes no state reaches a
stable stop instead of looping. A replacement descriptor is removed when its
source leaves the board.

Resolution callers submit the versioned
[`cleanup-decisions.schema.json`](../../schemas/cleanup-decisions.schema.json)
contract. Missing order or optional-use
choices returns `replacement_decision_required` without committing timing or
effect state. Optional choices that would require a new decision in a later
follow-up cleanup are not yet representable as one artifact and therefore also
stop without committing. Two or more applicable descriptors, non-prevention
replacement programs, different-controller turn-order execution, and the
general Core 373.2 sequence graph remain fail-closed.

## Kill and lethal cleanup slice

`kill` moves a supported non-token Unit or Gear from a board location to its
owner's Trash. A killed token ceases to exist after entering the non-board zone.
Typed self-death triggers are captured before the object leaves and handed to
the resolution bridge for Pending-item scheduling.

`perform_lethal_cleanup` implements Core 322–323.5 for the supported slice: a
board Unit is lethal when it has a non-zero marked damage value greater than or
equal to its current Might. It processes the simultaneous Kill group through
the bounded replacement sequence above, repeats after a state-changing cleanup,
and records attribution. It does not claim to perform the remaining Cleanup
steps.

## Typed self-death triggers

A supported object may carry ordered `death_triggers`. Kill captures these
descriptors before the object leaves the board. Each descriptor preserves its
trigger id, controller, source object, controller-local order, and optional
effect-program id.

The resolution bridge schedules them as Pending ability items after the current
resolution. When several players control simultaneous triggers, controller
blocks follow Turn Player then Turn Order; within one controller's block,
`controller_order` is mandatory and unique. Missing or ambiguous order prevents
the combined timing/effect commit.

Each trigger is bound to one `effect_program_id`, controller, and source object.
The resolution bridge rejects a mismatched program before either state changes.
If the trigger's effect begins with the rules-level optional “you may,” its
descriptor sets `optional_at_finalize`; the controller must explicitly perform
or decline it. Declining removes the Pending item and treats it as not having
triggered.

This slice covers only the killed object's own death/Deathknell descriptors.
Watching permanents, zone-dependent evaluation, “Nth time,” instruction-level
optional choices made on resolution, and replacement effects remain
unsupported.

## Reflexive trigger emission

`emit_reflexive` models the Chain-producing portion of “Do this:” and “Do this
N times.” It does not execute the nested instructions immediately. Instead it
emits one or more ordered typed descriptors, each bound to its own effect
program, and the resolution bridge schedules them as Pending ability items.

Each effect that emits triggers creates a chronological batch. Turn Player／Turn
Order sorting applies only inside that simultaneous batch; a later event's
triggers cannot move ahead of an earlier batch merely because another player
controls them. The conditional grammar that decides whether a reflexive trigger
is emitted must be represented by the containing typed program and tested per
card.

## Targets and linked instructions

A selector records the chosen object, its board/non-board zone class at choice
time, and — since ADR-0005 — the object's **identity** (`<id>@<generation>`).
Identity survives board moves and changes on any transition to or from a
non-board zone (Core 124, 359.3.e.4), so the same physical card back in the
same zone is a different object and fails revalidation. At execution a
selector can additionally require kind, Base/Battlefield/trash location,
zone ownership, team-aware friendly/enemy controller relation, and a Might
ceiling. A `team_id` on player state makes allied controllers friendly; without
one, distinct controllers are opponents.

Whether a selector **targets** is derived from it (Core 355.7–355.10): a
chosen object on the board, in Trash, or in Banishment targets within the
currently represented zones (Core 355.10.a, 108.6.e); a choice from a
non-public zone does not. A supplied `targeted` that disagrees with the derivation is
`invalid_input`. Callers do not get to change the rules by flag.

A single-target instruction that fails revalidation still records
`ignored_illegal_target` (unchanged value) and now also carries
`target_outcome: skipped_illegal_target` and `completion: none`. A
multi-target instruction (`targets` with `min`/`max` and either concrete
`selectors` or a `decision_ref`) expands into one application per valid
object through the ordinary path — replacements included — and records one
instruction event with `target_outcome` `applied_full` /
`applied_to_subset` / `skipped_illegal_target`, `completion`
`full` / `partial` / `none`, the invalid objects and why, and
`below_minimum` when fewer valid targets remained than the instruction
requires (Core 355.13, 359.3.e.7–8).

Choices arrive through `engine-decisions.v1` (`--decisions` on the runner):
`target_selection` at play declaration or trigger finalization,
`replacement_order` / `replacement_choice` at resolution. A selector or
`targets` with a `decision_ref` and no matching entry returns
`decision_required` naming the decision and its owner. Target selections also
carry `selection_identities`, binding each object when it was chosen so a
leave-and-return cannot be rebound during resolution. Wrong stage, stale hash,
or a missing identity is `invalid_input`; a well-formed choice from the wrong
controller is `illegal`. The legacy
cleanup-decisions object is still read and converted; it is no longer written.

Effects may carry `effect_id` and reference an earlier effect with `depends_on`.
The default `if_applied` mode implements a bounded “if you do”/linked-
instruction gate: if the earlier instruction was ignored or a no-op, the later
instruction records `skipped_linked_dependency`. This does not yet model every
English linking template; card programs must cite and test the exact wording.

## Costs and the play transaction

Playing a card is one atomic transaction (`play_transaction.py`, engine-check
kind `play`): choices (Core 355), total-cost determination (356), payment
(357), legality and chain insertion through the timing kernel (358). Any
failure restores the pre-play state — the result's next hashes equal its input
hashes and the trace ends in `rolled_back` (358.5). A committed play returns
both next states, the pending chain item, and a **cost receipt**.

The played card leaves the hand for the **shared chain** — the effect
state's top-level `chain_items[item_id]`, bound to the timing item, its
controller and its effect program — as a new object (Core 124). When a spell's
instructions finish, the resolution bridge moves it to its owner's trash
(Core 157) with another identity change, removes the chain entry, and only
then runs Cleanup. A Unit or Gear on the chain enters the board at
finalization (359.2) by a procedure the bridge does not have yet, so that
resolution is `unsupported`.

Costs are typed `cost_payment` records, not effects with a `cost: true`
flag. The declaration states base cost, base modifications (356.1),
additional costs marked mandatory or optional (356.2), increases (356.3),
discounts (356.4 — component discounts in the declared, player-confirmed
order, then total discounts on the aggregate Energy including chosen
additional Energy costs, each minimum its own), and total modifications
(356.5); the engine applies them and floors at zero (356.6). Energy and
Power are paid from the player's pool (357.1) as unique payment events that
the receipt's components reference with exact allocations. Any non-zero resource
cost first needs a human to confirm the Add window closed in
`payment_context` — the controller may use Add reactions during payment
(429.3) and the engine never assumes they decline, whether or not the pool
already covers the cost; until then the play is `decision_required`; exhaust and kill costs are paid through the ordinary
operations with a friendly-only selector (357.2), and a payment a replacement
effect prevents still counts as paid (357.2.a). Other non-standard costs are
`unsupported` by name, as is a replacement that needs a choice during
payment.

An optional cost's intent is an `optional_choice` decision at
`play_declaration` stage, owned by the card's controller; without it the play
is `decision_required` (kind `cost_choice`). The receipt records that intent
per component, and `paid` for an optional cost is that decision — a cost
discounted to zero is still paid (356.4.f.1). An unpayable supported cost is
`illegal`.

**Deflect** (809): once the play's targets are fixed and before the cost is
determined, each time the spell chooses an object with the `deflect`
keyword controlled by the opposing team adds a mandatory additional cost of
`deflect_value` (1 when bare, summed across sources, 809.2) any-domain
Power (`power_any`); objects merely affected by criteria are never chosen
and add nothing. Any-domain Power is paid by the player's
`resource_allocation` decision — the complete allocation, summing to the
amount, each domain within the confirmed pool. When only one allocation is
legal the engine proceeds; otherwise the play is `decision_required`
(`cost_choice`), and the engine never spends domains in an arbitrary
order. The Add window (429.3) is settled first; a pool still short after it
is `illegal`; a non-positive Deflect value is `invalid_input`.

A program may carry the receipt as `cost_receipt` and gate an instruction
with `predicate: {kind: cost_paid | cost_not_paid, cost_id}` — "If you do"
and "Otherwise" test the receipt, not whether a later instruction happened.
A predicate that does not hold records `skipped_linked_dependency` with the
predicate; an unknown `cost_id` is `invalid_input`.

The action predicates read the earlier instruction's event, not a flag:
`action_performed` / `action_not_performed` ask whether the **original**
game action happened — a partly prevented deal did (359.3.e.14.c), a wholly
prevented or replaced one did not (359.3.e.14.b, 205), a no-op did not;
`requested_count_not_reached` compares the event's applied count with its
requested count (a short Channel satisfies Mobilize's "If you couldn't",
430.5). It may only reference an instruction with a count contract —
`channel_rune` or a bounded `targets` instruction; referencing anything else
is `invalid_input`, never a guess. Every predicate must name an earlier
instruction; otherwise `invalid_input`.

`sole_controlled_unit_at_referent_location {effect_id}` (En Garde's "if it
is the only unit you control there") reads the earlier instruction's legal
referent at resolution — none, or a referent that was not acted on, means
the condition fails — takes "there" as the referent's current location, and
holds only when the effect's controller (teammates excluded) controls
exactly one unit there and it is the referent. Not holding is
`skipped_linked_dependency / completion: none`, never `illegal`.

Only a completed `move_board_object` raises "When I move" (`move_triggers`;
383.1, 319.8); Recall, return to hand and board entry are not Moves.

`discard {player, count, decision_ref?}` moves cards from the player's hand
to their owner's trash as new objects (422.1, 124). The choice is the
discarding player's, made with private information (422.1.a): a
`card_selection` decision (stage resolution, the player as controller, hand
object ids with their identities) that belongs to that player's own-private
artifacts only — the engine's `decision_required` names the decision and
the player, never the hand. When the whole hand must go the engine proceeds
(422.4); a choice outside the hand or by another player is `illegal`; an
unknown or stale identity is `invalid_input`. "Discard 1, then draw 1" is an
`action_performed` gate: nothing discarded → nothing drawn.

A replacement is either **source-backed** — a permanent's own ability,
active while the source is on the board — or **granted** by an effect
(`grant_replacement`, Highlander's "The next time it would die this turn
…"): bound to the chosen object's identity at grant time, once, for this
turn, stamped with `turn_id` and `granted_by`; exactly one of the two forms
is valid. A granted replacement stops applying after its use, at the
Expiration Step, when the target's identity changes (it left and came back,
Core 124) or when the target is no longer a board object; while it applies
it takes part in the ordinary replacement order and choice decisions.
`heal_all_damage` clears every point of marked damage (418).

`caused_kill` is not an in-program predicate. A Cleanup kill is only known
after the spell has left the chain, so "If this kills it, …" is declared as
a program-level `conditional_triggers` entry: the resolution bridge runs the
instructions, sends the spell to the trash, runs Cleanup, attributes each
Cleanup kill to the spell that dealt the damage immediately before it
(428.5.c) — or to a Kill instruction directly (428.5.b) — and only then
builds the Pending reflexive item (387–388). It shares the chronological
batch of the death triggers the same Cleanup kill produced, so the two are
ordered together by controller in Turn Order (383.3.d). When one controller
owns several triggers in that batch with missing or colliding orders, the
engine never picks: the resolution answers `decision_required`
(`trigger_order_required`, naming controller, batch and trigger ids) and
retries once a `trigger_order` decision in `engine-decisions.v1` supplies
the complete order (383.3.d.1); an incomplete, duplicated or foreign order
is `invalid_input`. A death a replacement prevented
builds nothing. Using `caused_kill` as an effect predicate answers
`unsupported`.

## Battlefield targets, affected objects, and Bonus Damage

"Deal 3 to all enemy units at a battlefield" has one target — the
Battlefield (Core 355.10.b), a selector of `kind: battlefield` with a
bindable identity, chosen at play and revalidated at resolution — and a set
of **affected objects** found by `affected.criteria` when the instruction
executes (355.5.a, 355.10.d). Affected objects are not targets: they get no
355.9 revalidation, no Deflect, no untargetability. The instruction's event
records the targeted Battlefield, the affected non-target objects, the
criteria and a snapshot hash, and one expansion event per object. A
Battlefield target that vanished or changed identity leaves the spell
resolving with that instruction `skipped_illegal_target`; "all units at
battlefields" targets nothing and expands over every Battlefield.

Bonus Damage (713–715) is a property of the Deal action. Sources live in
`damage_modifiers` with a positive amount and a scope: `controller_sources`
(the spell's or ability's controller) or `location` (the affected unit's
current Battlefield); an object source is active on the board, a
Battlefield source while it exists. Once a Deal with a non-zero base is
known to happen (715.4), every active Bonus is summed once (714) and added
per target (715.1–715.2) *before* any replacement, Prevent or
`reduce_damage` sees the amount (437.1.a.1); the event records the base,
the bonus and its sources. An unknown scope is `unsupported`.

## Entry replacements, conditional passives, and the end of the turn

`enter_board` is a replaceable event (Core 369.3): a Unit defaults to
exhausted, Gear to ready; an object's `entry_replacements` (Master Yi Honed:
"I enter ready") and this turn's `turn_effects` of kind
`entry_state_for_played_units` (Confront) replace that state, and the entry
trace records the default, every replacement, and the final state.

`effective_might(state, object)` is `current_might` plus every conditional
passive on the object whose condition holds now (364.3), only while it is on
the board (365.1). "You have N runes" counts the Runes the object's
controller controls on the board — Base or any Board Location, ready or
exhausted — and nothing in Non-Board Zones; a teammate's runes are not
"yours". Target restrictions and lethal Cleanup read `effective_might`;
`current_might` keeps its contract. Dependent or cyclic continuous effects
cannot be expressed and stay `unsupported: continuous_dependency`.

The end of the turn is two procedures (317). `begin_ending_step` leaves the
Main Phase (316.9.b), schedules the turn player's "At the end of your turn"
triggers as one batch — a trigger's own condition, such as "if I'm at a
battlefield", is part of the trigger condition and is checked now
(383.2.a.1) — and stops. `run_expiration_step` runs only once those chain
items and every outstanding task are done: one Ending Special Cleanup that
heals all Units, expires every "this turn" effect of this turn at once, and
empties every pool (317.2.b–317.2.d). Every "this turn" modifier and turn
effect carries the `turn_id` it belongs to, so another turn's effects are
never cleared. Wrong phase, an unfinished chain, or outstanding tasks are
`illegal`; an unknown turn-effect kind is `unsupported`. The next Beginning
Phase is not modelled and no complete turn transition is claimed.

## Permanent entry and play triggers

A Unit or Gear resolves by the entry procedure (ADR-0007 §1), not the spell
path: it leaves the shared chain and becomes a new object on the board
(Core 124); entry replacements apply to the default state — Unit exhausted
(143.4, 359.2.c), Non-Unit Gear ready (359.2.d); the Unit enters the
`entry_location` chosen while playing (355.2) and stored on the chain entry,
Gear its controller's Base; then the play is complete and "When you play
me" triggers are collected (419.4.a) as one batch, scheduled with the
resolution's other triggers, before the board-entry Cleanup (319.6). A Unit
entering a Battlefield its controller does not control marks it `contested`
with `contested_by`; no control transfer, Showdown or Combat is inferred.

A Unit's location is legal at play if it is the controller's Base, a
Battlefield the controller controls, or an open Battlefield (unoccupied and
uncontrolled, 170.11.c) when the card carries the compiled permission
`play_permissions: ["open_battlefield"]` (355.2.b). A Battlefield missing
from the state is `invalid_input`; one that exists but fails the rule is
`illegal`. The choice is not reopened later: the permanent enters the chosen
location whatever happened to it since (359.2.c).

## Combat designations and Attack / Defend triggers (ADR-0008 §1, §3)

A Unit in a Combat carries `combat_designation: {combat_id, role}`; nothing
else in the effect state says a Combat is happening. Designations are
assigned when the Combat opens and kept in step with presence by Cleanup
(323.2): a Unit of a participant that becomes present at the Combat
Battlefield gains its controller's designation, one elsewhere loses it, and
a zone change to a non-Board zone drops it with the old object (124.1).
`attack_triggers` / `defend_triggers` are trigger descriptors (optionally
with the `at_battlefield` condition) that fire when the Unit gains the
matching designation, once per object identity per Combat (383.4.e.2.a,
383.4.f.2.a): losing and regaining the designation does not trigger again,
leaving and returning is a new object and does. A Battlefield's own
`attack_triggers` / `defend_triggers` (Fortified Position) fire when its
controller gains that designation; uncontrolled, "you" refers to no one
(190.6.a, 190.6.d).

## Combat-relative Might and granted characteristics (ADR-0008 §5)

`effective_might` stays the rules-facing read and adds, on top of the
conditional passives: Shield while the Unit carries the Defender designation
(814.1.c; every printed and granted Shield value summed, an omitted X being
1, 814.2), the `attacking_or_defending_alone` condition (a designation and
no other friendly Unit at the location, team-aware, 740.2.a), and
`might_auras` with the bounded `friendly_unit_defends_alone` condition (an
external source, active on the board, over each friendly lone Defender). A
negative total is read as 0 (143.2.b) while `current_might` keeps the
arithmetic value. The keywords `shield` (with `shield_value`), `tank`,
`ganking` and `backline` are printed characteristics; `grant_keyword` adds
a `keyword_modifiers` entry bound to the object's identity now and to the
Combat in progress (`this_combat`, active only while the Unit's designation
names that Combat, expiring together at 466.7.c) or to this turn
(`this_turn`). A 'this combat' grant outside a Combat is unsupported: the
context comes from the resolution bridge, never from a caller's flag.

## Combat-scoped area effects and mutual Might damage (ADR-0008 §7)

`affected.criteria.location: active_combat` finds the Units at the Combat
Battlefield that carry that Combat's designation (740.2.c) — affected
objects, never targets, with the controller relation team-aware. The Combat
comes from the procedure context the resolution bridge supplies; with no
Combat in progress the set is empty and the instruction is a supported
no-op, and a claimed Combat whose Battlefield the state cannot confirm is
unsupported. `mutual_damage_current_might` revalidates both chosen Units,
snapshots both rules-facing Mights before either Deal, then performs the two
Deal events as one simultaneous Deal batch with the Units as the damage
sources (417.6.b.3, so no spell-scoped Bonus Damage and the responsible
player is each Unit's controller): every replacement's applicability is read
from the one pre-Deal state, and only mandatory Prevent values that belong to
exactly one of the two Deals are applied; any other mode, an optional
descriptor, or one descriptor over both Deals is unsupported rather than
resolved one Deal after the other; a Might that reads 0 deals nothing
(417.1.e); it is not Combat Damage.

## Execution model

An effect program is an ordered list. The interpreter executes it on a copied
state and emits one trace event per operation. A valid supported program commits
only after all operations succeed. An unsupported or malformed operation does
not expose a guessed `next_state`.

This fail-closed authoring model is intentionally stricter than resolution in a
real match, where some impossible instructions are ignored and later linked or
unlinked instructions may continue. Card programs cannot be considered faithful
until later R2 work models instruction linkage, targets, conditions, and
impossible-instruction semantics explicitly.

`resolution_bridge.py` combines one rules-core Chain Item with one supported
effect program. The bridge probes both pure transitions and exposes next timing
and effect states only if both succeed. An unsupported effect therefore cannot
remove a Chain Item, and an item that is not next to resolve cannot mutate the
effect state. The bridge runs the bounded lethal-cleanup slice after the effect
program; unsupported death-trigger handling prevents both states from
committing.
