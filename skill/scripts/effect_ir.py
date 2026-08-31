#!/usr/bin/env python3
"""Chronicle-owned typed effect IR and bounded atomic interpreter.

R2 intentionally supports a small official-action vocabulary. Card definitions
compose these operations; the interpreter contains no card-name conditionals.
Unsupported actions fail closed and never fall back to natural-language guesses.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


STATE_VERSION = "riftbound-effect-state.v1"
PROGRAM_VERSION = "riftbound-effect-program.v1"
CORE_RULESET = "2026-07-16"
FAQ_AS_OF = "2026-08-14"
PLAYER_ZONES = {"main_deck", "hand", "trash", "banishment", "base", "rune_deck"}
OBJECT_KINDS = {"unit", "gear", "spell", "rune"}
SUPPORTED_OPS = {
    "draw",
    "recycle_one",
    "move_board_object",
    "modify_might",
    "deal_damage",
    "heal_damage",
    "ready",
    "exhaust",
    "add_resource",
    "play_token",
    "kill",
    "emit_reflexive",
}


class ReplacementDecisionRequired(ValueError):
    def __init__(self, message: str, replacement_ids: list[str]):
        super().__init__(message)
        self.replacement_ids = replacement_ids

OP_RULES = {
    "draw": ["Core 413"],
    "recycle_one": ["Core 416"],
    "move_board_object": ["Core 420", "Core 445"],
    "modify_might": ["Core 135.2.e.3", "Core 477"],
    "deal_damage": ["Core 417"],
    "heal_damage": ["Core 418"],
    "ready": ["Core 415"],
    "exhaust": ["Core 414"],
    "add_resource": ["Core 429"],
    "play_token": ["Core 143.4", "Core 149.1", "Core 184–186", "Core 349", "Core 375"],
    "kill": ["Core 428"],
    "emit_reflexive": ["Core 386–388"],
}


def hash_value(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _ruleset_valid(value: Any) -> bool:
    return value == {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}


def validate_state(state: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, dict):
        return ["effect state must be an object"]
    if state.get("schema_version") != STATE_VERSION:
        errors.append(f"schema_version must be {STATE_VERSION}")
    if not _ruleset_valid(state.get("ruleset")):
        errors.append("ruleset must match the R2 v1 baseline")
    players = state.get("players")
    objects = state.get("objects")
    battlefields = state.get("battlefields")
    replacements = state.get("replacement_effects")
    if not isinstance(players, dict) or len(players) < 2:
        errors.append("players must be an object with at least two entries")
        players = {}
    if not isinstance(objects, dict):
        errors.append("objects must be an object")
        objects = {}
    if not isinstance(battlefields, dict):
        errors.append("battlefields must be an object")
        battlefields = {}
    if not isinstance(replacements, list):
        errors.append("replacement_effects must be an array")
        replacements = []

    occupancy: dict[str, list[str]] = {object_id: [] for object_id in objects}
    for player_id, player in players.items():
        if not isinstance(player, dict):
            errors.append(f"players.{player_id} must be an object")
            continue
        zones = player.get("zones")
        if not isinstance(zones, dict) or set(zones) != PLAYER_ZONES:
            errors.append(f"players.{player_id}.zones must contain exactly {sorted(PLAYER_ZONES)}")
            continue
        for zone, ids in zones.items():
            if not isinstance(ids, list) or len(ids) != len(set(ids)):
                errors.append(f"players.{player_id}.zones.{zone} must be a unique array")
                continue
            for object_id in ids:
                if object_id not in objects:
                    errors.append(f"unknown object {object_id!r} in {player_id}.{zone}")
                else:
                    occupancy[object_id].append(f"player:{player_id}:{zone}")
        resources = player.get("resources")
        if not isinstance(resources, dict) or not isinstance(resources.get("energy"), int) or resources.get("energy", -1) < 0:
            errors.append(f"players.{player_id}.resources.energy must be a non-negative integer")
        power = resources.get("power") if isinstance(resources, dict) else None
        if not isinstance(power, dict) or any(not isinstance(v, int) or v < 0 for v in power.values()):
            errors.append(f"players.{player_id}.resources.power must map domains to non-negative integers")

    for battlefield_id, battlefield in battlefields.items():
        if not isinstance(battlefield, dict) or not isinstance(battlefield.get("objects"), list):
            errors.append(f"battlefields.{battlefield_id}.objects must be an array")
            continue
        ids = battlefield["objects"]
        if len(ids) != len(set(ids)):
            errors.append(f"battlefields.{battlefield_id}.objects contains duplicates")
        for object_id in ids:
            if object_id not in objects:
                errors.append(f"unknown object {object_id!r} at battlefield {battlefield_id}")
            else:
                occupancy[object_id].append(f"battlefield:{battlefield_id}")

    for object_id, obj in objects.items():
        if not isinstance(obj, dict):
            errors.append(f"objects.{object_id} must be an object")
            continue
        if obj.get("owner") not in players or obj.get("controller") not in players:
            errors.append(f"objects.{object_id} has unknown owner/controller")
        if obj.get("kind") not in OBJECT_KINDS:
            errors.append(f"objects.{object_id}.kind is invalid")
        for field in ("base_might", "damage"):
            if not isinstance(obj.get(field), int) or obj.get(field, -1) < 0:
                errors.append(f"objects.{object_id}.{field} must be a non-negative integer")
        if not isinstance(obj.get("exhausted"), bool):
            errors.append(f"objects.{object_id}.exhausted must be boolean")
        death_triggers = obj.get("death_triggers", [])
        if not isinstance(death_triggers, list):
            errors.append(f"objects.{object_id}.death_triggers must be an array")
        else:
            for trigger_index, trigger in enumerate(death_triggers):
                required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize"}
                if not isinstance(trigger, dict) or not required.issubset(trigger):
                    errors.append(f"objects.{object_id}.death_triggers[{trigger_index}] has invalid shape")
                elif trigger.get("source_object") != object_id or trigger.get("controller") not in players:
                    errors.append(f"objects.{object_id}.death_triggers[{trigger_index}] has invalid source/controller")
                elif not isinstance(trigger.get("effect_program_id"), str) or not trigger.get("effect_program_id") or not isinstance(trigger.get("optional_at_finalize"), bool):
                    errors.append(f"objects.{object_id}.death_triggers[{trigger_index}] has invalid program/optional binding")
        if not isinstance(obj.get("is_token", False), bool):
            errors.append(f"objects.{object_id}.is_token must be boolean when supplied")
        keywords = obj.get("keywords", [])
        if not isinstance(keywords, list) or len(keywords) != len(set(keywords)) or any(keyword not in {"temporary"} for keyword in keywords):
            errors.append(f"objects.{object_id}.keywords must be a unique supported-keyword array")
        modifiers = obj.get("might_modifiers")
        if not isinstance(modifiers, list):
            errors.append(f"objects.{object_id}.might_modifiers must be an array")
        elif any(not isinstance(item, dict) or set(item) != {"amount", "duration", "source"} for item in modifiers):
            errors.append(f"objects.{object_id}.might_modifiers has invalid entries")
        places = occupancy.get(object_id, [])
        if len(places) != 1:
            errors.append(f"object {object_id!r} must occupy exactly one zone/location, got {places}")
    replacement_ids: set[str] = set()
    for index, replacement in enumerate(replacements):
        label = f"replacement_effects[{index}]"
        required = {"replacement_id", "controller", "source_object", "mode", "event_op", "optional", "uses_remaining"}
        if not isinstance(replacement, dict) or not required.issubset(replacement):
            errors.append(f"{label} has invalid shape")
            continue
        replacement_id = replacement.get("replacement_id")
        if not isinstance(replacement_id, str) or not replacement_id or replacement_id in replacement_ids:
            errors.append(f"{label}.replacement_id is invalid or duplicated")
        else:
            replacement_ids.add(replacement_id)
        if replacement.get("controller") not in players or replacement.get("source_object") not in objects:
            errors.append(f"{label} has unknown controller/source")
        elif objects[replacement["source_object"]].get("controller") != replacement.get("controller"):
            errors.append(f"{label}.controller must control its source object")
        if replacement.get("mode") not in {"prevent_event", "replace_with", "augment_with", "reduce_damage"}:
            errors.append(f"{label}.mode is unsupported")
        if replacement.get("event_op") not in SUPPORTED_OPS:
            errors.append(f"{label}.event_op is unsupported")
        if not isinstance(replacement.get("optional"), bool):
            errors.append(f"{label}.optional must be boolean")
        uses = replacement.get("uses_remaining")
        if uses is not None and (not isinstance(uses, int) or uses < 0):
            errors.append(f"{label}.uses_remaining must be null or non-negative integer")
        relation = replacement.get("target_controller_relation")
        if relation not in {None, "friendly", "enemy"}:
            errors.append(f"{label}.target_controller_relation is invalid")
        replacement_effects = replacement.get("replacement_effects")
        if replacement.get("mode") in {"replace_with", "augment_with"} and (not isinstance(replacement_effects, list) or not replacement_effects):
            errors.append(f"{label}.replacement_effects must be non-empty for {replacement.get('mode')}")
        if replacement.get("mode") == "reduce_damage":
            if replacement.get("event_op") != "deal_damage":
                errors.append(f"{label}.reduce_damage may only replace deal_damage")
            if not isinstance(replacement.get("prevent_remaining"), int) or replacement.get("prevent_remaining", 0) <= 0:
                errors.append(f"{label}.prevent_remaining must be a positive integer")
        source_places = occupancy.get(replacement.get("source_object"), [])
        if source_places and not any(place.startswith("battlefield:") or place.endswith(":base") for place in source_places):
            errors.append(f"{label}.source_object must be active on the board")
    return errors


def validate_program(program: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(program, dict):
        return ["effect program must be an object"]
    if program.get("schema_version") != PROGRAM_VERSION:
        errors.append(f"schema_version must be {PROGRAM_VERSION}")
    if not _ruleset_valid(program.get("ruleset")):
        errors.append("program ruleset must match the R2 v1 baseline")
    if not isinstance(program.get("program_id"), str) or not program.get("program_id"):
        errors.append("program_id must be non-empty")
    effects = program.get("effects")
    if not isinstance(effects, list) or not effects:
        errors.append("effects must be a non-empty array")
    elif any(not isinstance(effect, dict) or not isinstance(effect.get("op"), str) for effect in effects):
        errors.append("each effect must be an object with op")
    else:
        seen: set[str] = set()
        for index, effect in enumerate(effects):
            effect_id = effect.get("effect_id", f"effect-{index}")
            if not isinstance(effect_id, str) or not effect_id:
                errors.append(f"effects[{index}].effect_id must be non-empty when supplied")
                continue
            if effect_id in seen:
                errors.append(f"effects[{index}].effect_id is duplicated")
            dependency = effect.get("depends_on")
            if dependency is not None and dependency not in seen:
                errors.append(f"effects[{index}].depends_on must reference an earlier effect")
            if effect.get("dependency_mode", "if_applied") not in {"if_applied", "always"}:
                errors.append(f"effects[{index}].dependency_mode is invalid")
            modifiers = effect.get("event_modifiers")
            if modifiers is not None:
                if effect.get("op") != "play_token" or not isinstance(modifiers, dict) or not modifiers or set(modifiers) - {"entry_state", "result_keywords"}:
                    errors.append(f"effects[{index}].event_modifiers is unsupported for this operation")
                else:
                    if modifiers.get("entry_state") not in {None, "ready", "exhausted"}:
                        errors.append(f"effects[{index}].event_modifiers.entry_state is invalid")
                    result_keywords = modifiers.get("result_keywords", [])
                    if not isinstance(result_keywords, list) or len(result_keywords) != len(set(result_keywords)) or any(keyword not in {"temporary"} for keyword in result_keywords):
                        errors.append(f"effects[{index}].event_modifiers.result_keywords is invalid")
            if effect.get("op") == "play_token":
                destination = effect.get("destination")
                if not isinstance(effect.get("object_id"), str) or not effect.get("object_id"):
                    errors.append(f"effects[{index}].play_token requires object_id")
                if not isinstance(effect.get("owner"), str) or not effect.get("owner"):
                    errors.append(f"effects[{index}].play_token requires owner")
                if not isinstance(effect.get("controller"), str) or effect.get("token_kind") not in {"unit", "gear"}:
                    errors.append(f"effects[{index}].play_token requires controller and unit/gear token_kind")
                if not isinstance(effect.get("base_might"), int) or effect.get("base_might", -1) < 0:
                    errors.append(f"effects[{index}].play_token requires non-negative base_might")
                if not isinstance(destination, dict) or destination.get("kind") not in {"base", "battlefield"}:
                    errors.append(f"effects[{index}].play_token requires a base or battlefield destination")
                elif effect.get("token_kind") == "gear" and destination.get("kind") != "base":
                    errors.append(f"effects[{index}].non-Unit Gear token must enter a Base")
                elif destination.get("kind") == "base" and destination.get("player") != effect.get("controller"):
                    errors.append(f"effects[{index}].Base destination must match token controller")
            target = effect.get("target")
            if target is not None:
                if not isinstance(target, dict) or not isinstance(target.get("object_id"), str):
                    errors.append(f"effects[{index}].target must identify an object")
                elif target.get("chosen_zone_class") not in {"board", "non_board"}:
                    errors.append(f"effects[{index}].target.chosen_zone_class is required")
            seen.add(effect_id)
    return errors


def find_location(state: dict[str, Any], object_id: str) -> tuple[str, str, str | None] | None:
    for player_id, player in state["players"].items():
        for zone, ids in player["zones"].items():
            if object_id in ids:
                return ("player", player_id, zone)
    for battlefield_id, battlefield in state["battlefields"].items():
        if object_id in battlefield["objects"]:
            return ("battlefield", battlefield_id, None)
    return None


def zone_class(location: tuple[str, str, str | None] | None) -> str | None:
    if location is None:
        return None
    if location[0] == "battlefield" or location[2] == "base":
        return "board"
    return "non_board"


def evaluate_target(state: dict[str, Any], target: dict[str, Any], controller: str | None) -> tuple[bool, str]:
    object_id = target["object_id"]
    obj = state["objects"].get(object_id)
    if obj is None:
        return False, "target_object_missing"
    location = find_location(state, object_id)
    current_class = zone_class(location)
    if current_class != target.get("chosen_zone_class"):
        return False, "target_changed_board_zone_class"
    required_kind = target.get("kind")
    if required_kind is not None and obj.get("kind") != required_kind:
        return False, "target_kind_requirement_failed"
    required_location = target.get("location")
    if required_location == "battlefield" and (location is None or location[0] != "battlefield"):
        return False, "target_location_requirement_failed"
    if required_location == "base" and (location is None or location[0] != "player" or location[2] != "base"):
        return False, "target_location_requirement_failed"
    relation = target.get("controller_relation")
    if relation == "friendly" and controller is not None and obj.get("controller") != controller:
        return False, "target_controller_requirement_failed"
    if relation == "enemy" and controller is not None and obj.get("controller") == controller:
        return False, "target_controller_requirement_failed"
    if target.get("object_id") != target.get("bound_object_id", target.get("object_id")):
        return False, "target_identity_changed"
    return True, "ok"


def _remove_from_location(state: dict[str, Any], object_id: str) -> None:
    location = find_location(state, object_id)
    if location is None:
        raise ValueError(f"object {object_id!r} has no location")
    if location[0] == "player":
        state["players"][location[1]]["zones"][location[2]].remove(object_id)
    else:
        state["battlefields"][location[1]]["objects"].remove(object_id)


def _prune_inactive_replacements(state: dict[str, Any]) -> list[str]:
    removed = []
    active = []
    for replacement in state["replacement_effects"]:
        if zone_class(find_location(state, replacement["source_object"])) == "board":
            active.append(replacement)
        else:
            removed.append(replacement["replacement_id"])
    state["replacement_effects"] = active
    return removed


def _applicable_replacements(state: dict[str, Any], effect: dict[str, Any]) -> list[dict[str, Any]]:
    object_id = effect.get("object_id")
    obj = state["objects"].get(object_id) if object_id is not None else None
    applicable = []
    for replacement in state["replacement_effects"]:
        if replacement["event_op"] != effect.get("op"):
            continue
        if replacement["uses_remaining"] == 0:
            continue
        if replacement["mode"] == "reduce_damage" and replacement.get("prevent_remaining", 0) <= 0:
            continue
        required_object = replacement.get("target_object_id")
        if required_object is not None and required_object != object_id:
            continue
        relation = replacement.get("target_controller_relation")
        if relation is not None:
            if obj is None:
                continue
            friendly = obj.get("controller") == replacement["controller"]
            if relation == "friendly" and not friendly:
                continue
            if relation == "enemy" and friendly:
                continue
        applicable.append(replacement)
    return applicable


def _inherit_event_modifiers(original_effect: dict[str, Any], replacement_effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the bounded Core 375 modifier vocabulary to compatible child events."""
    inherited = original_effect.get("event_modifiers")
    children = copy.deepcopy(replacement_effects)
    if not inherited:
        return children
    for child in children:
        if child.get("op") != "play_token":
            continue
        applicable: dict[str, Any] = {}
        if "entry_state" in inherited:
            applicable["entry_state"] = inherited["entry_state"]
        inherited_keywords = inherited.get("result_keywords", [])
        if child.get("token_kind") == "unit" and inherited_keywords:
            applicable["result_keywords"] = copy.deepcopy(inherited_keywords)
        if not applicable:
            continue
        existing = child.get("event_modifiers", {})
        for key, value in applicable.items():
            if key in existing and existing[key] != value:
                raise NotImplementedError(f"conflicting inherited event modifier {key!r}")
        child["event_modifiers"] = {**applicable, **copy.deepcopy(existing)}
        child["modifier_inheritance"] = {"rule": "Core 375", "from_effect_id": original_effect.get("effect_id")}
    return children


def _select_replacement(state: dict[str, Any], effect: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    applicable = _applicable_replacements(state, effect)
    if not applicable:
        return None
    ids = [replacement["replacement_id"] for replacement in applicable]
    supplied_order = effect.get("replacement_order")
    if len(applicable) > 1:
        object_id = effect.get("object_id")
        affected_controller = state["objects"].get(object_id, {}).get("controller") if object_id is not None else None
        if affected_controller is None or effect.get("replacement_decider") != affected_controller:
            raise ReplacementDecisionRequired("the affected object's controller must decide replacement order", ids)
        if not isinstance(supplied_order, list) or len(supplied_order) != len(set(supplied_order)) or set(supplied_order) != set(ids):
            raise ReplacementDecisionRequired("affected controller must order all applicable replacement effects", ids)
        by_id = {replacement["replacement_id"]: replacement for replacement in applicable}
        applicable = [by_id[replacement_id] for replacement_id in supplied_order]
    choices = effect.get("replacement_choices", {})
    if not isinstance(choices, dict):
        raise ValueError("replacement_choices must be an object")
    for replacement in applicable:
        replacement_id = replacement["replacement_id"]
        if replacement["optional"]:
            if replacement_id not in choices or not isinstance(choices[replacement_id], bool):
                raise ReplacementDecisionRequired("optional replacement requires an explicit apply/decline choice", [replacement_id])
            if choices[replacement_id] is False:
                continue
        new_state = copy.deepcopy(state)
        stored = next(item for item in new_state["replacement_effects"] if item["replacement_id"] == replacement_id)
        if stored["uses_remaining"] is not None:
            stored["uses_remaining"] -= 1
        outcome = {
            "prevent_event": "replaced_prevented",
            "replace_with": "replaced_with",
            "augment_with": "augmented_with",
            "reduce_damage": "replaced_modified",
        }[replacement["mode"]]
        return new_state, {
            "op": effect["op"],
            "outcome": outcome,
            "replacement_id": replacement_id,
            "affected_object_id": effect.get("object_id"),
            "rule_locators": ["Core 367–375", "Core 370.1.b–370.2"] + (["Core 443"] if replacement["mode"] == "prevent_event" else []),
        }, copy.deepcopy(replacement)
    return None


def _apply_one(state: dict[str, Any], effect: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    op = effect.get("op")
    if op not in SUPPORTED_OPS:
        raise NotImplementedError(f"unsupported effect op {op!r}")
    new_state = copy.deepcopy(state)
    trace: dict[str, Any] = {"op": op, "outcome": "applied", "rule_locators": OP_RULES[op]}

    if op == "draw":
        player_id, count = effect.get("player"), effect.get("count")
        if player_id not in new_state["players"] or not isinstance(count, int) or count < 1:
            raise ValueError("draw requires a known player and positive count")
        deck = new_state["players"][player_id]["zones"]["main_deck"]
        if len(deck) < count:
            raise NotImplementedError("draw would require Burn Out, which is outside effect IR v1")
        drawn = deck[:count]
        del deck[:count]
        new_state["players"][player_id]["zones"]["hand"].extend(drawn)
        trace["objects"] = drawn

    elif op == "recycle_one":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("recycle_one requires a known object")
        obj = new_state["objects"][object_id]
        _remove_from_location(new_state, object_id)
        if obj.get("is_token"):
            del new_state["objects"][object_id]
            destination = "ceased_to_exist"
            trace.update({"object_id": object_id, "destination": destination})
            trace["rule_locators"] = ["Core 416", "Core 186.1"]
        else:
            destination = "rune_deck" if obj["kind"] == "rune" else "main_deck"
            new_state["players"][obj["owner"]]["zones"][destination].append(object_id)
            trace.update({"object_id": object_id, "destination": f"{obj['owner']}.{destination}.bottom"})

    elif op == "move_board_object":
        object_id, destination = effect.get("object_id"), effect.get("destination")
        if object_id not in new_state["objects"] or not isinstance(destination, dict):
            raise ValueError("move_board_object requires a known object and destination")
        source = find_location(new_state, object_id)
        if source is None or not (source[0] == "battlefield" or source[2] == "base"):
            raise ValueError("Move applies only between board locations")
        _remove_from_location(new_state, object_id)
        if destination.get("kind") == "base" and destination.get("player") in new_state["players"]:
            new_state["players"][destination["player"]]["zones"]["base"].append(object_id)
            target = f"base:{destination['player']}"
        elif destination.get("kind") == "battlefield" and destination.get("battlefield") in new_state["battlefields"]:
            new_state["battlefields"][destination["battlefield"]]["objects"].append(object_id)
            target = f"battlefield:{destination['battlefield']}"
        else:
            raise ValueError("unknown board destination")
        trace.update({"object_id": object_id, "from": source, "to": target})

    elif op == "modify_might":
        object_id, amount = effect.get("object_id"), effect.get("amount")
        duration, source = effect.get("duration"), effect.get("source")
        if object_id not in new_state["objects"] or not isinstance(amount, int):
            raise ValueError("modify_might requires a known object and integer amount")
        if duration not in {"this_turn", "persistent"} or not isinstance(source, str) or not source:
            raise ValueError("modify_might requires duration and source")
        new_state["objects"][object_id]["might_modifiers"].append({"amount": amount, "duration": duration, "source": source})
        trace.update({"object_id": object_id, "amount": amount, "duration": duration})

    elif op in {"deal_damage", "heal_damage"}:
        object_id, amount = effect.get("object_id"), effect.get("amount")
        if object_id not in new_state["objects"] or not isinstance(amount, int) or amount < 1:
            raise ValueError(f"{op} requires a known object and positive amount")
        before = new_state["objects"][object_id]["damage"]
        after = before + amount if op == "deal_damage" else max(0, before - amount)
        new_state["objects"][object_id]["damage"] = after
        trace.update({"object_id": object_id, "before": before, "after": after})
        if before == after:
            trace["outcome"] = "no_op"

    elif op in {"ready", "exhaust"}:
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError(f"{op} requires a known object")
        location = find_location(new_state, object_id)
        if location is None or not (location[0] == "battlefield" or location[2] == "base"):
            raise ValueError(f"{op} applies only to board objects")
        desired = op == "exhaust"
        before = new_state["objects"][object_id]["exhausted"]
        new_state["objects"][object_id]["exhausted"] = desired
        trace.update({"object_id": object_id, "before": before, "after": desired})
        if before == desired:
            trace["outcome"] = "no_op"

    elif op == "add_resource":
        player_id, resource, amount = effect.get("player"), effect.get("resource"), effect.get("amount")
        if player_id not in new_state["players"] or not isinstance(amount, int) or amount < 1:
            raise ValueError("add_resource requires a known player and positive amount")
        resources = new_state["players"][player_id]["resources"]
        if resource == "energy":
            resources["energy"] += amount
            trace.update({"player": player_id, "resource": resource, "amount": amount})
        elif resource == "power" and isinstance(effect.get("domain"), str) and effect["domain"]:
            domain = effect["domain"]
            resources["power"][domain] = resources["power"].get(domain, 0) + amount
            trace.update({"player": player_id, "resource": resource, "domain": domain, "amount": amount})
        else:
            raise ValueError("power addition requires a domain")

    elif op == "play_token":
        object_id = effect.get("object_id")
        owner = effect.get("owner")
        controller = effect.get("controller")
        token_kind = effect.get("token_kind")
        base_might = effect.get("base_might")
        destination = effect.get("destination")
        if not isinstance(object_id, str) or not object_id or object_id in new_state["objects"]:
            raise ValueError("play_token requires a new unique object_id")
        if owner not in new_state["players"] or controller not in new_state["players"]:
            raise ValueError("play_token requires known owner/controller players")
        if token_kind not in {"unit", "gear"} or not isinstance(base_might, int) or base_might < 0:
            raise ValueError("play_token requires a supported kind and non-negative base_might")
        if not isinstance(destination, dict):
            raise ValueError("play_token requires a destination")
        if token_kind == "gear" and destination.get("kind") != "base":
            raise ValueError("non-Unit Gear token must enter a Base")
        if destination.get("kind") == "base" and destination.get("player") != controller:
            raise ValueError("play_token Base destination must match token controller")
        modifiers = copy.deepcopy(effect.get("event_modifiers", {}))
        default_entry_state = "exhausted" if token_kind == "unit" else "ready"
        entry_state = modifiers.get("entry_state", default_entry_state)
        keywords = modifiers.get("result_keywords", []) if token_kind == "unit" else []
        new_state["objects"][object_id] = {
            "owner": owner,
            "controller": controller,
            "kind": token_kind,
            "is_token": True,
            "base_might": base_might,
            "might_modifiers": [],
            "damage": 0,
            "exhausted": entry_state == "exhausted",
            "keywords": copy.deepcopy(keywords),
        }
        if destination.get("kind") == "base" and destination.get("player") in new_state["players"]:
            new_state["players"][destination["player"]]["zones"]["base"].append(object_id)
            destination_label = f"{destination['player']}.base"
        elif destination.get("kind") == "battlefield" and destination.get("battlefield") in new_state["battlefields"]:
            new_state["battlefields"][destination["battlefield"]]["objects"].append(object_id)
            destination_label = f"battlefield:{destination['battlefield']}"
        else:
            raise ValueError("play_token destination is unknown")
        trace.update({
            "object_id": object_id,
            "token_kind": token_kind,
            "base_might": base_might,
            "destination": destination_label,
            "event_modifiers": modifiers,
            "modifier_inheritance": copy.deepcopy(effect.get("modifier_inheritance")),
        })

    elif op == "kill":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("kill requires a known object")
        obj = new_state["objects"][object_id]
        location = find_location(new_state, object_id)
        if location is None or not (location[0] == "battlefield" or location[2] == "base"):
            raise ValueError("Kill applies only to a permanent on the board")
        if obj.get("kind") not in {"unit", "gear"}:
            raise ValueError("effect IR v1 only kills supported Unit/Gear permanents")
        pending_triggers = copy.deepcopy(obj.get("death_triggers", []))
        _remove_from_location(new_state, object_id)
        if obj.get("is_token"):
            del new_state["objects"][object_id]
            destination = "ceased_to_exist"
            trace["rule_locators"] = ["Core 428", "Core 186.1"]
        else:
            new_state["players"][obj["owner"]]["zones"]["trash"].append(object_id)
            destination = f"{obj['owner']}.trash"
        disabled_replacements = _prune_inactive_replacements(new_state)
        trace.update({
            "object_id": object_id,
            "kill_mode": effect.get("kill_mode", "active"),
            "destination": destination,
            "attributed_sources": effect.get("attributed_sources", []),
            "pending_triggers": pending_triggers,
            "disabled_replacements": disabled_replacements,
        })

    elif op == "emit_reflexive":
        triggers = effect.get("triggers")
        if not isinstance(triggers, list) or not triggers:
            raise ValueError("emit_reflexive requires one or more trigger descriptors")
        copied = copy.deepcopy(triggers)
        for index, descriptor in enumerate(copied):
            required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize"}
            if not isinstance(descriptor, dict) or not required.issubset(descriptor):
                raise ValueError(f"reflexive trigger {index} has invalid shape")
            descriptor["trigger_kind"] = "reflexive"
        trace.update({"pending_triggers": copied, "reflexive_count": len(copied)})

    errors = validate_state(new_state)
    if errors:
        raise ValueError("effect produced invalid state: " + "; ".join(errors))
    return new_state, trace


def current_might(obj: dict[str, Any]) -> int:
    return obj["base_might"] + sum(modifier["amount"] for modifier in obj.get("might_modifiers", []))


def apply_simultaneous_kill_batch(
    state: dict[str, Any],
    object_ids: list[str],
    *,
    replacement_event_order: dict[str, list[str]] | None = None,
    replacement_choices: dict[str, dict[str, bool]] | None = None,
    kill_mode: str = "simultaneous",
    attributed_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a bounded Core 373 batch with at most one prevent descriptor."""
    base = {
        "schema_version": "riftbound-simultaneous-kill-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": hash_value(state),
    }
    errors = validate_state(state)
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "trace": []}
    if not isinstance(object_ids, list) or not object_ids or len(object_ids) != len(set(object_ids)):
        return {**base, "valid": False, "committed": False, "errors": ["object_ids must be a non-empty unique array"], "trace": []}
    for object_id in object_ids:
        obj = state["objects"].get(object_id)
        if obj is None or obj.get("kind") not in {"unit", "gear"} or zone_class(find_location(state, object_id)) != "board":
            return {**base, "valid": False, "committed": False, "errors": [f"{object_id!r} is not a supported board permanent"], "trace": []}
    if replacement_event_order is not None and not isinstance(replacement_event_order, dict):
        return {**base, "valid": False, "committed": False, "errors": ["replacement_event_order must be an object"], "trace": []}
    if replacement_choices is not None and not isinstance(replacement_choices, dict):
        return {**base, "valid": False, "committed": False, "errors": ["replacement_choices must be an object"], "trace": []}

    events = {
        object_id: {
            "effect_id": f"simultaneous-kill:{object_id}", "op": "kill", "object_id": object_id,
            "kill_mode": kill_mode, "attributed_sources": attributed_sources or [],
        }
        for object_id in object_ids
    }
    qualifying: dict[str, list[str]] = {}
    descriptors: dict[str, dict[str, Any]] = {}
    for object_id in object_ids:
        for descriptor in _applicable_replacements(state, events[object_id]):
            replacement_id = descriptor["replacement_id"]
            descriptors[replacement_id] = descriptor
            qualifying.setdefault(replacement_id, []).append(object_id)
    supplied_order_ids = set((replacement_event_order or {}).keys())
    supplied_choice_ids = set((replacement_choices or {}).keys())
    stale_decision_ids = (supplied_order_ids | supplied_choice_ids) - set(descriptors)
    if stale_decision_ids:
        return {
            **base, "valid": False, "committed": False,
            "errors": [f"cleanup decisions reference non-applicable replacements: {sorted(stale_decision_ids)}"],
            "trace": [],
        }
    if len(descriptors) > 1:
        return {
            **base, "valid": True, "committed": False, "unsupported": True,
            "reason": "multiple replacement descriptors in one simultaneous batch are outside the bounded Core 373 slice",
            "replacement_ids": sorted(descriptors), "trace": [],
        }
    if descriptors and next(iter(descriptors.values()))["mode"] != "prevent_event":
        descriptor = next(iter(descriptors.values()))
        return {
            **base, "valid": True, "committed": False, "unsupported": True,
            "reason": "simultaneous batch currently supports prevent_event only",
            "replacement_ids": [descriptor["replacement_id"]], "trace": [],
        }

    current = copy.deepcopy(state)
    trace: list[dict[str, Any]] = []
    prevented: set[str] = set()
    if descriptors:
        replacement_id, descriptor = next(iter(descriptors.items()))
        qualified_ids = qualifying[replacement_id]
        supplied = (replacement_event_order or {}).get(replacement_id)
        if len(qualified_ids) > 1:
            if not isinstance(supplied, list) or len(supplied) != len(set(supplied)) or set(supplied) != set(qualified_ids):
                return {
                    **base, "valid": True, "committed": False, "replacement_decision_required": True,
                    "reason": "replacement controller must order every qualifying simultaneous event",
                    "replacement_ids": [replacement_id], "event_ids": qualified_ids,
                    "decision_controller": descriptor["controller"], "trace": [],
                }
            event_order = supplied
        else:
            event_order = qualified_ids
        per_event_choices = (replacement_choices or {}).get(replacement_id, {})
        if not isinstance(per_event_choices, dict):
            return {**base, "valid": False, "committed": False, "errors": [f"replacement choices for {replacement_id} must be an object"], "trace": []}
        for sequence_index, object_id in enumerate(event_order):
            applicable_now = next((item for item in _applicable_replacements(current, events[object_id]) if item["replacement_id"] == replacement_id), None)
            if applicable_now is None:
                continue
            event = copy.deepcopy(events[object_id])
            if descriptor["optional"]:
                choice = per_event_choices.get(object_id)
                if not isinstance(choice, bool):
                    return {
                        **base, "valid": True, "committed": False, "replacement_decision_required": True,
                        "reason": "optional simultaneous replacement requires an explicit choice for the next qualifying event",
                        "replacement_ids": [replacement_id], "event_ids": [object_id],
                        "decision_controller": descriptor["controller"], "trace": trace,
                    }
                if choice is False:
                    unchanged_hash = hash_value(current)
                    trace.append({
                        "phase": "replacement_sequence", "sequence_index": sequence_index,
                        "effect_id": event["effect_id"], "object_id": object_id, "op": "kill",
                        "outcome": "replacement_declined", "replacement_id": replacement_id,
                        "before_state_hash": unchanged_hash, "after_state_hash": unchanged_hash,
                        "rule_locators": ["Core 371.2–371.2.b", "Core 373–373.2.a.1"],
                    })
                    continue
                event["replacement_choices"] = {replacement_id: choice}
            selection = _select_replacement(current, event)
            if selection is None:
                continue
            selected_state, replacement_trace, _ = selection
            current = selected_state
            sequence_locators = ["Core 373–373.2.a.1"]
            if descriptor["source_object"] in object_ids:
                sequence_locators.insert(0, "Core 370.4")
            replacement_trace.update({
                "phase": "replacement_sequence", "sequence_index": sequence_index,
                "effect_id": event["effect_id"], "object_id": object_id,
                "before_state_hash": trace[-1]["after_state_hash"] if trace else hash_value(state),
                "after_state_hash": hash_value(current),
                "rule_locators": list(dict.fromkeys(replacement_trace["rule_locators"] + sequence_locators)),
            })
            trace.append(replacement_trace)
            prevented.add(object_id)

    killed = []
    for object_id in object_ids:
        if object_id in prevented:
            continue
        current, event_trace = _apply_one(current, events[object_id])
        event_trace.update({
            "phase": "unmodified_simultaneous_events", "effect_id": events[object_id]["effect_id"],
            "simultaneous_group": copy.deepcopy(object_ids),
            "before_state_hash": trace[-1]["after_state_hash"] if trace else hash_value(state),
            "after_state_hash": hash_value(current),
            "rule_locators": list(dict.fromkeys(event_trace["rule_locators"] + ["Core 373.1.a"])),
        })
        trace.append(event_trace)
        killed.append(object_id)
    pending_triggers = [trigger for event in trace for trigger in event.get("pending_triggers", [])]
    return {
        **base, "valid": True, "committed": True, "unsupported": False,
        "next_state": current, "next_state_hash": hash_value(current),
        "killed_objects": killed, "prevented_objects": [object_id for object_id in object_ids if object_id in prevented],
        "trace": trace, "pending_triggers": pending_triggers,
        "coverage": "single-prevention-descriptor-simultaneous-kill-batch",
    }


def perform_lethal_cleanup(
    state: dict[str, Any],
    *,
    attributed_sources: list[str] | None = None,
    replacement_event_order: dict[str, list[str]] | None = None,
    replacement_choices: dict[str, dict[str, bool]] | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": "riftbound-lethal-cleanup-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": hash_value(state),
    }
    errors = validate_state(state)
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "trace": []}
    current = copy.deepcopy(state)
    trace: list[dict[str, Any]] = []
    pending_triggers: list[dict[str, Any]] = []
    initial_group: list[str] = []
    killed_objects: list[str] = []
    stable_prevented: list[str] = []
    iterations = 0
    while iterations < 16:
        lethal = []
        for object_id, obj in current["objects"].items():
            location = find_location(current, object_id)
            if obj["kind"] != "unit" or location is None or not (location[0] == "battlefield" or location[2] == "base"):
                continue
            might = current_might(obj)
            if obj["damage"] > 0 and obj["damage"] >= might:
                lethal.append((object_id, might, obj["damage"]))
        group = [object_id for object_id, _, _ in sorted(lethal)]
        if not group:
            break
        if not initial_group:
            initial_group = copy.deepcopy(group)
        facts = {object_id: (might, damage) for object_id, might, damage in lethal}
        before_iteration_hash = hash_value(current)
        batch = apply_simultaneous_kill_batch(
            current,
            group,
            replacement_event_order=replacement_event_order if iterations == 0 else None,
            replacement_choices=replacement_choices if iterations == 0 else None,
            kill_mode="passive_lethal_cleanup",
            attributed_sources=attributed_sources,
        )
        if batch.get("committed") is not True:
            return {
                **base, "valid": batch.get("valid", True), "committed": False,
                "unsupported": batch.get("unsupported", False),
                "replacement_decision_required": batch.get("replacement_decision_required", False),
                "reason": batch.get("reason", "; ".join(batch.get("errors", [])) or "simultaneous lethal batch failed"),
                "batch_result": batch, "trace": trace,
            }
        current = batch["next_state"]
        batch_id = f"lethal-cleanup:{hash_value(state).split(':', 1)[1][:12]}:{iterations}"
        for event in batch["trace"]:
            copied_event = copy.deepcopy(event)
            object_id = copied_event.get("object_id")
            if object_id in facts:
                copied_event["lethal_might"], copied_event["marked_damage"] = facts[object_id]
            copied_event["cleanup_iteration"] = iterations
            copied_event["rule_locators"] = list(dict.fromkeys(copied_event.get("rule_locators", []) + ["Core 142.4", "Core 322–323.5", "Core 428"]))
            trace.append(copied_event)
        for trigger in batch.get("pending_triggers", []):
            copied_trigger = copy.deepcopy(trigger)
            copied_trigger["batch_sequence"] = iterations
            copied_trigger["batch_id"] = batch_id
            copied_trigger.setdefault("trigger_kind", "self_death")
            pending_triggers.append(copied_trigger)
        killed_objects.extend(batch.get("killed_objects", []))
        iterations += 1
        if hash_value(current) == before_iteration_hash:
            stable_prevented = batch.get("prevented_objects", [])
            break
    else:
        return {
            **base, "valid": True, "committed": False, "unsupported": True,
            "reason": "lethal cleanup replacement loop exceeded 16 iterations", "trace": trace,
        }
    return {
        **base,
        "valid": True,
        "committed": True,
        "unsupported": False,
        "next_state": current,
        "next_state_hash": hash_value(current),
        "lethal_objects": initial_group,
        "killed_objects": killed_objects,
        "stable_prevented_objects": stable_prevented,
        "cleanup_iterations": iterations,
        "trace": trace,
        "pending_triggers": pending_triggers,
        "coverage": "lethal-damage-with-single-prevention-descriptor-sequencing",
    }


def apply_program(state: dict[str, Any], program: dict[str, Any], *, _replacement_depth: int = 0) -> dict[str, Any]:
    state_errors = validate_state(state)
    program_errors = validate_program(program)
    base = {
        "schema_version": "riftbound-effect-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "program_id": program.get("program_id") if isinstance(program, dict) else None,
        "input_state_hash": hash_value(state),
    }
    if state_errors or program_errors:
        return {**base, "valid": False, "committed": False, "errors": state_errors + program_errors, "trace": []}
    if _replacement_depth > 8:
        return {**base, "valid": True, "committed": False, "unsupported": True, "reason": "replacement recursion depth exceeded", "trace": []}
    current = copy.deepcopy(state)
    trace = []
    outcomes: dict[str, str] = {}
    for index, effect in enumerate(program["effects"]):
        before_hash = hash_value(current)
        effect_id = effect.get("effect_id", f"effect-{index}")
        dependency = effect.get("depends_on")
        if dependency is not None and effect.get("dependency_mode", "if_applied") == "if_applied" and outcomes.get(dependency) != "applied":
            event = {
                "index": index,
                "effect_id": effect_id,
                "op": effect["op"],
                "outcome": "skipped_linked_dependency",
                "depends_on": dependency,
                "rule_locators": ["Core 359.3.e.14"],
                "before_state_hash": before_hash,
                "after_state_hash": before_hash,
            }
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        target = effect.get("target")
        if target is not None:
            legal_target, reason = evaluate_target(current, target, program.get("controller"))
            if not legal_target:
                event = {
                    "index": index,
                    "effect_id": effect_id,
                    "op": effect["op"],
                    "outcome": "ignored_illegal_target",
                    "reason": reason,
                    "target_object_id": target["object_id"],
                    "rule_locators": ["Core 359.3.e.1–359.3.e.5", "Core 359.3.e.14"],
                    "before_state_hash": before_hash,
                    "after_state_hash": before_hash,
                }
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            if effect.get("object_id") is not None and effect.get("object_id") != target["object_id"]:
                return {
                    **base,
                    "valid": False,
                    "committed": False,
                    "failed_effect_index": index,
                    "errors": ["effect object_id must match target.object_id"],
                    "trace": trace,
                }
        affected_before_damage = current["objects"].get(effect.get("object_id"), {}).get("damage")
        try:
            replacement_selection = _select_replacement(current, effect)
        except ReplacementDecisionRequired as exc:
            return {
                **base,
                "valid": True,
                "committed": False,
                "replacement_decision_required": True,
                "failed_effect_index": index,
                "reason": str(exc),
                "replacement_ids": exc.replacement_ids,
                "trace": trace,
            }
        except ValueError as exc:
            return {
                **base,
                "valid": False,
                "committed": False,
                "failed_effect_index": index,
                "errors": [str(exc)],
                "trace": trace,
            }
        if replacement_selection is not None:
            selected_state, event, replacement = replacement_selection
            if replacement["mode"] == "prevent_event":
                current = selected_state
                event.update({"index": index, "effect_id": effect_id, "before_state_hash": before_hash, "after_state_hash": hash_value(current)})
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            replacement_id = replacement["replacement_id"]
            replacement_index = next(i for i, item in enumerate(selected_state["replacement_effects"]) if item["replacement_id"] == replacement_id)
            stored_replacement = copy.deepcopy(selected_state["replacement_effects"][replacement_index])
            if replacement["mode"] == "augment_with":
                recursive_state = copy.deepcopy(selected_state)
                del recursive_state["replacement_effects"][replacement_index]
                original_effect = copy.deepcopy(effect)
                supplied_order = original_effect.get("replacement_order")
                if isinstance(supplied_order, list):
                    original_effect["replacement_order"] = [item for item in supplied_order if item != replacement_id]
                original_program = {
                    "schema_version": PROGRAM_VERSION,
                    "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                    "program_id": f"augmentation-original:{replacement_id}:{program['program_id']}:{effect_id}",
                    "controller": program.get("controller"),
                    "source_object": program.get("source_object"),
                    "effects": [original_effect],
                }
                original_result = apply_program(recursive_state, original_program, _replacement_depth=_replacement_depth + 1)
                if original_result.get("committed") is not True:
                    return {
                        **base, "valid": original_result.get("valid", True), "committed": False,
                        "unsupported": original_result.get("unsupported", False), "failed_effect_index": index,
                        "reason": original_result.get("reason", "; ".join(original_result.get("errors", [])) or "augmented original event failed"),
                        "replacement_id": replacement_id, "replacement_result": original_result, "trace": trace,
                    }
                try:
                    augmentation_effects = _inherit_event_modifiers(effect, replacement["replacement_effects"])
                except NotImplementedError as exc:
                    return {
                        **base, "valid": True, "committed": False, "unsupported": True,
                        "failed_effect_index": index, "reason": str(exc), "replacement_id": replacement_id, "trace": trace,
                    }
                augmentation_program = {
                    "schema_version": PROGRAM_VERSION,
                    "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                    "program_id": f"augmentation-extra:{replacement_id}:{program['program_id']}:{effect_id}",
                    "controller": replacement["controller"],
                    "source_object": replacement["source_object"],
                    "effects": augmentation_effects,
                }
                augmentation_result = apply_program(original_result["next_state"], augmentation_program, _replacement_depth=_replacement_depth + 1)
                if augmentation_result.get("committed") is not True:
                    return {
                        **base, "valid": augmentation_result.get("valid", True), "committed": False,
                        "unsupported": augmentation_result.get("unsupported", False), "failed_effect_index": index,
                        "reason": augmentation_result.get("reason", "; ".join(augmentation_result.get("errors", [])) or "augmentation program failed"),
                        "replacement_id": replacement_id, "replacement_result": augmentation_result, "trace": trace,
                    }
                current = augmentation_result["next_state"]
                source_location = find_location(current, replacement["source_object"])
                active_uses = stored_replacement.get("uses_remaining") is None or stored_replacement.get("uses_remaining", 0) > 0
                if zone_class(source_location) == "board" and active_uses:
                    current["replacement_effects"].insert(min(replacement_index, len(current["replacement_effects"])), stored_replacement)
                if found := validate_state(current):
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": found, "trace": trace}
                original_trace = original_result.get("trace", [])
                augmentation_trace = augmentation_result.get("trace", [])
                original_happened = any(child.get("outcome") in {"applied", "replaced_modified_applied", "augmented_applied"} for child in original_trace)
                pending = []
                for offset, child_result in enumerate((original_result, augmentation_result)):
                    for trigger in child_result.get("pending_triggers", []):
                        copied_trigger = dict(trigger)
                        copied_trigger["batch_sequence"] = index * 1000 + offset * 500 + copied_trigger.get("batch_sequence", 0)
                        copied_trigger["batch_id"] = f"augmentation:{replacement_id}:{copied_trigger.get('batch_id', 'batch')}"
                        pending.append(copied_trigger)
                nested_locators = [locator for child in original_trace + augmentation_trace for locator in child.get("rule_locators", [])]
                event.update({
                    "outcome": "augmented_applied" if original_happened else "augmented_original_replaced",
                    "original_event_happened": original_happened,
                    "index": index,
                    "effect_id": effect_id,
                    "before_state_hash": before_hash,
                    "after_state_hash": hash_value(current),
                    "original_trace": original_trace,
                    "augmentation_trace": augmentation_trace,
                    "pending_triggers": pending,
                    "rule_locators": list(dict.fromkeys(event["rule_locators"] + nested_locators + ["Core 370.1.b.1"])),
                })
                trace.append(event)
                outcomes[effect_id] = "applied" if original_happened else event["outcome"]
                continue
            try:
                replacement_program_effects = _inherit_event_modifiers(effect, replacement.get("replacement_effects", []))
            except NotImplementedError as exc:
                return {
                    **base, "valid": True, "committed": False, "unsupported": True,
                    "failed_effect_index": index, "reason": str(exc), "replacement_id": replacement_id, "trace": trace,
                }
            original_damage = None
            prevented_damage = None
            if replacement["mode"] == "reduce_damage":
                original_damage = effect.get("amount")
                if not isinstance(original_damage, int) or original_damage < 1:
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": ["reduce_damage requires positive deal_damage amount"], "trace": trace}
                prevented_damage = min(original_damage, stored_replacement["prevent_remaining"])
                stored_replacement["prevent_remaining"] -= prevented_damage
                reduced = copy.deepcopy(effect)
                reduced["amount"] = original_damage - prevented_damage
                reduced.pop("replacement_order", None)
                reduced.pop("replacement_decider", None)
                reduced.pop("replacement_choices", None)
                replacement_program_effects = [] if reduced["amount"] == 0 else [reduced]
            recursive_state = copy.deepcopy(selected_state)
            del recursive_state["replacement_effects"][replacement_index]
            if replacement["mode"] == "reduce_damage" and not replacement_program_effects:
                current = recursive_state
                source_location = find_location(current, replacement["source_object"])
                if zone_class(source_location) == "board" and stored_replacement.get("prevent_remaining", 0) > 0:
                    current["replacement_effects"].insert(min(replacement_index, len(current["replacement_effects"])), stored_replacement)
                event.update({
                    "outcome": "replaced_prevented",
                    "index": index,
                    "effect_id": effect_id,
                    "original_damage": original_damage,
                    "prevented_damage": prevented_damage,
                    "remaining_damage": 0,
                    "before_state_hash": before_hash,
                    "after_state_hash": hash_value(current),
                    "rule_locators": list(dict.fromkeys(event["rule_locators"] + ["Core 437.1–437.4"])),
                })
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            recursive_program = {
                "schema_version": PROGRAM_VERSION,
                "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "program_id": f"replacement:{replacement_id}:{program['program_id']}:{effect_id}",
                "controller": replacement["controller"],
                "source_object": replacement["source_object"],
                "effects": replacement_program_effects,
            }
            recursive_result = apply_program(recursive_state, recursive_program, _replacement_depth=_replacement_depth + 1)
            if recursive_result.get("committed") is not True:
                return {
                    **base,
                    "valid": recursive_result.get("valid", True),
                    "committed": False,
                    "unsupported": recursive_result.get("unsupported", False),
                    "failed_effect_index": index,
                    "reason": recursive_result.get("reason", "; ".join(recursive_result.get("errors", [])) or "replacement program failed"),
                    "replacement_id": replacement_id,
                    "replacement_result": recursive_result,
                    "trace": trace,
                }
            current = recursive_result["next_state"]
            source_location = find_location(current, replacement["source_object"])
            replacement_still_active = replacement["mode"] != "reduce_damage" or stored_replacement.get("prevent_remaining", 0) > 0
            if zone_class(source_location) == "board" and replacement_still_active:
                current["replacement_effects"].insert(min(replacement_index, len(current["replacement_effects"])), stored_replacement)
            if found := validate_state(current):
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": found, "trace": trace}
            nested_locators = [locator for child in recursive_result.get("trace", []) for locator in child.get("rule_locators", [])]
            nested_triggers = [dict(trigger) for trigger in recursive_result.get("pending_triggers", [])]
            for trigger in nested_triggers:
                trigger["batch_sequence"] = index * 1000 + trigger.get("batch_sequence", 0)
                trigger["batch_id"] = f"replacement:{replacement_id}:{trigger.get('batch_id', 'batch')}"
            event.update({
                "index": index,
                "effect_id": effect_id,
                "before_state_hash": before_hash,
                "after_state_hash": hash_value(current),
                "replacement_trace": recursive_result.get("trace", []),
                "pending_triggers": nested_triggers,
                "rule_locators": list(dict.fromkeys(event["rule_locators"] + nested_locators)),
            })
            if replacement["mode"] == "reduce_damage":
                affected = effect.get("object_id")
                before_damage = affected_before_damage
                after_damage = current["objects"].get(affected, {}).get("damage")
                damage_applied = isinstance(before_damage, int) and isinstance(after_damage, int) and after_damage > before_damage
                event.update({
                    "outcome": "replaced_modified_applied" if damage_applied else "replaced_modified_prevented",
                    "original_damage": original_damage,
                    "prevented_damage": prevented_damage,
                    "remaining_damage": original_damage - prevented_damage,
                    "rule_locators": list(dict.fromkeys(event["rule_locators"] + ["Core 437.1–437.4"])),
                })
            trace.append(event)
            outcomes[effect_id] = "applied" if event["outcome"] == "replaced_modified_applied" else event["outcome"]
            continue
        try:
            current, event = _apply_one(current, effect)
        except NotImplementedError as exc:
            return {
                **base,
                "valid": True,
                "committed": False,
                "unsupported": True,
                "failed_effect_index": index,
                "reason": str(exc),
                "trace": trace,
            }
        except ValueError as exc:
            return {
                **base,
                "valid": False,
                "committed": False,
                "failed_effect_index": index,
                "errors": [str(exc)],
                "trace": trace,
            }
        event.update({"index": index, "effect_id": effect_id, "before_state_hash": before_hash, "after_state_hash": hash_value(current)})
        for trigger in event.get("pending_triggers", []):
            trigger.setdefault("batch_sequence", index)
            trigger.setdefault("batch_id", f"{program['program_id']}:{effect_id}")
            trigger.setdefault("trigger_kind", "self_death")
        trace.append(event)
        outcomes[effect_id] = event["outcome"]
    return {
        **base,
        "valid": True,
        "committed": True,
        "unsupported": False,
        "next_state": current,
        "next_state_hash": hash_value(current),
        "trace": trace,
        "pending_triggers": [trigger for event in trace for trigger in event.get("pending_triggers", [])],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Chronicle typed Riftbound effect IR")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect-state")
    inspect.add_argument("state", type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("state", type=Path)
    apply.add_argument("program", type=Path)
    args = parser.parse_args()
    try:
        state = _load(args.state)
        if args.command == "inspect-state":
            errors = validate_state(state)
            output = {"valid": not errors, "errors": errors, "state_hash": hash_value(state)}
        else:
            output = apply_program(state, _load(args.program))
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
