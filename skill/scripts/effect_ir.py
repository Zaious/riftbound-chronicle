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
    "kill",
}

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
    "kill": ["Core 428"],
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
    if not isinstance(players, dict) or len(players) < 2:
        errors.append("players must be an object with at least two entries")
        players = {}
    if not isinstance(objects, dict):
        errors.append("objects must be an object")
        objects = {}
    if not isinstance(battlefields, dict):
        errors.append("battlefields must be an object")
        battlefields = {}

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
        modifiers = obj.get("might_modifiers")
        if not isinstance(modifiers, list):
            errors.append(f"objects.{object_id}.might_modifiers must be an array")
        elif any(not isinstance(item, dict) or set(item) != {"amount", "duration", "source"} for item in modifiers):
            errors.append(f"objects.{object_id}.might_modifiers has invalid entries")
        places = occupancy.get(object_id, [])
        if len(places) != 1:
            errors.append(f"object {object_id!r} must occupy exactly one zone/location, got {places}")
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
        trace.update({
            "object_id": object_id,
            "kill_mode": effect.get("kill_mode", "active"),
            "destination": destination,
            "attributed_sources": effect.get("attributed_sources", []),
            "pending_triggers": pending_triggers,
        })

    errors = validate_state(new_state)
    if errors:
        raise ValueError("effect produced invalid state: " + "; ".join(errors))
    return new_state, trace


def current_might(obj: dict[str, Any]) -> int:
    return obj["base_might"] + sum(modifier["amount"] for modifier in obj.get("might_modifiers", []))


def perform_lethal_cleanup(state: dict[str, Any], *, attributed_sources: list[str] | None = None) -> dict[str, Any]:
    base = {
        "schema_version": "riftbound-lethal-cleanup-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": hash_value(state),
    }
    errors = validate_state(state)
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "trace": []}
    lethal = []
    for object_id, obj in state["objects"].items():
        location = find_location(state, object_id)
        if obj["kind"] != "unit" or location is None or not (location[0] == "battlefield" or location[2] == "base"):
            continue
        might = current_might(obj)
        if obj["damage"] > 0 and obj["damage"] >= might:
            lethal.append((object_id, might, obj["damage"]))
    current = copy.deepcopy(state)
    trace = []
    group = [object_id for object_id, _, _ in sorted(lethal)]
    for object_id, might, damage in sorted(lethal):
        effect = {
            "op": "kill",
            "object_id": object_id,
            "kill_mode": "passive_lethal_cleanup",
            "attributed_sources": attributed_sources or [],
        }
        current, event = _apply_one(current, effect)
        event.update({
            "object_id": object_id,
            "lethal_might": might,
            "marked_damage": damage,
            "simultaneous_group": group,
            "before_state_hash": trace[-1]["after_state_hash"] if trace else hash_value(state),
            "after_state_hash": hash_value(current),
            "rule_locators": ["Core 142.4", "Core 323.3–323.5", "Core 428"],
        })
        trace.append(event)
    return {
        **base,
        "valid": True,
        "committed": True,
        "unsupported": False,
        "next_state": current,
        "next_state_hash": hash_value(current),
        "lethal_objects": group,
        "trace": trace,
        "pending_triggers": [trigger for event in trace for trigger in event.get("pending_triggers", [])],
        "coverage": "lethal_damage_slice_only",
    }


def apply_program(state: dict[str, Any], program: dict[str, Any]) -> dict[str, Any]:
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
