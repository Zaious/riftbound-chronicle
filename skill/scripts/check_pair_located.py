#!/usr/bin/env python3
"""Regression gate: "Choose a friendly unit anywhere and an enemy unit at a battlefield. They deal damage equal to their
Mights to each other." (set 2 package A2: Marching Orders). The two choices are the pair's two target slots, chosen at
play (Core 355.5, 355.7): the friendly one at any Location, the enemy one at a Battlefield.

  P1  the friendly u5 (in p1's Base) and the enemy u2 (at bf1): committed; resolved, each took the other's Might
  P2  the enemy unit in p2's Base: refused at play (an illegal target)
  G   the line lowers to exactly this pair; its near misses do not
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_target_counts import board, play, resolve  # noqa: E402
from check_effect_ir import settle_contested  # noqa: E402
from effect_ir import effective_might  # noqa: E402

TEXT = "Choose a friendly unit anywhere and an enemy unit at a battlefield. They deal damage equal to their Mights to each other."
NEAR_MISSES = ("Choose a friendly unit and an enemy unit. They deal damage equal to their Mights to each other.",
               "Choose a friendly unit anywhere and an enemy unit anywhere. They deal damage equal to their Mights to each "
               "other.")
PAIR = {"op": "mutual_damage_current_might", "effect_id": "duel", "units": [
    {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"},
    {"decision_ref": "e", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy",
     "location": "battlefield"}]}


def main() -> int:
    errors: list[str] = []
    s = board()
    played = play(s, PAIR, t=["u5"], e=["u4"])
    if not played.get("committed"):
        errors.append(f"P1: refused {played.get('reason_code')} {played.get('reason')}")
    else:
        done = resolve(played, PAIR)
        after = (done.get("next_effect_state") or {}).get("objects") or {}
        u5, u4 = s["objects"]["u5"], s["objects"]["u4"]
        if not done.get("committed"):
            errors.append(f"P1: resolution refused {done.get('reason')}")
        elif after.get("u5", {}).get("damage", 0) != u5.get("damage", 0) + effective_might(s, "u4") \
                or ("u4" in after and after["u4"].get("damage", 0) < effective_might(s, "u4")
                    and "u4" in s["battlefields"]["bf1"]["objects"]):
            errors.append(f"P1: damage u5 {after.get('u5', {}).get('damage')}, u4 {after.get('u4', {}).get('damage')}")
    away = copy.deepcopy(s)
    away["battlefields"]["bf1"]["objects"].remove("u4")
    away["players"]["p2"]["zones"]["base"].append("u4")
    away = settle_contested(away)
    refused = play(away, PAIR, t=["u5"], e=["u4"])
    if refused.get("committed"):
        errors.append("P2: an enemy unit in its Base was accepted")
    grammar = CG.load_grammar()
    body = CG.compile_clause(TEXT, grammar)
    if body.get("unsupported") or body.get("program_effects") != [PAIR]:
        errors.append(f"G: {body.get('production_id')} {body.get('program_effects')}")
    for near in NEAR_MISSES:
        if CG.compile_clause(near, grammar).get("production_id") == body.get("production_id"):
            errors.append(f"G: the near miss {near!r} lowered to the row")
    if errors:
        print("located pair checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("located pair checks passed: a friendly unit in its Base and an enemy unit at a Battlefield deal their Mights to "
          "each other; an enemy unit in a Base is refused at play; lowered exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
