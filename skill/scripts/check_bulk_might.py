#!/usr/bin/env python3
"""
Regression gate: a Might change over every unit of a side, wherever it is (2026-09-24).

"Give friendly units +2 [M] this turn." names no place, and the clause grammar has always
lowered it to affected criteria with location `board`. The engine now expands that location:
every Base and every Battlefield (Core 105), a set found by criteria at execution, not
targets (Core 355.10.b).

Must hold:
  - +2 to friendly units reaches a friendly unit in its Base and one at a Battlefield;
    an enemy unit and a friendly gear are untouched;
  - -3 to enemy units, to a minimum of 1: each enemy unit on its own (4 -> 1, 2 -> 1), a
    friendly unit untouched;
  - "Kill all gear.": every Gear on the board, p1's in its Base and p2's at a Battlefield, goes
    to its owner's trash; every Unit stays where it was;
  - invalid: a whole-board instruction that also names a target.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, effective_might, find_location, validate_program  # noqa: E402


def board():
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u5"]}
    state["objects"]["u5"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("g1")
    state["objects"]["e5"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p2"]["zones"]["base"].append("e5")
    return state


def bulk(amount, relation, **extra):
    return {"op": "modify_might", "effect_id": "m", "amount": amount, "duration": "this_turn", "source": "s",
            "affected": {"criteria": {"kind": "unit", "controller_relation": relation, "location": "board"}}, **extra}


def main() -> int:
    errors: list[str] = []
    state = board()
    up = apply_program(state, program("up", bulk(2, "friendly")))
    if not up.get("committed"):
        errors.append(f"a whole-board +2 was refused: {up.get('reason') or up.get('errors')}")
    else:
        moved = {o: effective_might(up["next_state"], o) - effective_might(state, o) for o in ("u1", "u5", "u2", "e5", "g1")}
        if moved != {"u1": 2, "u5": 2, "u2": 0, "e5": 0, "g1": 0}:
            errors.append(f"+2 to friendly units did not reach exactly the friendly units, Base and Battlefield: {moved}")
    down = apply_program(state, program("down", bulk(-3, "enemy", minimum=1)))
    if not down.get("committed"):
        errors.append(f"a whole-board -3 was refused: {down.get('reason') or down.get('errors')}")
    else:
        after = {o: effective_might(down["next_state"], o) for o in ("u2", "e5", "u1")}
        if after != {"u2": 1, "e5": 1, "u1": effective_might(state, "u1")}:
            errors.append(f"-3 to enemy units, to a minimum of 1, did not hold per unit: {after}")
    # "Kill all gear." (2026-09-24, eff_160): the same `board` location over Gear, either side
    gear = board()
    gear["objects"]["g2"] = {"owner": "p2", "controller": "p2", "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False}
    gear["battlefields"]["bf1"]["objects"].append("g2")
    killed = apply_program(gear, program("gear", {"op": "kill", "effect_id": "k",
                                                  "affected": {"criteria": {"kind": "gear", "location": "board"}}}))
    if not killed.get("committed"):
        errors.append(f"killing all gear was refused: {killed.get('reason') or killed.get('errors')}")
    else:
        where = {o: find_location(killed["next_state"], o) for o in ("g1", "g2", "u1", "u5", "e5")}
        if where != {"g1": ("player", "p1", "trash"), "g2": ("player", "p2", "trash"), "u1": ("player", "p1", "base"),
                     "u5": ("battlefield", "bf1", None), "e5": ("player", "p2", "base")}:
            errors.append(f"'kill all gear' did not kill exactly every gear on the board: {where}")
    targeted = bulk(2, "friendly", target={"object_id": "u1", "chosen_zone_class": "board"})
    if not validate_program(program("bad", targeted)):
        errors.append("a whole-board instruction that names a target validated")
    if errors:
        print("FAILED: bulk might checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a whole-board Might change reaches every unit of its side in a Base or at a Battlefield and nothing "
          "else, the minimum holds per unit, and a whole-board instruction may not name a target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
