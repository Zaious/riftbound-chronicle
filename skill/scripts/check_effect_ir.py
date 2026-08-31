#!/usr/bin/env python3
"""Executable R2 regression suite for the Chronicle typed effect IR."""

from __future__ import annotations

import copy
import sys

from effect_ir import (
    CORE_RULESET,
    FAQ_AS_OF,
    PROGRAM_VERSION,
    STATE_VERSION,
    apply_program,
    hash_value,
    perform_lethal_cleanup,
    validate_state,
)


def base_state():
    return {
        "schema_version": STATE_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "players": {
            "p1": {
                "zones": {
                    "main_deck": ["c1", "c2"], "hand": [], "trash": ["c3"],
                    "banishment": [], "base": ["u1"], "rune_deck": ["r1"],
                },
                "resources": {"energy": 0, "power": {}},
            },
            "p2": {
                "zones": {
                    "main_deck": ["c4"], "hand": [], "trash": [],
                    "banishment": [], "base": ["u2"], "rune_deck": [],
                },
                "resources": {"energy": 0, "power": {}},
            },
        },
        "objects": {
            "c1": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False},
            "c2": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False},
            "c3": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False},
            "c4": {"owner": "p2", "controller": "p2", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False},
            "u1": {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 1, "exhausted": False},
            "u2": {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 4, "might_modifiers": [], "damage": 0, "exhausted": True},
            "r1": {"owner": "p1", "controller": "p1", "kind": "rune", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False},
        },
        "battlefields": {"bf1": {"controller": None, "objects": []}},
    }


def program(program_id, *effects):
    return {
        "schema_version": PROGRAM_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "program_id": program_id,
        "controller": "p1",
        "effects": list(effects),
    }


def main() -> int:
    failures = []
    state = base_state()
    if found := validate_state(state):
        failures.append(f"base state invalid: {found}")

    cases = [
        ("draw", program("draw", {"op": "draw", "player": "p1", "count": 1}), lambda s: s["players"]["p1"]["zones"]["hand"] == ["c1"]),
        ("recycle", program("recycle", {"op": "recycle_one", "object_id": "c3"}), lambda s: s["players"]["p1"]["zones"]["main_deck"][-1] == "c3"),
        ("move", program("move", {"op": "move_board_object", "object_id": "u1", "destination": {"kind": "battlefield", "battlefield": "bf1"}}), lambda s: s["battlefields"]["bf1"]["objects"] == ["u1"]),
        ("might", program("might", {"op": "modify_might", "object_id": "u1", "amount": 2, "duration": "this_turn", "source": "fixture"}), lambda s: s["objects"]["u1"]["might_modifiers"][0]["amount"] == 2),
        ("damage", program("damage", {"op": "deal_damage", "object_id": "u1", "amount": 3}), lambda s: s["objects"]["u1"]["damage"] == 4),
        ("heal", program("heal", {"op": "heal_damage", "object_id": "u1", "amount": 8}), lambda s: s["objects"]["u1"]["damage"] == 0),
        ("exhaust", program("exhaust", {"op": "exhaust", "object_id": "u1"}), lambda s: s["objects"]["u1"]["exhausted"] is True),
        ("ready", program("ready", {"op": "ready", "object_id": "u2"}), lambda s: s["objects"]["u2"]["exhausted"] is False),
        ("energy", program("energy", {"op": "add_resource", "player": "p1", "resource": "energy", "amount": 2}), lambda s: s["players"]["p1"]["resources"]["energy"] == 2),
        ("power", program("power", {"op": "add_resource", "player": "p1", "resource": "power", "domain": "fury", "amount": 1}), lambda s: s["players"]["p1"]["resources"]["power"]["fury"] == 1),
    ]
    for name, value, assertion in cases:
        result = apply_program(state, value)
        if not result.get("committed") or not assertion(result["next_state"]):
            failures.append(f"{name} did not apply correctly: {result}")
        elif not result["trace"] or not result["trace"][0].get("rule_locators"):
            failures.append(f"{name} lacks rule-grounded trace")

    sequence = program(
        "sequence",
        {"op": "exhaust", "object_id": "u1"},
        {"op": "add_resource", "player": "p1", "resource": "energy", "amount": 2},
        {"op": "draw", "player": "p1", "count": 1},
    )
    first = apply_program(state, sequence)
    second = apply_program(copy.deepcopy(state), sequence)
    if first.get("next_state_hash") != second.get("next_state_hash") or first.get("trace") != second.get("trace"):
        failures.append("effect program is not deterministic")

    unsupported = apply_program(state, program("unsupported", {"op": "counter", "chain_item_id": "x"}))
    if unsupported.get("committed") or unsupported.get("unsupported") is not True:
        failures.append("unsupported effect did not fail closed")
    if hash_value(state) != unsupported.get("input_state_hash"):
        failures.append("unsupported effect lost the original state hash")

    burn_out = apply_program(state, program("burn-out", {"op": "draw", "player": "p2", "count": 2}))
    if burn_out.get("committed") or "Burn Out" not in burn_out.get("reason", ""):
        failures.append("draw beyond deck did not defer to unsupported Burn Out handling")

    invalid = base_state()
    invalid["players"]["p1"]["zones"]["hand"].append("u1")
    if not any("exactly one" in item for item in validate_state(invalid)):
        failures.append("duplicate object occupancy was not rejected")

    legal_target = program(
        "legal-target",
        {
            "effect_id": "damage",
            "op": "deal_damage",
            "object_id": "u2",
            "amount": 2,
            "target": {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit", "location": "base", "controller_relation": "enemy"},
        },
        {"effect_id": "draw", "depends_on": "damage", "op": "draw", "player": "p1", "count": 1},
    )
    targeted = apply_program(state, legal_target)
    if not targeted.get("committed") or targeted["next_state"]["objects"]["u2"]["damage"] != 2 or targeted["next_state"]["players"]["p1"]["zones"]["hand"] != ["c1"]:
        failures.append("legal target and linked instruction did not execute")

    moved_target_state = base_state()
    moved_target_state["players"]["p2"]["zones"]["base"].remove("u2")
    moved_target_state["players"]["p2"]["zones"]["hand"].append("u2")
    ignored = apply_program(moved_target_state, legal_target)
    outcomes = [event["outcome"] for event in ignored.get("trace", [])]
    if not ignored.get("committed") or outcomes != ["ignored_illegal_target", "skipped_linked_dependency"]:
        failures.append(f"illegal target did not ignore and skip its linked instruction: {outcomes}")

    no_op_link = apply_program(state, program(
        "no-op-link",
        {"effect_id": "exhaust", "op": "exhaust", "object_id": "u2"},
        {"effect_id": "draw", "depends_on": "exhaust", "op": "draw", "player": "p1", "count": 1},
    ))
    no_op_outcomes = [event["outcome"] for event in no_op_link.get("trace", [])]
    if no_op_outcomes != ["no_op", "skipped_linked_dependency"]:
        failures.append(f"no-op linked action did not gate the dependent instruction: {no_op_outcomes}")

    killed = apply_program(state, program("kill", {"op": "kill", "object_id": "u2"}))
    if not killed.get("committed") or "u2" not in killed["next_state"]["players"]["p2"]["zones"]["trash"]:
        failures.append("active Kill did not move the Unit from board to owner Trash")

    token_state = base_state()
    token_state["objects"]["t1"] = {
        "owner": "p1", "controller": "p1", "kind": "unit", "is_token": True,
        "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False,
    }
    token_state["players"]["p1"]["zones"]["base"].append("t1")
    token_kill = apply_program(token_state, program("token-kill", {"op": "kill", "object_id": "t1"}))
    if not token_kill.get("committed") or "t1" in token_kill["next_state"]["objects"]:
        failures.append("killed token did not cease to exist after entering a non-board zone")

    lethal_state = base_state()
    lethal_state["objects"]["u2"]["damage"] = 4
    cleanup = perform_lethal_cleanup(lethal_state, attributed_sources=["fixture-spell"])
    if not cleanup.get("committed") or cleanup.get("lethal_objects") != ["u2"] or "u2" not in cleanup["next_state"]["players"]["p2"]["zones"]["trash"]:
        failures.append("lethal cleanup did not passively kill the lethal Unit")

    zero_might = base_state()
    zero_might["objects"]["u2"]["base_might"] = 0
    zero_cleanup = perform_lethal_cleanup(zero_might)
    if zero_cleanup.get("lethal_objects"):
        failures.append("zero-Might Unit without marked damage was incorrectly lethal")

    trigger_state = base_state()
    trigger_state["objects"]["u2"]["damage"] = 4
    trigger_state["objects"]["u2"]["death_triggers"] = [{
        "trigger_id": "u2-deathknell", "controller": "p2", "source_object": "u2",
        "controller_order": 0, "effect_program_id": "u2-deathknell-effects", "optional_at_finalize": False,
    }]
    trigger_cleanup = perform_lethal_cleanup(trigger_state)
    if not trigger_cleanup.get("committed") or [item["trigger_id"] for item in trigger_cleanup.get("pending_triggers", [])] != ["u2-deathknell"]:
        failures.append("lethal cleanup did not preserve typed death-trigger descriptors")

    print(f"[info] typed effect IR: {len(cases) + 1} supported operations plus sequence, targets, linked effects, lethal cleanup, unsupported, Burn Out, and state invariants.")
    if failures:
        print("\n".join(f"FAILED: {failure}" for failure in failures))
        return 1
    print("OK: bounded effect programs are typed, deterministic, rule-grounded, and fail closed without guessed card behavior.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
