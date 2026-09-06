#!/usr/bin/env python3
"""
Gate for C-38 (ADR-0010 §1, §6–9): the Start of Turn state machine and the
turn transition.

Must hold:
  - from setup, begin_turn keeps the selected first player, records the
    First Turn Process from mode.id (duel: the second player channels one
    more; skirmish: the first player skips the draw, the last channels one
    more) or explicit mode.first_turn facts, refuses a guess when neither
    is present, refuses match and team modes, and makes a Cleanup
    outstanding;
  - each Start of Turn step accepts only the phase and progress the previous
    step left: awaken readies the Turn Player's exhausted Units, Gear and
    Runes at once (not the opponent's; a stunned object is unsupported),
    the Beginning Phase schedules the Turn Player's beginning triggers and
    lets the Scoring Step wait for them, channel channels two (three on the
    first-turn extra, fewer with a short Rune Deck), draw draws one through
    the Burn Out-aware Draw (skipped when the mode says so; an immediate
    Burn Out victory writes the terminal and stops), main empties the Rune
    Pools, schedules main triggers and gives Priority to the Turn Player;
  - every transition makes a Cleanup outstanding and the next step refuses
    until it is handled; skipping a step or editing phase is refused;
    during 315 next_procedure blocks discretionary actions;
  - after the Ending and Expiration steps begin_turn advances to the next
    player, increments turn_id, prunes the per-turn ledger and clears the
    Ending Step; a second first turn reads no first-turn rule;
  - determinism, purity, engine-check wrapping, CLI off-cwd.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from battlefield_control import run_scoring_step  # noqa: E402
from check_combat_damage_assignment import add_unit  # noqa: E402
from check_combat_staging import trigger  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from resolution_bridge import begin_ending_step, run_expiration_step  # noqa: E402
from rules_core import next_procedure, state_hash, validate_state as validate_timing, validate_timing as legality  # noqa: E402
from turn_cycle import begin_turn, enter_beginning_phase, enter_main_phase, run_awaken_step, run_channel_step, run_draw_step  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def setup_timing(players=("p1", "p2")):
    t = fixture(priority=None)
    t.update({"players": list(players), "turn_order": list(players), "phase": "setup", "turns_taken": {p: 0 for p in players}})
    return t


def duel_board():
    e = base_state()
    e["mode"] = {"victory_score": 8, "id": "duel"}
    e["players"]["p1"]["zones"]["rune_deck"] = ["r1", "r2", "r3"]
    for r in ("r2", "r3"):
        e["objects"][r] = {"owner": "p1", "controller": "p1", "kind": "rune", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
    e["players"]["p2"]["zones"]["rune_deck"] = ["r4", "r5", "r6"]
    for r in ("r4", "r5", "r6"):
        e["objects"][r] = {"owner": "p2", "controller": "p2", "kind": "rune", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
    e["objects"]["u1"]["exhausted"] = True  # p1's exhausted unit at Base
    e["players"]["p2"]["zones"]["main_deck"] = ["c4", "c5"]
    e["objects"]["c5"] = copy.deepcopy(e["objects"]["c4"])
    return e


def handled(t):
    """The caller handles the outstanding transition Cleanup (run_cleanup is C-39)."""
    t = copy.deepcopy(t)
    t["outstanding_tasks"] = [x for x in t["outstanding_tasks"] if x != "cleanup"]
    return t


def main() -> int:
    errors: list[str] = []
    t0, e0 = setup_timing(), duel_board()

    # --- begin_turn from setup ------------------------------------------------------------------------------------
    snap_t, snap_e = copy.deepcopy(t0), copy.deepcopy(e0)
    began = begin_turn(t0, e0)
    if not began.get("committed"):
        errors.append(f"begin_turn from setup did not commit: {began.get('reason_code')} {began.get('reason') or began.get('errors')}")
        print("FAILED: turn cycle checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t1 = began["next_timing_state"]
    if t1["turn_player"] != "p1" or t1["phase"] != "awaken" or t1["turns_taken"] != {"p1": 1, "p2": 0} or t1["outstanding_tasks"] != ["cleanup"] or t1["turn_progress"].get("first_turn") != {"extra_channel": False, "skip_draw": False, "source": "mode:duel"}:
        errors.append(f"the first turn did not keep the first player with the duel First Turn Process: {t1['turn_player']} {t1['phase']} {t1.get('turns_taken')} {t1.get('turn_progress')}")
    if t0 != snap_t or e0 != snap_e or begin_turn(t0, e0) != began or validate_timing(t1):
        errors.append(f"begin_turn mutated inputs, is not deterministic or produced an invalid state: {validate_timing(t1)}")
    if next_procedure(t1).get("procedure") != "handle_outstanding_tasks":
        errors.append("the transition Cleanup is not the next required procedure (319.2)")
    if next_procedure(handled(t1)).get("procedure") != "turn_start_step_pending" or legality(handled(t1), {"actor": "p1", "kind": "play_card", "timing": "default"}).get("legal") is not False:
        errors.append("the Start of Turn allowed a discretionary action or was not reported as pending")
    check = build_engine_check("turn_step", began, input_hashes={"timing_state": state_hash(t0), "effect_state": hash_value(e0)})
    if check["outcome"] != "supported" or "turn_transition" not in check["coverage"]["supported_scope"] or "setup_procedure" not in check["coverage"]["unsupported_scope"]:
        errors.append(f"engine-check did not wrap begin_turn with its scope: {check['outcome']}")
    no_mode = copy.deepcopy(e0); no_mode["mode"] = {"victory_score": 8}
    if begin_turn(t0, no_mode).get("reason_code") != "first_turn_process_unknown" or begin_turn(t0, no_mode).get("unsupported") is not True:
        errors.append("a first turn without a Mode of Play or first-turn facts was guessed")
    explicit = copy.deepcopy(no_mode); explicit["mode"]["first_turn"] = {"extra_channel": ["p1"], "skip_draw": []}
    if begin_turn(t0, explicit).get("next_timing_state", {}).get("turn_progress", {}).get("first_turn", {}).get("extra_channel") is not True:
        errors.append("explicit mode.first_turn facts were not read")
    match = copy.deepcopy(e0); match["mode"]["id"] = "match"
    if begin_turn(t0, match).get("reason_code") != "match_mode":
        errors.append("the Match mode was read for its Victory Score alone")
    wrong = copy.deepcopy(e0); wrong["mode"]["victory_score"] = 11
    if begin_turn(t0, wrong).get("valid") is not False:
        errors.append("a duel with Victory Score 11 was accepted")
    if begin_turn(fixture(), e0).get("reason_code") != "phase_order":
        errors.append("a turn began from the Main Phase")

    # --- awaken ----------------------------------------------------------------------------------------------------------
    t1h = handled(t1)
    if run_awaken_step(t1, e0).get("reason_code") != "outstanding_tasks_pending":
        errors.append("the Awaken step ran with the transition Cleanup outstanding")
    awake = run_awaken_step(t1h, e0)
    if not awake.get("committed") or awake["next_effect_state"]["objects"]["u1"]["exhausted"] or awake["next_effect_state"]["objects"]["u2"]["exhausted"] is not True or awake["trace"].get("readied") != ["u1"] or awake["next_timing_state"]["turn_progress"].get("awaken_complete") is not True:
        errors.append(f"the Awaken step did not ready only the Turn Player's exhausted objects: {awake.get('reason_code')} {awake.get('trace')}")
    stunned = copy.deepcopy(e0); stunned["objects"]["u1"]["stunned"] = True
    if run_awaken_step(t1h, stunned).get("reason_code") != "ready_blocker_unknown" or run_awaken_step(t1h, stunned).get("unsupported") is not True:
        errors.append("a stunned object was readied or guessed around")
    if enter_beginning_phase(t1h, e0).get("reason_code") != "phase_step_incomplete":
        errors.append("the Beginning Phase was entered before the Awaken step completed")
    t2, e2 = awake["next_timing_state"], awake["next_effect_state"]
    if run_awaken_step(t2, e2).get("reason_code") != "step_already_complete":
        errors.append("the Awaken step ran twice")

    # --- beginning: triggers, then the Scoring Step ----------------------------------------------------------------------
    e2["objects"]["u1"]["beginning_phase_triggers"] = [trigger("u1-begin", "p1", "u1")]
    e2["objects"]["u2"]["beginning_phase_triggers"] = [trigger("u2-begin", "p2", "u2")]
    entered = enter_beginning_phase(t2, e2)
    if not entered.get("committed"):
        errors.append(f"the Beginning Phase was not entered: {entered.get('reason_code')} {entered.get('reason') or entered.get('errors')}")
        print("FAILED: turn cycle checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t3 = entered["next_timing_state"]
    if t3["phase"] != "beginning" or [i["id"] for i in t3["chain"]["items"]] != ["u1-begin"] or t3["outstanding_tasks"] != ["cleanup", "scoring_step"]:
        errors.append(f"the Beginning Step did not schedule only the Turn Player's trigger with the Cleanup and Scoring tasks outstanding: {t3['phase']} {[i['id'] for i in t3['chain']['items']]} {t3['outstanding_tasks']}")
    t3h = handled(t3)
    if next_procedure(t3h).get("procedure") != "finalize_oldest_pending":
        errors.append(f"the Scoring Step did not wait for the Beginning Step's chain: {next_procedure(t3h).get('procedure')}")
    if run_scoring_step(t3h, e2).get("reason_code") != "requires_quiet_cleanup_boundary":
        errors.append("the Scoring Step ran with the Beginning Step's chain open")
    t3q = copy.deepcopy(t3h); t3q["chain"]["items"] = []; t3q["chain"]["initiated_by"] = None
    if run_channel_step(t3q, e2).get("reason_code") not in {"outstanding_tasks_pending", "phase_step_incomplete"}:
        errors.append("the Channel step ran before the Scoring Step")
    scored = run_scoring_step(t3q, e2)
    if not scored.get("committed") or scored["next_timing_state"]["turn_progress"].get("scoring_complete") is not True or scored["next_timing_state"]["outstanding_tasks"] != []:
        errors.append(f"the Scoring Step did not complete and mark its progress: {scored.get('reason_code')} {scored.get('reason')}")
        print("FAILED: turn cycle checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t4, e4 = scored["next_timing_state"], scored["next_effect_state"]

    # --- channel, draw, main ------------------------------------------------------------------------------------------------
    channeled = run_channel_step(t4, e4)
    if not channeled.get("committed") or channeled["trace"].get("channeled") != ["r1", "r2"] or channeled["next_effect_state"]["players"]["p1"]["zones"]["rune_deck"] != ["r3"] or channeled["next_timing_state"]["phase"] != "channel" or channeled["next_timing_state"]["outstanding_tasks"] != ["cleanup"]:
        errors.append(f"the Channel step did not channel two Runes ready with a Cleanup outstanding: {channeled.get('reason_code')} {channeled.get('trace')}")
    t5, e5 = handled(channeled["next_timing_state"]), channeled["next_effect_state"]
    if enter_main_phase(t5, e5).get("reason_code") != "phase_order":
        errors.append("the Main Phase was entered from the Channel Phase")
    drew = run_draw_step(t5, e5)
    if not drew.get("committed") or drew["trace"]["draw"].get("objects") != ["c1"] or drew["next_timing_state"]["phase"] != "draw" or drew["next_timing_state"]["turn_progress"].get("draw_complete") is not True:
        errors.append(f"the Draw step did not draw one: {drew.get('reason_code')} {drew.get('reason')}")
    t6, e6 = handled(drew["next_timing_state"]), drew["next_effect_state"]
    e6["players"]["p1"]["resources"] = {"energy": 3, "power": {"fury": 1}}
    e6["objects"]["u1"]["main_phase_triggers"] = [trigger("u1-main", "p1", "u1")]
    entered_main = enter_main_phase(t6, e6)
    if not entered_main.get("committed"):
        errors.append(f"the Main Phase was not entered: {entered_main.get('reason_code')} {entered_main.get('reason') or entered_main.get('errors')}")
        print("FAILED: turn cycle checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t7, e7 = entered_main["next_timing_state"], entered_main["next_effect_state"]
    if t7["phase"] != "main" or t7["priority"] != "p1" or e7["players"]["p1"]["resources"] != {"energy": 0, "power": {}} or [i["id"] for i in t7["chain"]["items"]] != ["u1-main"] or t7["outstanding_tasks"] != ["cleanup"]:
        errors.append(f"the Main Phase entry did not empty the pools, schedule the trigger and give Priority: {t7['phase']} {t7['priority']} {e7['players']['p1']['resources']} {t7['outstanding_tasks']}")
    if validate_timing(t7) or validate_state(e7):
        errors.append(f"states after the Start of Turn are invalid: {validate_timing(t7)} {validate_state(e7)}")

    # --- the turn transition -------------------------------------------------------------------------------------------------
    t8 = handled(t7); t8["chain"]["items"] = []; t8["chain"]["initiated_by"] = None
    e8 = copy.deepcopy(e7); e8["players"]["p1"]["scored_this_turn"] = {"turn-0": ["bf1"]}
    ended = begin_ending_step(t8, e8)
    expired = run_expiration_step(ended["next_timing_state"], ended["next_effect_state"]) if ended.get("committed") else {}
    if not expired.get("committed"):
        errors.append(f"the Ending and Expiration steps did not run after the Start of Turn: {ended.get('reason_code')} {expired.get('reason_code')}")
    else:
        if begin_turn(ended["next_timing_state"], ended["next_effect_state"]).get("reason_code") != "ending_not_expired":
            errors.append("the next turn began before the Expiration Step")
        nxt = begin_turn(expired["next_timing_state"], expired["next_effect_state"])
        if not nxt.get("committed"):
            errors.append(f"the next turn did not begin: {nxt.get('reason_code')} {nxt.get('reason') or nxt.get('errors')}")
        else:
            tn, en = nxt["next_timing_state"], nxt["next_effect_state"]
            if tn["turn_player"] != "p2" or tn["phase"] != "awaken" or tn["turns_taken"] != {"p1": 1, "p2": 1} or en["turn_id"] != "turn-1" or en["players"]["p1"].get("scored_this_turn") != {"turn-1": []} or "ending_step" in tn or tn["turn_progress"].get("first_turn", {}).get("extra_channel") is not True:
                errors.append(f"the turn transition is wrong: {tn['turn_player']} {tn['phase']} {tn.get('turns_taken')} {en.get('turn_id')} {en['players']['p1'].get('scored_this_turn')} {tn.get('turn_progress')}")
            second = run_awaken_step(handled(tn), en)
            entered2 = enter_beginning_phase(second["next_timing_state"], second["next_effect_state"]) if second.get("committed") else {}
            t9 = handled(entered2.get("next_timing_state", {})) if entered2.get("committed") else None
            if t9 is not None:  # p2's own beginning trigger resolves first; the caller resolves it (315.2.a before 315.2.b)
                t9["chain"]["items"] = []; t9["chain"]["initiated_by"] = None
            scored2 = run_scoring_step(t9, entered2["next_effect_state"]) if t9 else {}
            channeled2 = run_channel_step(scored2["next_timing_state"], scored2["next_effect_state"]) if scored2.get("committed") else {}
            if not channeled2.get("committed") or channeled2["trace"].get("channeled") != ["r4", "r5", "r6"] or channeled2["trace"].get("first_turn_extra") != 1:
                errors.append(f"the second player's first Channel Phase did not channel three (485.7): {second.get('reason_code')} {entered2.get('reason_code')} {scored2.get('reason_code')} {channeled2.get('reason_code')} {channeled2.get('trace')}")

    # --- skirmish first-turn draw skip and the Burn Out terminal in the Draw step ---------------------------------------------
    t3p = setup_timing(("p1", "p2", "p3"))
    e3p = duel_board(); e3p["mode"] = {"victory_score": 8, "id": "skirmish"}
    e3p["players"]["p3"] = copy.deepcopy(e3p["players"]["p2"]); e3p["players"]["p3"]["zones"] = {z: [] for z in e3p["players"]["p3"]["zones"]}
    first3 = begin_turn(t3p, e3p)
    ft = first3.get("next_timing_state", {}).get("turn_progress", {}).get("first_turn")
    if not first3.get("committed") or ft != {"extra_channel": False, "skip_draw": True, "source": "mode:skirmish"}:
        errors.append(f"skirmish's first player did not get skip_draw (487.7): {first3.get('reason_code')} {ft}")
    else:
        chain = handled(first3["next_timing_state"])
        a = run_awaken_step(chain, first3["next_effect_state"]); b = enter_beginning_phase(a["next_timing_state"], a["next_effect_state"])
        s = run_scoring_step(handled(b["next_timing_state"]), b["next_effect_state"]); c = run_channel_step(s["next_timing_state"], s["next_effect_state"])
        d = run_draw_step(handled(c["next_timing_state"]), c["next_effect_state"])
        if not d.get("committed") or d["trace"].get("skipped_first_turn_draw") is not True or d["trace"].get("draw") is not None or d["next_effect_state"]["players"]["p1"]["zones"]["hand"] != []:
            errors.append(f"the first player's first Draw Phase was not skipped: {d.get('reason_code')} {d.get('trace')}")
    empty = copy.deepcopy(e5)
    for card in list(empty["players"]["p1"]["zones"]["main_deck"]) + list(empty["players"]["p1"]["zones"]["trash"]):
        del empty["objects"][card]
    empty["players"]["p1"]["zones"]["main_deck"] = []; empty["players"]["p1"]["zones"]["trash"] = []
    empty["mode"] = {"victory_score": 3, "id": "duel"}; empty["mode"]["victory_score"] = 8; empty["players"]["p2"]["points"] = 7
    burned = run_draw_step(t5, empty)
    if not burned.get("committed") or burned["next_timing_state"].get("terminal", {}).get("reason") != "burn_out_victory" or burned["next_timing_state"]["terminal"].get("winner") != "p2" or burned["next_timing_state"]["phase"] != "draw":
        errors.append(f"a Draw Phase Burn Out victory was not written as the terminal in the same commit: {burned.get('reason_code')} {burned.get('next_timing_state', {}).get('terminal')}")
    elif enter_main_phase(burned["next_timing_state"], burned["next_effect_state"]).get("reason_code") != "game_over":
        errors.append("the Main Phase was entered after the game ended")

    with tempfile.TemporaryDirectory(prefix="turncycle-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(t0), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(e0), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "turn-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "begin_turn", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI turn-step begin_turn failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: turn cycle checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: the Start of Turn is reached only by its own procedures in order with a Cleanup outstanding at every transition, the first turn keeps the selected player and reads the First Turn Process from the Mode of Play or explicit facts, Awaken readies the Turn Player's objects at once, the Scoring Step waits for the Beginning Step's chain, Channel and Draw follow the first-turn rules, a Draw Phase Burn Out victory is written in the same commit, the Main Phase empties the pools and gives Priority, and the next turn advances in Turn Order with a new turn_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
