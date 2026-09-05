#!/usr/bin/env python3
"""
Gate for C-34 (ADR-0009 §3, §4, §9): Non-Combat Showdowns and the board
Cleanup.

Must hold:
  - stage_showdown stages exactly the Battlefields where Contested was
    applied, the applier's Units are present, no opposing Units are, and
    nothing is ongoing; it rebuilds the set (stale entries drop) and refuses
    off a quiet Cleanup boundary;
  - open_showdown needs a Neutral Open State with no Combat staged, opens the
    sole candidate as a non_combat Showdown with Focus and Priority on the
    player who applied Contested, asks the Turn Player (showdown_location)
    among several, refuses a wrong controller and a Showdown no longer
    staged;
  - after every player passes Focus the Showdown is closing, no discretionary
    action is legal and control resolution is the next required procedure;
    a sole occupant who did not control the Battlefield establishes control
    and Conquers with Score triggers on the chain, a sole occupant who did
    controls it and gains nothing, no Units at all closes the Showdown with
    control untouched (deferred to 323.6), both players present is
    unsupported;
  - run_board_cleanup drops control where the controller has no Units,
    exempts only an ongoing Showdown or Combat (not a merely staged one),
    removes Contested whose applier is absent, re-applies it by the one
    non-controller present, refuses two different non-controllers as
    unsupported, refuses with a chain open, and reports the victory facts;
  - the Cleanup order board cleanup -> stage/open Showdown -> stage Combat
    holds end to end; determinism, purity, engine-check wrapping, CLI
    off-cwd.
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

from battlefield_control import SHOWDOWN_LOCATION_DECISION_ID, open_showdown, resolve_battlefield_control, run_board_cleanup, stage_showdown  # noqa: E402
from check_combat_damage_assignment import add_unit  # noqa: E402
from check_combat_staging import contested_board, trigger  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import combined_input_hash, stage_combat  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import derive_permissions, next_procedure, pass_focus, state_hash, validate_state as validate_timing, validate_timing as legality  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def lone_board(applier="p1", *, controller=None):
    """u1 (p1) alone at bf1 after a Move that applied Contested (447.2); u2 (p2) at its Base."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"]["objects"].append("u1")
    state["battlefields"]["bf1"].update({"contested": True, "contested_by": applier, "controller": controller})
    state["mode"] = {"victory_score": 8}
    return state


def decide(timing, effect, value, controller="p1"):
    return {"schema_version": "engine-decisions.v1", "input_hash": combined_input_hash(timing, effect),
            "decisions": [{"decision_id": SHOWDOWN_LOCATION_DECISION_ID, "stage": "procedure", "kind": "location_selection", "controller": controller, "value": value}]}


def main() -> int:
    errors: list[str] = []
    quiet = fixture()

    # --- staging --------------------------------------------------------------------------------------
    board = lone_board()
    snap_t, snap_e = copy.deepcopy(quiet), copy.deepcopy(board)
    staged = stage_showdown(quiet, board)
    entries = staged.get("next_timing_state", {}).get("staged_showdowns") if staged.get("committed") else None
    if entries != [{"battlefield": "bf1", "battlefield_identity": "bf1@0", "contested_by": "p1"}] or staged["next_effect_state"] != board:
        errors.append(f"a lone Unit at a Contested Battlefield did not stage a Showdown: {staged.get('reason')} {entries}")
    if quiet != snap_t or board != snap_e or stage_showdown(quiet, board) != staged:
        errors.append("stage_showdown mutated its inputs or is not deterministic")
    absent = lone_board(applier="p2")
    if stage_showdown(quiet, absent).get("next_timing_state", {}).get("staged_showdowns") != [] or stage_showdown(quiet, absent)["trace"]["considered"][0]["verdict"] != "applier_absent":
        errors.append("a Battlefield whose Contested applier has no Units there was staged (323.8.a)")
    if stage_showdown(quiet, contested_board())["trace"]["considered"][0]["verdict"] != "opposing_units_present":
        errors.append("a Battlefield with opposing Units was staged as a Non-Combat Showdown (that is a Combat, 461)")
    stale = {**quiet, "staged_showdowns": [{"battlefield": "bf1", "battlefield_identity": "bf1@0", "contested_by": "p1"}]}
    dropped = stage_showdown(stale, base_state())
    if not dropped.get("committed") or dropped["next_timing_state"]["staged_showdowns"] != [] or dropped["trace"].get("dropped") != ["bf1"]:
        errors.append("a stale staged Showdown was not dropped when nothing is staged")
    busy = fixture(items=[item("spell-1", "p1", "spell", "default")], priority="p2")
    if stage_showdown(busy, board).get("reason_code") != "requires_quiet_cleanup_boundary":
        errors.append("a Showdown was staged with the chain open")
    ongoing = {**staged["next_timing_state"], "showdown": {"active": True, "kind": "non_combat", "focus": "p1", "battlefield": "bf1", "focus_passes": []}}
    if stage_showdown(ongoing, board)["trace"]["considered"][0]["verdict"] != "showdown_ongoing":
        errors.append("a Battlefield with an ongoing Showdown was staged again")

    # --- opening --------------------------------------------------------------------------------------
    t1 = staged["next_timing_state"]
    opened = open_showdown(t1, board)
    if not opened.get("committed"):
        errors.append(f"the sole staged Showdown did not open: {opened.get('reason_code')} {opened.get('reason') or opened.get('errors')}")
        print("FAILED: showdown and board cleanup checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t2 = opened["next_timing_state"]
    if t2["showdown"] != {"active": True, "kind": "non_combat", "focus": "p1", "battlefield": "bf1", "focus_passes": []} or t2["priority"] != "p1" or t2["staged_showdowns"] != []:
        errors.append(f"the opened Showdown is wrong: {t2['showdown']} {t2['priority']} {t2['staged_showdowns']}")
    if next_procedure(t2).get("procedure") != "showdown_focus_window" or legality(t2, {"actor": "p1", "kind": "pass_focus"}).get("legal") is not True:
        errors.append("the applier does not hold Focus in the opened Showdown (345)")
    if open_showdown(t1, board) != opened:
        errors.append("open_showdown is not deterministic")
    if open_showdown(t2, board).get("reason_code") != "not_neutral_open_state":
        errors.append("a Showdown opened during a Showdown")
    if open_showdown(quiet, board).get("reason_code") != "no_staged_showdown":
        errors.append("a Showdown opened without staging")
    moved_away = copy.deepcopy(board); moved_away["battlefields"]["bf1"]["objects"].remove("u1"); moved_away["players"]["p1"]["zones"]["base"].append("u1")
    if open_showdown(t1, moved_away).get("reason_code") != "showdown_no_longer_staged":
        errors.append("a Showdown whose applier left opened anyway (323.8.a)")
    with_combat = copy.deepcopy(t1); with_combat["combat"] = {"combat_id": "combat:bf2:x", "battlefield": "bf2", "battlefield_identity": "bf2@0", "status": "staged", "attacker": None, "defender": None, "participants": ["p1", "p2"], "triggered_identities": {"attacker": [], "defender": []}}
    if open_showdown(with_combat, board).get("reason_code") != "combat_staged":
        errors.append("a Non-Combat Showdown opened after a Combat was staged (323.12 before 323.13)")
    two = lone_board()
    two["battlefields"]["bf2"] = {"controller": None, "objects": [], "contested": True, "contested_by": "p2"}
    add_unit(two, "u3", "p2", "bf2")
    t_two = stage_showdown(quiet, two)["next_timing_state"]
    if [s["battlefield"] for s in t_two["staged_showdowns"]] != ["bf1", "bf2"]:
        errors.append(f"two lone Battlefields were not both staged: {t_two['staged_showdowns']}")
    ask = open_showdown(t_two, two)
    if ask.get("committed") or ask.get("reason_code") != "location_selection_required" or ask.get("decision_controller") != "p1" or ask.get("options") != ["bf1", "bf2"]:
        errors.append(f"two staged Showdowns did not ask the Turn Player: {ask.get('reason_code')} {ask.get('options')}")
    else:
        check = build_engine_check("control_step", ask, input_hashes={"timing_state": state_hash(t_two), "effect_state": hash_value(two)})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "location_choice" or check["decision_required"]["decision_ids"] != [SHOWDOWN_LOCATION_DECISION_ID]:
            errors.append(f"showdown_location did not wrap as location_choice: {check.get('decision_required')}")
    chosen = open_showdown(t_two, two, decide(t_two, two, "bf2"))
    if not chosen.get("committed") or chosen["next_timing_state"]["showdown"]["battlefield"] != "bf2" or chosen["next_timing_state"]["showdown"]["focus"] != "p2" or [s["battlefield"] for s in chosen["next_timing_state"]["staged_showdowns"]] != ["bf1"]:
        errors.append(f"the Turn Player's Showdown choice was not honoured with Focus to the applier: {chosen.get('reason') or chosen.get('errors')}")
    if open_showdown(t_two, two, decide(t_two, two, "bf2", controller="p2")).get("reason_code") != "decision_controller_mismatch":
        errors.append("the non-Turn Player chose the Showdown location")

    # --- closing hands over -----------------------------------------------------------------------------
    p1 = pass_focus(t2, "p1")
    t3 = p1.get("next_state")
    if not t3 or t3["showdown"].get("closing") or next_procedure(t3).get("procedure") != "showdown_focus_window":
        errors.append(f"the first pass closed the Showdown early: {p1.get('reason_code')}")
        print("FAILED: showdown and board cleanup checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    p2 = pass_focus(t3, "p2")
    t4 = p2.get("next_state")
    if not t4 or t4["showdown"].get("closing") is not True or p2["transition"].get("type") != "non_combat_showdown_closing" or next_procedure(t4).get("procedure") != "control_resolution_pending":
        errors.append(f"every player passing did not mark the Non-Combat Showdown closing with control resolution next: {p2.get('reason_code')} {t4 and t4['showdown']}")
        print("FAILED: showdown and board cleanup checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    perms = derive_permissions(t4)["permissions"]
    if any(v["play_timings"] or v["activate_timings"] or v["may_pass_focus"] or v["may_pass_priority"] for v in perms.values()) or legality(t4, {"actor": "p1", "kind": "play_card", "timing": "action"}).get("legal") is not False:
        errors.append("discretionary actions were allowed in a closing Showdown")
    if validate_timing(t4):
        errors.append(f"the closing state is invalid: {validate_timing(t4)}")
    armed = copy.deepcopy(board); armed["objects"]["u1"]["conquer_triggers"] = [trigger("u1-conquer", "p1", "u1")]
    handed = resolve_battlefield_control(t4, armed)
    if not handed.get("committed"):
        errors.append(f"the closing Showdown did not hand over to control resolution: {handed.get('reason_code')} {handed.get('reason') or handed.get('errors')}")
    else:
        t5, e5 = handed["next_timing_state"], handed["next_effect_state"]
        bf = e5["battlefields"]["bf1"]
        if bf.get("controller") != "p1" or bf.get("contested") is not False or e5["players"]["p1"].get("points") != 1 or handed["trace"]["source"] != "non_combat_showdown" or handed["trace"]["control_step"] != "control_established":
            errors.append(f"the sole occupant did not establish control and Conquer (348.2.a): {bf} {handed['trace']}")
        if t5["showdown"].get("active") or t5.get("staged_showdowns") != [] or [i["id"] for i in t5["chain"]["items"]] != ["u1-conquer"]:
            errors.append(f"the Showdown did not close with the Score trigger on the chain: {t5['showdown']} {t5['chain']['items']}")
        if validate_timing(t5) or validate_state(e5):
            errors.append(f"states after the hand-over are invalid: {validate_timing(t5)} {validate_state(e5)}")
        if resolve_battlefield_control(t4, armed) != handed:
            errors.append("the hand-over is not deterministic")
    holder = lone_board(controller="p1")
    kept = resolve_battlefield_control(t4, holder)
    if not kept.get("committed") or kept["trace"]["control_step"] != "controller_unchanged" or kept["next_effect_state"]["players"]["p1"].get("points", 0) != 0 or kept["next_timing_state"]["showdown"]["active"]:
        errors.append(f"a sole occupant who already controlled the Battlefield scored or kept the Showdown open: {kept.get('reason_code')} {kept.get('trace', {}).get('control_step')}")
    empty = lone_board(controller="p2"); empty["battlefields"]["bf1"]["objects"].remove("u1"); empty["players"]["p1"]["zones"]["base"].append("u1")
    deferred = resolve_battlefield_control(t4, empty)
    if not deferred.get("committed") or deferred["trace"]["control_step"] != "deferred_to_board_cleanup" or deferred["next_effect_state"]["battlefields"]["bf1"] != empty["battlefields"]["bf1"] or deferred["next_timing_state"]["showdown"]["active"]:
        errors.append(f"a Showdown ending with no Units touched control instead of deferring to 323.6: {deferred.get('reason_code')} {deferred.get('trace', {}).get('control_step')}")
    both = lone_board(); both["battlefields"]["bf1"]["objects"].append("u2"); both["players"]["p2"]["zones"]["base"].remove("u2")
    if resolve_battlefield_control(t4, both).get("reason_code") != "showdown_participants_inconsistent" or resolve_battlefield_control(t4, both).get("unsupported") is not True:
        errors.append("a Non-Combat Showdown ending with both players present was resolved")
    if resolve_battlefield_control(t3, board).get("reason_code") != "control_resolution_not_pending":
        errors.append("control was resolved before every player passed")

    # --- board Cleanup ------------------------------------------------------------------------------------
    gone = base_state(); gone["battlefields"]["bf1"]["controller"] = "p1"; gone["mode"] = {"victory_score": 8}  # p1 controls bf1 with no Units there
    lost = run_board_cleanup(quiet, gone)
    if not lost.get("committed") or lost["next_effect_state"]["battlefields"]["bf1"]["controller"] is not None or [s["step"] for s in lost["trace"]["steps"]] != ["control_lost"] or lost["next_timing_state"] != quiet:
        errors.append(f"an absent controller kept the Battlefield (323.6): {lost.get('reason_code')} {lost.get('trace')}")
    if lost.get("committed") and (lost["trace"]["victory_check"].get("threshold_met") != [] or run_board_cleanup(quiet, gone) != lost):
        errors.append("the board Cleanup did not report victory facts or is not deterministic")
    showdown_here = {**quiet, "showdown": {"active": True, "kind": "non_combat", "focus": "p1", "battlefield": "bf1", "focus_passes": []}}
    exempt = run_board_cleanup(showdown_here, gone)
    if not exempt.get("committed") or exempt["next_effect_state"]["battlefields"]["bf1"]["controller"] != "p1" or exempt["trace"]["exempt"] != [{"battlefield": "bf1", "ongoing": "showdown"}]:
        errors.append(f"an ongoing Showdown did not exempt its Battlefield from 323.6: {exempt.get('trace')}")
    staged_only = {**quiet, "staged_showdowns": [{"battlefield": "bf1", "battlefield_identity": "bf1@0", "contested_by": "p2"}]}
    if run_board_cleanup(staged_only, gone)["next_effect_state"]["battlefields"]["bf1"]["controller"] is not None:
        errors.append("a merely staged Showdown exempted its Battlefield from 323.6 (ADR-0009 §9)")
    left = lone_board(applier="p2", controller="p2")  # p2 applied Contested, left; p1's u1 remains
    reapplied = run_board_cleanup(quiet, left)
    bf = reapplied.get("next_effect_state", {}).get("battlefields", {}).get("bf1", {})
    if not reapplied.get("committed") or [s["step"] for s in reapplied["trace"]["steps"]] != ["control_lost", "contested_removed", "contested_reapplied"] or bf.get("controller") is not None or bf.get("contested") is not True or bf.get("contested_by") != "p1":
        errors.append(f"Contested removal and re-application went wrong (323.11, 323.11.a): {reapplied.get('reason_code')} {reapplied.get('trace', {}).get('steps')} {bf}")
    stays = lone_board(applier="p1", controller="p2")  # p1 applied and is present: Contested stays, p2 loses control
    stayed = run_board_cleanup(quiet, stays)
    if not stayed.get("committed") or stayed["next_effect_state"]["battlefields"]["bf1"].get("contested") is not True or stayed["next_effect_state"]["battlefields"]["bf1"].get("controller") is not None:
        errors.append("Contested whose applier is present was removed, or a controller with no Units kept control")
    crowd = base_state(); crowd["players"]["p1"]["zones"]["base"].remove("u1"); crowd["players"]["p2"]["zones"]["base"].remove("u2")
    crowd["players"]["p3"] = copy.deepcopy(crowd["players"]["p2"]); crowd["players"]["p3"]["zones"] = {zone: [] for zone in crowd["players"]["p3"]["zones"]}
    crowd["battlefields"]["bf1"].update({"objects": ["u1", "u2"], "contested": True, "contested_by": "p3", "controller": None})
    crowd["mode"] = {"victory_score": 8}
    three_timing = {**quiet, "players": ["p1", "p2", "p3"], "turn_order": ["p1", "p2", "p3"]}
    ambiguous = run_board_cleanup(three_timing, crowd)
    if ambiguous.get("committed") or ambiguous.get("reason_code") != "contested_reapplication_ambiguous" or ambiguous.get("unsupported") is not True:
        errors.append(f"two non-controllers left after Contested removal were not refused: {ambiguous.get('reason_code')} {ambiguous.get('errors')}")
    if run_board_cleanup(busy, gone).get("reason_code") != "requires_quiet_cleanup_boundary":
        errors.append("the board Cleanup ran with the chain open")
    check = build_engine_check("control_step", lost, input_hashes={"timing_state": state_hash(quiet), "effect_state": hash_value(gone)})
    if check["outcome"] != "supported" or "board_cleanup" not in check["coverage"]["supported_scope"] or "gear_rune_recall_cleanup" not in check["coverage"]["unsupported_scope"]:
        errors.append(f"engine-check did not wrap the board Cleanup with its scope: {check['outcome']}")

    # --- the Cleanup order, end to end --------------------------------------------------------------------
    scene = lone_board(applier="p1", controller="p2")  # p2 controlled bf1 and left; p1 moved in and applied Contested
    scene["battlefields"]["bf2"] = {"controller": None, "objects": [], "contested": True, "contested_by": "p2"}
    add_unit(scene, "u3", "p2", "bf2"); add_unit(scene, "u4", "p1", "bf2")  # a Combat is staged at bf2
    c1 = run_board_cleanup(quiet, scene)
    s1 = stage_showdown(c1["next_timing_state"], c1["next_effect_state"]) if c1.get("committed") else {}
    o1 = open_showdown(s1["next_timing_state"], s1["next_effect_state"]) if s1.get("committed") else {}
    if not o1.get("committed") or o1["next_timing_state"]["showdown"]["battlefield"] != "bf1" or c1["next_effect_state"]["battlefields"]["bf1"]["controller"] is not None:
        errors.append(f"the Cleanup order board cleanup -> stage -> open did not run: {c1.get('reason_code')} {s1.get('reason_code')} {o1.get('reason_code')}")
    else:
        tt, ee = o1["next_timing_state"], o1["next_effect_state"]
        during = stage_combat(tt, ee)
        if not during.get("committed") or during["trace"].get("outcome") != "no_staged_combat":
            errors.append(f"during the Non-Combat Showdown at bf1 a Combat elsewhere was staged (323.14): {during.get('reason_code')} {during.get('trace')}")
        tt = pass_focus(pass_focus(tt, "p1")["next_state"], "p2")["next_state"]
        done = resolve_battlefield_control(tt, ee)
        after = stage_combat(done["next_timing_state"], done["next_effect_state"]) if done.get("committed") else {}
        if not after.get("committed") or after["next_timing_state"].get("combat", {}).get("battlefield") != "bf2" or done["next_effect_state"]["battlefields"]["bf1"]["controller"] != "p1" or done["next_effect_state"]["players"]["p1"].get("points") != 1:
            errors.append(f"after the Showdown closed the Combat at bf2 did not stage, or p1 did not Conquer bf1: {done.get('reason_code')} {after.get('reason_code')}")

    with tempfile.TemporaryDirectory(prefix="showdown-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(quiet), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(board), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "control-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "stage_showdown", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI control-step stage_showdown failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: showdown and board cleanup checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Non-Combat Showdowns are staged as the set of Contested Battlefields held only by their applier, opened from a Neutral Open State by the Turn Player's choice with Focus to the applier before any Combat stages, closed by every player passing into a control resolution that hands a sole occupant control and a Conquer, defers an empty Battlefield to 323.6 and refuses both present; the board Cleanup drops absent controllers, exempts only what is ongoing, removes and re-applies Contested per 323.11 and refuses an ambiguous re-application.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
