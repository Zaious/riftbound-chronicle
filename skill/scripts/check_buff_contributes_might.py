#!/usr/bin/env python3
"""Regression gate: a Buff counter contributes its +1 Might.

Core 703: "Each Buff individually contributes +1 Might to a Unit." The engine
set a `buffed` flag on the object and stopped. `Buff a unit.` reported applied,
the flag went true, and the Unit's Might did not move - a signed mapping that
validates and then does less than the card says, which is the one failure mode
the whole mapping-review apparatus exists to catch.

476.3's own worked example is what it costs. Fiora, Victorious has printed
Might 4 and reads "While I'm Mighty, I have Deflect, Ganking, and Shield". The
rule walks through a player placing a buff on her: her Might is increased in
the Arithmetic layer, the Ability-Altering layer is then re-checked, and she
finalises at 5 Might WITH the three keywords. Miss the +1 and three keywords
silently stay off.

A Buff is a counter, not a continuous effect, so it is not in the effect list -
it is added as the layer runner seeds the Arithmetic layer, and it shows up in
the applied trace like anything else that moved the number.

What must hold:
  - a buffed Unit of printed Might 4 is 5, and the trace says where the 1 came
    from;
  - Buffing an already-Buffed Unit is a no_op and does NOT add a second +1
    (702.3, 426.1.b.1);
  - the Buff is in the Arithmetic layer, so a later limited decrease snapshots
    against the buffed number (477.3.b);
  - taking the Buff away takes the +1 away, which is 476.3's second example.

Not covered, and named rather than left implicit: the engine does not model
Mighty (Core 706), so the half of 476.3's example where 5 Might turns keywords
on cannot be asserted here. That is a gap in Mighty, not in Buff.

    python3 skill/scripts/check_buff_contributes_might.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from check_effect_ir import base_state, program  # noqa: E402
import effect_ir as IR  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def unit_at(might: int) -> dict:
    state = copy.deepcopy(base_state())
    state["objects"]["u1"].update({"base_might": might, "damage": 0})
    return state


def buff(state: dict) -> dict:
    result = IR.apply_program(state, program("b", {"op": "buff", "effect_id": "bf",
                                                   "object_id": "u1"}))
    if not result.get("committed"):
        raise AssertionError(f"buff did not commit: {result.get('errors') or result.get('reason')}")
    return result


def main() -> int:
    failures: list[str] = []

    # --- Core 703: the +1 lands, and the trace says where it came from -------
    result = buff(unit_at(4))
    state = result["next_state"]
    if not state["objects"]["u1"].get("buffed"):
        failures.append("the Buff counter was not placed (426.1.b)")
    got = IR.effective_might(state, "u1")
    if got != 5:
        failures.append(f"a buffed 4 Might Unit reads {got}; Core 703 gives each Buff +1 Might")
    applied = IR.characteristics(state, "u1").get("applied") or []
    buff_rows = [row for row in applied if row.get("effect_id") == "buff:u1"]
    if not buff_rows:
        failures.append("the +1 does not appear in the applied trace; a number that moved with "
                        "no record of what moved it is not reviewable")
    elif buff_rows[0].get("layer") != "arithmetic":
        failures.append(f"the Buff was applied in layer {buff_rows[0].get('layer')!r}; 476.3 puts "
                        f"it in the Arithmetic layer")

    # --- 702.3 / 426.1.b.1: one Buff at a time ------------------------------
    again = IR.apply_program(state, program("b2", {"op": "buff", "effect_id": "bf2",
                                                   "object_id": "u1"}))
    if again["trace"][0].get("outcome") != "no_op":
        failures.append("Buffing an already-Buffed Unit was not a no_op (426.1.b.1)")
    if again.get("committed") and IR.effective_might(again["next_state"], "u1") != 5:
        failures.append(f"a second Buff added another +1: the Unit reads "
                        f"{IR.effective_might(again['next_state'], 'u1')}, and 702.3 allows one "
                        f"Buff at a time")

    # --- the Buff is in the Arithmetic layer, so a limit snapshots against it -
    floored = IR.apply_program(state, program("f", {
        "op": "modify_might", "effect_id": "st", "object_id": "u1", "amount": -4, "minimum": 1,
        "duration": "this_turn", "source": "stupefy"}))
    if not floored.get("committed"):
        failures.append(f"the floored decrease did not commit: {floored.get('errors')}")
    else:
        moved = floored["trace"][0].get("amount")
        if moved != -4:
            failures.append(f"'-4 to a minimum of 1' on a buffed 4 Might Unit moved {moved}; the "
                            f"Unit is at 5, so the floor does not bite and the whole -4 applies "
                            f"(477.3.b). Reading the Buff after the decrease would give -3")
        if IR.effective_might(floored["next_state"], "u1") != 1:
            failures.append(f"the buffed Unit ends at "
                            f"{IR.effective_might(floored['next_state'], 'u1')}, expected 1")

    # --- 476.3's second example: the Buff goes, the +1 goes ------------------
    unbuffed = copy.deepcopy(state)
    unbuffed["objects"]["u1"]["buffed"] = False
    if IR.effective_might(unbuffed, "u1") != 4:
        failures.append(f"with the Buff removed the Unit reads "
                        f"{IR.effective_might(unbuffed, 'u1')}, expected its printed 4 (476.3)")

    print("Buff counters contribute Might (Core 703, 476.3, 702.3, 426.1.b.1)")
    print("  a buffed 4 Might Unit is 5, recorded in the Arithmetic layer")
    print("  a second Buff is a no_op and adds nothing; removing the Buff removes the +1")
    print("  NOT covered: Mighty (Core 706) is not modelled, so the keywords half of 476.3's")
    print("  example cannot be asserted. That is a gap in Mighty, not in Buff.")
    for failure in failures:
        print("\nFAILED: " + failure)
    if failures:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
