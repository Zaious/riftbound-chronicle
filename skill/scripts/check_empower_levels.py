#!/usr/bin/env python3
"""Regression gate: Empowered counts where a card's own text permits it.

Core 441.1.a says Empowered is binary and 441.1.b/c stop a second Empower. But
441.1.c.1 says a card may grant permission to be Empowered several times, and a
card whose text reads "I can be Empowered up to three times" is exactly that
case. The engine used to model the state as a flag, so such a card could only
ever be Empowered once and one Disempower removed everything.

What must hold:
  - with no permission (the default limit of one) nothing changes: a second
    Empower is the no_op of 441.1.c, and Disempower clears the state;
  - with a permission, each Empower adds a level while there is room, and the
    one that first makes the object Empowered is the only "becomes Empowered"
    event of 441.2.a - after that it was already Empowered;
  - at the limit, a further Empower is a no_op;
  - one Disempower removes one level (442.1), and the object stays Empowered
    while any level remains; the last one clears the state;
  - `empowered` and the count never disagree: an object is Empowered exactly
    while its count is above zero, and the validator says so.

    python3 skill/scripts/check_empower_levels.py
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


def last(result: dict) -> dict:
    """The trace row of the effect just applied; apply_program calls it `trace`."""
    rows = result.get("trace") or []
    return rows[-1] if rows else {}


def empower(state: dict, object_id: str):
    return IR.apply_program(state, program("e", {"op": "empower", "effect_id": "e", "object_id": object_id}))


def disempower(state: dict, object_id: str):
    return IR.apply_program(state, program("d", {"op": "disempower", "effect_id": "d", "object_id": object_id}))


def main() -> int:
    failures: list[str] = []
    base = base_state()

    # --- no permission: the rules as they were, unchanged -------------------
    state = copy.deepcopy(base)
    first = empower(state, "u1")
    if not first.get("committed") or first["next_state"]["objects"]["u1"].get("empowered") is not True:
        failures.append("a plain Empower no longer renders the object Empowered (441.1)")
    else:
        again = empower(first["next_state"], "u1")
        trace = last(again)
        if trace.get("outcome") != "no_op" or trace.get("became_empowered") is not False:
            failures.append("a second Empower without permission is not the no_op of 441.1.c")
        cleared = disempower(first["next_state"], "u1")
        if cleared["next_state"]["objects"]["u1"].get("empowered"):
            failures.append("Disempower did not remove the Empowered status (442.1)")

    # --- with permission: three levels, one event, one level removed --------
    state = copy.deepcopy(base)
    state["objects"]["u1"][IR.EMPOWER_LIMIT_FIELD] = 3
    step = empower(state, "u1")
    traces = [last(step)]
    if traces[0].get("became_empowered") is not True or traces[0].get("empowered_count") != 1:
        failures.append("the first Empower under a permission is not the becomes-Empowered event (441.2.a)")
    for expected in (2, 3):
        step = empower(step["next_state"], "u1")
        trace = last(step)
        traces.append(trace)
        if trace.get("empowered_count") != expected:
            failures.append(f"Empower under a permission did not reach level {expected} (441.1.c.1)")
        if trace.get("became_empowered") is not False:
            failures.append("a level after the first is reported as becoming Empowered; it was already Empowered")
    at_limit = empower(step["next_state"], "u1")
    limit_trace = last(at_limit)
    if limit_trace.get("outcome") != "no_op" or limit_trace.get("empowered_count") != 3:
        failures.append("Empower at the card's limit is not a no_op")

    one_off = disempower(step["next_state"], "u1")
    obj = one_off["next_state"]["objects"]["u1"]
    off_trace = last(one_off)
    if obj.get("empowered") is not True or obj.get(IR.EMPOWER_COUNT_FIELD) != 2:
        failures.append("one Disempower removed more than one level (442.1)")
    if off_trace.get("still_empowered") is not True or off_trace.get("levels_removed") != 1:
        failures.append("the Disempower trace does not report one level removed")
    down = one_off
    for _ in range(2):
        down = disempower(down["next_state"], "u1")
    final = down["next_state"]["objects"]["u1"]
    if final.get("empowered") or final.get(IR.EMPOWER_COUNT_FIELD):
        failures.append("the last Disempower left the object Empowered (441.1.a)")

    # --- the state cannot claim both ---------------------------------------
    bad = copy.deepcopy(base)
    bad["objects"]["u1"][IR.EMPOWER_LIMIT_FIELD] = 3
    bad["objects"]["u1"][IR.EMPOWER_COUNT_FIELD] = 2       # count without the state
    if not IR.validate_state(bad):
        failures.append("a state whose count and Empowered flag disagree is accepted")
    over = copy.deepcopy(base)
    over["objects"]["u1"]["empowered"] = True
    over["objects"]["u1"][IR.EMPOWER_COUNT_FIELD] = 4      # above the default limit of one
    if not IR.validate_state(over):
        failures.append("a count above the card's limit is accepted")

    print("empower levels (Core 441.1.c.1, 442.1)")
    print(f"  default limit {IR.DEFAULT_EMPOWER_LIMIT}; fields {IR.EMPOWER_LIMIT_FIELD}, {IR.EMPOWER_COUNT_FIELD}")
    print(f"  levels seen under a permission: {[t.get('empowered_count') for t in traces]}; "
          f"becomes-Empowered events: {sum(1 for t in traces if t.get('became_empowered'))}")
    for failure in failures:
        print("\nFAILED: " + failure)
    if failures:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
