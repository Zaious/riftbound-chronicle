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
        "replacement_effects": [],
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
        (
            "play-token",
            program("play-token", {
                "op": "play_token", "object_id": "token-1", "owner": "p1", "controller": "p1",
                "token_kind": "unit", "base_might": 3, "destination": {"kind": "base", "player": "p1"},
                "event_modifiers": {"entry_state": "ready", "result_keywords": ["temporary"]},
            }),
            lambda s: s["objects"]["token-1"]["exhausted"] is False and s["objects"]["token-1"]["keywords"] == ["temporary"],
        ),
        (
            "play-gear-token",
            program("play-gear-token", {
                "op": "play_token", "object_id": "gear-token-1", "owner": "p1", "controller": "p1",
                "token_kind": "gear", "base_might": 0, "destination": {"kind": "base", "player": "p1"},
            }),
            lambda s: s["objects"]["gear-token-1"]["exhausted"] is False,
        ),
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

    misplaced_gear = apply_program(state, program("misplaced-gear", {
        "op": "play_token", "object_id": "gear-token-bf", "owner": "p1", "controller": "p1",
        "token_kind": "gear", "base_might": 0, "destination": {"kind": "battlefield", "battlefield": "bf1"},
    }))
    if misplaced_gear.get("committed") or misplaced_gear.get("valid") is not False:
        failures.append("non-Unit Gear token was allowed to enter a Battlefield")

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

    reflexive = apply_program(state, program(
        "reflexive",
        {
            "op": "emit_reflexive",
            "effect_id": "do-this-twice",
            "triggers": [
                {"trigger_id": "reflexive-1", "controller": "p1", "source_object": "c1", "controller_order": 0, "effect_program_id": "reflexive-1-effects", "optional_at_finalize": False},
                {"trigger_id": "reflexive-2", "controller": "p1", "source_object": "c1", "controller_order": 1, "effect_program_id": "reflexive-2-effects", "optional_at_finalize": False}
            ]
        }
    ))
    if not reflexive.get("committed") or [item["trigger_id"] for item in reflexive.get("pending_triggers", [])] != ["reflexive-1", "reflexive-2"]:
        failures.append("reflexive effect did not emit ordered typed Pending descriptors")
    elif reflexive.get("next_state_hash") != reflexive.get("input_state_hash"):
        failures.append("emit_reflexive unexpectedly mutated effect state")

    prevented_state = base_state()
    prevented_state["replacement_effects"] = [{
        "replacement_id": "shield-u2", "controller": "p2", "source_object": "u2",
        "mode": "prevent_event", "event_op": "deal_damage", "optional": False,
        "uses_remaining": 1, "target_object_id": "u2"
    }]
    prevented = apply_program(prevented_state, program(
        "prevented",
        {"effect_id": "damage", "op": "deal_damage", "object_id": "u2", "amount": 3},
        {"effect_id": "draw", "depends_on": "damage", "op": "draw", "player": "p1", "count": 1},
        {"effect_id": "damage-again", "op": "deal_damage", "object_id": "u2", "amount": 2},
    ))
    replacement_outcomes = [event["outcome"] for event in prevented.get("trace", [])]
    if not prevented.get("committed") or replacement_outcomes != ["replaced_prevented", "skipped_linked_dependency", "applied"]:
        failures.append(f"mandatory one-use prevention did not gate linked effect then expire: {replacement_outcomes}")
    elif prevented["next_state"]["objects"]["u2"]["damage"] != 2 or prevented["next_state"]["replacement_effects"][0]["uses_remaining"] != 0:
        failures.append("prevention state/usage was not updated correctly")

    optional_state = base_state()
    optional_state["replacement_effects"] = [{
        "replacement_id": "optional-shield", "controller": "p2", "source_object": "u2",
        "mode": "prevent_event", "event_op": "deal_damage", "optional": True,
        "uses_remaining": 1, "target_object_id": "u2"
    }]
    missing_choice = apply_program(optional_state, program("optional-missing", {"op": "deal_damage", "object_id": "u2", "amount": 2}))
    if missing_choice.get("committed") or missing_choice.get("replacement_decision_required") is not True:
        failures.append("optional replacement applied without an explicit choice")
    declined = apply_program(optional_state, program("optional-decline", {"op": "deal_damage", "object_id": "u2", "amount": 2, "replacement_choices": {"optional-shield": False}}))
    if not declined.get("committed") or declined["next_state"]["objects"]["u2"]["damage"] != 2 or declined["next_state"]["replacement_effects"][0]["uses_remaining"] != 1:
        failures.append("declined optional replacement did not preserve use and execute event")
    accepted = apply_program(optional_state, program("optional-accept", {"op": "deal_damage", "object_id": "u2", "amount": 2, "replacement_choices": {"optional-shield": True}}))
    if not accepted.get("committed") or accepted["next_state"]["objects"]["u2"]["damage"] != 0:
        failures.append("accepted optional replacement did not prevent event")

    multiple_state = base_state()
    multiple_state["replacement_effects"] = [
        {"replacement_id": "r1", "controller": "p1", "source_object": "u1", "mode": "prevent_event", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "target_object_id": "u2"},
        {"replacement_id": "r2", "controller": "p2", "source_object": "u2", "mode": "prevent_event", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "target_object_id": "u2"}
    ]
    unordered = apply_program(multiple_state, program("unordered", {"op": "deal_damage", "object_id": "u2", "amount": 2}))
    if unordered.get("committed") or unordered.get("replacement_decision_required") is not True:
        failures.append("multiple replacements did not require affected-controller ordering")
    ordered = apply_program(multiple_state, program("ordered", {"op": "deal_damage", "object_id": "u2", "amount": 2, "replacement_decider": "p2", "replacement_order": ["r2", "r1"]}))
    if not ordered.get("committed") or ordered.get("trace", [{}])[0].get("replacement_id") != "r2":
        failures.append("affected-controller replacement order was not respected")

    invalid_replacements = base_state()
    duplicate_replacement = {"replacement_id": "dup", "controller": "p1", "source_object": "u1", "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": 1}
    invalid_replacements["replacement_effects"] = [duplicate_replacement, dict(duplicate_replacement)]
    if not any("duplicated" in item for item in validate_state(invalid_replacements)):
        failures.append("duplicate replacement ids were not rejected")

    replace_state = base_state()
    replace_state["objects"]["u2"]["damage"] = 3
    replace_state["replacement_effects"] = [{
        "replacement_id": "save-u2", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "kill", "optional": False,
        "uses_remaining": 1, "target_object_id": "u2",
        "replacement_effects": [
            {"op": "kill", "object_id": "u1"},
            {"op": "heal_damage", "object_id": "u2", "amount": 99},
            {"op": "exhaust", "object_id": "u2"}
        ]
    }]
    replaced = apply_program(replace_state, program(
        "replace-kill",
        {"effect_id": "kill-u2", "op": "kill", "object_id": "u2"},
        {"effect_id": "draw", "depends_on": "kill-u2", "op": "draw", "player": "p1", "count": 1},
    ))
    if not replaced.get("committed") or [event["outcome"] for event in replaced.get("trace", [])] != ["replaced_with", "skipped_linked_dependency"]:
        failures.append("replace_with did not replace the original event and gate its linked instruction")
    else:
        next_state = replaced["next_state"]
        if "u2" not in next_state["players"]["p2"]["zones"]["base"] or next_state["objects"]["u2"]["damage"] != 0 or next_state["objects"]["u2"]["exhausted"] is not True:
            failures.append("replace_with program did not preserve/heal/exhaust the affected Unit")
        if "u1" not in next_state["players"]["p1"]["zones"]["trash"] or next_state["replacement_effects"]:
            failures.append("replacement source left board but its replacement descriptor remained active")

    recursive_state = base_state()
    recursive_state["replacement_effects"] = [
        {
            "replacement_id": "replace-u2-kill", "controller": "p1", "source_object": "u1",
            "mode": "replace_with", "event_op": "kill", "optional": False,
            "uses_remaining": 1, "target_object_id": "u2",
            "replacement_effects": [{"op": "kill", "object_id": "u1"}]
        },
        {
            "replacement_id": "prevent-u1-kill", "controller": "p2", "source_object": "u2",
            "mode": "prevent_event", "event_op": "kill", "optional": False,
            "uses_remaining": 1, "target_object_id": "u1"
        }
    ]
    recursive = apply_program(recursive_state, program("recursive-replacement", {"op": "kill", "object_id": "u2"}))
    if not recursive.get("committed") or "u1" not in recursive["next_state"]["players"]["p1"]["zones"]["base"] or "u2" not in recursive["next_state"]["players"]["p2"]["zones"]["base"]:
        failures.append("another replacement did not apply to a replace_with child event")

    prevent_value_state = base_state()
    prevent_value_state["replacement_effects"] = [{
        "replacement_id": "prevent-five", "controller": "p1", "source_object": "u1",
        "mode": "reduce_damage", "event_op": "deal_damage", "optional": False,
        "uses_remaining": None, "prevent_remaining": 5, "target_object_id": "u2"
    }]
    prevent_value = apply_program(prevent_value_state, program(
        "prevent-value",
        {"effect_id": "damage-1", "op": "deal_damage", "object_id": "u2", "amount": 3},
        {"effect_id": "draw-1", "depends_on": "damage-1", "op": "draw", "player": "p1", "count": 1},
        {"effect_id": "damage-2", "op": "deal_damage", "object_id": "u2", "amount": 4},
        {"effect_id": "draw-2", "depends_on": "damage-2", "op": "draw", "player": "p1", "count": 1},
    ))
    prevent_outcomes = [event["outcome"] for event in prevent_value.get("trace", [])]
    if not prevent_value.get("committed") or prevent_outcomes != ["replaced_prevented", "skipped_linked_dependency", "replaced_modified_applied", "applied"]:
        failures.append(f"finite prevention value did not distinguish full and partial prevention: {prevent_outcomes}")
    else:
        next_state = prevent_value["next_state"]
        if next_state["objects"]["u2"]["damage"] != 2 or next_state["players"]["p1"]["zones"]["hand"] != ["c1"]:
            failures.append("partial prevention did not deal remaining damage or satisfy linked instruction")
        if next_state["replacement_effects"]:
            failures.append("depleted prevention value remained active")

    augment_state = base_state()
    augment_state["replacement_effects"] = [{
        "replacement_id": "damage-and-draw", "controller": "p1", "source_object": "u1",
        "mode": "augment_with", "event_op": "deal_damage", "optional": False,
        "uses_remaining": 1, "target_object_id": "u2",
        "replacement_effects": [{"op": "draw", "player": "p1", "count": 1}]
    }]
    augmented = apply_program(augment_state, program(
        "augment-damage",
        {"effect_id": "damage", "op": "deal_damage", "object_id": "u2", "amount": 2},
        {"effect_id": "linked-draw", "depends_on": "damage", "op": "draw", "player": "p1", "count": 1},
    ))
    if not augmented.get("committed") or [event["outcome"] for event in augmented.get("trace", [])] != ["augmented_applied", "applied"]:
        failures.append("augment_with did not preserve the original event and satisfy its linked instruction")
    else:
        next_state = augmented["next_state"]
        if next_state["objects"]["u2"]["damage"] != 2 or next_state["players"]["p1"]["zones"]["hand"] != ["c1", "c2"]:
            failures.append("augment_with did not execute the original event before its additional program")
        if next_state["replacement_effects"]:
            failures.append("one-use augmentation remained active")

    augmented_then_prevented_state = base_state()
    augmented_then_prevented_state["replacement_effects"] = [
        {
            "replacement_id": "damage-and-draw", "controller": "p1", "source_object": "u1",
            "mode": "augment_with", "event_op": "deal_damage", "optional": False,
            "uses_remaining": 1, "target_object_id": "u2",
            "replacement_effects": [{"op": "draw", "player": "p1", "count": 1}]
        },
        {
            "replacement_id": "prevent-damage", "controller": "p2", "source_object": "u2",
            "mode": "prevent_event", "event_op": "deal_damage", "optional": False,
            "uses_remaining": 1, "target_object_id": "u2"
        },
        {
            "replacement_id": "prevent-damage-later", "controller": "p1", "source_object": "u1",
            "mode": "prevent_event", "event_op": "deal_damage", "optional": False,
            "uses_remaining": 1, "target_object_id": "u2"
        },
    ]
    augmented_then_prevented = apply_program(augmented_then_prevented_state, program(
        "augment-then-prevent",
        {
            "effect_id": "damage", "op": "deal_damage", "object_id": "u2", "amount": 2,
            "replacement_decider": "p2",
            "replacement_order": ["damage-and-draw", "prevent-damage", "prevent-damage-later"],
        },
        {"effect_id": "linked-draw", "depends_on": "damage", "op": "draw", "player": "p1", "count": 1},
    ))
    if not augmented_then_prevented.get("committed") or [event["outcome"] for event in augmented_then_prevented.get("trace", [])] != ["augmented_original_replaced", "skipped_linked_dependency"]:
        failures.append("augmentation did not distinguish an original event prevented by another replacement")
    else:
        next_state = augmented_then_prevented["next_state"]
        if next_state["objects"]["u2"]["damage"] != 0 or next_state["players"]["p1"]["zones"]["hand"] != ["c1"]:
            failures.append("augmentation did not run exactly once after its original event was prevented")

    inheritance_state = base_state()
    inheritance_state["replacement_effects"] = [{
        "replacement_id": "double-token", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "play_token", "optional": False,
        "uses_remaining": 1, "target_object_id": "mech-token",
        "replacement_effects": [
            {
                "op": "play_token", "object_id": "mech-token", "owner": "p1", "controller": "p1",
                "token_kind": "unit", "base_might": 3, "destination": {"kind": "base", "player": "p1"},
            },
            {
                "op": "play_token", "object_id": "recruit-token", "owner": "p1", "controller": "p1",
                "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"},
            },
        ]
    }]
    inherited = apply_program(inheritance_state, program("inherit-token-modifiers", {
        "effect_id": "make-mech", "op": "play_token", "object_id": "mech-token", "owner": "p1", "controller": "p1",
        "token_kind": "unit", "base_might": 3, "destination": {"kind": "base", "player": "p1"},
        "event_modifiers": {"entry_state": "ready", "result_keywords": ["temporary"]},
    }))
    if not inherited.get("committed") or inherited.get("trace", [{}])[0].get("outcome") != "replaced_with":
        failures.append("Core 375 token replacement did not commit")
    else:
        next_state = inherited["next_state"]
        for object_id in ("mech-token", "recruit-token"):
            token = next_state["objects"].get(object_id, {})
            if token.get("exhausted") is not False or token.get("keywords") != ["temporary"]:
                failures.append(f"Core 375 modifiers were not inherited by {object_id}")
        nested = inherited["trace"][0].get("replacement_trace", [])
        if not nested or any(event.get("modifier_inheritance", {}).get("rule") != "Core 375" for event in nested):
            failures.append("Core 375 modifier provenance was not preserved in nested trace")

    conflict_state = base_state()
    conflict_state["replacement_effects"] = [{
        "replacement_id": "conflicting-token", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "play_token", "optional": False,
        "uses_remaining": 1, "target_object_id": "conflict-token",
        "replacement_effects": [{
            "op": "play_token", "object_id": "conflict-token", "owner": "p1", "controller": "p1",
            "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"},
            "event_modifiers": {"entry_state": "exhausted"},
        }]
    }]
    conflict = apply_program(conflict_state, program("conflicting-inheritance", {
        "op": "play_token", "object_id": "conflict-token", "owner": "p1", "controller": "p1",
        "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"},
        "event_modifiers": {"entry_state": "ready"},
    }))
    if conflict.get("committed") or conflict.get("unsupported") is not True or "conflicting inherited event modifier" not in conflict.get("reason", ""):
        failures.append("conflicting inherited modifiers did not fail closed")

    inapplicable_state = base_state()
    inapplicable_state["replacement_effects"] = [{
        "replacement_id": "token-to-draw", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "play_token", "optional": False,
        "uses_remaining": 1, "target_object_id": "ignored-token",
        "replacement_effects": [{"op": "draw", "player": "p1", "count": 1}]
    }]
    inapplicable = apply_program(inapplicable_state, program("inapplicable-inheritance", {
        "op": "play_token", "object_id": "ignored-token", "owner": "p1", "controller": "p1",
        "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"},
        "event_modifiers": {"entry_state": "ready", "result_keywords": ["temporary"]},
    }))
    if not inapplicable.get("committed") or inapplicable["next_state"]["players"]["p1"]["zones"]["hand"] != ["c1"] or "ignored-token" in inapplicable["next_state"]["objects"]:
        failures.append("inapplicable Core 375 token modifiers were not ignored on a draw replacement")

    print(f"[info] typed effect IR: {len(cases) + 2} supported operations plus sequence, targets, linked effects, lethal cleanup, trigger emission, replacements, unsupported, Burn Out, and state invariants.")
    if failures:
        print("\n".join(f"FAILED: {failure}" for failure in failures))
        return 1
    print("OK: bounded effect programs are typed, deterministic, rule-grounded, and fail closed without guessed card behavior.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
