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

    trigger_effects = base_state()
    trigger_effects["objects"]["u2"]["death_triggers"] = [{
        "trigger_id": "u2-deathknell", "controller": "p2", "source_object": "u2",
        "controller_order": 0, "effect_program_id": "u2-deathknell-effects",
    }]
    trigger_result = resolve_with_program(timing, "spell-1", trigger_effects, lethal_program)
    trigger_items = trigger_result.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not trigger_result.get("committed") or [item["id"] for item in trigger_items] != ["u2-deathknell"] or trigger_items[0]["status"] != "pending":
        failures.append("death trigger was not scheduled as a Pending Chain Item")

    ambiguous = base_state()
    ambiguous["objects"]["u2"]["death_triggers"] = [
        {"trigger_id": "u2-a", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "a"},
        {"trigger_id": "u2-b", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "b"},
    ]
    ambiguous_result = resolve_with_program(timing, "spell-1", ambiguous, lethal_program)
    if ambiguous_result.get("committed") or ambiguous_result.get("stage") != "trigger_schedule":
        failures.append("ambiguous same-controller death-trigger order did not block the atomic commit")
    if "next_timing_state" in ambiguous_result or "next_effect_state" in ambiguous_result:
        failures.append("ambiguous trigger ordering leaked a partial next state")

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
