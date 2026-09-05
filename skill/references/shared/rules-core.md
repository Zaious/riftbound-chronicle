# Chronicle Sovereign Rules Core

Read this reference when an answer depends on Open/Closed state, Showdown,
Action/Reaction timing, Priority, Focus, Pending/Finalized Chain Items, or the
HOT/FEPR procedure.  This is Chronicle-owned executable knowledge; it is not a
complete card-effect engine and never outranks the current official sources.

## Sovereignty contract

- Chronicle owns the schemas, terminology, executable cases, implementation,
  versioning, and release decisions in this repository.
- The core has no runtime dependency on another fan simulator, AI project,
  model vendor, or private API.
- Official rules and scoped official FAQs are normative.  If an executable
  result disagrees, record a conformance failure and fix or version the core.
- Every result identifies its rules baseline and source locators.
- Unsupported card behavior is unknown, never inferred as legal or resolved.

The initial implementation is `${CLAUDE_SKILL_DIR}/scripts/rules_core.py`; its
state schema is `${CLAUDE_SKILL_DIR}/schemas/rules-core-state.schema.json`, and
its executable fixtures are `${CLAUDE_SKILL_DIR}/data/rules_core_cases.json`.
A case may carry an optional `source` naming the official document, its version,
and the exact clause the case encodes; `check_rules_core.py` fails if a cited
version drifts from the corpus baseline, so a clause is re-read rather than
inherited when the baseline moves.
Supported card-state mutations live separately in
`${CLAUDE_SKILL_DIR}/references/shared/effect-ir.md`; timing permission does not
imply effect support.

## Four-state timing model

| State | Showdown/Combat | Chain | Timing permission |
| --- | --- | --- | --- |
| Neutral Open / 普通開環 | no | no | by default, the Turn Player with Priority in Main may play or activate legally timed cards/abilities |
| Neutral Closed / 普通閉環 | no | yes | the Priority holder may add only Reaction / 反應 items |
| Showdown Open / 法術對決開環 | yes | no | the player with Focus and Priority may start a Chain with Action / 迅捷 or Reaction / 反應 |
| Showdown Closed / 法術對決閉環 | yes | yes | the Priority holder may add only Reaction / 反應 items |

Do not confuse rules `Closed State / 閉環` with a Deck Coach evaluation
`closed loop`.  Machine fields use `chain_state` or the combined four-state
label for rules, and `evaluation_cycle` for product feedback loops.

## HOT/FEPR

The core must expose the next required procedure rather than jumping directly
from a proposed card to a guessed board state:

```text
Handle Outstanding Tasks
  -> Finalize pending items oldest-first
  -> Execute or pass Priority
  -> after every player passes in sequence
  -> Resolve the newest Finalized item in full
```

Units, Gear, and Add abilities require immediate resolution when finalized.
Their special handling must be explicit in the transition trace.  Pending
items finalize oldest-first, while Finalized items resolve newest-first.

## Safe use by each system

- **Deck Coach:** validate that a proposed sequence has a supported timing
  path; do not turn an unsupported effect into a strategic claim.
- **Rule Consult:** use the executable trace as a consistency check after
  retrieving official text.  The cited official source remains the answer's
  authority.
- **Player 2 Agent:** when a sufficiently structured state exists, remove
  timing-impossible candidates before strategy ranking.  Card-effect coverage
  or missing facts can still require human legality confirmation.
- **Match Analyst (planned):** reconstruct one perspective-safe timeline. Review
  distinguishes a rules execution error from a legal but strategically weak
  choice; Commentary explains confirmed sequences and turning points. Missing
  hidden information or timing facts must produce `unknown`, not a misplay or
  invented narration.

## Combat record (ADR-0008 §1–3)

The timing state may carry one `combat` record — `combat_id`, the Battlefield
and its identity, `status` (staged, open, then the damage / cleanup / result /
closed steps), attacker, defender, the two participants, and the object
identities whose Attack / Defend triggers already fired this Combat. The
Showdown record gains an optional `battlefield`. Absence means no Combat is
staged or open; it is never read as an unknown Combat fact. `combat.py`
holds the procedures over the timing/effect pair: `stage_combat` (Contested
applied, Units of exactly two opposing players; the Turn Player chooses among
several by a `location_selection` decision; three controllers at one
Battlefield are unsupported, never reduced to a pair), `open_combat` (the
attacker is `contested_by`, the defender the other participant; a new Combat
Showdown gives the attacker Focus, an existing one at that Battlefield keeps
its Focus; Units present gain designations and their triggers form the Combat
Chain attacker first, defender last), and `sync_combat_designations` (the
Cleanup task of 323.2, also run by the resolution bridge after its Cleanup).
Decisions for these procedures bind to `combined_input_hash(timing, effect)`,
which every result reports as `input_hash`.

`pass_focus` is the Showdown's own transition (347.2): until every player
has passed Focus in sequence, Focus and Priority move to the next player;
a play breaks the sequence. When all have passed, a Combat Showdown closes
into the Combat Damage Step (348.1) — the record moves to `showdown_closed`,
`next_procedure` reports `combat_step_pending` with no discretionary play,
and `combat.assign_combat_damage` takes over: if both sides still have
designated Units, each side's Might is summed (Stunned Units contribute
nothing, negative Might reads 0) and, attacker first, each player's
complete `damage_assignment` is validated against 465.2.c in full — lethal
in full before another Unit, no over-assignment while another Unit remains,
Tank first and Backline last with a per-Unit choice when a Unit has both,
minimum lethal computed with the Unit's damage replacements previewed
(465.2.c.5; only Prevent values are previewable, anything else is
unsupported). The engine proceeds by itself only when exactly one
assignment is legal. A receipt per side records raw, prevented and applied
amounts and the replacements the Deal step will consume exactly once. A
Non-Combat Showdown's close establishes control (348.2) and is refused as
the G2 boundary.

`validate_timing` also answers `kind: standard_move` (ADR-0008 §6, Core
144.1): legal only for the Turn Player in their Main Phase in a Neutral Open
State with no Combat staged or in progress. `combat.standard_move` is the
player action itself: one destination for every selected ready Unit the
actor controls, all exhausted at once as the cost (144.2–144.3.c; an
unconfirmed cost is `decision_required`), Base→Battlefield and
Battlefield→own Base by default, Battlefield→Battlefield only with active
Ganking (144.4.c, 810.1.c — a permission, never an extra move), a
Battlefield holding two other players' Units refused (144.4.a.1). The
relocation delegates to the Move operation so Move triggers and Cleanup stay
one implementation; engine-check wraps it as `standard_move`.

## Current coverage

Version 1 covers the four-state permission model, the next HOT/FEPR procedure,
and structural timing transitions: add a Pending item, finalize oldest-first,
pass Priority, complete exactly one newest Finalized resolution, and move or
retain Focus when the Chain empties. Every transition includes reproducible
before/after state hashes and rule locators.

Triggered Pending Items may bind an effect program and declare an optional
Finalize choice. The controller must explicitly perform or decline an optional
trigger; after the last Pending item finalizes, Priority is granted to the
controller of the newest Finalized item.

Trigger scheduling preserves chronological batches. Simultaneous triggers in
one batch use Turn Player／Turn Order controller blocks; separate event batches
remain ordered by `batch_sequence`. Self-death and Reflexive descriptors share
this scheduler without becoming the same kind of trigger.

It does not execute arbitrary card instructions, combat, scoring, replacement
effects, layers, or a complete game. `complete-resolution` requires the caller
to confirm that the effect was executed; the timing core never invents the
result of unsupported card behavior.
