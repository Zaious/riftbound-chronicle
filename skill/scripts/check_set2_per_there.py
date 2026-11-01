#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "Give a friendly unit at a battlefield +2 [M] this turn for each enemy unit there."
(Against the Odds) - modify_might per_unit_there {controller_relation: enemy}.

  P1 two enemy units at the unit's Battlefield, one more at another Battlefield, a friendly one beside it: +4 (2 x 2); the
     enemy elsewhere and the friendly one are not counted
  P2 no enemy unit there: nothing moves (a no_op, Core 370.1.a)
  P3 counted as it executes: one enemy unit moved away before it resolves - +2
  V  per_unit_there on a draw, with another relation, or beside an amount_ref - refused

    python skill/scripts/check_set2_per_there.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, effective_might, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might=2):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "odds", "controller": "p1", "effects": effects}


ODDS = [{"op": "modify_might", "effect_id": "mm", "object_id": "hero", "amount": 2, "duration": "this_turn",
         "source": "odds", "per_unit_there": {"controller_relation": "enemy"}}]


def board(enemies_here=2):
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["objects"]["hero"] = unit("p1", 3)
    state["objects"]["pal"] = unit("p1", 3)
    state["battlefields"]["bf1"]["objects"] = ["hero", "pal"]
    for n in range(enemies_here):
        state["objects"][f"foe{n}"] = unit("p2", 4)
        state["battlefields"]["bf1"]["objects"].append(f"foe{n}")
    state["objects"]["far"] = unit("p2", 4)
    state["battlefields"]["bf2"]["objects"] = ["far"]
    return settle_contested(state)


def might_after(state, effects=ODDS):
    done = apply_program(state, program(effects))
    if not done.get("committed"):
        return f"refused: {done.get('errors') or done.get('reason')}"
    return effective_might(done["next_state"], "hero")


def main() -> int:
    if (got := might_after(board())) != 7:
        fail("P1", f"two enemy units there: Might {got}, not 7 (3 + 2 x 2)")
    if (got := might_after(board(0))) != 3:
        fail("P2", f"no enemy unit there: Might {got}, not 3")
    moved = board()
    moved["battlefields"]["bf1"]["objects"].remove("foe1")
    moved["battlefields"]["bf2"]["objects"].append("foe1")
    if (got := might_after(settle_contested(moved))) != 5:
        fail("P3", f"one enemy unit moved away first: Might {got}, not 5")
    for label, bad in (("on a draw", {"op": "draw", "effect_id": "d", "player": "p1", "count": 1,
                                      "per_unit_there": {"controller_relation": "enemy"}}),
                       ("another relation", {**ODDS[0], "per_unit_there": {"controller_relation": "any"}}),
                       ("beside an amount_ref", {**{k: v for k, v in ODDS[0].items() if k != "amount"},
                                                 "amount_ref": {"kind": "object_current_might"}})):
        if not any("per_unit_there" in p for p in validate_program(program([bad]))):
            fail("V", f"{label} validated")
    if errors:
        print("FAILED: set 2 per_unit_there")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'for each enemy unit there' counts the enemy units at the unit's own Battlefield as it executes (359.3.f.2) "
          "- not elsewhere, not friendly ones; none there moves nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
