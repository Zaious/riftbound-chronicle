#!/usr/bin/env python3
"""
Gate for C-35 (ADR-0009 §8, §10): the Scoring Step (Hold) and the victory
facts.

Must hold:
  - in the Beginning Phase the Turn Player Holds every Battlefield they
    control that they have not scored this turn, in Battlefield-id order,
    gaining one point each; a Battlefield already scored this turn and an
    opponent's Battlefield are not held; control and Contested do not change;
  - Hold is never subject to the Final Point rule: at Victory Score - 1 a Hold
    gains the point, no draw;
  - the Hold triggers of every held Battlefield (the Unit there, a
    controller-scope source, the Battlefield's own) are one batch on the
    chain; a Unit at an unheld Battlefield does not fire; the scoring_step
    task is consumed;
  - a missing Mode of Play and any team are unsupported; the Main Phase, an
    open chain, another outstanding task and an ongoing Showdown refuse;
  - the victory facts after a Hold name threshold_met, strict_leader and
    tied_at_threshold and declare no winner; the victory_facts step changes
    nothing;
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

from battlefield_control import SCORING_TASK, report_victory_facts, run_scoring_step  # noqa: E402
from check_combat_damage_assignment import add_unit  # noqa: E402
from check_combat_staging import trigger  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import state_hash, validate_state as validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def beginning(**kw):
    return {**fixture(**kw), "phase": "beginning", "priority": None}


def holdings(*, victory_score=8, points=0):
    """p1 controls bf1 (u1 there) and bf2 (u3 there); p2 controls bf3 (u2 there)."""
    state = base_state()
    state["mode"] = {"victory_score": victory_score}
    state["players"]["p1"]["points"] = points
    state["players"]["p1"]["zones"]["base"].remove("u1"); state["battlefields"]["bf1"]["objects"].append("u1"); state["battlefields"]["bf1"]["controller"] = "p1"
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
    add_unit(state, "u3", "p1", "bf2", might=2, hold_triggers=[trigger("u3-hold", "p1", "u3", order=1)])
    state["players"]["p2"]["zones"]["base"].remove("u2"); state["battlefields"]["bf3"] = {"controller": "p2", "objects": ["u2"]}
    state["objects"]["u2"]["hold_triggers"] = [trigger("u2-hold", "p2", "u2")]
    return state


def main() -> int:
    errors: list[str] = []
    t = beginning(tasks=[SCORING_TASK])

    # --- a plain Hold ---------------------------------------------------------------------------------
    e = holdings()
    snap_t, snap_e = copy.deepcopy(t), copy.deepcopy(e)
    held = run_scoring_step(t, e)
    if not held.get("committed"):
        errors.append(f"the Scoring Step did not commit: {held.get('reason_code')} {held.get('reason') or held.get('errors')}")
        print("FAILED: scoring step checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    th, eh = held["next_timing_state"], held["next_effect_state"]
    if held["trace"]["held"] != ["bf1", "bf2"] or eh["players"]["p1"].get("points") != 2 or eh["players"]["p1"].get("scored_this_turn") != {"turn-0": ["bf1", "bf2"]} or eh["players"]["p2"].get("points", 0) != 0:
        errors.append(f"the Turn Player did not Hold exactly their Battlefields: {held['trace']['held']} {eh['players']['p1']}")
    if [i["id"] for i in th["chain"]["items"]] != ["u3-hold"] or th["outstanding_tasks"] != [] or th["chain"]["items"][0]["batch_id"] != "score:hold:turn-0:p1":
        errors.append(f"the Hold trigger of the held Battlefield was not scheduled once as the Hold batch, or the task remains: {th['chain']['items']} {th['outstanding_tasks']}")
    if {b: bf.get("controller") for b, bf in eh["battlefields"].items()} != {"bf1": "p1", "bf2": "p1", "bf3": "p2"} or any(bf.get("contested") for bf in eh["battlefields"].values()):
        errors.append("the Hold changed control or Contested")
    if validate_timing(th) or validate_state(eh):
        errors.append(f"states after the Hold are invalid: {validate_timing(th)} {validate_state(eh)}")
    if t != snap_t or e != snap_e or run_scoring_step(t, e) != held:
        errors.append("run_scoring_step mutated its inputs or is not deterministic")
    check = build_engine_check("control_step", held, input_hashes={"timing_state": state_hash(t), "effect_state": hash_value(e)})
    if check["outcome"] != "supported" or "hold_scoring" not in check["coverage"]["supported_scope"] or "beginning_phase" not in check["coverage"]["unsupported_scope"]:
        errors.append(f"engine-check did not wrap the Scoring Step with its scope: {check['outcome']}")
    facts = held["trace"]["victory_check"]
    if facts.get("threshold_met") != [] or facts.get("strict_leader") is not None or facts.get("tied_at_threshold") is not False:
        errors.append(f"victory facts after the Hold are wrong: {facts}")

    # --- already scored, one batch across Battlefields, controller-scope and Battlefield sources -----------
    e2 = holdings()
    e2["players"]["p1"]["scored_this_turn"] = {"turn-0": ["bf1"]}
    e2["objects"]["u1"]["hold_triggers"] = [trigger("u1-hold", "p1", "u1")]  # at bf1, already scored: silent
    add_unit(e2, "g1", "p1", "base:p1", might=0, kind="gear", hold_triggers=[{**trigger("g1-you-hold", "p1", "g1", order=0), "scope": "controller"}])
    e2["battlefields"]["bf2"]["hold_triggers"] = [{"trigger_id": "bf2-hold", "controller_order": 2, "effect_program_id": "bf2-hold-effects", "optional_at_finalize": False}]
    partial = run_scoring_step(t, e2)
    ids = [i["id"] for i in partial.get("next_timing_state", {}).get("chain", {}).get("items", [])]
    if not partial.get("committed") or partial["trace"]["held"] != ["bf2"] or partial["trace"]["skipped_already_scored"] != ["bf1"] or partial["next_effect_state"]["players"]["p1"].get("points") != 1:
        errors.append(f"a Battlefield already scored this turn was held again (470): {partial.get('reason_code')} {partial.get('trace', {}).get('held')}")
    elif ids != ["g1-you-hold", "u3-hold", "bf2-hold"] or len({i["batch_id"] for i in partial["next_timing_state"]["chain"]["items"]}) != 1:
        errors.append(f"the Hold triggers are not one batch from the right sources: {ids}")
    # --- Hold is not restricted by the Final Point rule --------------------------------------------------------
    e3 = holdings(victory_score=3, points=2)
    del e3["battlefields"]["bf2"]; del e3["objects"]["u3"]
    final = run_scoring_step(t, e3)
    if not final.get("committed") or final["next_effect_state"]["players"]["p1"].get("points") != 3 or final["trace"]["scoring"][0].get("gain") != "point" or len(final["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != 0:
        errors.append(f"a Hold at Victory Score - 1 did not gain the point outright (471.1.a.1): {final.get('trace', {}).get('scoring')}")
    else:
        facts = final["trace"]["victory_check"]
        if facts.get("threshold_met") != ["p1"] or facts.get("strict_leader") != "p1" or facts.get("tied_at_threshold") is not False or "winner" in facts:
            errors.append(f"victory facts at the threshold are wrong or name a winner: {facts}")
        tied = copy.deepcopy(final["next_effect_state"]); tied["players"]["p2"]["points"] = 3
        vf = report_victory_facts(final["next_timing_state"], tied)
        if not vf.get("committed") or vf["next_effect_state"] != tied or vf["trace"]["victory_check"].get("tied_at_threshold") is not True or vf["trace"]["victory_check"].get("strict_leader") is not None or vf["trace"].get("winner_declared") is not False:
            errors.append(f"the victory_facts step changed something or missed the tie: {vf.get('reason_code')} {vf.get('trace')}")

    # --- refusals -------------------------------------------------------------------------------------------
    e = holdings()
    no_mode = copy.deepcopy(e); del no_mode["mode"]
    if run_scoring_step(t, no_mode).get("reason_code") != "mode_unknown" or run_scoring_step(t, no_mode).get("unsupported") is not True:
        errors.append("a Hold without a Mode of Play guessed a Victory Score")
    team = copy.deepcopy(e); team["players"]["p2"]["team_id"] = "B"
    if run_scoring_step(t, team).get("reason_code") != "team_scoring":
        errors.append("team scoring was attempted in the Scoring Step")
    if run_scoring_step(fixture(), e).get("reason_code") != "scoring_step_requires_beginning_phase":
        errors.append("the Scoring Step ran in the Main Phase")
    if run_scoring_step(beginning(items=[item("spell-1", "p1", "spell", "default")], priority="p2"), e).get("reason_code") != "requires_quiet_cleanup_boundary":
        errors.append("the Scoring Step ran with the chain open")
    if run_scoring_step(beginning(tasks=["cleanup"]), e).get("reason_code") != "requires_quiet_cleanup_boundary":
        errors.append("the Scoring Step ran with another task outstanding")
    in_showdown = beginning(showdown=True, focus="p1"); in_showdown["priority"] = "p1"
    if run_scoring_step(in_showdown, e).get("reason_code") != "showdown_or_combat_ongoing":
        errors.append("the Scoring Step ran during a Showdown")
    nothing = run_scoring_step(t, base_state() | {"mode": {"victory_score": 8}})
    if not nothing.get("committed") or nothing["trace"]["held"] != [] or nothing["next_effect_state"]["players"]["p1"].get("points", 0) != 0:
        errors.append("a Turn Player controlling nothing did not Hold nothing")
    with tempfile.TemporaryDirectory(prefix="scoring-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(t), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(e), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "control-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "scoring_step", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI control-step scoring_step failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: scoring step checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: in the Beginning Phase the Turn Player Holds every Battlefield they control and have not scored this turn for one point each with no Final Point restriction, the Hold triggers of all held Battlefields are one batch, control and Contested stay, a missing Mode of Play or a team is unsupported, and the victory condition is reported as facts without a winner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
