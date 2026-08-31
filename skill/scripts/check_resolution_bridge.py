#!/usr/bin/env python3
"""Regression checks for atomic timing + effect resolution."""

from __future__ import annotations

import copy
import sys

from check_effect_ir import base_state, program
from check_rules_core import fixture, item
from rules_core import finalize_oldest_pending, pass_priority
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
        "controller_order": 0, "effect_program_id": "u2-deathknell-effects", "optional_at_finalize": False,
    }]
    trigger_result = resolve_with_program(timing, "spell-1", trigger_effects, lethal_program)
    trigger_items = trigger_result.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not trigger_result.get("committed") or [item["id"] for item in trigger_items] != ["u2-deathknell"] or trigger_items[0]["status"] != "pending":
        failures.append("death trigger was not scheduled as a Pending Chain Item")

    ambiguous = base_state()
    ambiguous["objects"]["u2"]["death_triggers"] = [
        {"trigger_id": "u2-a", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "a", "optional_at_finalize": False},
        {"trigger_id": "u2-b", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "b", "optional_at_finalize": False},
    ]
    ambiguous_result = resolve_with_program(timing, "spell-1", ambiguous, lethal_program)
    if ambiguous_result.get("committed") or ambiguous_result.get("stage") != "trigger_schedule":
        failures.append("ambiguous same-controller death-trigger order did not block the atomic commit")
    if "next_timing_state" in ambiguous_result or "next_effect_state" in ambiguous_result:
        failures.append("ambiguous trigger ordering leaked a partial next state")

    pending_trigger_state = trigger_result.get("next_timing_state", {})
    finalized_trigger = finalize_oldest_pending(pending_trigger_state) if pending_trigger_state else {}
    if finalized_trigger.get("applied"):
        trigger_closed = finalized_trigger["next_state"]
        first_pass = pass_priority(trigger_closed, "p2")
        second_pass = pass_priority(first_pass["next_state"], "p1") if first_pass.get("applied") else {}
        trigger_program = program("u2-deathknell-effects", {"op": "draw", "player": "p2", "count": 1})
        trigger_program["controller"] = "p2"
        trigger_program["source_object"] = "u2"
        trigger_resolution = resolve_with_program(second_pass.get("next_state", {}), "u2-deathknell", trigger_result["next_effect_state"], trigger_program)
        if not trigger_resolution.get("committed") or trigger_resolution["next_effect_state"]["players"]["p2"]["zones"]["hand"] != ["c4"]:
            failures.append("bound death-trigger effect program did not resolve")
        wrong_program = dict(trigger_program)
        wrong_program["program_id"] = "wrong-effects"
        rejected_program = resolve_with_program(second_pass.get("next_state", {}), "u2-deathknell", trigger_result["next_effect_state"], wrong_program)
        if rejected_program.get("committed") or rejected_program.get("reason") != "effect_program_id_mismatch":
            failures.append("mismatched trigger effect program was not rejected")
    else:
        failures.append("scheduled death trigger did not finalize for bound-program test")

    reflexive_program = program(
        "reflexive-source-effects",
        {
            "op": "emit_reflexive", "effect_id": "earlier-event",
            "triggers": [{"trigger_id": "earlier-p2", "controller": "p2", "source_object": "spell-1", "controller_order": 0, "effect_program_id": "earlier-p2-effects", "optional_at_finalize": False}]
        },
        {
            "op": "emit_reflexive", "effect_id": "later-event",
            "triggers": [{"trigger_id": "later-p1", "controller": "p1", "source_object": "spell-1", "controller_order": 0, "effect_program_id": "later-p1-effects", "optional_at_finalize": False}]
        },
    )
    reflexive_result = resolve_with_program(timing, "spell-1", effects, reflexive_program)
    reflexive_items = reflexive_result.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not reflexive_result.get("committed") or [item["id"] for item in reflexive_items] != ["earlier-p2", "later-p1"]:
        failures.append("reflexive trigger batches were not preserved in event order")
    elif any(item.get("trigger_kind") != "reflexive" or item.get("status") != "pending" for item in reflexive_items):
        failures.append("reflexive descriptors were not scheduled as typed Pending abilities")

    replacement_state = base_state()
    replacement_state["replacement_effects"] = [{
        "replacement_id": "prevent-u2-damage", "controller": "p2", "source_object": "u2",
        "mode": "prevent_event", "event_op": "deal_damage", "optional": False,
        "uses_remaining": 1, "target_object_id": "u2"
    }]
    replacement_result = resolve_with_program(timing, "spell-1", replacement_state, damage_program)
    if not replacement_result.get("committed") or replacement_result["next_effect_state"]["objects"]["u2"]["damage"] != 0:
        failures.append("replacement prevention did not participate in atomic Chain resolution")
    elif replacement_result["next_effect_state"]["replacement_effects"][0]["uses_remaining"] != 0:
        failures.append("replacement usage was not committed with the resolved Chain Item")

    replace_state = base_state()
    replace_state["replacement_effects"] = [{
        "replacement_id": "save-u2", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "kill", "optional": False,
        "uses_remaining": 1, "target_object_id": "u2",
        "replacement_effects": [{"op": "kill", "object_id": "u1"}, {"op": "exhaust", "object_id": "u2"}]
    }]
    replace_program = program("replace-in-bridge", {"op": "kill", "object_id": "u2"})
    replace_result = resolve_with_program(timing, "spell-1", replace_state, replace_program)
    if not replace_result.get("committed") or "u2" not in replace_result["next_effect_state"]["players"]["p2"]["zones"]["base"]:
        failures.append("replace_with did not commit atomically with Chain resolution")
    elif "u1" not in replace_result["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        failures.append("replace_with child actions were not committed through the resolution bridge")

    partial_state = base_state()
    partial_state["replacement_effects"] = [{
        "replacement_id": "prevent-two", "controller": "p1", "source_object": "u1",
        "mode": "reduce_damage", "event_op": "deal_damage", "optional": False,
        "uses_remaining": None, "prevent_remaining": 2, "target_object_id": "u2"
    }]
    partial_result = resolve_with_program(timing, "spell-1", partial_state, damage_program)
    if not partial_result.get("committed") or partial_result["next_effect_state"]["objects"]["u2"]["damage"] != 1:
        failures.append("partial prevention value did not commit remaining damage with Chain resolution")

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
