#!/usr/bin/env python3
"""
Regression gate: a card's printed static aura (2026-09-24).

"Other friendly units have +1 [M] here." is a passive ability of a unit on the board
(Core 365.1): a continuous effect over a set found by criteria, applied in the arithmetic
layer (Core 476-480) for as long as its source is active. The object carries it as
`static_auras`, read live - it is never copied into the state's effect list.

Must hold:
  - a source at bf1 gives another friendly unit at bf1 +1; not itself, not a friendly
    unit in its Base, not an enemy unit at bf1;
  - the aura stops the moment its source leaves the board (to its owner's trash);
  - moving the source to its Base stops "here" for the units at bf1;
  - the buffed variant reaches only a buffed friendly unit;
  - a Battlefield's own aura ("Units here have +1 [M].") reaches every unit at it, either
    side, and none elsewhere;
  - invalid: an aura with amount 0, and one with a criterion the engine cannot read.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import effective_might, validate_state  # noqa: E402

HERE = {"kind": "unit", "controller_relation": "friendly", "exclude_source": True, "at_source_battlefield": True}


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False, **extra}


def board(criteria=HERE):
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["g1", "u5", "u6", "e5"],
                                  "contested": True, "contested_by": "p2"}
    state["objects"]["g1"] = unit("p1", 4, static_auras=[{"aura_id": "here", "amount": 1, "criteria": dict(criteria)}])
    state["objects"]["u5"] = unit("p1", 2)
    state["objects"]["u6"] = unit("p1", 2, buffed=True)
    state["objects"]["e5"] = unit("p2", 2)
    return state


def mights(state):
    return {o: effective_might(state, o) for o in ("g1", "u5", "u6", "e5", "u1")}


def main() -> int:
    errors: list[str] = []
    state = board()
    if found := validate_state(state):
        errors.append(f"a board with a printed aura was invalid: {found}")
    got = mights(state)
    if got != {"g1": 4, "u5": 3, "u6": 4, "e5": 2, "u1": 3}:
        errors.append(f"'other friendly units have +1 here' reached the wrong units: {got}")

    gone = copy.deepcopy(state)
    gone["battlefields"]["bf1"]["objects"].remove("g1")
    gone["players"]["p1"]["zones"]["trash"].append("g1")
    if (got := mights(gone)) != {"g1": 4, "u5": 2, "u6": 3, "e5": 2, "u1": 3}:
        errors.append(f"the aura outlived its source leaving the board: {got}")

    home = copy.deepcopy(state)
    home["battlefields"]["bf1"]["objects"].remove("g1")
    home["players"]["p1"]["zones"]["base"].append("g1")
    if (got := mights(home)) != {"g1": 4, "u5": 2, "u6": 3, "e5": 2, "u1": 3}:
        errors.append(f"'here' still reached bf1 with its source in its Base: {got}")

    buffed = board({**HERE, "buffed": True})
    if (got := mights(buffed)) != {"g1": 4, "u5": 2, "u6": 4, "e5": 2, "u1": 3}:
        errors.append(f"'other buffed friendly units' reached an unbuffed unit or missed a buffed one: {got}")

    # a Battlefield's own aura: every Unit at it, either side; not a Unit elsewhere
    camp = base_state()
    camp["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u5", "e5"], "contested": True, "contested_by": "p2",
                                   "static_auras": [{"aura_id": "here", "amount": 1, "criteria": {"kind": "unit"}}]}
    camp["objects"]["u5"] = unit("p1", 2)
    camp["objects"]["e5"] = unit("p2", 2)
    if found := validate_state(camp):
        errors.append(f"a Battlefield with a printed aura was invalid: {found}")
    if (got := {o: effective_might(camp, o) for o in ("u5", "e5", "u1", "u2")}) != {"u5": 3, "e5": 3, "u1": 3, "u2": 4}:
        errors.append(f"'units here have +1' reached the wrong units: {got}")
    camp["battlefields"]["bf1"]["static_auras"][0]["criteria"] = {"kind": "gear"}
    if not validate_state(camp):
        errors.append("a Battlefield aura over gear validated")

    for bad in ({"aura_id": "zero", "amount": 0, "criteria": HERE},
                {"aura_id": "odd", "amount": 1, "criteria": {**HERE, "tribe": "yordle"}}):
        broken = board()
        broken["objects"]["g1"]["static_auras"] = [bad]
        if not validate_state(broken):
            errors.append(f"an invalid aura validated: {bad}")

    if errors:
        print("FAILED: static aura checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a printed aura reaches exactly the other friendly units at its source's battlefield (or only the buffed "
          "ones), stops when its source leaves the board or the battlefield, and a zero or unreadable aura is invalid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
