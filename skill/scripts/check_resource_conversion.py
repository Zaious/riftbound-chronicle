#!/usr/bin/env python3
"""Regression gate: resource conversion (set 2 package A2: Ancient Henge, Hextech Anomaly; Core 204.3.a, 430).

  C1  "Pay any amount of Energy to [Add] that much [A]": paying 2 Energy takes 2 and adds 2 universal Power
  C2  "Pay any amount of [A] to [Add] that much Energy": paying 2 Power adds 2 Energy
  C3  declined, the add is ignored with it; paid 0, nothing is added
  C4  paying more Energy than the pool holds is refused; the validator takes amount_ref on add_resource only as the
      linked paid amount, and pay_any_amount of a resource other than power_any or energy is refused
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, hash_value, validate_program  # noqa: E402


def decisions(pay, value, state):
    out = [{"decision_id": "payq", "kind": "optional_choice", "stage": "resolution", "controller": "p1", "value": pay}]
    if pay:
        out.append({"decision_id": "amt", "kind": "resource_allocation", "stage": "resolution", "controller": "p1",
                    "value": value})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": out}


def run(resource, add, pay, value, *, energy=3, power=None):
    state = base_state()
    state["players"]["p1"]["resources"] = {"energy": energy, "power": dict(power or {})}
    prog = program("conv", {"op": "pay_any_amount", "effect_id": "pay", "resource": resource, "decision_ref": "amt",
                            "pay_ref": "payq"},
                   {"op": "add_resource", "effect_id": "add", "player": "p1",
                    "amount_ref": {"kind": "linked_paid_amount", "effect_id": "pay"}, **add})
    problems = validate_program(prog)
    if problems:
        return None, problems
    return apply_program(state, prog, decisions=decisions(pay, value, state)), None


def main() -> int:
    errors: list[str] = []
    to_power = {"resource": "power", "universal": True}
    done, problems = run("energy", to_power, True, {"energy": 2})
    if problems or not done.get("committed"):
        errors.append(f"C1: {problems or done.get('reason_code')} {(done or {}).get('reason')}")
    else:
        res = done["next_state"]["players"]["p1"]["resources"]
        if res.get("energy") != 1 or sum((res.get("universal_power") or {}).values() if isinstance(res.get("universal_power"), dict)
                                         else [res.get("universal_power") or 0]) != 2:
            errors.append(f"C1: after paying 2 Energy the pool is {res}")
    done, problems = run("power_any", {"resource": "energy"}, True, {"fury": 2}, energy=0, power={"fury": 2})
    if problems or not done.get("committed") or done["next_state"]["players"]["p1"]["resources"].get("energy") != 2:
        errors.append(f"C2: {problems or (done or {}).get('reason_code')} {(done or {}).get('next_state', {}).get('players', {}).get('p1', {}).get('resources')}")
    for label, pay, value in (("declined", False, None), ("paid 0", True, {"energy": 0})):
        done, problems = run("energy", to_power, pay, value)
        if problems or not done.get("committed") or done["next_state"]["players"]["p1"]["resources"].get("energy") != 3:
            errors.append(f"C3 {label}: {problems or done.get('reason_code')}")
        elif (done["trace"][-1] or {}).get("outcome") not in ("skipped_linked_dependency", "no_op"):
            errors.append(f"C3 {label}: the add came out {(done['trace'][-1] or {}).get('outcome')}")
    done, _ = run("energy", to_power, True, {"energy": 5})
    if done is None or done.get("committed"):
        errors.append("C4: paying more Energy than the pool holds was accepted")
    bad = program("bad", {"op": "pay_any_amount", "effect_id": "pay", "resource": "xp", "decision_ref": "amt", "pay_ref": "payq"})
    if not validate_program(bad):
        errors.append("C4: pay_any_amount of xp was accepted")
    wrong = program("w", {"op": "add_resource", "effect_id": "add", "player": "p1", "resource": "energy",
                          "amount_ref": {"kind": "linked_object_current_might", "effect_id": "x"}})
    if not validate_program(wrong):
        errors.append("C4: add_resource reading a Might was accepted")
    if errors:
        print("resource conversion checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("resource conversion checks passed: any amount of Energy paid adds that much Power of any Domain, any Power paid "
          "adds that much Energy; declined or 0 adds nothing; overpaying refused; the shapes held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
