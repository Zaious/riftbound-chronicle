#!/usr/bin/env python3
"""Regression gate: "When you conquer here with one or more [Mighty] units" (set 2 package A2: Sunken Temple).

  M1  the printed form lowers to the Battlefield's Conquer trigger carrying {controls_units, count 1, location here,
      mighty: true} (Core 383.2.a.1: part of the Trigger Condition, read as the conquer is processed)
  M2  the condition holds with a Mighty Unit (5 Might) of the controller's at the Battlefield; not with a 4-Might one, nor
      an opponent's Mighty one there, nor the controller's Mighty Unit in its Base (Core 708)
  M3  mighty other than true is refused by the validator
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import evaluate_condition, validate_condition  # noqa: E402

CONDITION = {"kind": "controls_units", "count": 1, "location": "here", "mighty": True}


def board(units):
    state = base_state()
    bf = state["battlefields"]["bf1"]
    for held in list(bf.get("objects", [])):
        bf["objects"].remove(held)
        state["players"][state["objects"][held]["controller"]]["zones"]["base"].append(held)
    for oid, controller, might, where in units:
        state["objects"][oid] = {"owner": controller, "controller": controller, "kind": "unit", "base_might": might,
                                 "might_modifiers": [], "damage": 0, "exhausted": False}
        if where == "bf1":
            bf["objects"].append(oid)
        else:
            state["players"][controller]["zones"]["base"].append(oid)
    return state


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause("When you conquer here with one or more [Mighty] units, draw 1.", CG.load_grammar())
    triggers = ((got.get("passive") or {}).get("battlefield_fields") or {}).get("conquer_triggers") or [{}]
    if triggers[0].get("condition") != CONDITION:
        errors.append(f"M1: lowered to {got.get('production_id')} {triggers}")
    for label, units, want in (("a Mighty unit of p1's here", [("m", "p1", 5, "bf1")], True),
                               ("a 4-Might unit of p1's here", [("m", "p1", 4, "bf1")], False),
                               ("p2's Mighty unit here", [("m", "p2", 6, "bf1")], False),
                               ("p1's Mighty unit in its Base", [("m", "p1", 6, "base")], False)):
        if evaluate_condition(board(units), CONDITION, controller="p1", object_id="bf1") != want:
            errors.append(f"M2: {label} read {not want}")
    if not validate_condition({**CONDITION, "mighty": False}):
        errors.append("M3: mighty false was accepted")
    # M3: on a Battlefield's conquer trigger the validator takes this condition, and not the hold trigger's shape there
    from effect_ir import validate_state
    for label, cond, want_ok in (("mighty", CONDITION, True),
                                 ("no mighty", {k: v for k, v in CONDITION.items() if k != "mighty"}, False)):
        state = board([])
        state["battlefields"]["bf1"]["conquer_triggers"] = [
            {"trigger_id": "on-conquer", "controller_order": 0, "effect_program_id": "p", "optional_at_finalize": False,
             "condition": dict(cond)}]
        ok = not any("conquer_triggers" in e for e in validate_state(state))
        if ok != want_ok:
            errors.append(f"M3: a conquer trigger's condition with {label} validated {ok}")
    if errors:
        print("set 2 conquer-with-mighty checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("set 2 conquer-with-mighty checks passed: the Battlefield's Conquer trigger read with the controller's Mighty "
          "units there only; mighty other than true refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
