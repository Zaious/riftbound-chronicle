#!/usr/bin/env python3
"""Executable conformance checks for the Chronicle sovereign timing core."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rules_core import (
    FAQ_AS_OF,
    CORE_RULESET,
    SCHEMA_VERSION,
    add_pending_item,
    complete_resolution,
    derive_permissions,
    finalize_oldest_pending,
    next_procedure,
    pass_priority,
    schedule_triggered_items,
    state_hash,
    validate_state,
    validate_timing,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
CASES = SKILL_DIR / "data" / "rules_core_cases.json"


def item(item_id, controller, object_kind, timing, status="finalized", ability_kind=None):
    return {
        "id": item_id,
        "controller": controller,
        "object_kind": object_kind,
        "timing": timing,
        "status": status,
        "ability_kind": ability_kind,
    }


def fixture(*, showdown=False, focus=None, priority="p1", tasks=None, items=None, passes=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "players": ["p1", "p2"],
        "turn_order": ["p1", "p2"],
        "turn_player": "p1",
        "phase": "main",
        "showdown": {"active": showdown, "kind": "combat" if showdown else None, "focus": focus},
        "priority": priority,
        "outstanding_tasks": tasks or [],
        "chain": {"initiated_by": "played_card" if items else None, "items": items or [], "consecutive_passes": passes or []},
    }


FIXTURES = {
    "neutral_open": fixture(),
    "showdown_open": fixture(showdown=True, focus="p1"),
    "neutral_closed": fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default")]),
    "showdown_closed": fixture(showdown=True, focus="p1", priority="p2", items=[item("spell-1", "p1", "spell", "action")]),
    "pending_spell": fixture(items=[item("spell-1", "p1", "spell", "default", "pending")]),
    "pending_unit": fixture(items=[item("unit-1", "p1", "unit", "reaction", "pending")]),
    "two_finalized_all_passed": fixture(
        priority="p2",
        items=[item("spell-1", "p1", "spell", "default"), item("reaction-2", "p2", "spell", "reaction")],
        passes=["p2", "p1"],
    ),
    "outstanding_cleanup": fixture(tasks=["cleanup"]),
}


def main() -> int:
    errors = []
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    ids = [case.get("case_id") for case in cases.get("cases", [])]
    if len(ids) != len(set(ids)):
        errors.append("rules-core cases contain duplicate case ids")
    if cases.get("ruleset") != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("rules-core case baseline does not match the executable kernel")

    for name, state in FIXTURES.items():
        if found := validate_state(state):
            errors.append(f"fixture {name} invalid: {found}")

    expected_permissions = {
        "neutral_open": ("p1", ["default", "action", "reaction"]),
        "showdown_open": ("p1", ["action", "reaction"]),
        "neutral_closed": ("p2", ["reaction"]),
        "showdown_closed": ("p2", ["reaction"]),
    }
    for name, (actor, timings) in expected_permissions.items():
        result = derive_permissions(FIXTURES[name])
        actual = result.get("permissions", {}).get(actor, {}).get("play_timings")
        if actual != timings:
            errors.append(f"fixture {name}: expected play timings {timings}, got {actual}")

    for case in cases.get("cases", []):
        case_id = case["case_id"]
        state = FIXTURES.get(case.get("state"))
        if state is None:
            errors.append(f"{case_id}: unknown fixture {case.get('state')}")
            continue
        expected = case["expected"]
        action = case.get("action")
        if action:
            result = validate_timing(state, action)
            for key in ("state_label", "legal", "reason_code"):
                if key in expected and result.get(key) != expected[key]:
                    errors.append(f"{case_id}: expected {key}={expected[key]!r}, got {result.get(key)!r}")
            if "next_procedure" in expected:
                actual = next_procedure(state).get("procedure")
                if actual != expected["next_procedure"]:
                    errors.append(f"{case_id}: expected next procedure {expected['next_procedure']}, got {actual}")
        elif "next_procedure" in expected:
            result = next_procedure(state)
            for key, source in (("state_label", "state_label"), ("next_procedure", "procedure"), ("subject", "subject")):
                if key in expected and result.get(source) != expected[key]:
                    errors.append(f"{case_id}: expected {key}={expected[key]!r}, got {result.get(source)!r}")
        else:
            result = finalize_oldest_pending(state)
            transition = result.get("transition", {})
            if result.get("state_label") != expected.get("state_label"):
                errors.append(f"{case_id}: state label mismatch")
            if transition.get("item_id") != expected.get("finalized_item"):
                errors.append(f"{case_id}: finalized item mismatch")
            if transition.get("immediate_resolution_required") != expected.get("immediate_resolution_required"):
                errors.append(f"{case_id}: immediate-resolution classification mismatch")

    # Negative invariants: malformed authority and inconsistent state never get
    # repaired silently by the core.
    bad = fixture(showdown=False, focus="p1")
    if not validate_state(bad):
        errors.append("neutral state incorrectly accepted a Focus holder")
    bad = fixture()
    bad["chain"]["items"] = [item("x", "p1", "spell", "default"), item("x", "p2", "spell", "reaction")]
    if not any("duplicated" in value for value in validate_state(bad)):
        errors.append("duplicate Chain Item ids were not rejected")

    # Structural trace: Action starts a Showdown Chain, finalizes, both players
    # pass, the one item resolves, and ordinary Chain closure passes Focus.
    start = FIXTURES["showdown_open"]
    add = add_pending_item(start, {
        "actor": "p1",
        "kind": "play_card",
        "initiated_by": "played_card",
        "item": item("action-1", "p1", "spell", "action", "pending"),
    })
    if not add.get("applied"):
        errors.append(f"trace: could not add pending item: {add}")
    else:
        pending = add["next_state"]
        finalized = finalize_oldest_pending(pending)
        if not finalized.get("applied"):
            errors.append("trace: pending item did not finalize")
        else:
            closed = finalized["next_state"]
            p1_pass = pass_priority(closed, "p1")
            p2_pass = pass_priority(p1_pass["next_state"], "p2") if p1_pass.get("applied") else {}
            if p2_pass.get("next_procedure", {}).get("procedure") != "resolve_newest_finalized":
                errors.append("trace: consecutive passes did not reach one-item resolution")
            else:
                resolved = complete_resolution(p2_pass["next_state"], "action-1", effect_execution_confirmed=True)
                if not resolved.get("applied"):
                    errors.append("trace: finalized item did not complete resolution")
                else:
                    after = resolved["next_state"]
                    if resolved["transition"].get("focus_after") != "p2":
                        errors.append("trace: ordinary Showdown Chain closure did not pass Focus")
                    if state_hash(after) != resolved.get("next_state_hash"):
                        errors.append("trace: next-state hash is not reproducible")

    # Triggered and Add initiated Chains keep Focus when they become empty.
    for origin in ("triggered_ability", "add_ability"):
        state = fixture(
            showdown=True,
            focus="p1",
            priority="p1",
            items=[item(f"{origin}-1", "p1", "ability", "reaction", "finalized", "add" if origin == "add_ability" else "standard")],
            passes=[] if origin == "add_ability" else ["p1", "p2"],
        )
        state["chain"]["initiated_by"] = origin
        resolved = complete_resolution(state, f"{origin}-1", effect_execution_confirmed=True)
        if not resolved.get("applied") or resolved["next_state"]["showdown"]["focus"] != "p1":
            errors.append(f"trace: {origin} Chain closure incorrectly moved Focus")

    trigger_base = FIXTURES["neutral_open"]
    scheduled = schedule_triggered_items(trigger_base, [
        {"trigger_id": "p2-a", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "p2-a-effects", "optional_at_finalize": False},
        {"trigger_id": "p1-b", "controller": "p1", "source_object": "u1", "controller_order": 1, "effect_program_id": "p1-b-effects", "optional_at_finalize": False},
        {"trigger_id": "p1-a", "controller": "p1", "source_object": "u1", "controller_order": 0, "effect_program_id": "p1-a-effects", "optional_at_finalize": False},
    ])
    expected_order = ["p1-a", "p1-b", "p2-a"]
    if not scheduled.get("applied") or scheduled.get("transition", {}).get("ordered_trigger_ids") != expected_order:
        errors.append(f"trigger scheduling did not use Turn Player blocks and controller order: {scheduled}")
    duplicate_order = schedule_triggered_items(trigger_base, [
        {"trigger_id": "a", "controller": "p1", "source_object": "u1", "controller_order": 0, "effect_program_id": "a-effects", "optional_at_finalize": False},
        {"trigger_id": "b", "controller": "p1", "source_object": "u1", "controller_order": 0, "effect_program_id": "b-effects", "optional_at_finalize": False},
    ])
    if duplicate_order.get("applied") or duplicate_order.get("reason_code") != "trigger_order_required":
        errors.append("ambiguous same-controller trigger ordering did not fail closed")

    optional_scheduled = schedule_triggered_items(trigger_base, [{
        "trigger_id": "optional-1", "controller": "p1", "source_object": "u1",
        "controller_order": 0, "effect_program_id": "optional-effects", "optional_at_finalize": True,
    }])
    optional_state = optional_scheduled.get("next_state", {})
    blocked = finalize_oldest_pending(optional_state) if optional_state else {}
    if blocked.get("applied") or blocked.get("reason_code") != "trigger_finalize_choice_required":
        errors.append("optional trigger finalized without an explicit perform/decline choice")
    performed = finalize_oldest_pending(optional_state, perform_optional_trigger=True) if optional_state else {}
    if not performed.get("applied") or performed.get("next_state", {}).get("chain", {}).get("items", [{}])[0].get("status") != "finalized":
        errors.append("accepted optional trigger did not finalize")
    declined = finalize_oldest_pending(optional_state, perform_optional_trigger=False) if optional_state else {}
    if not declined.get("applied") or declined.get("next_state", {}).get("chain", {}).get("items"):
        errors.append("declined optional trigger was not removed from the Chain")

    off_turn_trigger = schedule_triggered_items(trigger_base, [{
        "trigger_id": "p2-trigger", "controller": "p2", "source_object": "u2",
        "controller_order": 0, "effect_program_id": "p2-effects", "optional_at_finalize": False,
    }])
    off_turn_finalized = finalize_oldest_pending(off_turn_trigger.get("next_state", {})) if off_turn_trigger.get("applied") else {}
    if off_turn_finalized.get("next_state", {}).get("priority") != "p2":
        errors.append("Finalize did not grant Priority to the newest Finalized item's controller")

    print(f"[info] sovereign rules core: {len(ids)} executable cases; {len(FIXTURES)} canonical fixtures.")
    if errors:
        print("\n".join(f"FAILED: {error}" for error in errors))
        return 1
    print("OK: four-state permissions, HOT/FEPR gating, structural Chain traces, Focus movement, and immediate-resolution classification validate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
