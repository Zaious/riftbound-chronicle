#!/usr/bin/env python3
"""Regression gate: swapping two Units' Might is two Might changes, not a write.

"Swap the Might of two units this turn" reads as one instruction, but Core 477
has no operation that assigns a Might. What it has is Might changes, and the
official reading is that the difference is worked out first and then applied to
both Units - a decrease on one and an increase on the other. That is not a
pedantic distinction: it is what lets a Replacement Effect worded "if a spell
would give me -Might" see the decrease, and it is why the second change is not
computed from a Might the first one already moved.

What must hold:
  - 6 and 2 end up 2 and 6, and the trace shows one snapshot and one delta;
  - the two changes are ordinary modify_might events, each with its own
    effect_id, so replacements and the Arithmetic layer treat them normally;
  - two Units already equal produce no event at all (Core 370.1.a);
  - the same Unit twice, or a Unit that is not a legal referent, is refused
    without half-applying (Core 359.3.e.5);
  - the op never reaches _apply_one: it is composite, like the mutual damage of
    a Gentlemen's Duel.

    python3 skill/scripts/check_swap_might.py
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


def selector(object_id: str, relation: str) -> dict:
    return {"object_id": object_id, "chosen_zone_class": "board", "kind": "unit",
            "controller_relation": relation}


def two_units(might_a: int, might_b: int) -> dict:
    state = base_state()
    state["objects"]["u1"]["base_might"] = might_a
    state["objects"]["u2"] = copy.deepcopy(state["objects"]["u1"])
    state["objects"]["u2"].update({"base_might": might_b, "controller": "p2", "owner": "p2"})
    return state


def swap(units: list[dict]) -> dict:
    return program("swap", {"op": "swap_might", "effect_id": "sw", "source": "kayle",
                            "units": units, "duration": "this_turn"})


def event_for(result: dict, effect_id: str) -> dict | None:
    for event in result.get("trace") or []:
        if event.get("effect_id") == effect_id:
            return event
    return None


def main() -> int:
    failures: list[str] = []
    pair = [selector("u1", "friendly"), selector("u2", "enemy")]

    # --- the ordinary case ---------------------------------------------------
    result = IR.apply_program(two_units(6, 2), swap(pair))
    if not result.get("committed"):
        failures.append(f"a legal swap did not commit: {result.get('errors') or result.get('reason')}")
    else:
        after = {oid: IR.effective_might(result["next_state"], oid) for oid in ("u1", "u2")}
        if after != {"u1": 2, "u2": 6}:
            failures.append(f"6 and 2 did not become 2 and 6: {after}")
        parent = event_for(result, "sw")
        if not parent or parent.get("might_before") != {"u1": 6, "u2": 2} or parent.get("delta") != -4:
            failures.append(f"the swap event does not record one snapshot and one delta: {parent}")
        children = [event_for(result, "sw:a"), event_for(result, "sw:b")]
        if any(child is None or child.get("op") != "modify_might" for child in children):
            failures.append("the swap did not expand into two ordinary modify_might events (Core 477)")
        elif [child["amount"] for child in children] != [-4, 4]:
            failures.append(f"the two Might changes are not the one difference, both ways: {children}")

    # The second change must come from the snapshot, not from a Might the first
    # one already moved. Computed serially, u2 would end at 2 + (2 - 2) = 2.
    serial = IR.apply_program(two_units(5, 1), swap(pair))
    if serial.get("committed"):
        after = {oid: IR.effective_might(serial["next_state"], oid) for oid in ("u1", "u2")}
        if after != {"u1": 1, "u2": 5}:
            failures.append(f"the second change was computed after the first moved: {after}")

    # --- Core 370.1.a: already equal, so nothing happens ---------------------
    equal = IR.apply_program(two_units(4, 4), swap(pair))
    parent = event_for(equal, "sw")
    if not equal.get("committed") or not parent or parent.get("outcome") != "no_op":
        failures.append(f"two Units of equal Might still produced an event: {parent}")
    if equal.get("committed") and (equal["next_state"].get("continuous_effects") or []):
        failures.append("an equal-Might swap left a continuous effect behind (370.1.a)")

    # --- Core 359.3.e.5: the swap relates to both Units ----------------------
    same = IR.apply_program(two_units(6, 2), swap([selector("u1", "friendly"), selector("u1", "friendly")]))
    parent = event_for(same, "sw")
    if not parent or parent.get("outcome") != "ignored_illegal_target":
        failures.append(f"swapping a Unit with itself was allowed: {parent}")

    gone = two_units(6, 2)
    gone["objects"]["u2"]["kind"] = "spell"
    illegal = IR.apply_program(gone, swap(pair))
    parent = event_for(illegal, "sw")
    if not parent or parent.get("outcome") != "ignored_illegal_target":
        failures.append(f"a pair with an illegal referent was still swapped: {parent}")
    elif illegal.get("committed") and IR.effective_might(illegal["next_state"], "u1") != 6:
        failures.append("an illegal pair half-applied: u1's Might moved")

    # --- shape and composition ----------------------------------------------
    if "swap_might" not in IR.COMPOSITE_OPS:
        failures.append("swap_might must be composite: apply_program expands it, _apply_one never sees it")
    try:
        IR._apply_one(two_units(6, 2), {"op": "swap_might", "effect_id": "sw", "units": pair})
    except ValueError:
        pass
    else:
        failures.append("_apply_one accepted swap_might instead of refusing it")

    bad = IR.apply_program(two_units(6, 2), program("swap", {
        "op": "swap_might", "effect_id": "sw", "source": "kayle", "amount": 3,
        "units": pair, "duration": "this_turn"}))
    if bad.get("valid") is not False:
        failures.append("swap_might accepted an amount of its own; the change is the difference (Core 477)")

    one = IR.apply_program(two_units(6, 2), program("swap", {
        "op": "swap_might", "effect_id": "sw", "source": "kayle",
        "units": [selector("u1", "friendly")], "duration": "this_turn"}))
    if one.get("valid") is not False:
        failures.append("swap_might accepted a single Unit")

    print("swap_might (Core 477, 135.2.e.3, 370.1.a, 373.2, 359.3.e.5)")
    print(f"  rule locators: {IR.OP_RULES['swap_might']}")
    print("  6/2 -> 2/6 as two modify_might events; equal Mights leave no event;")
    print("  the same Unit twice and an illegal referent are both refused whole")
    for failure in failures:
        print("\nFAILED: " + failure)
    if failures:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
