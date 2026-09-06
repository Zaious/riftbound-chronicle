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
unsupported — so this is a bounded slice of 465.2.c, not the full contract:
damage-exemption sources (465.2.c.10) and non-Prevent assignment
replacements are declared unsupported). The engine proceeds by itself only when exactly one
assignment is legal. A receipt per side records raw, prevented and applied
amounts and the replacements the Deal step will consume exactly once. A
Non-Combat Showdown's close establishes control (348.2) and is refused as
the G2 boundary.

The rest of the Combat is four refusable steps. `deal_combat_damage` Deals
every applied amount at once from the receipts, consuming the previewed
Prevent values now and never applying a replacement twice, with the
opposing Units as sources (465.2.d, 417.6.c); FEPR is skipped (465.3).
`combat_cleanup` runs one Combat Special Cleanup in the order of 323 — step 2
designations follow presence first (a Unit that arrived during the Showdown
is a Defender before lethal damage is judged), then 3a/3b lethal Cleanup with
each Combat-Damage kill attributed to the opposing side's Units and their
controller (428.5.c.2), heal all Units, Recall Attackers if Defenders remain,
and a 324.2 follow-up Cleanup that drops the recalled Units' designations —
scheduling the designation triggers before the death triggers.
`determine_combat_result` waits for that chain to empty (466.2) and applies
466.3: win only when one designated player alone has Units remaining, No
Result on a Recall, on both remaining (which stages again) or on neither.
`deal_combat_damage` requires the effect state and the receipts exactly as
they were at assignment (465.2.c.1.a leaves no window); anything else is a
stale receipt and nothing is Dealt. `close_combat` removes designations, the
Combat and Showdown records and every 'this combat' effect of this Combat at
once (466.7), stages a fresh Combat when both sides remain (466.3.d.1, with
`open_combat` the next required procedure). Before it, 466.5 is
`battlefield_control.resolve_battlefield_control` (ADR-0009): the one player
whose Units remain establishes control if they did not hold it and Conquers
unless they already scored that Battlefield this turn (469.1, 470), Contested
is cleared (466.5.a), no Units left makes the Battlefield Uncontrolled
(466.5.b), and the Score triggers of the scoring player's board objects and
of the Battlefield form the chain that must empty before the Combat closes
(466.6). Scoring is one transaction: the Final Point rule (471.1.b) gives the
point only when every Battlefield was scored this turn and otherwise draws
instead, and a draw that would Burn Out refuses the whole transaction as
unsupported. The victory condition is reported as facts (threshold_met,
strict_leader, tied_at_threshold; 472) and never enacted.

Non-Combat Showdowns (ADR-0009 §3, §4, §9) live in the same module. At a
quiet Cleanup boundary `stage_showdown` rebuilds `staged_showdowns` from the
board (Contested applied, the applier's Units present, no opposing Units,
nothing ongoing there; 316.8.b, 323.8, 323.8.a) and `open_showdown` opens one
from a Neutral Open State — several staged need the Turn Player's
`location_selection` `showdown_location` (323.12) — as a `non_combat`
Showdown whose Focus goes to the player who applied Contested (345), before
323.13 stages any Combat. When every player has passed Focus in it,
`pass_focus` marks the Showdown `closing` and `resolve_battlefield_control`
is the next required procedure (348.2): exactly one player with Units there
establishes control and may Conquer, no Units at all closes the Showdown and
leaves control loss to the next board Cleanup (323.6), both players present
is refused as unsupported. `run_board_cleanup` applies, per Battlefield with
no ongoing Showdown or Combat (a merely staged one exempts nothing), 323.6
control loss, 323.11 Contested removal and 323.11.a re-application by the
one non-controller present (two different ones are unsupported), and reports
the victory facts. A Cleanup boundary runs it before `stage_showdown`, then
`stage_combat`; if an eligible Non-Combat Showdown exists, `open_showdown` is
the next required procedure (323.12), otherwise the staged Combat opens
(323.13). No discretionary action occurs between staging and that choice.
`run_scoring_step` is the Scoring Step (315.2.b, ADR-0009 §8): with the
caller-supplied phase `beginning`, an empty chain and no Showdown or Combat,
the Turn Player Holds every Battlefield they control and have not scored this
turn (469.2, 470), gaining a point each with no Final Point restriction
(471.1.a.1); the Hold triggers of all held Battlefields form one batch
(315.2.b.2, 471.2.b). Every scoring trace and the `victory_facts` step report
472 as facts only.

The terminal state (ADR-0010 §3–4) is `terminal.check_terminal`, Cleanup
step 1 (323.1, 194.2): the one player at or above the Victory Score with more
points than every other player wins and the game ends (196); a tie at the
threshold continues (194.2.b, `continue_tied`); the record names the reason
(`victory_score` and `burn_out_victory` are derived by the engine only;
`concession` and `external` are recorded from the caller by
`declare_terminal`), the winner, the final points and the turn. After it the
snapshot is frozen, chain items included: `next_procedure` reports
`game_over`, `validate_timing` answers `legal: false`, and every kernel
mutator, two-state procedure, resolution and play refuses `game_over` at its
shared entry. `reward_adapter.terminal_reward` is a read-only projection of
that record for a two-player game (+1 / −1 / 0) and is not an engine check.

The Start of Turn (ADR-0010 §1, §6–9) is `turn_cycle.py`: `begin_turn`
(317.3; from `setup` the selected first player keeps the turn, from an
expired Ending Phase the next player in Turn Order; turn_id advances, the
per-turn ledger is pruned, `turns_taken` increments and the First Turn
Process is read from `mode.id` — duel, skirmish — or explicit
`mode.first_turn` facts, never guessed), `run_awaken_step` (315.1; a ready
blocker is unsupported), `enter_beginning_phase` (315.2.a triggers, the
Scoring Step outstanding after them), G2's `run_scoring_step`,
`run_channel_step` (315.3 plus the first-turn extra), `run_draw_step`
(315.4 through the Burn Out-aware Draw, skipped on a first turn the mode
says so, an immediate Burn Out victory written here) and `enter_main_phase`
(316.2–316.4, Priority to the Turn Player). Each accepts only the phase and
`turn_progress` the previous step left, every phase transition makes a
Cleanup outstanding (319.2), and `next_procedure` reports
`turn_start_step_pending` with no discretionary action during 315. `match`
and team modes are unsupported as a whole; Setup itself is not modelled.

`turn_cycle.run_cleanup` (ADR-0010 §5) is one Cleanup as one atomic run:
steps 1–10a of 323 in order on a working state — the terminal check, the
designation sync, the lethal Cleanup whose death triggers go Pending on the
chain while nothing resolves (320), control loss, 323.7 (refused as
unsupported whenever a non-Unit Gear or Rune is at a Battlefield), Showdown
staging, Combat staging, Contested maintenance, Showdown opening and Combat
opening — then the 322 follow-up Cleanups on the same working state until
one changes nothing. A terminal at step 1 ends the run with the rest
recorded as `skipped_after_terminal`; any `decision_required` or unsupported
step commits nothing; the outstanding Cleanup task, when first, is consumed.
Inside the run the staging and opening procedures accept Pending chain items
and the task being handled (`within_cleanup`); called on their own they
still require the quiet boundary.

`validate_timing` also answers `kind: standard_move` (ADR-0008 §6, Core
144.1): legal only for the Turn Player in their Main Phase in a Neutral Open
State with no Combat staged or in progress. `combat.standard_move` is the
player action itself: one destination for every selected ready Unit the
actor controls, each bound to its identity in the declaration, all exhausted
at once as the cost (144.2–144.3.c; an unconfirmed cost is
`decision_required`), Base→Battlefield and Battlefield→own Base by default,
Battlefield→Battlefield only with active Ganking (144.4.c, 810.1.c — a
permission, never an extra move), a Battlefield holding a teammate's Units
(447.2.b) or two other players' Units (144.4.a.1) refused. Its decisions
bind to the hash of timing state, effect state and declaration together. The
relocation delegates to the Move operation so Move triggers and Cleanup stay
one implementation; engine-check wraps it as `standard_move`.

## Removing a countered chain item (ADR-0011 §5)

`remove_chain_item` clears one item from the Chain when an effect Counters
it (425.1). It is the timing half of a Counter: the effect IR moves the card
(425.1.a) and reports `countered_chain_items`, and the resolution bridge
calls this in the same commit. Removing the item clears the pass sequence
and, when the Chain empties, reopens the state exactly as a completed
resolution would. An item that is not on the Chain answers
`chain_item_not_found` and changes nothing.

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
