# ADR-0009 — G2 Battlefield control, Conquer, Hold and scoring

- Status: Accepted (Codex rulings on the Round E packet, 2026-09-05)
- Scope: the G2 milestone — establishing and losing control of Battlefields,
  Contested maintenance, Non-Combat Showdowns, Conquer and Hold scoring, Score
  triggers, and the victory-condition facts the G3 milestone will consume.
- Rules baseline: English Core Rules 2026-07-16, especially 190, 315.2.b,
  316.8, 323.6–323.13, 344–348, 383.4.c–d, 447.2, 466.5–466.6, 467–472.
- Not decided here: the Beginning Phase state machine, terminal state, Burn
  Out (G3); team scoring; Hidden cards; gear/rune Recall in Cleanup (323.7);
  non-Conquer/Hold point sources; "activate" of named triggers (383.4.g).

## Context

After ADR-0008 the engine stops at two explicit boundaries: `close_combat`
when 466.5 would change control, and `pass_focus` when a Non-Combat Showdown
closes (348.2). Cleanup steps 4, 6–9 (323.6, 323.8, 323.11, 323.12) and the
Scoring Step (315.2.b) do not exist. No Wave-A card clause references
conquer, hold, score or control, so G2 is a procedure milestone: its fixtures
are the official examples and counterexamples, not card programs.

## Decisions

### 1. Points and mode are effect state (DP-36)

The effect state carries `mode: {victory_score, teams: false}`, each player's
`points` (absent means 0) and `scored_this_turn: {turn_id: [battlefields]}`,
of which only the current turn's entry is read. A missing `mode` makes every
scoring procedure `unsupported: mode_unknown`; `teams: true` or any
`team_id` makes it `unsupported: team_scoring`.

### 2. Establishing control is one atomic procedure (DP-37)

`resolve_battlefield_control` performs, on one copy of both states, the
control change (466.5 / 348.2.a), the Conquer scoring (469.1, 470, 471), and
the scheduling of Score triggers (471.2), committing all or nothing. After a
Combat it runs on `result_determined` (never on a both-remain restage) and
moves the record to `control_resolved`; `close_combat` accepts only that
status and only once the Score-trigger chain has emptied (466.6). A player
who already controls the Battlefield does not Conquer; Contested is cleared
(466.5.a); no Units at all makes the Battlefield Uncontrolled (466.5.b).

### 3. Non-Combat Showdowns are staged as a set and opened by choice (DP-38)

The timing state carries `staged_showdowns: [{battlefield,
battlefield_identity, contested_by}]`, rebuilt from the derivable candidate
set (Contested applied, the applier's Units present, no opposing Units,
nothing ongoing there) by `stage_showdown`. `open_showdown` needs a Neutral
Open State; several staged Showdowns need the Turn Player's
`location_selection` (`showdown_location`); the one that opens is a
`non_combat` Showdown whose Focus goes to the player who applied Contested
(345). In one Cleanup the Non-Combat Showdown of 323.12 comes before the
Combat of 323.13.

### 4. A Non-Combat Showdown's close hands over only a sole occupant (DP-39)

When every player has passed Focus in a Non-Combat Showdown, the Showdown is
`closing` and `resolve_battlefield_control` is the next required procedure.
Exactly one player with Units there establishes control (348.2.a) and may
Conquer; no Units at all is not 466.5.b — the Showdown closes and control loss
is left to the next board Cleanup (323.6); Units of both players there is an
inconsistent state and is refused as unsupported.

### 5. Conquer scores once per Battlefield per turn (DP-40)

`score_battlefield(player, battlefield, how)` records the Battlefield in the
player's `scored_this_turn` for the current turn and gains up to one point;
a Battlefield already scored this turn by that player gains nothing and
triggers nothing (470, 471.2.c). Control still changes hands; only the score
is withheld.

### 6. The Final Point rule and the rollback on Burn Out (DP-41)

When a Conquer would take a player to the Victory Score or beyond, the point
is gained only if every Battlefield in the state has been scored by that
player this turn (this one included); otherwise the player draws a card
instead (471.1.b.1). Hold is not a Conquer and gains normally (471.1.a.1). If
that draw would Burn Out, the whole control/score transaction is refused as
`unsupported: burn_out`: no control change, no ledger entry, no trigger.

### 7. Score triggers are typed and limited to modelled board sources (DP-42)

Objects and Battlefields may carry `conquer_triggers` / `hold_triggers`. A
Unit's trigger with scope `unit_here` fires when that Unit, controlled by the
scoring player, is at the Battlefield scored; scope `controller` fires from
any board object the scoring player controls (383.4.c.2.b). A Battlefield's
own trigger follows its controller (190.6). Sources the engine does not model
as board objects (Legends, Runes) are unsupported. A Score that is replaced by
a draw still triggers (383.4.c.2.c). Same-controller collisions use
`trigger_order`.

### 8. Hold is the Scoring Step (DP-43)

`run_scoring_step` runs in the Beginning Phase (the phase fact is still
caller-supplied until G3), with an empty chain and no Showdown or Combat, and
Holds every Battlefield the Turn Player controls that they have not scored
this turn, in Battlefield-id order, scheduling the Hold triggers as one batch.

### 9. Board Cleanup maintains control and Contested (DP-44)

`run_board_cleanup` runs in an Open State and applies, per Battlefield that has
no ongoing Showdown or Combat (a merely staged one does not exempt), 323.6
control loss, 323.11 Contested removal, then 323.11.a re-application by the
present non-controller (two different non-controllers present is unsupported,
not guessed). It is not chained into the resolution bridge; a caller runs the
Cleanup boundary as `run_board_cleanup` → `stage_showdown` / `open_showdown`
→ `stage_combat` / `open_combat` (323.6, 323.11, 323.12, 323.13). 323.7 is not
modelled.

### 10. The victory condition is reported, never enacted (DP-45)

Scoring procedures and the board Cleanup report `victory_check:
{threshold_met, strict_leader, tied_at_threshold}` as facts (472). No winner
is declared and no terminal state exists; that is G3.

### 11. Triggers and decisions (DP-46)

Score triggers open a chain (`triggered_ability`); `close_combat` and the
return to a Neutral Open State after a Non-Combat Showdown wait for it to
empty. Decisions of these two-state procedures bind to
`combined_input_hash(timing, effect)`.

### 12. Versioning and vocabulary (DP-47)

Everything is additive: effect-state `mode`, `points`, `scored_this_turn`,
`conquer_triggers` / `hold_triggers`; timing-state `staged_showdowns`,
`showdown.closing`, combat status `control_resolved`; procedures
`resolve_battlefield_control`, `stage_showdown`, `open_showdown`,
`run_scoring_step`, `run_board_cleanup` in `battlefield_control.py`;
engine-check kind `control_step` (component `battlefield_control`); decision
id `showdown_location`. Existing field meanings and outcome vocabulary do not
change.

## Implementation order

1. C-33: state and validators, `resolve_battlefield_control`, Conquer scoring
   with the Final Point rule and its rollback, Score triggers, `close_combat`
   on `control_resolved`.
2. C-34: `stage_showdown` / `open_showdown`, the Non-Combat Showdown close
   handing over to control resolution, `run_board_cleanup`.
3. C-35: `run_scoring_step` (Hold), `victory_check` facts, engine-check kind
   and scopes, documentation.

Each package is one focused commit with in-repo and off-cwd gates and the
capability manifest and R5-A report regenerated. There is no card batch.

## Coverage boundary

Not supported and declared so: team scoring (469.1.a, 315.2.b.3), 323.7,
466.5.c Hidden, non-Conquer/Hold point sources, 383.4.g "activate", the
Beginning Phase machine, terminal state and Burn Out. The checklist's
"Score, conquer, hold, battlefield control, and Victory Score operations" item
stays open with a bounded-slice note.

## Rejected alternatives

- Establishing control as a side effect inside `close_combat`.
- A single `showdown_staged` record instead of the staged set.
- Applying 466.5.b's "Uncontrolled" to a Non-Combat Showdown that ends with
  no Units present.
- Reporting a winner from the victory check.
- Chaining the board Cleanup into the resolution bridge.
