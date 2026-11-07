#!/usr/bin/env python3
"""Regression gate: "I have +1 [M] for each friendly gear." (set 2 package A2: Ornn - Forge God). A passive Might per the
Gear its controller controls on the board (dynamic_might per friendly_gear_count), read fresh each time (Core 479.4.b).

  M1  ornn (4 Might) with p1's gear in p1's Base and p1's Equipment attached to another unit: 6
  M2  p2's gear on the board, and p1's gear in the trash, add nothing
  M3  a gear leaving the board lowers it at once (no snapshot)
  G   the printed line lowers to exactly that field
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402


def gear(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def main() -> int:
    errors: list[str] = []
    s = base_state()
    s["objects"]["ornn"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4, "might_modifiers": [],
                            "damage": 0, "exhausted": False,
                            "dynamic_might": [{"modifier_id": "own-text", "amount": 1, "per": {"kind": "friendly_gear_count"}}]}
    s["objects"]["g1"] = gear("p1")
    s["objects"]["g2"] = gear("p1", tags=["Equipment"], might_bonus=0)
    s["objects"]["g3"] = gear("p2")
    s["objects"]["g4"] = gear("p1")
    s["players"]["p1"]["zones"]["base"] += ["ornn", "g1", "g2"]
    s["players"]["p2"]["zones"]["base"].append("g3")
    s["players"]["p1"]["zones"]["trash"].append("g4")
    done = IR.apply_program(s, {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
                                "program_id": "at", "controller": "p1",
                                "effects": [{"op": "attach", "effect_id": "at", "object_id": "g2", "to": "u1"}]})
    if not done.get("committed"):
        errors.append(f"board: the attach did not commit: {done.get('reason') or done.get('errors')}")
        s2 = s
    else:
        s2 = done["next_state"]
    if IR.validate_state(s2):
        errors.append(f"board: {IR.validate_state(s2)[:2]}")
    if IR.effective_might(s2, "ornn") != 6:
        errors.append(f"M1/M2: ornn has {IR.effective_might(s2, 'ornn')}, expected 6 (two friendly gear on the board)")
    gone = copy.deepcopy(s2)
    gone["players"]["p1"]["zones"]["base"].remove("g1")
    gone["players"]["p1"]["zones"]["trash"].append("g1")
    if IR.effective_might(gone, "ornn") != 5:
        errors.append(f"M3: with g1 in the trash ornn has {IR.effective_might(gone, 'ornn')}, expected 5")
    got = CG.compile_clause("I have +1 :rb_might: for each friendly gear.", CG.load_grammar())
    if (got.get("passive") or {}).get("object_fields") != {"dynamic_might": [
            {"modifier_id": "own-text", "amount": 1, "per": {"kind": "friendly_gear_count"}}]}:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    if errors:
        print("might-per-gear checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("might-per-gear checks passed: +1 for each Gear its controller controls on the board (an attached Equipment "
          "included), none for the opponent's or the trash's, read fresh; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
