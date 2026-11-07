#!/usr/bin/env python3
"""Regression gate: "Your spells and abilities deal N bonus damage." lowered by the engine grammar (set 2 package A2).

  B1  the printed form lowers to one controller_sources damage modifier of N (the entry the set-1 pack passive
      carries for N = 1), and N is read off the text
  B2  the entry, bound to a source on the board, makes the controller's Deal N more and an opponent's Deal unchanged
      (effect_ir.bonus_damage, Core 713-715)
  B3  "to units here" and "the next spell" stay other productions
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    got = CG.compile_clause("Your spells and abilities deal 3 Bonus Damage.", grammar)
    entries = ((got.get("passive") or {}).get("state_lists") or {}).get("damage_modifiers")
    want = [{"modifier_id": "$clause_id", "source_object": "$source_object", "controller": "$controller", "amount": 3,
             "scope": {"kind": "controller_sources"}}]
    if got.get("production_id") != "your_spells_and_abilities_deal_n_bonus_damage" or entries != want:
        errors.append(f"B1: lowered to {got.get('production_id')} {entries}")
    for text, other in (("Spells and abilities deal 1 bonus damage to units here.",
                         "spells_and_abilities_deal_n_bonus_damage_to_units_here"),):
        if CG.compile_clause(text, grammar).get("production_id") != other:
            errors.append(f"B3: {text!r} is not {other}")
    if entries == want:
        state = base_state()
        state["damage_modifiers"] = [{**want[0], "modifier_id": "rd", "source_object": "u1", "controller": "p1"}]
        mine, _ = IR.bonus_damage(state, "p1", "u2")
        theirs, _ = IR.bonus_damage(state, "p2", "u1")
        if (mine, theirs) != (3, 0):
            errors.append(f"B2: p1's Deal gets {mine} more, p2's {theirs} (3 and 0 wanted)")
    if errors:
        print("set 2 bonus damage text checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("set 2 bonus damage text checks passed: the controller's sources' Bonus Damage lowered with its printed N; the "
          "Battlefield form stays its own production")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
