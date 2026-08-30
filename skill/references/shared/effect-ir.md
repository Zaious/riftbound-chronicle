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
| `kill` | kill a supported Unit/Gear permanent without death-trigger or replacement handling | Core 428 |

This version deliberately excludes Burn Out, simultaneous multi-card recycle,
cost payment, the full Cleanup procedure, open-ended target choice and target
groups, countering, attachments, replacement effects, layers, triggers,
scoring, and token creation. Those require additional state and ordering
contracts; they are not simulated by approximation.

## Kill and lethal cleanup slice

`kill` moves a supported non-token Unit or Gear from a board location to its
owner's Trash. A killed token ceases to exist after entering the non-board zone.
Objects with death-trigger metadata fail closed until trigger scheduling exists.

`perform_lethal_cleanup` implements only Core 323.3–323.5: a board Unit is
lethal when it has a non-zero marked damage value greater than or equal to its
current Might. It passively kills every supported lethal Unit and records their
simultaneous group and attribution. It does not claim to perform the remaining
Cleanup steps.

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

This slice covers only the killed object's own death/Deathknell descriptors.
Watching permanents, zone-dependent evaluation, “Nth time,” optional-at-
finalize choices, reflexive triggers, and replacement effects remain
unsupported.

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
