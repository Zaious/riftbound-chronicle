# Engine-check CLI examples

Input files for the commands in
[`../../references/shared/engine-check.md`](../../references/shared/engine-check.md).
Every command in that document's runner block runs as written against these
files, and `skill/scripts/check_engine_check.py` executes each one and asserts
the outcome it produces — so a documented command that stops working fails CI
rather than failing a reader.

| File | Used by | Produces |
| --- | --- | --- |
| `timing-state.json` | `timing` | Neutral Open, Main Phase, Turn Player holds Priority |
| `proposed-action.json` | `timing --payload` | `supported` — the Turn Player may play a unit here |
| `effect-state.json` | `effect`, `resolution` | Two units on the board, one card in each deck |
| `effect-program.json` | `effect`, `resolution` | `supported` — a typed one-card draw |
| `closed-timing-state.json` | `resolution` | Closed state with finalized chain item `spell-1` |
| `cleanup-state.json` | `cleanup` | `decision_required` — two simultaneously lethal objects under one `prevent_event` replacement |
| `cleanup-decisions.json` | `cleanup --cleanup-decisions` | `supported` — the same state once the controller supplies the event order |
| `play-timing-state.json` | `play` | Neutral Open, `p1` holds Priority, empty chain |
| `play-effect-state.json` | `play` | `c1` in `p1`'s hand, 3 Energy and 1 Fury in the pool, one ready unit |
| `play-declaration.json` | `play` | A 2-Energy 1-Fury spell with an optional exhaust-a-unit additional cost |
| `play-decisions.json` | `play --decisions` | `supported` — the controller's intent to pay the optional cost; without it the play is `decision_required` |

The last two rows are the point of the set: the same state answers
`decision_required` without the decision and `supported` with it. The component
does not choose an order to keep going.

These are engine inputs, not card data or rules text. They assert nothing about
Riftbound beyond what the bounded components already model, and nothing here is
official. Regenerate expectations by running the commands; do not hand-edit a
file to make a check pass.
