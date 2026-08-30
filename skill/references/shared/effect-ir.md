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

This version deliberately excludes Burn Out, simultaneous multi-card recycle,
cost payment, kill/cleanup, targeting, countering, attachments, replacement
effects, layers, triggers, scoring, and token creation. Those require additional
state and ordering contracts; they are not simulated by approximation.

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
effect state.
