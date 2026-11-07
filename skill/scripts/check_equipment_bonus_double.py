#!/usr/bin/env python3
"""Regression gate: "Each Equipment attached to me gives double its base Might bonus." (set 2 package A2: Gearhead). A
unit's own printed multiplier on the printed Might Bonus of each Equipment attached to it (Core 159.1).

  D1  Gearhead (2 Might) with an Equipment of Might Bonus +2 attached: 6 Might (2 + 2x2)
  D2  the same Equipment attached to a plain 2-Might unit: 4 Might
  D3  a non-Equipment gear with a Might Bonus attached to Gearhead: counted once
  V   a multiplier other than 2 does not validate
  G   the printed line lowers to exactly the field
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

TEXT = "Each Equipment attached to me gives double its base Might bonus."


def scene(multiplier=True, tags=("Equipment",)):
    s = base_state()
    s["objects"]["gh"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False, **({"equipment_bonus_multiplier": 2} if multiplier else {})}
    s["objects"]["eq"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": list(tags), "might_bonus": 2}
    s["players"]["p1"]["zones"]["base"] += ["gh", "eq"]
    done = IR.apply_program(s, {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET,
                                                                                    "faq_as_of": IR.FAQ_AS_OF},
                                "program_id": "at", "controller": "p1",
                                "effects": [{"op": "attach", "effect_id": "at", "object_id": "eq", "to": "gh"}]})
    if not done.get("committed"):
        raise SystemExit(f"the attach did not commit: {done.get('reason') or done.get('errors')}")
    return done["next_state"]


def main() -> int:
    errors: list[str] = []
    s = scene()
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    if IR.effective_might(s, "gh") != 6:
        errors.append(f"D1: {IR.effective_might(s, 'gh')}")
    if IR.effective_might(scene(multiplier=False), "gh") != 4:
        errors.append(f"D2: {IR.effective_might(scene(multiplier=False), 'gh')}")
    if IR.effective_might(scene(tags=()), "gh") != 4:
        errors.append(f"D3: {IR.effective_might(scene(tags=()), 'gh')}")
    bad = copy.deepcopy(s)
    bad["objects"]["gh"]["equipment_bonus_multiplier"] = 3
    if not any("equipment_bonus_multiplier" in p for p in IR.validate_state(bad)):
        errors.append("V: a multiplier of 3 validated")
    got = CG.compile_clause(TEXT, CG.load_grammar())
    if (got.get("passive") or {}).get("object_fields") != {"equipment_bonus_multiplier": 2}:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    if errors:
        print("equipment bonus double checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("equipment bonus double checks passed: an attached Equipment's printed bonus counts twice on the card, once on "
          "another unit, and a non-Equipment gear's once; validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
