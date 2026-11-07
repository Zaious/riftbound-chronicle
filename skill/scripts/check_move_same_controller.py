#!/usr/bin/env python3
"""Regression gate: "Move an enemy unit to a location where there's a unit with the same controller." (set 2 package A2:
Temptation). A chosen Move destination restricted to a Location (a Base or a Battlefield, Core 198.1) holding another
Unit the moved unit's controller controls (with_same_controller_unit) - read where the destination is chosen and again
as the Move executes (Core 355.4.a, 355.15).

  M1 offered      u2 (p2) in p2's Base, p2's e3 at bf1, bf2 empty: the only destination offered is bf1 (not bf2; not
                  p2's Base, where u2 is the only p2 unit)
  M2 moved        bf1 chosen at play: u2 moves to bf1
  M3 not offered  bf2 chosen: refused
  M4 gone         e3 left bf1 before the Move executes: the Move is not carried out (skipped_illegal_destination)
  V  shape        the restriction without a decision_ref does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value,  # noqa: E402
                       move_destination_candidates, object_identity, validate_program)

MOVE = {"op": "move_board_object", "effect_id": "mv",
        "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"},
        "destination": {"decision_ref": "d", "restriction": "with_same_controller_unit"}}
errors: list[str] = []


def scene():
    s = base_state()
    s["objects"]["e3"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["battlefields"]["bf1"]["objects"].append("e3")
    s["battlefields"]["bf1"]["controller"] = "p2"
    s["battlefields"]["bf2"] = {"controller": None, "objects": []}
    return settle_contested(s)


def program(effect):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "tm", "controller": "p1", "effects": [copy.deepcopy(effect)]}


def run(state, place, chosen_state=None):
    at = chosen_state or state
    return apply_program(state, program(MOVE), decisions={"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                                                          "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u2"],
         "selection_identities": {"u2": object_identity(at, "u2")}},
        {"decision_id": "d", "stage": "play_declaration", "kind": "location_selection", "controller": "p1", "value": place}]})


def main() -> int:
    s = scene()
    if validate_program(program(MOVE)):
        errors.append(f"V: the program does not validate: {validate_program(program(MOVE))[:2]}")
    offered = move_destination_candidates(s, "u2", MOVE["destination"])
    if offered != ["battlefield:bf1"]:
        errors.append(f"M1 offered: {offered}")
    moved = run(s, "battlefield:bf1")
    if not moved.get("committed") or "u2" not in moved["next_state"]["battlefields"]["bf1"]["objects"]:
        errors.append(f"M2 moved: {moved.get('reason_code')} {moved.get('errors') or moved.get('reason')}")
    wrong = run(s, "battlefield:bf2")
    if wrong.get("committed") and "u2" in wrong["next_state"]["battlefields"]["bf2"]["objects"]:
        errors.append("M3 not offered: u2 moved to bf2")
    gone = copy.deepcopy(s)
    gone["battlefields"]["bf1"]["objects"].remove("e3")
    gone["players"]["p2"]["zones"]["trash"].append("e3")
    gone["battlefields"]["bf1"].pop("contested", None)
    gone["battlefields"]["bf1"].pop("contested_by", None)
    late = run(gone, "battlefield:bf1", chosen_state=s)
    outcomes = [t.get("outcome") for t in late.get("trace") or []]
    if not late.get("committed") or "skipped_illegal_destination" not in outcomes \
            or "u2" not in late["next_state"]["players"]["p2"]["zones"]["base"]:
        errors.append(f"M4 gone: {late.get('reason_code')} {late.get('errors') or late.get('reason')} {outcomes}")
    bad = {**MOVE, "destination": {"restriction": "with_same_controller_unit"}}
    if not validate_program(program(bad)):
        errors.append("V: the restriction with no decision_ref validated")
    if errors:
        print("same-controller move destination checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("same-controller move destination checks passed: only a Location holding another unit of the moved unit's "
          "controller is offered, it is moved there, another is refused, and one emptied before the Move is not carried out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
