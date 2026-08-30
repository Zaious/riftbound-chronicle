#!/usr/bin/env python3
"""Regression checks for atomic timing + effect resolution."""

from __future__ import annotations

import copy
import sys

from check_effect_ir import base_state, program
from check_rules_core import fixture, item
from resolution_bridge import resolve_with_program


def main() -> int:
    failures = []
    timing = fixture(
        priority="p2",
        items=[item("spell-1", "p1", "spell", "default", "finalized")],
        passes=["p1", "p2"],
    )
    effects = base_state()
    damage_program = program("spell-1-effects", {"op": "deal_damage", "object_id": "u2", "amount": 3})
    result = resolve_with_program(timing, "spell-1", effects, damage_program)
    if not result.get("committed"):
        failures.append(f"supported resolution did not commit: {result}")
    else:
        if result["next_effect_state"]["objects"]["u2"]["damage"] != 3:
            failures.append("effect state did not apply damage")
        if result["next_timing_state"]["chain"]["items"]:
            failures.append("timing state did not remove exactly the resolved item")
        if not result.get("rule_locators"):
            failures.append("combined resolution lacks rule locators")

    unsupported = resolve_with_program(
        timing,
        "spell-1",
        effects,
        program("unsupported", {"op": "counter", "chain_item_id": "other"}),
    )
    if unsupported.get("committed") or unsupported.get("stage") != "effect":
        failures.append("unsupported effect did not prevent the combined commit")
    if "next_timing_state" in unsupported or "next_effect_state" in unsupported:
        failures.append("failed combined resolution leaked a next state")

    lethal_program = program("lethal", {"op": "deal_damage", "object_id": "u2", "amount": 4})
    lethal_result = resolve_with_program(timing, "spell-1", effects, lethal_program)
    if not lethal_result.get("committed") or "u2" not in lethal_result["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        failures.append("combined resolution did not run the lethal cleanup slice")

    not_next = fixture(
        priority="p2",
        items=[
            item("spell-1", "p1", "spell", "default", "finalized"),
            item("reaction-2", "p2", "spell", "reaction", "finalized"),
        ],
        passes=["p1", "p2"],
    )
    rejected = resolve_with_program(not_next, "spell-1", copy.deepcopy(effects), damage_program)
    if rejected.get("committed") or rejected.get("stage") != "timing":
        failures.append("non-top Finalized item was allowed to resolve")

    print("[info] resolution bridge: supported commit, unsupported-effect rollback, and non-top timing rejection.")
    if failures:
        print("\n".join(f"FAILED: {failure}" for failure in failures))
        return 1
    print("OK: timing and typed effects commit atomically without leaking guessed or partial next states.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
