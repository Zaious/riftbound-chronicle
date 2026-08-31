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
| `move_board_object` | move one known object between Base/Battlefield locations | Core 420, 445 |
| `modify_might` | append a typed Might modifier with source and duration | Core 135.2.e.3, 477 |
| `deal_damage` | mark positive damage on one unit/object | Core 417 |
| `heal_damage` | clear up to a specified amount of marked damage | Core 418 |
| `ready` | ready a supported board object; already ready is a no-op | Core 415 |
| `exhaust` | exhaust a supported board object; already exhausted is a no-op | Core 414 |
| `add_resource` | add Energy or domain-labelled Power | Core 429 |
| `play_token` | create one explicitly identified Unit/Gear token at a Base or Battlefield; Units default exhausted and Gear ready | Core 143.4, 149.1, 184–186, 349, 375 |
| `kill` | kill a supported Unit/Gear permanent with typed self-death trigger capture and replacement handling | Core 428 |

This version deliberately excludes Burn Out, simultaneous multi-card recycle,
cost payment, the full Cleanup procedure, open-ended target choice and target
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

R2 v1 records the target's object id and board/non-board zone class at choice
time. At execution it can additionally require kind, Base/Battlefield location,
and friendly/enemy controller relation. A failed requirement produces
`ignored_illegal_target` without mutating state.

Effects may carry `effect_id` and reference an earlier effect with `depends_on`.
The default `if_applied` mode implements a bounded “if you do”/linked-
instruction gate: if the earlier instruction was ignored or a no-op, the later
instruction records `skipped_linked_dependency`. This does not yet model every
English linking template; card programs must cite and test the exact wording.

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
