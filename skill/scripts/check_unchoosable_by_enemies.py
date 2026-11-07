#!/usr/bin/env python3
"""Regression gate: "I can't be chosen by enemy spells and abilities." (set 2 package A2: Ruin Runner; Core 355.5).

  U1  an opponent's choice cannot name the object; its own controller's can; a choice with no known controller is refused
  U2  the restriction does not reach a set found by criteria (nothing is chosen there)
  U3  the printed form lowers to the field; the validator refuses a value other than true
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, evaluate_target, object_identity, validate_state  # noqa: E402


def main() -> int:
    errors: list[str] = []
    state = base_state()
    state["objects"]["u1"]["unchoosable_by_enemies"] = True
    target = {"object_id": "u1", "kind": "unit", "chosen_zone_class": "board",
              "bound_identity": object_identity(state, "u1") or "u1@0"}
    for chooser, want in (("p2", False), ("p1", True), (None, False)):
        ok, reason = evaluate_target(state, dict(target), chooser)
        if ok != want:
            errors.append(f"U1: chosen for {chooser!r}: {ok} ({reason})")
    owner = state["objects"]["u1"]["controller"]
    where = next(z for z, ids in state["players"][owner]["zones"].items() if "u1" in ids) \
        if any("u1" in ids for ids in state["players"][owner]["zones"].values()) else "battlefield"
    done = apply_program(state, {**program("all", {"op": "exhaust", "effect_id": "ex",
                                                    "affected": {"criteria": {"kind": "unit", "location": "board"}}}),
                                 "controller": "p2"})
    if not done.get("committed") or not done["next_state"]["objects"]["u1"].get("exhausted"):
        errors.append(f"U2: a set by criteria left it out ({done.get('reason_code')}, u1 in {where})")
    got = CG.compile_clause("I can't be chosen by enemy spells and abilities.", CG.load_grammar())
    if ((got.get("passive") or {}).get("object_fields") or {}) != {"unchoosable_by_enemies": True}:
        errors.append(f"U3: lowered to {got.get('production_id')} {got.get('passive')}")
    bad = base_state()
    bad["objects"]["u1"]["unchoosable_by_enemies"] = "yes"
    if not any("unchoosable_by_enemies" in e for e in validate_state(bad)):
        errors.append("U3: a non-true value was accepted")
    if errors:
        print("unchoosable-by-enemies checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("unchoosable-by-enemies checks passed: an opponent's choice refused, its controller's allowed, an unknown "
          "chooser refused; a set by criteria still reaches it; lowered; a bad value refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
