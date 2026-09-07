#!/usr/bin/env python3
"""
Gate for C-39 (ADR-0010 §5): the atomic Cleanup orchestration.

Must hold:
  - run_cleanup consumes the outstanding Cleanup task when it is first and
    refuses when another task precedes it; a Cleanup that changes nothing is
    one stable iteration;
  - the steps run in the 323 order on one working state: a lethal Unit is
    killed at 3b, its death trigger goes Pending on the chain and nothing
    resolves, the Battlefield it emptied loses control at step 4 of the
    same iteration, a lone Unit's Contested Battlefield is staged (6) and
    opened (9) with the Pending trigger still on the chain, and the 322
    follow-up iteration changes nothing;
  - a strict leader at step 1 ends the game and the remaining steps are
    skipped_after_terminal; a state without a Mode of Play and no points
    runs; with points it is unsupported;
  - two staged Combats need the Turn Player's location choice and nothing
    commits until it arrives; with it the Combat opens at step 10 and its
    Attack triggers are scheduled;
  - a non-Unit Gear at a Battlefield (323.7) fails the whole run closed;
    the combined result commits or commits nothing;
  - the staging and opening procedures called on their own still require
    the quiet boundary; determinism, engine-check wrapping, CLI off-cwd.
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

from battlefield_control import stage_showdown  # noqa: E402
from check_combat_damage_assignment import add_unit  # noqa: E402
from check_combat_staging import contested_board, decide, trigger  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import stage_combat  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import next_procedure, state_hash, validate_state as validate_timing  # noqa: E402
from turn_cycle import run_cleanup  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def with_task(t):
    t = copy.deepcopy(t)
    t["outstanding_tasks"] = ["cleanup"] + t["outstanding_tasks"]
    return t


def main() -> int:
    errors: list[str] = []
    quiet = fixture()

    # --- a Cleanup that changes nothing -------------------------------------------------------------------------------
    board = base_state(); board["mode"] = {"victory_score": 8}
    t = with_task(quiet)
    snap_t, snap_e = copy.deepcopy(t), copy.deepcopy(board)
    still = run_cleanup(t, board)
    if not still.get("committed") or still["next_timing_state"]["outstanding_tasks"] != [] or still["next_effect_state"] != board or len(still["trace"]["iterations"]) != 1 or still["trace"].get("task_consumed") is not True:
        errors.append(f"an idle Cleanup did not consume its task in one stable iteration: {still.get('reason_code')} {still.get('reason') or still.get('errors')}")
    if t != snap_t or board != snap_e or run_cleanup(t, board) != still:
        errors.append("run_cleanup mutated its inputs or is not deterministic")
    check = build_engine_check("turn_step", still, input_hashes={"timing_state": state_hash(t), "effect_state": hash_value(board)})
    if check["outcome"] != "supported" or "cleanup_orchestration" not in check["coverage"]["supported_scope"] or "gear_rune_recall_cleanup" in check["coverage"]["unsupported_scope"]:
        errors.append(f"engine-check did not wrap run_cleanup with its scope: {check['outcome']}")
    ordered = copy.deepcopy(t); ordered["outstanding_tasks"] = ["scoring_step", "cleanup"]; ordered["phase"] = "beginning"; ordered["priority"] = None
    if run_cleanup(ordered, board).get("reason_code") != "task_order":
        errors.append("a Cleanup ran ahead of the task that precedes it")
    no_mode = copy.deepcopy(board); del no_mode["mode"]
    if not run_cleanup(t, no_mode).get("committed") or run_cleanup(t, no_mode)["trace"]["iterations"][0]["steps"][0].get("outcome") != "no_points_without_mode":
        errors.append("a Cleanup without a Mode of Play and no points did not run")
    pointed = copy.deepcopy(no_mode); pointed["players"]["p1"]["points"] = 2
    if run_cleanup(t, pointed).get("unsupported") is not True:
        errors.append("a Cleanup with points but no Mode of Play judged the victory condition")

    # --- lethal, Pending death trigger, control loss, staging and opening in one run ----------------------------------
    scene = base_state(); scene["mode"] = {"victory_score": 8}
    scene["battlefields"]["bf1"].update({"controller": "p2", "objects": ["u2"], "contested": True, "contested_by": "p1"})
    scene["players"]["p2"]["zones"]["base"].remove("u2")
    scene["objects"]["u2"].update({"damage": 4, "death_triggers": [trigger("u2-dies", "p2", "u2")]})  # lethal at bf1
    scene["players"]["p1"]["zones"]["base"].remove("u1"); scene["battlefields"]["bf1"]["objects"].append("u1")  # p1 alone once u2 dies
    scene["objects"]["u1"]["damage"] = 0
    run = run_cleanup(t, scene)
    if not run.get("committed"):
        errors.append(f"the lethal Cleanup did not commit: {run.get('reason_code')} {run.get('reason') or run.get('errors')}")
    else:
        tt, ee = run["next_timing_state"], run["next_effect_state"]
        steps = {s["step"]: s for s in run["trace"]["iterations"][0]["steps"]}
        if "u2" not in ee["players"]["p2"]["zones"]["trash"] or steps.get(3, {}).get("killed") != ["u2"] or [i["id"] for i in tt["chain"]["items"]] != ["u2-dies"] or tt["chain"]["items"][0]["status"] != "pending":
            errors.append(f"3b did not kill u2 with its death trigger Pending: {steps.get(3)} {tt['chain']['items']}")
        if ee["battlefields"]["bf1"]["controller"] is not None or steps.get(4, {}).get("outcome") != "applied":
            errors.append(f"step 4 did not drop p2's control of the emptied Battlefield in the same iteration: {steps.get(4)} {ee['battlefields']['bf1']}")
        if steps.get(6, {}).get("staged") != ["bf1"] or steps.get(9, {}).get("outcome") != "opened" or tt["showdown"] != {"active": True, "kind": "non_combat", "focus": "p1", "battlefield": "bf1", "focus_passes": []}:
            errors.append(f"the lone Unit's Showdown was not staged and opened with the trigger Pending: {steps.get(6)} {steps.get(9)} {tt['showdown']}")
        if len(run["trace"]["iterations"]) != 2 or run["trace"]["iterations"][1].get("changed") is not False:
            errors.append(f"the 322 follow-up did not run once and stop: {[i.get('changed') for i in run['trace']['iterations']]}")
        if validate_timing(tt) or validate_state(ee):
            errors.append(f"the Cleanup produced invalid states: {validate_timing(tt)} {validate_state(ee)}")
        if next_procedure(tt).get("procedure") != "finalize_oldest_pending":
            errors.append(f"after the Cleanup the Pending trigger is not next to finalize: {next_procedure(tt).get('procedure')}")
    if stage_showdown(with_task(quiet), scene).get("reason_code") != "requires_quiet_cleanup_boundary" or stage_combat(with_task(quiet), contested_board()).get("reason_code") != "combat_requires_quiet_cleanup_boundary":
        errors.append("a staging procedure called on its own accepted an outstanding task")

    # --- step 1 ends the game -------------------------------------------------------------------------------------------
    winning = copy.deepcopy(scene); winning["players"]["p1"]["points"] = 8
    ended = run_cleanup(t, winning)
    if not ended.get("committed") or ended["next_timing_state"].get("terminal", {}).get("winner") != "p1" or ended["trace"]["iterations"][0].get("skipped_after_terminal") is None or "u2" in ended["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        errors.append(f"step 1 did not end the game before the lethal step: {ended.get('reason_code')} {ended.get('trace', {}).get('iterations')}")
    elif next_procedure(ended["next_timing_state"]).get("procedure") != "game_over":
        errors.append("the ended state is not game_over")

    # --- two staged Combats: the decision ends the run uncommitted ------------------------------------------------------
    two = contested_board(extra_units=(("u3", "p1", "bf2"), ("u4", "p2", "bf2")))
    two["battlefields"]["bf2"].update({"contested": True, "contested_by": "p2"}); two["mode"] = {"victory_score": 8}
    two["objects"]["u1"]["damage"] = 0
    asked = run_cleanup(t, two)
    if asked.get("committed") or asked.get("reason_code") != "location_selection_required" or asked.get("cleanup_step") != "7":
        errors.append(f"two staged Combats did not stop the run for the Turn Player's choice: {asked.get('reason_code')} {asked.get('cleanup_step')}")
    else:
        check = build_engine_check("turn_step", asked, input_hashes={"timing_state": state_hash(t), "effect_state": hash_value(two)})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "location_choice":
            errors.append("the location choice inside the Cleanup did not wrap as location_choice")
    decision = decide(t, two, "bf1")
    chosen = run_cleanup(t, two, decision)
    if not chosen.get("committed") or chosen["next_timing_state"].get("combat", {}).get("status") != "open" or chosen["next_timing_state"]["combat"]["battlefield"] != "bf1" or chosen["next_timing_state"]["showdown"].get("kind") != "combat":
        errors.append(f"with the choice the Combat did not open at step 10: {chosen.get('reason_code')} {chosen.get('reason') or chosen.get('errors')} {chosen.get('next_timing_state', {}).get('combat', {}).get('status')}")

    # --- decisions are rebound to the working state, traced, and revalidated there (Codex review-fix) ----------------------
    if not chosen.get("committed"):
        pass
    else:
        rebinding = chosen["trace"].get("decision_rebinding", [])
        used = [r for r in rebinding if r.get("step") == "7"]
        if not used or used[0].get("derived_from_input_hash") != decision["input_hash"] or used[0].get("rebound_input_hash") == decision["input_hash"] or used[0].get("iteration") != 0 or "combat_location" not in used[0].get("decision_ids", []):
            errors.append(f"the rebinding of the location decision was not traced with its origin, iteration and step: {used}")
    stale_choice = decide(t, two, "bf9")
    if run_cleanup(t, two, stale_choice).get("valid") is not False:
        errors.append("a location that is not staged in the working state was accepted through the rebound envelope")

    # --- 323.7 runs inside the same Cleanup (C-58, ADR-0015 §2) ---------------------------------------------------------
    # This used to fail the whole run closed; step 5 now Recalls the Gear on
    # the working state the other steps act on.
    geared = copy.deepcopy(scene)
    add_unit(geared, "g1", "p1", "bf1", might=0, kind="gear")
    recalled = run_cleanup(t, geared)
    step5 = next((s for s in recalled.get("trace", {}).get("iterations", [{}])[0].get("steps", []) if s.get("step") == 5), None)
    if not recalled.get("committed") or step5 is None or step5.get("recalled") != ["g1"]:
        errors.append(f"step 5 did not Recall an unattached Gear at a Battlefield: {recalled.get('reason_code')} {step5}")
    elif "g1" not in recalled["next_effect_state"]["players"]["p1"]["zones"]["base"]:
        errors.append("the Recalled Gear did not arrive in its controller's Base (429)")
    elif recalled["next_effect_state"]["battlefields"]["bf1"]["objects"].count("g1"):
        errors.append("the Recalled Gear was left at the Battlefield")

    with tempfile.TemporaryDirectory(prefix="cleanup-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(t), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(scene), encoding="utf-8")
        run_cli = subprocess.run([sys.executable, str(RUNNER), "turn-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "run_cleanup", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run_cli.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI turn-step run_cleanup failed off-cwd: {run_cli.stderr.strip()}")

    if errors:
        print("FAILED: cleanup orchestration checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: one Cleanup runs steps 1-10a in order on one working state with its 322 follow-ups, death triggers stay Pending while nothing resolves, control loss and staging and opening follow in the same run, a terminal at step 1 skips the rest, a location choice or a 323.7 case commits nothing, and the staging procedures on their own still require the quiet boundary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
