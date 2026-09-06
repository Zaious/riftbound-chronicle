# ADR-0010 — G3 Start of Turn, Burn Out, terminal state and Cleanup orchestration

- Status: Accepted (Codex rulings on the Round F packet, 2026-09-06)
- Scope: the G3 milestone — the Start of Turn state machine, Burn Out on
  Draw, the terminal state and its guard, a whole-Cleanup orchestration, the
  turn transition, and the reward projection consumers read.
- Rules baseline: English Core Rules 2026-07-16, especially 115, 194, 196,
  303.2.a, 315–317, 319–324, 413, 415, 430, 431, 472, 481–489.
- Not decided here: team modes and Match / Best-of formats (486.6, 489);
  Burn Out from instructions other than Draw (431.1.b); Predict / look /
  reveal exceptions (431.1.c, 436.4.a); "gain points" and "lose points" card
  effects (194.1.c, 194.4); ready blockers (Stun and others, 423); 323.7
  Gear / Rune Recall and Hidden; facedown reveal at game end (421.4); Setup
  itself (485.5 and the like); concession and judge rulings beyond recording
  them; policy evaluation (R5-B).

## Context

After ADR-0009 the engine stops at three points: `score_battlefield` refuses a
draw-instead from an empty Main Deck as `unsupported: burn_out`, the effect
IR's `draw` cannot Burn Out, and `victory_check` reports facts without ending
anything. The Start of Turn (315) has no state machine — `phase` is a fact
the caller supplies — and nothing follows the Expiration Step (317.3). No
Wave-A clause references Burn Out, victory or the Beginning Phase, so G3 is a
procedure milestone; the Draw clauses that stayed `partial` for want of Burn
Out are re-derived once every Draw entry is bridged to the terminal state.

## Decisions

### 1. The Start of Turn is an explicit state machine with typed progress (DP-48)

The timing `phase` enumeration gains `setup`, `awaken`, `beginning`,
`channel` and `draw`; `main` and `ending` keep their meaning. A typed
`turn_progress` record separates "the phase was entered" from "its
procedure completed" (`awaken_complete`, `beginning_entered`,
`channel_complete`, `draw_complete`, `main_entered`). Every phase transition
makes a Cleanup outstanding (319.2); the next phase is never reached by a
caller editing `phase`. During 315 `next_procedure` reports the pending Start
of Turn step and no discretionary action is legal. The procedures live in
`turn_cycle.py` and wrap under engine-check kind `turn_step`.

### 2. Burn Out is a replacement on Draw; the Trash order is an external randomization receipt (DP-49)

The effect IR's `draw` becomes Burn Out-aware (413.4, 431.2): draw as many as
possible; Recycle the Trash into the Main Deck in the order given by a
`randomization-receipt.v1` bound to the input hash and an operation id and
carrying the complete permutation and its provider / method provenance — the
order is never a player choice and never `card_selection`; every recycled
card is a new object (124); one opponent gains one point — automatic with
exactly one opponent, otherwise a `player_selection` decision; then the
remaining cards are drawn. A missing receipt or beneficiary is
`decision_required` (external input) and nothing changes; a permutation that
is not the Trash exactly is `invalid_input`. Every receipt and beneficiary the
whole Draw needs must be present before anything commits.

With an empty Trash (431.3) each further attempt Burns Out again for one
point until an opponent reaches the Victory Score with a strict lead and wins
at once (431.3.c.1). The loop bound is derived from the scores — the points
needed to lift every opponent past the current top score plus one — and
exceeding it without an immediate winner is `invalid_input`.

The effect IR never writes the timing state. A Draw that ends the game emits
a typed `terminal_event`; `resolution_bridge`, the G2 control and scoring
transactions and `run_draw_step` write it into `timing.terminal` inside their
own atomic two-state commit. Draw clauses stay `partial` until every Draw
entry is bridged. Burn Out from a non-Draw instruction is
`unsupported: burn_out_non_draw`.

### 3. The terminal state is state, guarded at the shared entries (DP-50)

The timing state carries an optional `terminal: {status: "ended", reason,
winner, final_points, turn_id, derived, rule_locators}`. Two reasons are
derived and only the engine writes them: `victory_score` (323.1, 194.2) and
`burn_out_victory` (431.3.c). Two are declared by the caller with
`derived: false` through `declare_terminal`: `concession` and `external`
(winner may be null). `check_terminal` is Cleanup step 1: a strict leader at
or above the Victory Score ends the game; a tie at the threshold continues
(194.2.b) and is recorded as `continue_tied`. After the terminal state
`next_procedure` reports `game_over`, `validate_timing` answers `legal:
false` with `game_over`, and every procedure refuses at its shared entry —
the timing kernel and the two-state validators, not each function on its
own. The snapshot is frozen, chain items included.

### 4. One winner, and nothing runs after the terminal (DP-51)

Several players at the threshold resolve to the one with more points; equal
points continue. `check_terminal` judges the whole state once; a Burn Out
victory is written inside the Draw's transaction with `immediate: true`. Once
a Cleanup's step 1 or an inner Burn Out establishes the terminal, the
remaining Cleanup steps are not executed and are recorded as
`skipped_after_terminal`.

### 5. A Cleanup is one atomic run that never pauses on the chain (DP-52)

`run_cleanup` performs the steps of 323 in order — 1 `check_terminal`, 2
designation sync, 3a/3b lethal Cleanup, 4 control loss, 5 (323.7, refused as
`unsupported: gear_rune_recall_cleanup` whenever it would apply), 6 Showdown
staging, 7/7a Combat staging, 8/8a Contested maintenance, 9 Showdown
opening, 10/10a Combat opening — on one working state. Chain items are
neither finalized nor resolved during a Cleanup (320): death triggers from 3a
stay Pending and the Cleanup continues to 10a; when its events call for
another Cleanup (322) the follow-up iterations run on the same working state,
Pending triggers accumulating in chronological batches; only when every
Cleanup task is done does the state return to HOT / FEPR. The whole chain of
iterations commits atomically or not at all: any `decision_required` or
unsupported step leaves nothing committed, and step 5 fails the whole run
closed. There is no half-committed progress record.

### 6. The turn transition keeps the first player and reads the Mode of Play (DP-53)

The game opens in `phase: setup` (Setup itself may be unsupported). The
first `begin_turn` keeps the selected first Turn Player; only the 317.3 path
advances to the next player in Turn Order. `begin_turn` moves `turn-<n>` to
`turn-<n+1>`, prunes `scored_this_turn` to the new turn, clears the Ending
Step record and increments `turns_taken` for the player starting the turn;
first-turn rules read the count before the increment. `mode.id` from the
sanctioned catalogue (`duel`, `skirmish`, `war`) or an explicit
`mode.first_turn: {extra_channel, skip_draw}` supplies the First Turn Process
(483.7, 485.7, 487.7); both absent on a player's first turn is `unsupported:
first_turn_process_unknown`. `match` carries 486.6 Game Win semantics and is
unsupported as a whole; `magma_chamber` and any team stay `team_scoring`.

### 7. Awaken readies what can be readied (DP-54)

`run_awaken_step` readies, at once, every Board object the Turn Player
controls that can be readied (315.1, 415.3.a). A known or unknown ready
blocker — `stunned` included — whose complete rule this slice lacks is
`unsupported: ready_blocker_unknown`. It writes
`turn_progress.awaken_complete`; entering the Beginning Phase is a separate
procedure.

### 8. Beginning and Main Phase game effects (DP-55)

`enter_beginning_phase` requires `awaken_complete`, enters `beginning`,
schedules `beginning_phase_triggers` (scope `your_beginning_phase`) of the
Turn Player's active Board sources, makes the `scoring_step` task
outstanding and the 319.2 Cleanup. `enter_main_phase` requires
`draw_complete`, empties every Rune Pool (316.3), schedules
`main_phase_triggers` (scope `your_main_phase`), sets `phase: main` and
Priority to the Turn Player, and makes the transition Cleanup. Opponent or
global watchers are not claimed.

### 9. Channel and Draw (DP-56, DP-57)

`run_channel_step` requires the Beginning triggers, the Scoring task and the
related Cleanups done, enters `channel`, Channels two Runes (plus the
first-turn extra; fewer if the Rune Deck is short, 430.3) and writes
`channel_complete`. `run_draw_step` requires `channel_complete`, enters
`draw`, draws one (skipped for a first-turn `skip_draw` player) through the
Burn Out-aware Draw, writes `draw_complete`, and on an immediate Burn Out
victory writes the terminal in the same commit and stops.

### 10. Reward is a versioned read-only projection (DP-58)

`reward_adapter.terminal_reward(timing, player)` reads only `terminal` of a
two-player non-team game: winner +1, the other −1, ongoing or no winner 0;
it names the terminal hash, player and reason; an unknown player is invalid;
anything else is unsupported. It never reads point margins, turn counts or
strategy, and it does not enter the engine-check envelope.

### 11. Versioning and vocabulary (DP-59)

Everything is additive on the v1 schemas: timing `phase` values `setup`,
`awaken`, `beginning`, `channel`, `draw`; `terminal`, `turn_progress`,
`turns_taken`; effect `mode.id`, `mode.first_turn`,
`beginning_phase_triggers`, `main_phase_triggers`; the decision kind
`player_selection`; `randomization-receipt.v1`; procedures `check_terminal`,
`declare_terminal`, `begin_turn`, `run_awaken_step`,
`enter_beginning_phase`, `run_channel_step`, `run_draw_step`,
`enter_main_phase`, `run_cleanup`. `burn_out` leaves a scope only once every
Draw entry of that scope is bridged to the terminal state; 323.7, ready
blockers, non-Draw Burn Out and team / Match keep `complete_game: false`.

## Implementation order

1. C-36: the terminal record, `check_terminal` / `declare_terminal`, the
   shared game-over guard, the reward adapter.
2. C-37: the randomization receipt, the Burn Out-aware Draw, the
   `terminal_event` bridge in every Draw entry, the G2 draw-instead wiring.
3. C-38: `setup` / `turn_progress`, the Mode of Play and First Turn Process,
   the Awaken / Beginning / Channel / Draw / Main procedures with 319.2
   Cleanup gating.
4. C-39: the atomic `run_cleanup` with 322 iterations, documentation, and the
   bounded checklist patch.

## Coverage boundary

Declared unsupported: team scoring and Match / Best-of, Burn Out outside
Draw, Predict / look / reveal exceptions, gain / lose points effects, ready
blockers, 323.7, facedown reveal at game end, Setup, concession and judge
rulings as rules (only recorded), policy evaluation. The G3 milestone stays a
bounded slice; the Burn Out and Cleanup checklist items stay open with the
Draw-path and 323.7 notes.

## Rejected alternatives

- The recycled Trash order as a `card_selection` decision of the player.
- A fixed Burn Out loop bound of `victory_score`.
- Writing `timing.terminal` from the effect IR.
- Pausing a Cleanup at 3a to resolve death triggers before 3b–10a, and a
  half-committed progress record.
- Advancing the Turn Player on the first `begin_turn`.
- Reporting a Match mode as supported by its Victory Score alone.
