#!/usr/bin/env python3
"""Regression gate for "Buff a friendly unit in your base, then move it to a battlefield."
(Showstopper): a later LINKED instruction on the same chosen object, and a chosen Move
destination that must be a Battlefield (Core 359.3.e.14, 359.3.e.14.a, 355.4.a, 144.4.b, 426.1.c).

The program: buff {target t: friendly unit in base}; move_board_object {target t (the SAME
decision - "it"), destination chosen, restriction battlefield, depends_on the buff,
dependency_mode unless_ignored}. Must hold:
  - the unit in its Base is Buffed and moved to the Battlefield chosen at resolution;
  - with no destination chosen, the candidates offered are exactly the Battlefields (no Base);
    a Base named as the destination is refused by name;
  - a Unit that already has a Buff is still chosen (426.1.c): the Buff is a no_op and the Move
    still happens - the earlier instruction executed;
  - the unit moved to a Battlefield before resolution: the Buff is ignored (illegal target), and
    the linked Move is skipped with it (359.3.e.14.a) - the unit stays where it was;
  - mutations: the same program with dependency_mode if_applied skips the Move of an already
    Buffed Unit (wrong), and without depends_on it moves the unit the Buff ignored (wrong);
  - an unknown dependency_mode is refused by the validator.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program  # noqa: E402

BUFF = {"op": "buff", "effect_id": "bf", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                                    "controller_relation": "friendly", "location": "base"}}
MOVE = {"op": "move_board_object", "effect_id": "mv", "target": {"decision_ref": "t", "chosen_zone_class": "board"},
        "destination": {"decision_ref": "dest", "restriction": "battlefield"},
        "depends_on": "bf", "dependency_mode": "unless_ignored"}


def board(*, buffed=False, at=None):
    """u1 (p1's) in p1's Base; two Battlefields, u2 (p2's) at bf1. `at` moves u1 to a
    Battlefield AFTER it was chosen (the decision still names it)."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["players"]["p2"]["zones"]["base"] = []
    state["battlefields"]["bf1"]["objects"] = ["u2"]
    state["objects"]["u1"]["damage"] = 0
    state["objects"]["u1"]["buffed"] = buffed
    state = settle_contested(state)
    chosen = object_identity(state, "u1")
    if at is not None:
        state["players"]["p1"]["zones"]["base"].remove("u1")
        state["battlefields"][at]["objects"].append("u1")
        state = settle_contested(state)
    return state, chosen


def run(state, chosen, dest="battlefield:bf2", effects=None):
    prog = program("showstopper", *(copy.deepcopy(effects) if effects is not None else [BUFF, MOVE]))
    prog["source_object"] = "c1"
    decisions = [{"decision_id": "t", "kind": "target_selection", "stage": "play_declaration", "controller": "p1",
                  "value": ["u1"], "selection_identities": {"u1": chosen}}]
    if dest is not None:
        decisions.append({"decision_id": "dest", "kind": "location_selection", "stage": "resolution",
                          "controller": "p1", "value": dest})
    return apply_program(state, prog, decisions={"schema_version": "engine-decisions.v1",
                                                 "input_hash": hash_value(state), "decisions": decisions})


def where(state, object_id):
    for bf, battlefield in state["battlefields"].items():
        if object_id in battlefield["objects"]:
            return f"battlefield:{bf}"
    for player, data in state["players"].items():
        if object_id in data["zones"]["base"]:
            return f"base:{player}"
    return None


def outcomes(result):
    return {e.get("effect_id"): e.get("outcome") for e in result.get("trace") or [] if e.get("effect_id") in {"bf", "mv"}}


def main() -> int:
    errors: list[str] = []
    if validate_program(program("showstopper", BUFF, MOVE)):
        errors.append(f"the linked program is invalid: {validate_program(program('showstopper', BUFF, MOVE))}")

    state, chosen = board()
    done = run(state, chosen)
    if not done.get("committed") or where(done["next_state"], "u1") != "battlefield:bf2" \
            or not done["next_state"]["objects"]["u1"].get("buffed"):
        errors.append(f"the unit in Base was not Buffed and moved to bf2: {done.get('reason') or outcomes(done)}")

    undecided = run(state, chosen, dest=None)
    if undecided.get("reason_code") != "location_selection_required" \
            or sorted(undecided.get("location_candidates") or []) != ["battlefield:bf1", "battlefield:bf2"]:
        errors.append(f"the destination candidates are not exactly the Battlefields: {undecided.get('reason_code')} "
                      f"{undecided.get('location_candidates')}")
    to_base = run(state, chosen, dest="base:p2")
    if to_base.get("committed"):
        errors.append("a Base was accepted as the destination of 'move it to a battlefield'")

    state, chosen = board(buffed=True)
    done = run(state, chosen)
    if not done.get("committed") or outcomes(done).get("bf") != "no_op" or where(done["next_state"], "u1") != "battlefield:bf2":
        errors.append(f"an already Buffed unit was not still moved (426.1.c; the Buff executed): {outcomes(done)}")
    wrong = run(state, chosen, effects=[BUFF, {**MOVE, "dependency_mode": "if_applied"}])
    if wrong.get("committed") and where(wrong["next_state"], "u1") == "battlefield:bf2":
        errors.append("mutation not caught: with if_applied the already Buffed unit still moved; the gate cannot tell the modes apart")

    state, chosen = board(at="bf1")
    done = run(state, chosen)
    if not done.get("committed") or outcomes(done) != {"bf": "ignored_illegal_target", "mv": "skipped_linked_dependency"} \
            or where(done["next_state"], "u1") != "battlefield:bf1":
        errors.append(f"a unit that left its Base was moved although the Buff was ignored (359.3.e.14.a): {outcomes(done)}")
    unlinked = run(state, chosen, effects=[BUFF, {k: v for k, v in MOVE.items() if k not in ("depends_on", "dependency_mode")}])
    if not (unlinked.get("committed") and where(unlinked["next_state"], "u1") == "battlefield:bf2"):
        errors.append("mutation not caught: without depends_on the ignored Buff's unit was not moved, so the case does not bite")

    forged = program("showstopper", BUFF, {**MOVE, "dependency_mode": "unless_whatever"})
    if not validate_program(forged):
        errors.append("an unknown dependency_mode was accepted")

    if errors:
        print("FAILED: linked move" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'Buff a friendly unit in your base, then move it to a battlefield': the chosen unit is Buffed and moved "
          "to the Battlefield chosen at resolution (a Base is never a candidate); an already Buffed unit is still moved "
          "(426.1.c); a unit that left its Base is neither Buffed nor moved (359.3.e.14.a); both mutations bite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
