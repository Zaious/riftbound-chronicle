#!/usr/bin/env python3
"""Regression gate: "Units can't move to base." printed on a permanent (set 2 package A2: Minotaur Reckoner).

  R1  with the permanent on the board (either player's), a Unit at a Battlefield may not move to a Base - the one
      predicate both the Standard Move and the Move instruction read (move_restricted, Core 359.3.e.6)
  R2  a move to another Battlefield is not restricted; with the permanent in a trash, nothing is
  R3  a Move instruction to a Base is ignored as it resolves, the Unit staying where it was
  R4  the printed form lowers to the field; another shape of it is refused by the validator
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import apply_program, find_location, move_restricted, validate_state  # noqa: E402

RESTRICTION = [{"affected_kind": "unit", "destination_kind": "base"}]


def board(where="base", owner="p2"):
    state = base_state()
    for held in list(state["players"]["p1"]["zones"]["base"]):
        if state["objects"][held].get("kind") == "unit":
            state["players"]["p1"]["zones"]["base"].remove(held)
            state["battlefields"]["bf1"]["objects"].append(held)
    state["objects"]["reckoner"] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 4,
                                    "might_modifiers": [], "damage": 0, "exhausted": False,
                                    "printed_move_restrictions": [dict(r) for r in RESTRICTION]}
    state["players"][owner]["zones"][where].append("reckoner")
    settle_contested(state)
    return state


def main() -> int:
    errors: list[str] = []
    unit = "u1"
    for owner in ("p1", "p2"):
        state = board(owner=owner)
        if find_location(state, unit)[0] != "battlefield":
            errors.append("fixture: u1 is not at a battlefield")
            break
        if move_restricted(state, unit, {"kind": "base", "player": "p1"}) is None:
            errors.append(f"R1: with {owner}'s permanent on the board, a move to base was not restricted")
        if move_restricted(state, unit, {"kind": "battlefield", "battlefield": "bf2"}) is not None:
            errors.append(f"R2: with {owner}'s permanent, a move to another battlefield was restricted")
    if move_restricted(board(where="trash"), unit, {"kind": "base", "player": "p1"}) is not None:
        errors.append("R2: the permanent in a trash still restricted the move")
    state = board()
    done = apply_program(state, program("mv", {"op": "move_board_object", "effect_id": "mv", "object_id": unit,
                                               "destination": {"kind": "base", "player": "p1"}}))
    if not done.get("committed") or find_location(done["next_state"], unit)[0] != "battlefield" \
            or (done.get("trace") or [{}])[0].get("outcome") != "skipped_restricted_move":
        errors.append(f"R3: the Move instruction to a base: {done.get('reason_code')} "
                      f"{(done.get('trace') or [{}])[0].get('outcome')}")
    got = CG.compile_clause("Units can't move to base.", CG.load_grammar())
    if ((got.get("passive") or {}).get("object_fields") or {}) != {"printed_move_restrictions": RESTRICTION}:
        errors.append(f"R4: lowered to {got.get('production_id')} {got.get('passive')}")
    bad = board()
    bad["objects"]["reckoner"]["printed_move_restrictions"] = [{"affected_kind": "unit", "destination_kind": "battlefield"}]
    if not any("printed_move_restrictions" in e for e in validate_state(bad)):
        errors.append("R4: another restriction shape was accepted")
    if errors:
        print("move-to-base restriction checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("move-to-base restriction checks passed: a permanent's 'Units can't move to base' restricts every Unit's move to "
          "a Base while it is on the board, either player's; not another destination, not from a trash; lowered; one shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
