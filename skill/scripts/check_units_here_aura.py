#!/usr/bin/env python3
"""Regression gate: "Your units here have [Ganking]." (set 2 package A2: Shurelya's Requiem [Effect Text]).

  A1  with the source at bf1: the source and p1's other unit at bf1 have Ganking; p1's unit at bf2, p1's unit in its
      Base and p2's unit at bf1 do not
  A2  the source moved to its Base: no unit has it from the aura ("here" names a Battlefield, at_source_battlefield)
  A3  the printed form lowers to the aura; "other friendly units here" keeps its own production
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import has_keyword, validate_state  # noqa: E402


def unit(owner):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(fields, source_at="bf1"):
    state = base_state()
    for bf in ("bf1", "bf2"):
        state["battlefields"].setdefault(bf, {"controller": None, "objects": []})
        for held in list(state["battlefields"][bf]["objects"]):
            state["battlefields"][bf]["objects"].remove(held)
            state["players"][state["objects"][held]["controller"]]["zones"]["base"].append(held)
    state["objects"]["src"] = {**unit("p1"), **copy.deepcopy(fields)}
    for oid, owner, where in (("mate", "p1", "bf1"), ("far", "p1", "bf2"), ("home", "p1", "base"), ("foe", "p2", "bf1")):
        state["objects"][oid] = unit(owner)
        if where == "base":
            state["players"][owner]["zones"]["base"].append(oid)
        else:
            state["battlefields"][where]["objects"].append(oid)
    if source_at == "base":
        state["players"]["p1"]["zones"]["base"].append("src")
    else:
        state["battlefields"][source_at]["objects"].append("src")
    return settle_contested(state)


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    got = CG.compile_clause("Your units here have [Ganking].", grammar)
    fields = (got.get("passive") or {}).get("object_fields") or {}
    if got.get("production_id") != "your_units_here_have_keyword" or fields.get("static_auras") != [
            {"aura_id": "here-ganking", "keyword": "ganking",
             "criteria": {"kind": "unit", "controller_relation": "friendly", "at_source_battlefield": True}}]:
        errors.append(f"A3: lowered to {got.get('production_id')} {fields}")
    other = CG.compile_clause("Other friendly units here have [Assault].", grammar)
    if other.get("production_id") != "other_friendly_units_here_have_keyword":
        errors.append(f"A3: the other-units aura lowered to {other.get('production_id')}")
    state = board(fields)
    if validate_state(state):
        errors.append(f"fixture invalid: {validate_state(state)[:2]}")
    want = {"src": True, "mate": True, "far": False, "home": False, "foe": False}
    got_on = {o: has_keyword(state, o, "ganking") for o in want}
    if got_on != want:
        errors.append(f"A1: Ganking {got_on}, wanted {want}")
    away = board(fields, source_at="base")
    if any(has_keyword(away, o, "ganking") for o in want):
        errors.append(f"A2: with the source in its Base: {[o for o in want if has_keyword(away, o, 'ganking')]}")
    if errors:
        print("units-here aura checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("units-here aura checks passed: the source and p1's other unit at its Battlefield have the keyword; elsewhere, "
          "the opponent's and with the source in its Base none; lowered beside the other-units aura")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
