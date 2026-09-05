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
# ADR-0007 §3: compiled permissions that widen the valid play locations (355.2.b).
PLAY_PERMISSIONS = {"open_battlefield"}
# Keywords the state may carry on an object. `deflect` (Core 809) imposes a
# mandatory any-domain Power cost on opponents' spells that choose the object.
# ADR-0008 §5: Shield, Tank, Ganking (and Backline, required by the Tank
# contract) are characteristics printed on the object.
OBJECT_KEYWORDS = {"temporary", "deflect", "shield", "tank", "ganking", "backline"}
COMBAT_ROLES = {"attacker", "defender"}
# ADR-0007 §6–8.
TURN_EFFECT_KINDS = {"entry_state_for_played_units"}
# ADR-0008 §5: attacking_or_defending_alone reads the Unit's own designation
# and company (740.2.a); friendly_unit_defends_alone is the bounded external
# aura of the Master Yi Legend clause, carried by a might_auras entry.
CONDITION_KINDS = {"runes_at_least", "attacking_or_defending_alone"}
AURA_CONDITION_KINDS = {"friendly_unit_defends_alone"}
GRANTABLE_KEYWORDS = {"shield", "tank", "ganking", "backline"}
KEYWORD_MODIFIER_DURATIONS = {"this_combat", "this_turn"}
TRIGGER_CONDITION_KINDS = {"at_battlefield"}
DEFAULT_TURN_ID = "turn-0"
# ADR-0005 §5 named predicates. Only the cost pair is implemented; the rest are
# reserved so C-17 does not bump the program major.
PREDICATE_KINDS = ("cost_paid", "cost_not_paid", "action_performed", "action_not_performed", "requested_count_not_reached", "caused_kill", "sole_controlled_unit_at_referent_location")
IMPLEMENTED_PREDICATES = {"cost_paid", "cost_not_paid", "action_performed", "action_not_performed", "requested_count_not_reached", "sole_controlled_unit_at_referent_location"}
# Outcomes in which the *original* game action happened. A partly prevented
# deal still happened (359.3.e.14.c); a wholly prevented or replaced one did
# not (359.3.e.14.b, 205). `caused_kill` is not an in-program predicate: a
# kill by Cleanup is only known after the spell has left the chain (428.5.c),
# so it lives on `conditional_triggers` and is evaluated by the resolution
# bridge.
PERFORMED_OUTCOMES = {"applied", "replaced_modified_applied", "augmented_applied"}
# Instructions that carry a requested/applied count contract; only these may be
# referenced by requested_count_not_reached (Codex Round B, point 4).
COUNT_CONTRACT_OPS = {"channel_rune"}
CONDITIONAL_TRIGGER_KINDS = {"caused_kill"}
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
    # C-16 (ADR-0005 §6, §8): three distinct events, not one "move".
    "return_to_hand",
    "recall",
    "channel_rune",
    # C-21 (ADR-0007 §6): a "this turn" effect such as Confront's, expiring at 317.2.
    "grant_turn_effect",
    # C-22 (ADR-0007 §10): hand → trash by the discarding player's private choice.
    "discard",
    # C-24 (ADR-0007 §12): a replacement created by an effect, bound to a target's identity for this turn.
    "grant_replacement",
    "heal_all_damage",
    # C-27 (ADR-0008 §5): a granted characteristic (Shield X, Tank, ...) for this combat or this turn.
    "grant_keyword",
    # C-29 (ADR-0008 §7): two chosen Units deal their current Might to each other, simultaneously.
    "mutual_damage_current_might",
}
# Composite instructions resolved by apply_program itself (they consist of
# several Deal events that each pass through the replacement path).
COMPOSITE_OPS = {"mutual_damage_current_might"}


class ReplacementDecisionRequired(ValueError):
    def __init__(self, message: str, replacement_ids: list[str]):
        super().__init__(message)
        self.replacement_ids = replacement_ids


class IllegalOperation(ValueError):
    """A well-formed instruction the rules refuse for this object (ADR-0005 §10
    `illegal`), as opposed to a malformed one (`invalid_input`)."""


class CardSelectionRequired(ValueError):
    """A private-zone choice (Core 355.10.a) the deciding player has not made."""

    def __init__(self, message: str, decision_ids: list[str], controller: str | None):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller


class TargetDecisionRequired(ValueError):
    """A selector defers to a decision entry that was not supplied (ADR-0005 §1/§2)."""

    def __init__(self, message: str, decision_ids: list[str], controller: str | None):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller


class IllegalDecision(ValueError):
    """A well-formed supplied decision is owned by another controller."""


def object_identity(state: dict[str, Any], object_id: str) -> str | None:
    """ADR-0005 §3: identity survives board moves and changes on any transition
    to or from a non-board zone. States written before this field existed carry
    none; they are read as generation 0 without being rewritten."""
    obj = state["objects"].get(object_id)
    if obj is None:
        return None
    return obj.get("identity", f"{object_id}@0")


def battlefield_identity(state: dict[str, Any], battlefield_id: str) -> str | None:
    """ADR-0007 §4: a Battlefield is a target with a bindable identity."""
    battlefield = state["battlefields"].get(battlefield_id)
    if battlefield is None:
        return None
    return battlefield.get("identity", f"{battlefield_id}@0")


def entity_identity(state: dict[str, Any], entity_id: str) -> str | None:
    """Identity of an object or, failing that, a Battlefield."""
    return object_identity(state, entity_id) if entity_id in state["objects"] else battlefield_identity(state, entity_id)


def _bump_identity(state: dict[str, Any], object_id: str) -> str:
    current = object_identity(state, object_id) or f"{object_id}@0"
    base, _, generation = current.rpartition("@")
    nxt = f"{base or object_id}@{int(generation) + 1 if generation.isdigit() else 1}"
    state["objects"][object_id]["identity"] = nxt
    return nxt

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
    "return_to_hand": ["Core 124", "Core 124.1", "Core 446.2"],
    "recall": ["Core 455", "Core 456.1", "Core 458.1"],
    "channel_rune": ["Core 430.1", "Core 430.2.a", "Core 430.3", "Core 124"],
    "grant_turn_effect": ["Core 369.3", "Core 317.2.c"],
    "discard": ["Core 422.1", "Core 422.1.a", "Core 422.4", "Core 124"],
    "grant_replacement": ["Core 370", "Core 355.10.c", "Core 124", "Core 317.2.c"],
    "heal_all_damage": ["Core 418"],
    "grant_keyword": ["Core 814.2", "Core 466.7.c", "Core 317.2.c", "Core 124"],
    "mutual_damage_current_might": ["Core 417.1.d", "Core 417.6.b.3", "Core 417.6.b.4", "Core 143.2.b", "Core 359.3.e.5"],
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
        if "team_id" in player and (not isinstance(player["team_id"], str) or not player["team_id"]):
            errors.append(f"players.{player_id}.team_id must be a non-empty string when supplied")

    for battlefield_id, battlefield in battlefields.items():
        if not isinstance(battlefield, dict) or not isinstance(battlefield.get("objects"), list):
            errors.append(f"battlefields.{battlefield_id}.objects must be an array")
            continue
        # ADR-0007 §1: a unit entering a Battlefield its controller does not
        # control marks it contested (190.3.a.1); who contests is recorded, and
        # nothing about control transfer is inferred.
        if "contested" in battlefield and not isinstance(battlefield["contested"], bool):
            errors.append(f"battlefields.{battlefield_id}.contested must be boolean when supplied")
        if "contested_by" in battlefield and battlefield["contested_by"] is not None and battlefield["contested_by"] not in players:
            errors.append(f"battlefields.{battlefield_id}.contested_by must be a player or null")
        if battlefield.get("contested") and battlefield.get("contested_by") is None:
            errors.append(f"battlefields.{battlefield_id} is contested without contested_by")
        identity = battlefield.get("identity")
        if identity is not None and (not isinstance(identity, str) or "@" not in identity or not identity.rsplit("@", 1)[1].isdigit()):
            errors.append(f"battlefields.{battlefield_id}.identity must look like '<id>@<generation>' when supplied")
        # ADR-0008 §4: a Battlefield's own Attack / Defend triggers (Fortified
        # Position). Their controller is the Battlefield's controller at the
        # time they trigger (190.6.a), so the descriptor names none.
        for trigger_field in ("attack_triggers", "defend_triggers"):
            triggers = battlefield.get(trigger_field, [])
            if not isinstance(triggers, list):
                errors.append(f"battlefields.{battlefield_id}.{trigger_field} must be an array")
                continue
            for trigger_index, trigger in enumerate(triggers):
                if (not isinstance(trigger, dict) or set(trigger) != {"trigger_id", "controller_order", "effect_program_id", "optional_at_finalize"}
                        or not isinstance(trigger["trigger_id"], str) or not trigger["trigger_id"] or not isinstance(trigger["controller_order"], int) or trigger["controller_order"] < 0
                        or not isinstance(trigger["effect_program_id"], str) or not trigger["effect_program_id"] or not isinstance(trigger["optional_at_finalize"], bool)):
                    errors.append(f"battlefields.{battlefield_id}.{trigger_field}[{trigger_index}] must carry trigger_id, controller_order, effect_program_id, optional_at_finalize (the controller is the Battlefield's, 190.6.a)")
        ids = battlefield["objects"]
        if len(ids) != len(set(ids)):
            errors.append(f"battlefields.{battlefield_id}.objects contains duplicates")
        for object_id in ids:
            if object_id not in objects:
                errors.append(f"unknown object {object_id!r} at battlefield {battlefield_id}")
            else:
                occupancy[object_id].append(f"battlefield:{battlefield_id}")

    # The chain is one shared zone (Core 328), not a per-player zone: cards
    # played and not yet resolved sit here keyed by their timing item id.
    chain_items = state.get("chain_items", {})
    if not isinstance(chain_items, dict):
        errors.append("chain_items must be an object keyed by chain item id")
        chain_items = {}
    for item_id, entry in chain_items.items():
        if not isinstance(item_id, str) or not item_id or not isinstance(entry, dict) or set(entry) - {"card", "controller", "effect_program_id", "entry_location"} or not {"card", "controller"} <= set(entry):
            errors.append(f"chain_items.{item_id} must carry card and controller")
            continue
        location = entry.get("entry_location")
        if location is not None:
            if not isinstance(location, dict) or location.get("kind") not in {"base", "battlefield"} or set(location) - {"kind", "battlefield"}:
                errors.append(f"chain_items.{item_id}.entry_location must be {{kind: base}} or {{kind: battlefield, battlefield}}")
            elif location["kind"] == "battlefield" and location.get("battlefield") not in battlefields:
                errors.append(f"chain_items.{item_id}.entry_location names an unknown battlefield")
        if entry["controller"] not in players:
            errors.append(f"chain_items.{item_id}.controller is not a player")
        if entry["card"] not in objects:
            errors.append(f"unknown object {entry['card']!r} on the chain as {item_id}")
        else:
            occupancy[entry["card"]].append(f"chain:{item_id}")
        if "effect_program_id" in entry and (not isinstance(entry["effect_program_id"], str) or not entry["effect_program_id"]):
            errors.append(f"chain_items.{item_id}.effect_program_id must be a non-empty string when supplied")

    # ADR-0007 §8: every "this turn" effect is stamped with the turn it belongs
    # to, so an Expiration Step never clears another turn's effects.
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    if not isinstance(turn_id, str) or not turn_id:
        errors.append("turn_id must be a non-empty string when supplied")
    turn_effects = state.get("turn_effects", [])
    if not isinstance(turn_effects, list):
        errors.append("turn_effects must be an array")
        turn_effects = []
    effect_ids: set[str] = set()
    for index, effect in enumerate(turn_effects):
        label = f"turn_effects[{index}]"
        if not isinstance(effect, dict) or not {"effect_id", "kind", "controller", "turn_id"} <= set(effect) or set(effect) - {"effect_id", "kind", "controller", "turn_id", "value", "source"}:
            errors.append(f"{label} must carry effect_id, kind, controller, turn_id (and value/source)")
            continue
        if not isinstance(effect["effect_id"], str) or not effect["effect_id"] or effect["effect_id"] in effect_ids:
            errors.append(f"{label}.effect_id is invalid or duplicated")
        effect_ids.add(effect.get("effect_id", ""))
        if effect["controller"] not in players:
            errors.append(f"{label}.controller is not a player")
        if not isinstance(effect["turn_id"], str) or not effect["turn_id"]:
            errors.append(f"{label}.turn_id must be a non-empty string")
        if effect["kind"] == "entry_state_for_played_units" and effect.get("value") not in {"ready", "exhausted"}:
            errors.append(f"{label}.value must be ready or exhausted")
    # ADR-0007 §5: Bonus Damage sources. A source is an object (active while on
    # the board) or a Battlefield (active while it exists) — never pruned by the
    # object rule.
    modifiers = state.get("damage_modifiers", [])
    if not isinstance(modifiers, list):
        errors.append("damage_modifiers must be an array")
        modifiers = []
    modifier_ids: set[str] = set()
    for index, modifier in enumerate(modifiers):
        label = f"damage_modifiers[{index}]"
        if not isinstance(modifier, dict) or set(modifier) != {"modifier_id", "source_object", "controller", "amount", "scope"}:
            errors.append(f"{label} must carry exactly modifier_id, source_object, controller, amount, scope")
            continue
        if not isinstance(modifier["modifier_id"], str) or not modifier["modifier_id"] or modifier["modifier_id"] in modifier_ids:
            errors.append(f"{label}.modifier_id is invalid or duplicated")
        modifier_ids.add(modifier.get("modifier_id", ""))
        if modifier["source_object"] not in objects and modifier["source_object"] not in battlefields:
            errors.append(f"{label}.source_object is neither an object nor a battlefield")
        if modifier["controller"] not in players:
            errors.append(f"{label}.controller is not a player")
        if not isinstance(modifier["amount"], int) or modifier["amount"] < 1:
            errors.append(f"{label}.amount must be a positive integer (Core 714.1)")
        scope = modifier["scope"]
        if not isinstance(scope, dict) or not isinstance(scope.get("kind"), str):
            errors.append(f"{label}.scope must carry a kind")
        elif scope["kind"] == "location" and (set(scope) != {"kind", "battlefield"} or scope.get("battlefield") not in battlefields):
            errors.append(f"{label}.scope.location must name a known battlefield")
        elif scope["kind"] == "controller_sources" and set(scope) != {"kind"}:
            errors.append(f"{label}.scope.controller_sources carries no other fields")

    # ADR-0008 §5: bounded external Might auras (a source on the board or a
    # Battlefield; a named condition read by effective_might).
    auras = state.get("might_auras", [])
    if not isinstance(auras, list):
        errors.append("might_auras must be an array")
        auras = []
    aura_ids: set[str] = set()
    for index, aura in enumerate(auras):
        label = f"might_auras[{index}]"
        if not isinstance(aura, dict) or set(aura) != {"modifier_id", "source_object", "controller", "amount", "condition"}:
            errors.append(f"{label} must carry exactly modifier_id, source_object, controller, amount, condition")
            continue
        if not isinstance(aura["modifier_id"], str) or not aura["modifier_id"] or aura["modifier_id"] in aura_ids:
            errors.append(f"{label}.modifier_id is invalid or duplicated")
        aura_ids.add(aura.get("modifier_id", ""))
        if aura["source_object"] not in objects and aura["source_object"] not in battlefields:
            errors.append(f"{label}.source_object is neither an object nor a battlefield")
        if aura["controller"] not in players:
            errors.append(f"{label}.controller is not a player")
        if not isinstance(aura["amount"], int) or isinstance(aura["amount"], bool):
            errors.append(f"{label}.amount must be an integer")
        if not isinstance(aura["condition"], dict) or aura["condition"].get("kind") not in AURA_CONDITION_KINDS or set(aura["condition"]) != {"kind"}:
            errors.append(f"{label}.condition.kind must be one of {sorted(AURA_CONDITION_KINDS)}")

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
        # ADR-0008 §1: a Unit's current Combat designation, kept in step by Cleanup (323.2).
        designation = obj.get("combat_designation")
        if designation is not None and (not isinstance(designation, dict) or set(designation) != {"combat_id", "role"} or not isinstance(designation["combat_id"], str)
                                        or not designation["combat_id"] or designation["role"] not in COMBAT_ROLES):
            errors.append(f"objects.{object_id}.combat_designation must be {{combat_id, role: attacker|defender}}")
        elif designation is not None and obj.get("kind") != "unit":
            errors.append(f"objects.{object_id}.combat_designation applies to Units only (464.2.c.3)")
        if "shield_value" in obj and (not isinstance(obj["shield_value"], int) or isinstance(obj["shield_value"], bool) or obj["shield_value"] < 1):
            errors.append(f"objects.{object_id}.shield_value must be a positive integer (Core 814.1.b)")
        # Typed trigger lists: death (self-death, 808), play (419.4.a), move (383.1),
        # end of turn (317.1), attack / defend (383.4.e–f).
        for trigger_field in ("death_triggers", "play_triggers", "move_triggers", "end_of_turn_triggers", "attack_triggers", "defend_triggers"):
            triggers = obj.get(trigger_field, [])
            if not isinstance(triggers, list):
                errors.append(f"objects.{object_id}.{trigger_field} must be an array")
                continue
            for trigger_index, trigger in enumerate(triggers):
                required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize"}
                if not isinstance(trigger, dict) or not required.issubset(trigger):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}] has invalid shape")
                elif trigger.get("source_object") != object_id or trigger.get("controller") not in players:
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}] has invalid source/controller")
                elif not isinstance(trigger.get("effect_program_id"), str) or not trigger.get("effect_program_id") or not isinstance(trigger.get("optional_at_finalize"), bool):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}] has invalid program/optional binding")
                elif "condition" in trigger and (not isinstance(trigger["condition"], dict) or trigger["condition"].get("kind") not in TRIGGER_CONDITION_KINDS):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].condition.kind must be one of {sorted(TRIGGER_CONDITION_KINDS)} (Core 383.2.a.1)")
        entry_ids: set[str] = set()
        for r_index, replacement in enumerate(obj.get("entry_replacements", []) or []):
            if not isinstance(replacement, dict) or replacement.get("mode") != "entry_state" or replacement.get("value") not in {"ready", "exhausted"} or set(replacement) - {"replacement_id", "mode", "value"}:
                errors.append(f"objects.{object_id}.entry_replacements[{r_index}] must be {{replacement_id?, mode: entry_state, value: ready|exhausted}}")
            elif "replacement_id" in replacement and (not isinstance(replacement["replacement_id"], str) or not replacement["replacement_id"] or replacement["replacement_id"] in entry_ids):
                errors.append(f"objects.{object_id}.entry_replacements[{r_index}].replacement_id is invalid or duplicated")
            elif "replacement_id" in replacement:
                entry_ids.add(replacement["replacement_id"])
        seen_conditional: set[str] = set()
        for c_index, conditional in enumerate(obj.get("conditional_might", []) or []):
            label = f"objects.{object_id}.conditional_might[{c_index}]"
            if not isinstance(conditional, dict) or set(conditional) != {"modifier_id", "amount", "condition"} or not isinstance(conditional["amount"], int):
                errors.append(f"{label} must carry modifier_id, amount, condition")
                continue
            if not isinstance(conditional["modifier_id"], str) or not conditional["modifier_id"] or conditional["modifier_id"] in seen_conditional:
                errors.append(f"{label}.modifier_id is invalid or duplicated")
            seen_conditional.add(conditional.get("modifier_id", ""))
            condition = conditional["condition"]
            if not isinstance(condition, dict) or condition.get("kind") not in CONDITION_KINDS:
                errors.append(f"{label}.condition.kind must be one of {sorted(CONDITION_KINDS)}")
            elif condition["kind"] == "runes_at_least" and (set(condition) != {"kind", "count"} or not isinstance(condition["count"], int) or condition["count"] < 0):
                errors.append(f"{label}.condition.runes_at_least needs a non-negative count")
            elif condition["kind"] == "attacking_or_defending_alone" and set(condition) != {"kind"}:
                errors.append(f"{label}.condition.attacking_or_defending_alone carries no other fields")
        # ADR-0008 §5: granted characteristics, each bound to the object identity
        # it was granted to and to the Combat or turn it lasts for.
        seen_keyword_modifiers: set[str] = set()
        for k_index, modifier in enumerate(obj.get("keyword_modifiers", []) or []):
            label = f"objects.{object_id}.keyword_modifiers[{k_index}]"
            if not isinstance(modifier, dict) or {"modifier_id", "keyword", "source", "duration", "target_identity"} - set(modifier) or set(modifier) - {"modifier_id", "keyword", "value", "source", "duration", "combat_id", "turn_id", "target_identity"}:
                errors.append(f"{label} must carry modifier_id, keyword, source, duration, target_identity (and value, combat_id or turn_id)")
                continue
            if not isinstance(modifier["modifier_id"], str) or not modifier["modifier_id"] or modifier["modifier_id"] in seen_keyword_modifiers:
                errors.append(f"{label}.modifier_id is invalid or duplicated")
            seen_keyword_modifiers.add(modifier.get("modifier_id", ""))
            if modifier["keyword"] not in GRANTABLE_KEYWORDS:
                errors.append(f"{label}.keyword must be one of {sorted(GRANTABLE_KEYWORDS)}")
            if "value" in modifier and (not isinstance(modifier["value"], int) or isinstance(modifier["value"], bool) or modifier["value"] < 1):
                errors.append(f"{label}.value must be a positive integer (Core 814.1.b)")
            if not isinstance(modifier["source"], str) or not modifier["source"]:
                errors.append(f"{label}.source must be a non-empty string")
            if modifier["duration"] not in KEYWORD_MODIFIER_DURATIONS:
                errors.append(f"{label}.duration must be one of {sorted(KEYWORD_MODIFIER_DURATIONS)}")
            elif modifier["duration"] == "this_combat" and (not isinstance(modifier.get("combat_id"), str) or not modifier.get("combat_id") or "turn_id" in modifier):
                errors.append(f"{label}: a this_combat grant carries its combat_id (466.7.c)")
            elif modifier["duration"] == "this_turn" and (not isinstance(modifier.get("turn_id"), str) or not modifier.get("turn_id") or "combat_id" in modifier):
                errors.append(f"{label}: a this_turn grant carries its turn_id (317.2.c)")
            if not isinstance(modifier["target_identity"], str) or "@" not in modifier["target_identity"]:
                errors.append(f"{label}.target_identity must be an identity token")
        deflect_value = obj.get("deflect_value")
        if deflect_value is not None and (not isinstance(deflect_value, int) or deflect_value < 1):
            errors.append(f"objects.{object_id}.deflect_value must be a positive integer (Core 809.1.b)")
        permissions = obj.get("play_permissions", [])
        if not isinstance(permissions, list) or len(permissions) != len(set(permissions)) or any(p not in PLAY_PERMISSIONS for p in permissions):
            errors.append(f"objects.{object_id}.play_permissions must be a unique array drawn from {sorted(PLAY_PERMISSIONS)}")
        if not isinstance(obj.get("is_token", False), bool):
            errors.append(f"objects.{object_id}.is_token must be boolean when supplied")
        identity = obj.get("identity")
        if identity is not None and (not isinstance(identity, str) or "@" not in identity or not identity.rsplit("@", 1)[1].isdigit()):
            errors.append(f"objects.{object_id}.identity must look like '<id>@<generation>' when supplied")
        keywords = obj.get("keywords", [])
        if not isinstance(keywords, list) or len(keywords) != len(set(keywords)) or any(keyword not in OBJECT_KEYWORDS for keyword in keywords):
            errors.append(f"objects.{object_id}.keywords must be a unique supported-keyword array")
        modifiers = obj.get("might_modifiers")
        if not isinstance(modifiers, list):
            errors.append(f"objects.{object_id}.might_modifiers must be an array")
        elif any(not isinstance(item, dict) or not {"amount", "duration", "source"} <= set(item) or set(item) - {"amount", "duration", "source", "turn_id"}
                 or ("turn_id" in item and (not isinstance(item["turn_id"], str) or not item["turn_id"])) for item in modifiers):
            errors.append(f"objects.{object_id}.might_modifiers has invalid entries (amount, duration, source, optional turn_id)")
        places = occupancy.get(object_id, [])
        if len(places) != 1:
            errors.append(f"object {object_id!r} must occupy exactly one zone/location, got {places}")
    replacement_ids: set[str] = set()
    for index, replacement in enumerate(replacements):
        label = f"replacement_effects[{index}]"
        required = {"replacement_id", "controller", "mode", "event_op", "optional", "uses_remaining"}
        if not isinstance(replacement, dict) or not required.issubset(replacement):
            errors.append(f"{label} has invalid shape")
            continue
        replacement_id = replacement.get("replacement_id")
        if not isinstance(replacement_id, str) or not replacement_id or replacement_id in replacement_ids:
            errors.append(f"{label}.replacement_id is invalid or duplicated")
        else:
            replacement_ids.add(replacement_id)
        # ADR-0007 §12: a replacement is either source-backed (a permanent's own
        # ability, active while it is on the board) or granted by an effect to
        # one object's identity for this turn — exactly one of the two.
        source_backed, granted = "source_object" in replacement, "granted" in replacement
        if source_backed == granted:
            errors.append(f"{label} must be exactly one of source-backed (source_object) or granted (granted)")
            continue
        if replacement.get("controller") not in players:
            errors.append(f"{label} has unknown controller")
        if source_backed:
            if replacement.get("source_object") not in objects:
                errors.append(f"{label} has unknown source")
            elif objects[replacement["source_object"]].get("controller") != replacement.get("controller"):
                errors.append(f"{label}.controller must control its source object")
        else:
            grant = replacement["granted"]
            if not isinstance(grant, dict) or set(grant) != {"target_object", "target_identity", "duration", "turn_id", "granted_by"}:
                errors.append(f"{label}.granted must carry target_object, target_identity, duration, turn_id, granted_by")
            else:
                if grant["target_object"] not in objects:
                    errors.append(f"{label}.granted.target_object is unknown")
                if not isinstance(grant["target_identity"], str) or "@" not in grant["target_identity"]:
                    errors.append(f"{label}.granted.target_identity must be an identity token")
                if grant["duration"] != "this_turn":
                    errors.append(f"{label}.granted.duration must be this_turn")
                if not isinstance(grant["turn_id"], str) or not grant["turn_id"] or not isinstance(grant["granted_by"], str) or not grant["granted_by"]:
                    errors.append(f"{label}.granted needs turn_id and granted_by")
                if replacement.get("uses_remaining") != 1:
                    errors.append(f"{label} granted replacements apply once (uses_remaining 1)")
                if replacement.get("target_object_id") != grant["target_object"]:
                    errors.append(f"{label}.target_object_id must equal granted.target_object")
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
        if "source_object" in replacement:
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
    errors.extend(_receipt_errors(program.get("cost_receipt")))
    conditional = program.get("conditional_triggers")
    if conditional is not None:
        effect_ids = {e.get("effect_id", f"effect-{i}") for i, e in enumerate(program.get("effects") or []) if isinstance(e, dict)}
        if not isinstance(conditional, list):
            errors.append("conditional_triggers must be an array")
        else:
            required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize", "condition"}
            ids: set[str] = set()
            for i, ct in enumerate(conditional):
                if not isinstance(ct, dict) or not required <= set(ct) or set(ct) - required:
                    errors.append(f"conditional_triggers[{i}] must carry exactly {sorted(required)}")
                    continue
                if not isinstance(ct["trigger_id"], str) or not ct["trigger_id"] or ct["trigger_id"] in ids:
                    errors.append(f"conditional_triggers[{i}].trigger_id is invalid or duplicated")
                ids.add(ct.get("trigger_id", ""))
                cond = ct["condition"]
                if not isinstance(cond, dict) or cond.get("kind") not in CONDITIONAL_TRIGGER_KINDS or set(cond) != {"kind", "effect_id"}:
                    errors.append(f"conditional_triggers[{i}].condition must be {{kind: caused_kill, effect_id}}")
                elif cond["effect_id"] not in effect_ids:
                    errors.append(f"conditional_triggers[{i}].condition.effect_id {cond['effect_id']!r} is not an instruction of this program")
                if not isinstance(ct["optional_at_finalize"], bool) or not isinstance(ct["controller_order"], int) or ct["controller_order"] < 0:
                    errors.append(f"conditional_triggers[{i}] optional_at_finalize/controller_order are invalid")
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
            predicate = effect.get("predicate")
            if predicate is not None:
                errors.extend(f"effects[{index}].predicate {e}" for e in _predicate_errors(predicate, program.get("cost_receipt"), seen, {e.get("effect_id", f"effect-{i}"): e for i, e in enumerate(effects[:index]) if isinstance(e, dict)}))
            if effect.get("op") == "mutual_damage_current_might":
                units = effect.get("units")
                if not isinstance(units, list) or len(units) != 2:
                    errors.append(f"effects[{index}].mutual_damage_current_might needs exactly two unit selectors")
                else:
                    for j, sel in enumerate(units):
                        errors.extend(f"effects[{index}].units[{j}] {e}" for e in _selector_errors(sel))
                if effect.get("target") is not None or effect.get("targets") is not None or effect.get("object_id") is not None or effect.get("affected") is not None:
                    errors.append(f"effects[{index}].mutual_damage_current_might carries its two units, not target/targets/object_id/affected")
            if effect.get("op") == "grant_keyword":
                if effect.get("keyword") not in GRANTABLE_KEYWORDS:
                    errors.append(f"effects[{index}].grant_keyword.keyword must be one of {sorted(GRANTABLE_KEYWORDS)}")
                if effect.get("duration") not in KEYWORD_MODIFIER_DURATIONS:
                    errors.append(f"effects[{index}].grant_keyword.duration must be one of {sorted(KEYWORD_MODIFIER_DURATIONS)}")
                if "value" in effect and (not isinstance(effect["value"], int) or isinstance(effect["value"], bool) or effect["value"] < 1):
                    errors.append(f"effects[{index}].grant_keyword.value must be a positive integer")
                if not isinstance(effect.get("source"), str) or not effect.get("source"):
                    errors.append(f"effects[{index}].grant_keyword requires a source")
            if effect.get("op") == "discard":
                if not isinstance(effect.get("player"), str) or not isinstance(effect.get("count"), int) or effect.get("count", 0) < 1:
                    errors.append(f"effects[{index}].discard requires player and a positive count")
                if "decision_ref" in effect and (not isinstance(effect["decision_ref"], str) or not effect["decision_ref"]):
                    errors.append(f"effects[{index}].discard.decision_ref must be a non-empty string")
                if effect.get("target") is not None or effect.get("targets") is not None or effect.get("objects") is not None:
                    errors.append(f"effects[{index}].discard is not a targeted instruction (Core 355.10.a) and resolves its own selection")
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
                errors.extend(f"effects[{index}].target {e}" for e in _selector_errors(target))
            affected = effect.get("affected")
            if affected is not None:
                criteria = affected.get("criteria") if isinstance(affected, dict) else None
                if not isinstance(affected, dict) or set(affected) != {"criteria"} or not isinstance(criteria, dict) or set(criteria) - {"kind", "controller_relation", "location"} or "location" not in criteria:
                    errors.append(f"effects[{index}].affected must be {{criteria: {{location, kind?, controller_relation?}}}}")
                else:
                    if criteria["location"] not in {"target_battlefield", "any_battlefield", "active_combat"}:
                        errors.append(f"effects[{index}].affected.criteria.location is invalid")
                    if criteria["location"] == "active_combat" and target is not None:
                        errors.append(f"effects[{index}].affected over active_combat targets nothing (Core 355.10.d, 740.2.c)")
                    if "kind" in criteria and criteria["kind"] not in {"unit", "gear"}:
                        errors.append(f"effects[{index}].affected.criteria.kind is invalid")
                    if "controller_relation" in criteria and criteria["controller_relation"] not in {"friendly", "enemy"}:
                        errors.append(f"effects[{index}].affected.criteria.controller_relation is invalid")
                    if criteria["location"] == "target_battlefield" and (not isinstance(target, dict) or target.get("kind") != "battlefield"):
                        errors.append(f"effects[{index}].affected over target_battlefield needs a battlefield target")
                    if criteria["location"] == "any_battlefield" and target is not None:
                        errors.append(f"effects[{index}].affected over any_battlefield targets nothing (Core 355.10.b)")
                if effect.get("op") not in MULTI_TARGET_OPS:
                    errors.append(f"effects[{index}].affected is not supported for {effect.get('op')!r}")
                if effect.get("targets") is not None or effect.get("object_id") is not None:
                    errors.append(f"effects[{index}].affected excludes targets and object_id")
            targets = effect.get("targets")
            if targets is not None:
                if target is not None:
                    errors.append(f"effects[{index}] may carry target or targets, not both")
                if effect.get("op") not in MULTI_TARGET_OPS:
                    errors.append(f"effects[{index}].targets is not supported for {effect.get('op')!r}")
                if not isinstance(targets, dict) or set(targets) - {"selectors", "decision_ref", "min", "max", "restrictions"} or not {"min", "max"} <= set(targets):
                    errors.append(f"effects[{index}].targets must carry min, max, and selectors or decision_ref")
                else:
                    if not isinstance(targets["min"], int) or not isinstance(targets["max"], int) or targets["min"] < 0 or targets["max"] < max(1, targets["min"]):
                        errors.append(f"effects[{index}].targets.min/max are invalid")
                    if ("selectors" in targets) == ("decision_ref" in targets):
                        errors.append(f"effects[{index}].targets needs exactly one of selectors or decision_ref")
                    for j, sel in enumerate(targets.get("selectors", []) or []):
                        errors.extend(f"effects[{index}].targets.selectors[{j}] {e}" for e in _selector_errors(sel))
                    if "selectors" in targets and len(targets["selectors"]) > targets["max"]:
                        errors.append(f"effects[{index}].targets has more selectors than max")
                    if "decision_ref" in targets and (not isinstance(targets["decision_ref"], str) or not targets["decision_ref"]):
                        errors.append(f"effects[{index}].targets.decision_ref must be non-empty")
            seen.add(effect_id)
    return errors


MULTI_TARGET_OPS = {"deal_damage", "heal_damage", "ready", "exhaust", "move_board_object", "kill", "modify_might", "recycle_one", "return_to_hand", "recall", "grant_replacement", "heal_all_damage", "grant_keyword"}
SELECTOR_FIELDS = {"object_id", "bound_object_id", "bound_identity", "chosen_zone_class", "kind", "location", "controller_relation", "zone_owner_relation", "targeted", "decision_ref", "max_might"}


def derive_targeted(selector: dict[str, Any]) -> bool:
    """ADR-0005 §1: target status is compiled from the selector, never set by the caller.
    A chosen object in a public zone (the board, or a public non-board zone such as
    the trash) is a target; a choice from a non-public zone is not (Core 355.10.a)."""
    if selector.get("chosen_zone_class") == "board":
        return True
    return selector.get("location") in {"trash", "banishment"}


def _selector_errors(selector: Any) -> list[str]:
    if not isinstance(selector, dict):
        return ["must be an object"]
    errors = []
    if set(selector) - SELECTOR_FIELDS:
        errors.append(f"has unsupported fields {sorted(set(selector) - SELECTOR_FIELDS)}")
    if "decision_ref" in selector:
        if not isinstance(selector["decision_ref"], str) or not selector["decision_ref"]:
            errors.append("decision_ref must be non-empty")
    elif not isinstance(selector.get("object_id"), str) or not selector.get("object_id"):
        errors.append("must identify an object or defer to a decision_ref")
    if selector.get("chosen_zone_class") not in {"board", "non_board"}:
        errors.append("chosen_zone_class is required")
    if "location" in selector and selector["location"] not in {"board", "battlefield", "base", "non_board", "main_deck", "hand", "trash", "banishment", "rune_deck", "chain"}:
        errors.append("location is invalid")
    if "controller_relation" in selector and selector["controller_relation"] not in {"friendly", "enemy"}:
        errors.append("controller_relation is invalid")
    if "zone_owner_relation" in selector and selector["zone_owner_relation"] not in {"own", "opponent"}:
        errors.append("zone_owner_relation is invalid")
    if "targeted" in selector and selector["targeted"] != derive_targeted(selector):
        errors.append("targeted is derived from the selector and cannot be overridden")
    if "bound_identity" in selector and (not isinstance(selector["bound_identity"], str) or "@" not in selector["bound_identity"]):
        errors.append("bound_identity must be an identity token")
    if "max_might" in selector and (not isinstance(selector["max_might"], int) or selector["max_might"] < 0):
        errors.append("max_might must be a non-negative integer")
    return errors


def _receipt_errors(receipt: Any) -> list[str]:
    if receipt is None:
        return []
    from cost_receipt import validate_cost_receipt  # standalone module; no cycle
    return [f"cost_receipt {e}" for e in validate_cost_receipt(receipt)]


def _predicate_errors(predicate: Any, receipt: Any, earlier: set[str] | None = None, earlier_effects: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """ADR-0005 §5: named predicates, not one ambiguous negative dependency.
    A cost predicate must name a component of the program's receipt; an
    action predicate must name an earlier instruction; an unknown id is
    invalid_input. Recognized-but-unimplemented kinds validate here and
    answer `unsupported` at execution."""
    if not isinstance(predicate, dict) or predicate.get("kind") not in PREDICATE_KINDS or set(predicate) - {"kind", "cost_id", "effect_id"}:
        return ["must carry a known kind"]
    if predicate["kind"] in {"cost_paid", "cost_not_paid"}:
        if not isinstance(predicate.get("cost_id"), str) or not predicate["cost_id"]:
            return ["cost_id is required for cost predicates"]
        if receipt is None:
            return ["needs the program's cost_receipt"]
        if predicate["cost_id"] not in {c.get("cost_id") for c in receipt.get("components", [])}:
            return [f"cost_id {predicate['cost_id']!r} is not on the receipt"]
    else:
        if not isinstance(predicate.get("effect_id"), str) or not predicate["effect_id"]:
            return ["effect_id is required for action predicates"]
        if earlier is not None and predicate["effect_id"] not in earlier:
            return [f"effect_id {predicate['effect_id']!r} must reference an earlier instruction"]
        if predicate["kind"] == "requested_count_not_reached" and earlier_effects is not None:
            referenced = earlier_effects.get(predicate["effect_id"], {})
            if referenced.get("op") not in COUNT_CONTRACT_OPS and not isinstance(referenced.get("targets"), dict):
                return [f"requested_count_not_reached may only reference an instruction with a count contract (channel_rune or bounded targets); {predicate['effect_id']!r} is {referenced.get('op')!r}"]
    return []


def action_performed(event: dict[str, Any]) -> bool:
    """Did the original game action of this instruction happen (359.3.e.14.b, 205)?"""
    return event.get("outcome") in PERFORMED_OUTCOMES


def sole_controlled_unit_at_referent_location(state: dict[str, Any], controller: str | None, event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """ADR-0007 §9 (En Garde): the earlier instruction's legal referent must be
    the only unit its controller — the effect's controller, teammates
    excluded — controls at the referent's current location."""
    referent = event.get("object_id") if action_performed(event) else None
    if not isinstance(referent, str) or referent not in state["objects"]:
        return False, {"referent": None, "reason": "no legal referent"}
    location = find_location(state, referent)
    if location is None:
        return False, {"referent": referent, "reason": "referent has no location"}
    if location[0] == "battlefield":
        present = list(state["battlefields"][location[1]]["objects"])
    else:
        present = list(state["players"][location[1]]["zones"][location[2]])
    controlled = [o for o in present if state["objects"][o].get("kind") == "unit" and state["objects"][o].get("controller") == controller]
    holds = controlled == [referent]
    return holds, {"referent": referent, "location": location, "controlled_units_there": controlled}


def evaluate_predicate(predicate: dict[str, Any], receipt: dict[str, Any] | None, events: dict[str, dict[str, Any]] | None = None, state: dict[str, Any] | None = None, controller: str | None = None) -> tuple[bool | None, list[str]]:
    """Returns (holds, locators); holds is None when the kind is not implemented."""
    kind = predicate["kind"]
    if kind not in IMPLEMENTED_PREDICATES:
        return None, []
    if kind in {"cost_paid", "cost_not_paid"}:
        component = next(c for c in receipt["components"] if c["cost_id"] == predicate["cost_id"])
        paid = bool(component["paid"])
        return (paid if kind == "cost_paid" else not paid), ["Core 356.4.f.1", "Core 356.2.b.1"]
    event = (events or {}).get(predicate["effect_id"])
    if event is None:
        return False, ["Core 359.3.e.14.a"]
    if kind == "action_performed":
        return action_performed(event), ["Core 359.3.e.14.b", "Core 359.3.e.14.c", "Core 205"]
    if kind == "action_not_performed":
        return not action_performed(event), ["Core 359.3.e.14.b", "Core 205"]
    if kind == "sole_controlled_unit_at_referent_location":
        holds, _ = sole_controlled_unit_at_referent_location(state or {}, controller, event)
        return holds, ["Core 135.2.b.5.a", "Core 359.3.e.14.a"]
    # requested_count_not_reached: "If you couldn't" tests actual < requested
    # (430.5); an instruction that did not happen at all also did not reach it.
    requested = event.get("requested_count", event.get("requested_targets"))
    applied = event.get("applied_count", event.get("applied_targets"))
    if not (isinstance(requested, int) and isinstance(applied, int)):
        # validate_program keeps this unreachable for well-formed programs; a
        # referenced event without counts is a malformed program, never a guess.
        raise ValueError(f"requested_count_not_reached references {predicate['effect_id']!r}, whose event carries no count contract")
    return applied < requested, ["Core 430.3", "Core 430.5", "Core 055"]


BONUS_SCOPES = {"controller_sources", "location"}


def bonus_damage(state: dict[str, Any], controller: str | None, object_id: str | None) -> tuple[int, list[dict[str, Any]]]:
    """Core 713–715: every active Bonus Damage that applies to this Deal,
    summed once (714). `controller_sources` follows the spell's or ability's
    controller; `location` follows the affected unit's current Battlefield.
    An inactive source contributes nothing; an unknown scope is a mechanic
    the engine does not have."""
    total = 0
    sources: list[dict[str, Any]] = []
    location = find_location(state, object_id) if object_id is not None else None
    for modifier in state.get("damage_modifiers", []) or []:
        source = modifier["source_object"]
        active = (source in state["battlefields"]) or zone_class(find_location(state, source)) == "board"
        if not active:
            continue
        kind = modifier["scope"]["kind"]
        if kind not in BONUS_SCOPES:
            raise NotImplementedError(f"Bonus Damage scope {kind!r} is not modelled")
        if kind == "controller_sources" and modifier["controller"] != controller:
            continue
        if kind == "location" and not (location is not None and location[0] == "battlefield" and location[1] == modifier["scope"]["battlefield"]):
            continue
        total += modifier["amount"]
        sources.append({"modifier_id": modifier["modifier_id"], "source_object": source, "amount": modifier["amount"], "scope": dict(modifier["scope"])})
    return total, sources


def same_side(state: dict[str, Any], left: str | None, right: str | None) -> bool:
    """Module-level friendliness for criteria expansion: the same player, or the
    same declared team_id (2v2)."""
    if left is None or right is None:
        return False
    if left == right:
        return True
    left_team = state["players"].get(left, {}).get("team_id")
    right_team = state["players"].get(right, {}).get("team_id")
    return left_team is not None and left_team == right_team


def find_location(state: dict[str, Any], object_id: str) -> tuple[str, str, str | None] | None:
    for player_id, player in state["players"].items():
        for zone, ids in player["zones"].items():
            if object_id in ids:
                return ("player", player_id, zone)
    for battlefield_id, battlefield in state["battlefields"].items():
        if object_id in battlefield["objects"]:
            return ("battlefield", battlefield_id, None)
    for item_id, entry in (state.get("chain_items") or {}).items():
        if entry.get("card") == object_id:
            return ("chain", item_id, None)
    return None


def zone_class(location: tuple[str, str, str | None] | None) -> str | None:
    if location is None:
        return None
    if location[0] == "battlefield" or location[2] == "base":
        return "board"
    return "non_board"


def evaluate_target(state: dict[str, Any], target: dict[str, Any], controller: str | None) -> tuple[bool, str]:
    object_id = target["object_id"]
    if target.get("kind") == "battlefield":
        # ADR-0007 §4: "all units at a battlefield" targets the Battlefield
        # (355.10.b), which has a bindable identity like any target.
        if object_id not in state["battlefields"]:
            return False, "target_battlefield_missing"
        if target.get("chosen_zone_class") != "board":
            return False, "target_changed_board_zone_class"
        bound = target.get("bound_identity")
        if bound is not None and battlefield_identity(state, object_id) != bound:
            return False, "target_identity_changed"
        return True, "ok"
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
    if required_location == "board" and current_class != "board":
        return False, "target_location_requirement_failed"
    if required_location == "non_board" and current_class != "non_board":
        return False, "target_location_requirement_failed"
    if required_location in PLAYER_ZONES - {"base"} and (location is None or location[0] != "player" or location[2] != required_location):
        return False, "target_location_requirement_failed"
    def friendly_players(left: str | None, right: str | None) -> bool:
        if left is None or right is None:
            return False
        if left == right:
            return True
        left_team = state["players"].get(left, {}).get("team_id")
        right_team = state["players"].get(right, {}).get("team_id")
        return bool(left_team and right_team and left_team == right_team)
    relation = target.get("controller_relation")
    if relation is not None and controller not in state["players"]:
        return False, "target_controller_context_missing"
    if relation == "friendly" and not friendly_players(controller, obj.get("controller")):
        return False, "target_controller_requirement_failed"
    if relation == "enemy" and friendly_players(controller, obj.get("controller")):
        return False, "target_controller_requirement_failed"
    zone_owner_relation = target.get("zone_owner_relation")
    if zone_owner_relation is not None and controller not in state["players"]:
        return False, "target_controller_context_missing"
    zone_owner = location[1] if location is not None and location[0] == "player" else None
    if zone_owner_relation == "own" and zone_owner != controller:
        return False, "target_zone_owner_requirement_failed"
    if zone_owner_relation == "opponent" and friendly_players(controller, zone_owner):
        return False, "target_zone_owner_requirement_failed"
    if target.get("object_id") != target.get("bound_object_id", target.get("object_id")):
        return False, "target_identity_changed"
    # ADR-0005 §3 / Core 359.3.e.4: the same physical card back in the same zone
    # is a different object once it has been through a non-board zone.
    bound = target.get("bound_identity")
    if bound is not None and object_identity(state, object_id) != bound:
        return False, "target_identity_changed"
    max_might = target.get("max_might")
    if max_might is not None and effective_might(state, object_id) > max_might:
        return False, "target_might_requirement_failed"
    return True, "ok"


def _remove_from_location(state: dict[str, Any], object_id: str) -> None:
    location = find_location(state, object_id)
    if location is None:
        raise ValueError(f"object {object_id!r} has no location")
    if location[0] == "player":
        state["players"][location[1]]["zones"][location[2]].remove(object_id)
    elif location[0] == "chain":
        del state["chain_items"][location[1]]
    else:
        state["battlefields"][location[1]]["objects"].remove(object_id)


def replacement_active(state: dict[str, Any], replacement: dict[str, Any]) -> bool:
    """Source-backed: the source is on the board. Granted: the target still
    exists on the board with the identity it had when granted (ADR-0007 §12);
    a used-up granted replacement is gone."""
    if "granted" in replacement:
        grant = replacement["granted"]
        target = grant["target_object"]
        if replacement.get("uses_remaining") == 0:
            return False
        if grant.get("duration") == "this_turn" and grant.get("turn_id") != state.get("turn_id", DEFAULT_TURN_ID):
            return False
        return (target in state["objects"] and zone_class(find_location(state, target)) == "board"
                and object_identity(state, target) == grant["target_identity"])
    return zone_class(find_location(state, replacement["source_object"])) == "board"


def _prune_inactive_replacements(state: dict[str, Any]) -> list[str]:
    removed = []
    active = []
    for replacement in state["replacement_effects"]:
        if replacement_active(state, replacement):
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
        if "granted" in replacement and not replacement_active(state, replacement):
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
        for object_id in drawn:
            _bump_identity(new_state, object_id)
        trace["objects"] = drawn
        trace["identities_after"] = {object_id: object_identity(new_state, object_id) for object_id in drawn}
        trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 124"]))

    elif op == "recycle_one":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("recycle_one requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
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
            source_zone = source[2] if source and source[0] == "player" else None
            if source is not None and (source[0] == "battlefield" or source_zone != destination):
                trace["identity_after"] = _bump_identity(new_state, object_id)
                trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 124"]))

    elif op == "move_board_object":
        object_id, destination = effect.get("object_id"), effect.get("destination")
        if object_id not in new_state["objects"] or not isinstance(destination, dict):
            raise ValueError("move_board_object requires a known object and destination")
        source = find_location(new_state, object_id)
        if source is None or not (source[0] == "battlefield" or source[2] == "base"):
            raise ValueError("Move applies only between board locations")
        _remove_from_location(new_state, object_id)
        destination = dict(destination)
        if destination.get("kind") == "base" and destination.get("player_relation") == "object_controller":
            # "Move ... to base" names each unit's own controller's Base (Core
            # 355.4.a valid Location), not the spell controller's; resolved per
            # object so a 2v2 teammate's unit goes home, not to the caster.
            destination["player"] = new_state["objects"][object_id]["controller"]
        if destination.get("kind") == "base" and destination.get("player") in new_state["players"]:
            new_state["players"][destination["player"]]["zones"]["base"].append(object_id)
            target = f"base:{destination['player']}"
        elif destination.get("kind") == "battlefield" and destination.get("battlefield") in new_state["battlefields"]:
            new_state["battlefields"][destination["battlefield"]]["objects"].append(object_id)
            target = f"battlefield:{destination['battlefield']}"
        else:
            raise ValueError("unknown board destination")
        trace.update({"object_id": object_id, "from": source, "to": target})
        # ADR-0007 §10: only a completed Move raises "When I move" (383.1, 319.8);
        # Recall, return to hand and board entry are not Moves.
        moved = new_state["objects"][object_id]
        move_triggers = []
        for descriptor in moved.get("move_triggers", []) or []:
            copied = copy.deepcopy(descriptor)
            copied.setdefault("trigger_kind", "triggered")
            copied["move"] = {"from": source, "to": target}
            move_triggers.append(copied)
        if move_triggers:
            trace["pending_triggers"] = move_triggers

    elif op == "return_to_hand":
        # DP-06 / Q1: a zone change (446.2 — not a Move), so a new object (124)
        # that keeps nothing of the old one (124.1). Board or the owner's trash
        # only; a token entering a non-board zone ceases to exist (186.1).
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("return_to_hand requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
        on_board = source is not None and (source[0] == "battlefield" or source[2] == "base")
        in_owner_trash = source == ("player", obj["owner"], "trash")
        if not (on_board or in_owner_trash):
            raise IllegalOperation(f"return_to_hand applies only to a board object or a card in its owner's trash; {object_id!r} is at {source}")
        _remove_from_location(new_state, object_id)
        if obj.get("is_token"):
            del new_state["objects"][object_id]
            trace.update({"object_id": object_id, "from": source, "destination": "ceased_to_exist", "not_a_move": True})
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 186.1"]))
        else:
            obj["damage"] = 0
            obj["might_modifiers"] = []
            obj["exhausted"] = False
            for transient in ("statuses", "counters", "combat_designation"):
                obj.pop(transient, None)  # a new object carries no designation (124.1, 464.2.c.3)
            new_state["players"][obj["owner"]]["zones"]["hand"].append(object_id)
            trace.update({"object_id": object_id, "from": source, "destination": f"{obj['owner']}.hand",
                          "identity_after": _bump_identity(new_state, object_id), "not_a_move": True})
        if on_board:
            trace["disabled_replacements"] = _prune_inactive_replacements(new_state)

    elif op == "recall":
        # DP-06 / Q2: relocation to the current controller's Base (455); not a
        # Move (456.1), so Move triggers never fire; damage, exhaustion and
        # modifiers stay (458.1); the object is the same object.
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("recall requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
        if source is None or not (source[0] == "battlefield" or source[2] == "base"):
            raise IllegalOperation(f"recall applies only to a board object; {object_id!r} is at {source}")
        controller = obj["controller"]
        retained = {"damage": obj["damage"], "exhausted": obj["exhausted"], "might_modifiers": len(obj.get("might_modifiers", []))}
        if source == ("player", controller, "base"):
            trace.update({"object_id": object_id, "from": source, "to": f"base:{controller}", "not_a_move": True, "retained": retained, "outcome": "no_op"})
        else:
            _remove_from_location(new_state, object_id)
            new_state["players"][controller]["zones"]["base"].append(object_id)
            trace.update({"object_id": object_id, "from": source, "to": f"base:{controller}", "not_a_move": True, "retained": retained,
                          "identity_after": object_identity(new_state, object_id)})

    elif op == "channel_rune":
        # DP-08 / Q3: top runes of the Rune Deck enter the board (430.1) with the
        # stated entry state (430.2, ready by default 430.2.a); as many as
        # possible when short (430.3); a non-board → board change, so new
        # objects (124). Not a Move; runes are not permanents.
        player_id, count = effect.get("player"), effect.get("count")
        entry_state = effect.get("entry_state", "ready")
        if player_id not in new_state["players"] or not isinstance(count, int) or count < 1:
            raise ValueError("channel_rune requires a known player and positive count")
        if entry_state not in {"ready", "exhausted"}:
            raise ValueError("channel_rune entry_state must be ready or exhausted")
        rune_deck = new_state["players"][player_id]["zones"]["rune_deck"]
        taken = rune_deck[:count]
        del rune_deck[:count]
        for rune_id in taken:
            new_state["objects"][rune_id]["exhausted"] = entry_state == "exhausted"
            new_state["players"][player_id]["zones"]["base"].append(rune_id)
            _bump_identity(new_state, rune_id)
        applied = len(taken)
        trace.update({"player": player_id, "requested_count": count, "applied_count": applied, "entry_state": entry_state,
                      "objects": taken, "identities_after": {rune_id: object_identity(new_state, rune_id) for rune_id in taken},
                      "completion": "full" if applied == count else ("partial" if applied else "none"), "not_a_move": True})
        if applied == 0:
            trace["outcome"] = "no_op"

    elif op == "modify_might":
        object_id, amount = effect.get("object_id"), effect.get("amount")
        duration, source = effect.get("duration"), effect.get("source")
        if object_id not in new_state["objects"] or not isinstance(amount, int):
            raise ValueError("modify_might requires a known object and integer amount")
        if duration not in {"this_turn", "persistent"} or not isinstance(source, str) or not source:
            raise ValueError("modify_might requires duration and source")
        modifier = {"amount": amount, "duration": duration, "source": source}
        if duration == "this_turn":
            modifier["turn_id"] = new_state.get("turn_id", DEFAULT_TURN_ID)
        new_state["objects"][object_id]["might_modifiers"].append(modifier)
        trace.update({"object_id": object_id, "amount": amount, "duration": duration, "turn_id": modifier.get("turn_id")})

    elif op == "discard":
        player_id, objects = effect.get("player"), effect.get("objects")
        if player_id not in new_state["players"] or not isinstance(objects, list):
            raise ValueError("discard requires a known player and a resolved selection")
        hand = new_state["players"][player_id]["zones"]["hand"]
        identities = {}
        for object_id in objects:
            if object_id not in hand:
                raise IllegalOperation(f"{object_id!r} is not in {player_id}'s hand")
            hand.remove(object_id)
            owner = new_state["objects"][object_id]["owner"]
            new_state["players"][owner]["zones"]["trash"].append(object_id)
            identities[object_id] = _bump_identity(new_state, object_id)
        requested = effect.get("count")
        trace.update({"player": player_id, "requested_count": requested, "applied_count": len(objects), "objects": list(objects), "identities_after": identities,
                      "not_a_target": True, "selection": effect.get("selection_meta", {}),
                      "completion": "full" if len(objects) == requested else ("partial" if objects else "none")})
        if not objects:
            trace["outcome"] = "no_op"

    elif op == "heal_all_damage":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("heal_all_damage requires a known object")
        before = new_state["objects"][object_id]["damage"]
        new_state["objects"][object_id]["damage"] = 0
        trace.update({"object_id": object_id, "before": before, "after": 0})
        if before == 0:
            trace["outcome"] = "no_op"

    elif op == "grant_replacement":
        # ADR-0007 §12 (Highlander): "Choose a friendly unit. The next time it
        # would die this turn, ... instead." creates a replacement bound to the
        # chosen object's identity, once, for this turn; the spell itself is
        # gone by then, so the replacement is granted, not source-backed.
        object_id, spec, controller = effect.get("object_id"), effect.get("replacement"), effect.get("controller")
        if object_id not in new_state["objects"] or not isinstance(spec, dict) or controller not in new_state["players"]:
            raise ValueError("grant_replacement requires a known object, a replacement spec and a controller")
        if zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"grant_replacement applies only to a board object; {object_id!r} is not on the board")
        if not isinstance(effect.get("granted_by"), str) or not effect.get("granted_by"):
            raise ValueError("grant_replacement requires granted_by")

        def bind_target(value):
            if isinstance(value, dict):
                return {k: bind_target(v) for k, v in value.items()}
            if isinstance(value, list):
                return [bind_target(v) for v in value]
            return object_id if value == "$granted_target" else value

        granted = {
            "replacement_id": spec.get("replacement_id") or f"granted:{effect.get('granted_by')}:{object_id}",
            "controller": controller, "mode": spec.get("mode"), "event_op": spec.get("event_op"), "optional": bool(spec.get("optional", False)),
            "uses_remaining": 1, "target_object_id": object_id,
            "granted": {"target_object": object_id, "target_identity": object_identity(new_state, object_id) or f"{object_id}@0", "duration": "this_turn",
                        "turn_id": new_state.get("turn_id", DEFAULT_TURN_ID), "granted_by": effect["granted_by"]},
        }
        if spec.get("replacement_effects") is not None:
            granted["replacement_effects"] = bind_target(copy.deepcopy(spec["replacement_effects"]))
        if any(r["replacement_id"] == granted["replacement_id"] for r in new_state["replacement_effects"]):
            raise ValueError(f"replacement {granted['replacement_id']!r} already exists")
        new_state["replacement_effects"].append(granted)
        trace.update({"object_id": object_id, "replacement_id": granted["replacement_id"], "granted": copy.deepcopy(granted["granted"])})

    elif op == "grant_keyword":
        # ADR-0008 §5 (Fortified Position: "It gains [Shield 2] this combat."):
        # a granted characteristic bound to the object's identity now and to
        # the Combat in progress (expires with it, 466.7.c) or to this turn.
        object_id, keyword, duration = effect.get("object_id"), effect.get("keyword"), effect.get("duration")
        if object_id not in new_state["objects"] or keyword not in GRANTABLE_KEYWORDS or duration not in KEYWORD_MODIFIER_DURATIONS:
            raise ValueError("grant_keyword requires a known object, a grantable keyword and a duration")
        if new_state["objects"][object_id].get("kind") != "unit" or zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"grant_keyword applies only to a Unit on the board; {object_id!r} is not one")
        value = effect.get("value")
        if keyword != "shield" and value is not None:
            raise ValueError(f"{keyword} carries no value")
        modifier = {"modifier_id": f"{keyword}:{effect.get('source')}:{object_id}:{len(new_state['objects'][object_id].get('keyword_modifiers', []) or [])}",
                    "keyword": keyword, "source": effect.get("source"), "duration": duration,
                    "target_identity": object_identity(new_state, object_id) or f"{object_id}@0"}
        if keyword == "shield":
            modifier["value"] = value if value is not None else 1
        if duration == "this_combat":
            combat = effect.get("combat_context")
            if not isinstance(combat, dict) or not combat.get("combat_id"):
                raise NotImplementedError("a 'this combat' grant needs the Combat in progress as context (466.7.c); none was supplied")
            modifier["combat_id"] = combat["combat_id"]
        else:
            modifier["turn_id"] = new_state.get("turn_id", DEFAULT_TURN_ID)
        new_state["objects"][object_id].setdefault("keyword_modifiers", []).append(modifier)
        trace.update({"object_id": object_id, "keyword": keyword, "value": modifier.get("value"), "duration": duration,
                      "combat_id": modifier.get("combat_id"), "turn_id": modifier.get("turn_id"), "modifier_id": modifier["modifier_id"],
                      "shield_total": shield_total(new_state, object_id) if keyword == "shield" else None})

    elif op == "grant_turn_effect":
        kind, value, controller = effect.get("turn_effect_kind"), effect.get("value"), effect.get("controller")
        if kind not in TURN_EFFECT_KINDS:
            raise NotImplementedError(f"turn effect {kind!r} is not modelled")
        if controller not in new_state["players"] or value not in {"ready", "exhausted"}:
            raise ValueError("grant_turn_effect requires a known controller and a ready|exhausted value")
        turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
        granted = {"effect_id": f"{kind}:{controller}:{turn_id}:{len(new_state.get('turn_effects', []))}", "kind": kind, "controller": controller,
                   "value": value, "turn_id": turn_id, "source": effect.get("source", "effect")}
        new_state.setdefault("turn_effects", []).append(granted)
        trace.update({"turn_effect": granted})

    elif op == "mutual_damage_current_might":
        raise ValueError("mutual_damage_current_might is resolved by apply_program as two simultaneous Deal events")

    elif op in {"deal_damage", "heal_damage"}:
        object_id, amount = effect.get("object_id"), effect.get("amount")
        if object_id not in new_state["objects"] or not isinstance(amount, int) or amount < 1:
            raise ValueError(f"{op} requires a known object and positive amount")
        before = new_state["objects"][object_id]["damage"]
        after = before + amount if op == "deal_damage" else max(0, before - amount)
        new_state["objects"][object_id]["damage"] = after
        trace.update({"object_id": object_id, "before": before, "after": after})
        if effect.get("source_object") is not None:
            # Core 417.6.b.3: a Unit named as the source is the source, not the spell.
            trace.update({"source_object": effect["source_object"], "source_kind": effect.get("source_kind", "object"),
                          "responsible_player": new_state["objects"].get(effect["source_object"], {}).get("controller")})
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 417.6.b.3", "Core 417.6.b.4"]))
        if effect.get("bonus_damage"):
            trace["bonus_damage"] = copy.deepcopy(effect["bonus_damage"])
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 713–715"]))
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
            "identity": f"{object_id}@0",
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
            obj.pop("combat_designation", None)
            trace["identity_after"] = _bump_identity(new_state, object_id)
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 124"]))
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


def runes_on_board(state: dict[str, Any], controller: str) -> int:
    """ADR-0007 §7: every Rune the player controls on the Board — Base or any
    Board Location, ready or exhausted; nothing in Non-Board Zones; a
    teammate's runes are not "yours"."""
    count = 0
    for object_id, obj in state["objects"].items():
        if obj.get("kind") != "rune" or obj.get("controller") != controller:
            continue
        if zone_class(find_location(state, object_id)) == "board":
            count += 1
    return count


def keyword_modifier_active(state: dict[str, Any], object_id: str, modifier: dict[str, Any]) -> bool:
    """A granted characteristic applies to the identity it was granted to, for
    the matching Combat (the Unit's own designation names it, 466.7.c) or the
    current turn (317.2.c)."""
    obj = state["objects"][object_id]
    if modifier.get("target_identity") != (object_identity(state, object_id) or f"{object_id}@0"):
        return False
    if modifier["duration"] == "this_combat":
        designation = obj.get("combat_designation")
        return designation is not None and designation.get("combat_id") == modifier.get("combat_id")
    return modifier.get("turn_id") == state.get("turn_id", DEFAULT_TURN_ID)


def has_keyword(state: dict[str, Any], object_id: str, keyword: str) -> bool:
    """Printed (keywords) or granted (an active keyword_modifiers entry)."""
    obj = state["objects"][object_id]
    if keyword in (obj.get("keywords") or []):
        return True
    return any(m["keyword"] == keyword and keyword_modifier_active(state, object_id, m) for m in obj.get("keyword_modifiers", []) or [])


def shield_total(state: dict[str, Any], object_id: str) -> int:
    """Core 814.2: every Shield value the Unit has or was granted, summed; an
    omitted X is 1 (814.1.b.3)."""
    obj = state["objects"][object_id]
    total = (obj.get("shield_value") or 1) if "shield" in (obj.get("keywords") or []) else 0
    for modifier in obj.get("keyword_modifiers", []) or []:
        if modifier["keyword"] == "shield" and keyword_modifier_active(state, object_id, modifier):
            total += modifier.get("value") or 1
    return total


def is_alone(state: dict[str, Any], object_id: str) -> bool:
    """Core 740.2.a: no other friendly Unit (team-aware, 740.1.a) at the same location."""
    obj = state["objects"][object_id]
    location = find_location(state, object_id)
    if location is None:
        return False
    for other_id, other in state["objects"].items():
        if other_id == object_id or other.get("kind") != "unit":
            continue
        if find_location(state, other_id) == location and same_side(state, obj["controller"], other["controller"]):
            return False
    return True


def combat_might_contributions(state: dict[str, Any], object_id: str) -> list[dict[str, Any]]:
    """ADR-0008 §5: the Combat-relative parts of a Unit's rules-facing Might —
    Shield while it is a Defender (814.1.c), 'attacking or defending alone'
    passives (740.2.a), and external auras over lone friendly Defenders."""
    obj = state["objects"][object_id]
    designation = obj.get("combat_designation")
    parts: list[dict[str, Any]] = []
    if designation is not None and designation.get("role") == "defender":
        shield = shield_total(state, object_id)
        if shield:
            parts.append({"kind": "shield", "amount": shield, "rule_locators": ["Core 814.1.c", "Core 814.2"]})
    alone = designation is not None and is_alone(state, object_id)
    for conditional in obj.get("conditional_might", []) or []:
        if conditional["condition"]["kind"] == "attacking_or_defending_alone" and alone:
            parts.append({"kind": "attacking_or_defending_alone", "modifier_id": conditional["modifier_id"], "amount": conditional["amount"], "rule_locators": ["Core 740.2.a", "Core 364.3"]})
    for aura in state.get("might_auras", []) or []:
        source = aura["source_object"]
        active = (source in state["battlefields"]) or (source in state["objects"] and zone_class(find_location(state, source)) == "board")
        if not active or not same_side(state, aura["controller"], obj["controller"]):
            continue
        if aura["condition"]["kind"] == "friendly_unit_defends_alone" and designation is not None and designation.get("role") == "defender" and alone:
            parts.append({"kind": "friendly_unit_defends_alone", "modifier_id": aura["modifier_id"], "source_object": source, "amount": aura["amount"], "rule_locators": ["Core 740.2.a", "Core 365.1"]})
    return parts


def effective_might(state: dict[str, Any], object_id: str) -> int:
    """Context-aware Might: current_might plus every conditional passive
    whose condition holds now (Core 364.3, 365.1), the Combat-relative parts
    of ADR-0008 §5, clamped at zero when referenced by rules (143.2.b) while
    the stored arithmetic value stays as it is. current_might keeps its
    contract; rules paths that must see passives call this."""
    obj = state["objects"][object_id]
    current_turn = state.get("turn_id", DEFAULT_TURN_ID)
    # current_might intentionally retains its original context-free contract.
    # Rules-facing paths use only persistent modifiers and this turn's stamp.
    might = obj["base_might"] + sum(
        modifier["amount"]
        for modifier in obj.get("might_modifiers", [])
        if modifier.get("duration") != "this_turn" or modifier.get("turn_id", current_turn) == current_turn
    )
    if zone_class(find_location(state, object_id)) != "board":
        return max(0, might)
    for conditional in obj.get("conditional_might", []) or []:
        condition = conditional["condition"]
        if condition["kind"] == "runes_at_least" and runes_on_board(state, obj["controller"]) >= condition["count"]:
            might += conditional["amount"]
    might += sum(part["amount"] for part in combat_might_contributions(state, object_id))
    return max(0, might)


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
            might = effective_might(current, object_id)
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


def _resolve_discard(state: dict[str, Any], effect: dict[str, Any], decisions: dict[str, Any] | None) -> dict[str, Any]:
    """ADR-0007 §10 / Core 422: the discarding player chooses from their own
    hand with private information (422.1.a) — a card_selection decision, never
    a target. When the whole hand must go and only one set is legal, the
    engine proceeds; otherwise it stops for the decision."""
    import engine_decisions as ed
    player_id, count = effect.get("player"), effect.get("count")
    if player_id not in state["players"] or not isinstance(count, int) or count < 1:
        raise ValueError("discard requires a known player and a positive count")
    hand = list(state["players"][player_id]["zones"]["hand"])
    if len(hand) <= count:
        return {**effect, "objects": hand, "selection_meta": {"forced": True, "reason": "every card in hand must be discarded (Core 422.4)"}}
    ref = effect.get("decision_ref")
    entry = next((e for e in ed.entries(decisions, kind="card_selection") if e["decision_id"] == ref), None) if ref else None
    if entry is None:
        raise CardSelectionRequired(f"{player_id} chooses {count} card(s) from hand to discard (Core 422.1.a)", [ref or f"discard:{player_id}"], player_id)
    if entry["controller"] != player_id:
        raise IllegalDecision(f"card selection {ref!r} was made by {entry['controller']!r}, not the discarding player")
    if entry["stage"] != "resolution":
        raise ValueError(f"card selection {ref!r} must be a resolution-stage decision")
    chosen = list(entry["value"])
    if len(chosen) != count:
        raise ValueError(f"card selection {ref!r} names {len(chosen)} cards; {count} required")
    for object_id in chosen:
        if object_id not in hand:
            raise IllegalOperation(f"card selection {ref!r} names {object_id!r}, which is not in {player_id}'s hand")
        bound = (entry.get("selection_identities") or {}).get(object_id)
        if bound is not None and bound != object_identity(state, object_id):
            raise ValueError(f"card selection {ref!r} was bound to {bound!r}; {object_id} is now {object_identity(state, object_id)!r}")
    return {**effect, "objects": chosen, "selection_meta": {"forced": False, "decision_id": entry["decision_id"]}}


def _resolve_selectors(state: dict[str, Any], effect: dict[str, Any], program: dict[str, Any], decisions: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn `targets` (or a decision_ref on `target`) into concrete selectors,
    consuming a target_selection decision when the program defers to one.
    Returns (selectors, meta) where meta says which decision was used."""
    import engine_decisions as ed  # local import keeps effect_ir importable on its own
    controller = program.get("controller")
    targets = effect.get("targets")
    template = {k: v for k, v in (targets or {}).get("restrictions", {}).items()} if targets else {}
    if targets is None:
        target = effect.get("target")
        if target is not None and "decision_ref" in target:
            entry = ed.target_selection(decisions, target["decision_ref"])
            if entry is None:
                raise TargetDecisionRequired(f"target selection {target['decision_ref']!r} is required", [target["decision_ref"]], controller)
            if entry["controller"] != controller:
                raise IllegalDecision(f"target selection {target['decision_ref']!r} was made by {entry['controller']!r}, not the program controller")
            if entry["stage"] not in {"play_declaration", "trigger_finalization"}:
                raise ValueError(f"target selection {target['decision_ref']!r} was supplied at the wrong stage")
            if len(entry["value"]) != 1:
                raise ValueError(f"target selection {target['decision_ref']!r} must name exactly one object for a single-target instruction")
            concrete = {k: v for k, v in target.items() if k != "decision_ref"}
            concrete["object_id"] = entry["value"][0]
            concrete.setdefault("bound_identity", entry["selection_identities"][concrete["object_id"]])
            if concrete.get("kind") == "battlefield":
                concrete.setdefault("chosen_zone_class", "board")
            return [concrete], {"decision_id": entry["decision_id"]}
        return ([target] if target is not None else []), {}
    if "selectors" in targets:
        return [dict(sel) for sel in targets["selectors"]], {}
    entry = ed.target_selection(decisions, targets["decision_ref"])
    if entry is None:
        raise TargetDecisionRequired(f"target selection {targets['decision_ref']!r} is required", [targets["decision_ref"]], controller)
    if entry["controller"] != controller:
        raise IllegalDecision(f"target selection {targets['decision_ref']!r} was made by {entry['controller']!r}, not the program controller")
    if entry["stage"] not in {"play_declaration", "trigger_finalization"}:
        raise ValueError(f"target selection {targets['decision_ref']!r} was supplied at the wrong stage")
    chosen = list(entry["value"])
    if not (targets["min"] <= len(chosen) <= targets["max"]):
        raise ValueError(f"target selection {targets['decision_ref']!r} chose {len(chosen)} objects; allowed {targets['min']}..{targets['max']}")
    selectors = []
    for object_id in chosen:
        sel = dict(template)
        sel["object_id"] = object_id
        sel.setdefault("chosen_zone_class", zone_class(find_location(state, object_id)) or "non_board")
        sel.setdefault("bound_identity", entry["selection_identities"][object_id])
        selectors.append(sel)
    return selectors, {"decision_id": entry["decision_id"]}


def apply_program(state: dict[str, Any], program: dict[str, Any], *, decisions: dict[str, Any] | None = None, context: dict[str, Any] | None = None, _replacement_depth: int = 0) -> dict[str, Any]:
    """`context` carries facts only a procedure knows — today the Combat in
    progress ({"combat": {"combat_id", "battlefield"}}) that a 'this combat'
    grant binds to. The bridge supplies it; a bare effect run has none."""
    state_errors = validate_state(state)
    program_errors = validate_program(program)
    if decisions is not None:
        import engine_decisions as ed
        program_errors = program_errors + ed.validate_engine_decisions(decisions)
        if not program_errors and decisions.get("input_hash") != hash_value(state):
            program_errors = program_errors + ["engine_decisions.input_hash does not match the state being transitioned"]
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
        predicate = effect.get("predicate")
        if predicate is not None:
            try:
                holds, predicate_locators = evaluate_predicate(predicate, program.get("cost_receipt"), {e.get("effect_id"): e for e in trace}, current, program.get("controller"))
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
            if holds is None:
                return {
                    **base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                    "reason": f"predicate kind {predicate['kind']!r} is recognized but not implemented", "trace": trace,
                }
            if not holds:
                event = {
                    "index": index, "effect_id": effect_id, "op": effect["op"],
                    "outcome": "skipped_linked_dependency", "predicate": copy.deepcopy(predicate), "predicate_result": False,
                    "completion": "none", "rule_locators": predicate_locators + ["Core 359.3.e.14"],
                    "before_state_hash": before_hash, "after_state_hash": before_hash,
                }
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
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
        # ADR-0005 §1–3: resolve selectors (possibly from a decision), then either
        # run the legacy single-target path unchanged or expand a multi-target
        # instruction into per-object applications with a typed instruction outcome.
        try:
            selectors, selector_meta = _resolve_selectors(current, effect, program, decisions)
        except TargetDecisionRequired as exc:
            return {
                **base, "valid": True, "committed": False, "target_decision_required": True,
                "reason_code": "target_selection_required", "reason": str(exc),
                "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                "failed_effect_index": index, "trace": trace,
            }
        except IllegalDecision as exc:
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": "decision_controller_mismatch", "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
            }
        except ValueError as exc:
            return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
        if effect.get("op") == "grant_keyword" and context is not None and context.get("combat") is not None:
            effect = {**effect, "combat_context": context["combat"]}
        if effect.get("op") == "discard":
            try:
                effect = _resolve_discard(current, effect, decisions)
            except CardSelectionRequired as exc:
                return {
                    **base, "valid": True, "committed": False, "card_selection_required": True,
                    "reason_code": "card_selection_required", "reason": str(exc),
                    "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                    "failed_effect_index": index, "trace": trace,
                }
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch", "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except IllegalOperation as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation", "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
        if effect.get("op") == "mutual_damage_current_might":
            # ADR-0008 §7 (Gentlemen's Duel): both Units are revalidated, both
            # rules-facing Mights are read before either Deal, then the two Deal
            # events happen as one simultaneous action with the Units as sources
            # (417.6.b.3); one illegal Unit skips the whole pair (each Deal
            # relates to both). Never Combat Damage, never sequential reads.
            pair = []
            try:
                for position, selector in enumerate(effect["units"]):
                    resolved, meta = _resolve_selectors(current, {"target": selector}, program, decisions)
                    pair.append((resolved[0], meta))
            except TargetDecisionRequired as exc:
                return {**base, "valid": True, "committed": False, "target_decision_required": True, "reason_code": "target_selection_required", "reason": str(exc),
                        "decision_ids": exc.decision_ids, "decision_controller": exc.controller, "failed_effect_index": index, "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch", "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
            verdicts = [(sel, *evaluate_target(current, sel, program.get("controller"))) for sel, _ in pair]
            ids = [sel["object_id"] for sel, _, _ in verdicts]
            invalid = [{"object_id": sel["object_id"], "reason": reason} for sel, ok, reason in verdicts if not ok]
            if ids[0] == ids[1] and not invalid:
                invalid = [{"object_id": ids[0], "reason": "same_unit_twice"}]
            if invalid:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "ignored_illegal_target", "target_outcome": "skipped_illegal_target",
                         "completion": "none", "units": ids, "invalid_targets": invalid, "reason": "a Unit of the pair is not a legal referent; both Deals relate to it (359.3.e.5)",
                         "rule_locators": ["Core 359.3.e.1–359.3.e.5", "Core 359.3.e.14"], "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            snapshot = {object_id: effective_might(current, object_id) for object_id in ids}
            working = current
            sub_trace = []
            failure = None
            for source, receiver in ((ids[0], ids[1]), (ids[1], ids[0])):
                amount = snapshot[source]
                if amount < 1:
                    sub_trace.append({"op": "deal_damage", "effect_id": f"{effect_id}:{source}->{receiver}", "object_id": receiver, "source_object": source, "source_kind": "unit",
                                      "amount": amount, "outcome": "no_op", "completion": "none", "reason": "no valid damage: the source's Might reads as 0 (417.1.e, 143.2.b)",
                                      "rule_locators": ["Core 417.1.e", "Core 143.2.b"]})
                    continue
                single = {"op": "deal_damage", "effect_id": f"{effect_id}:{source}->{receiver}", "object_id": receiver, "amount": amount, "source_object": source, "source_kind": "unit"}
                for key in ("replacement_order", "replacement_decider", "replacement_choices"):
                    if key in effect:
                        single[key] = effect[key]
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"mutual:{program['program_id']}:{effect_id}", "controller": program.get("controller"), "source_object": source, "effects": [single]}
                sub = apply_program(working, sub_program, decisions=None, context=context, _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    failure = sub
                    break
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            if failure is not None:
                return {**base, "valid": failure.get("valid", True), "committed": False, "unsupported": failure.get("unsupported", False),
                        "replacement_decision_required": failure.get("replacement_decision_required", False), "replacement_ids": failure.get("replacement_ids", []),
                        "failed_effect_index": index, "reason": failure.get("reason", "; ".join(failure.get("errors", [])) or "mutual damage failed"), "expansion_result": failure, "trace": trace}
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in PERFORMED_OUTCOMES)
            event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "applied" if applied else "no_op",
                     "completion": "full" if applied == 2 else ("partial" if applied else "none"), "units": ids, "might_snapshot": snapshot,
                     "simultaneous": True, "not_combat_damage": True, "sources": {ids[0]: ids[1], ids[1]: ids[0]}, "expansion_trace": sub_trace,
                     "pending_triggers": [t for ev in sub_trace for t in ev.get("pending_triggers", [])],
                     "rule_locators": list(dict.fromkeys(OP_RULES["mutual_damage_current_might"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                     "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            for _, meta in pair:
                event.update(meta)
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("affected") is not None:
            # ADR-0007 §4: two layers. The Battlefield (if any) is the target and is
            # revalidated; the units are found by criteria now and are NOT targets —
            # no 355.9 revalidation, no Deflect, no untargetability (355.10.b, 355.10.d).
            criteria = effect["affected"]["criteria"]
            battlefield_ids: list[str] = []
            targeted_battlefield = None
            active_combat = None
            if criteria["location"] == "active_combat":
                # ADR-0008 §7 (Cannon Barrage): Units at the Combat Battlefield that
                # carry that Combat's designation (740.2.c). No Combat in progress
                # is an empty set — a supported no-op; a claimed Combat whose
                # Battlefield or identity the state cannot confirm is unsupported.
                active_combat = (context or {}).get("combat")
                if active_combat is not None:
                    combat_battlefield = active_combat.get("battlefield")
                    if combat_battlefield not in current["battlefields"] or (active_combat.get("battlefield_identity") is not None and battlefield_identity(current, combat_battlefield) != active_combat["battlefield_identity"]):
                        return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                                "reason": f"the Combat context names Battlefield {combat_battlefield!r}, which the state cannot confirm; 'in combat' is not inferred", "trace": trace}
                    battlefield_ids = [combat_battlefield]
            elif criteria["location"] == "target_battlefield":
                sel = selectors[0]
                legal, reason = evaluate_target(current, sel, program.get("controller"))
                targeted_battlefield = sel["object_id"]
                if not legal:
                    event = {
                        "index": index, "effect_id": effect_id, "op": effect["op"],
                        "outcome": "skipped_illegal_target", "target_outcome": "skipped_illegal_target", "completion": "none",
                        "targeted_battlefield": targeted_battlefield, "target_reason": reason, "affected_objects": [], "affected_are_targets": False,
                        "criteria": dict(criteria), "rule_locators": ["Core 355.10.b", "Core 359.3.e.2", "Core 359.3.e.5"],
                        "before_state_hash": before_hash, "after_state_hash": before_hash, **selector_meta,
                    }
                    trace.append(event)
                    outcomes[effect_id] = "skipped_illegal_target"
                    continue
                battlefield_ids = [targeted_battlefield]
            else:
                battlefield_ids = sorted(current["battlefields"])
            affected_ids: list[str] = []
            for battlefield_id in battlefield_ids:
                for candidate in current["battlefields"][battlefield_id]["objects"]:
                    obj = current["objects"][candidate]
                    if "kind" in criteria and obj["kind"] != criteria["kind"]:
                        continue
                    if active_combat is not None and (obj.get("combat_designation") or {}).get("combat_id") != active_combat.get("combat_id"):
                        continue  # present but not yet designated: not "in combat" (740.2.c)
                    relation = criteria.get("controller_relation")
                    if relation == "friendly" and not same_side(current, program.get("controller"), obj.get("controller")):
                        continue
                    if relation == "enemy" and same_side(current, program.get("controller"), obj.get("controller")):
                        continue
                    affected_ids.append(candidate)
            snapshot_hash = hash_value({"state": before_hash, "criteria": criteria, "battlefields": battlefield_ids, "affected": affected_ids})
            sub_trace = []
            working = current
            failure = None
            for object_id in affected_ids:
                single = {k: v for k, v in effect.items() if k not in {"affected", "target", "targets", "effect_id"}}
                single["object_id"] = object_id
                single["effect_id"] = f"{effect_id}:{object_id}"
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"affected:{program['program_id']}:{effect_id}", "controller": program.get("controller"),
                               "source_object": program.get("source_object"), "effects": [single]}
                sub = apply_program(working, sub_program, decisions=None, context=context, _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    failure = sub
                    break
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            if failure is not None:
                return {
                    **base, "valid": failure.get("valid", True), "committed": False,
                    "unsupported": failure.get("unsupported", False),
                    "replacement_decision_required": failure.get("replacement_decision_required", False),
                    "replacement_ids": failure.get("replacement_ids", []),
                    "failed_effect_index": index, "reason": failure.get("reason", "; ".join(failure.get("errors", [])) or "criteria expansion failed"),
                    "expansion_result": failure, "trace": trace,
                }
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in {"applied", "replaced_modified_applied", "augmented_applied"})
            event = {
                "index": index, "effect_id": effect_id, "op": effect["op"],
                "outcome": "applied" if applied else "no_op",
                "completion": "full" if (applied == len(affected_ids)) else ("partial" if applied else "none") if affected_ids else "full",
                "targeted_battlefield": targeted_battlefield, "affected_objects": affected_ids, "affected_are_targets": False,
                "criteria": dict(criteria), "criteria_snapshot_hash": snapshot_hash, "expansion_trace": sub_trace,
                **({"active_combat": dict(active_combat) if active_combat else None} if criteria["location"] == "active_combat" else {}),
                "pending_triggers": [t for ev in sub_trace for t in ev.get("pending_triggers", [])],
                "rule_locators": list(dict.fromkeys(["Core 355.5.a", "Core 355.10.b", "Core 355.10.d"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                "before_state_hash": before_hash, "after_state_hash": hash_value(current), **selector_meta,
            }
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("targets") is not None:
            verdicts = [(sel, *evaluate_target(current, sel, program.get("controller"))) for sel in selectors]
            valid_sels = [sel for sel, ok, _ in verdicts if ok]
            invalid = [{"object_id": sel.get("object_id"), "reason": reason} for sel, ok, reason in verdicts if not ok]
            requested = len(selectors)
            if requested and not valid_sels:
                event = {
                    "index": index, "effect_id": effect_id, "op": effect["op"],
                    "outcome": "skipped_illegal_target", "target_outcome": "skipped_illegal_target", "completion": "none",
                    "requested_targets": requested, "applied_targets": 0, "invalid_targets": invalid,
                    "rule_locators": ["Core 359.3.e.5", "Core 359.3.e.7"],
                    "before_state_hash": before_hash, "after_state_hash": before_hash, **selector_meta,
                }
                trace.append(event)
                outcomes[effect_id] = "skipped_illegal_target"
                continue
            sub_trace = []
            working = current
            expansion_failed = None
            for sel in valid_sels:
                single = {k: v for k, v in effect.items() if k not in {"targets", "effect_id"}}
                single["object_id"] = sel["object_id"]
                single["target"] = sel
                single["effect_id"] = f"{effect_id}:{sel['object_id']}"
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"expand:{program['program_id']}:{effect_id}", "controller": program.get("controller"),
                               "source_object": program.get("source_object"), "effects": [single]}
                sub = apply_program(working, sub_program, decisions=None, context=context, _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    expansion_failed = sub
                    break
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            if expansion_failed is not None:
                return {
                    **base, "valid": expansion_failed.get("valid", True), "committed": False,
                    "unsupported": expansion_failed.get("unsupported", False),
                    "replacement_decision_required": expansion_failed.get("replacement_decision_required", False),
                    "replacement_ids": expansion_failed.get("replacement_ids", []),
                    "failed_effect_index": index, "reason": expansion_failed.get("reason", "; ".join(expansion_failed.get("errors", [])) or "multi-target expansion failed"),
                    "expansion_result": expansion_failed, "trace": trace,
                }
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in {"applied", "replaced_modified_applied", "augmented_applied"})
            target_outcome = "applied_full" if not invalid and applied == requested else "applied_to_subset"
            below_min = len(valid_sels) < effect["targets"]["min"]
            event = {
                "index": index, "effect_id": effect_id, "op": effect["op"],
                "outcome": "applied" if applied else "no_op",
                "target_outcome": target_outcome,
                "completion": "full" if (applied == requested and not invalid) else ("partial" if applied else "none"),
                "requested_targets": requested, "applied_targets": applied, "invalid_targets": invalid,
                "below_minimum": below_min,
                "expansion_trace": sub_trace,
                "pending_triggers": [t for ev in sub_trace for t in ev.get("pending_triggers", [])],
                "rule_locators": list(dict.fromkeys(["Core 355.13", "Core 359.3.e.8"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                "before_state_hash": before_hash, "after_state_hash": hash_value(current), **selector_meta,
            }
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        target = selectors[0] if selectors else None
        if target is not None:
            effect = {**effect, "target": target, "object_id": effect.get("object_id", target.get("object_id"))}
            legal_target, reason = evaluate_target(current, target, program.get("controller"))
            if not legal_target:
                event = {
                    "index": index,
                    "effect_id": effect_id,
                    "op": effect["op"],
                    "outcome": "ignored_illegal_target",
                    "target_outcome": "skipped_illegal_target",
                    "completion": "none",
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
        # ADR-0007 §5: Bonus Damage is a property of the Deal action — added
        # once the Deal is known to happen with a non-zero base (715.4), before
        # any replacement or Prevent looks at the amount (437.1.a.1).
        if effect.get("op") == "deal_damage" and isinstance(effect.get("amount"), int) and effect["amount"] >= 1 and "bonus_damage" not in effect and effect.get("source_kind") != "unit":
            try:
                bonus, bonus_sources = bonus_damage(current, program.get("controller"), effect.get("object_id"))
            except NotImplementedError as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index, "reason": str(exc), "trace": trace}
            if bonus:
                effect = {**effect, "amount": effect["amount"] + bonus,
                          "bonus_damage": {"base_amount": effect["amount"], "amount": bonus, "sources": bonus_sources, "rule_locators": ["Core 713", "Core 714", "Core 715.1", "Core 715.2", "Core 437.1.a.1"]}}
        if decisions is not None and (effect.get("replacement_order") is None or effect.get("replacement_choices") is None):
            import engine_decisions as ed
            order_map, choice_map = ed.replacement_maps(decisions)
            effect = dict(effect)
            key = effect.get("effect_id", effect_id)
            if effect.get("replacement_order") is None and order_map and key in order_map:
                effect["replacement_order"] = list(order_map[key])
                effect.setdefault("replacement_decider", next((e["controller"] for e in ed.entries(decisions, kind="replacement_order")), None))
            if effect.get("replacement_choices") is None and choice_map:
                merged = {rid: by_event.get(key, by_event.get("*")) for rid, by_event in choice_map.items()}
                merged = {rid: v for rid, v in merged.items() if isinstance(v, bool)}
                if merged:
                    effect["replacement_choices"] = merged
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
        except IllegalOperation as exc:
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": "illegal_operation", "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
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
                original_result = apply_program(recursive_state, original_program, context=context, _replacement_depth=_replacement_depth + 1)
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
                    **({"source_object": replacement["source_object"]} if "source_object" in replacement else {}),
                    "effects": augmentation_effects,
                }
                augmentation_result = apply_program(original_result["next_state"], augmentation_program, context=context, _replacement_depth=_replacement_depth + 1)
                if augmentation_result.get("committed") is not True:
                    return {
                        **base, "valid": augmentation_result.get("valid", True), "committed": False,
                        "unsupported": augmentation_result.get("unsupported", False), "failed_effect_index": index,
                        "reason": augmentation_result.get("reason", "; ".join(augmentation_result.get("errors", [])) or "augmentation program failed"),
                        "replacement_id": replacement_id, "replacement_result": augmentation_result, "trace": trace,
                    }
                current = augmentation_result["next_state"]
                source_still_active = replacement_active(current, stored_replacement)
                active_uses = stored_replacement.get("uses_remaining") is None or stored_replacement.get("uses_remaining", 0) > 0
                if source_still_active and active_uses:
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
                if replacement_active(current, stored_replacement) and stored_replacement.get("prevent_remaining", 0) > 0:
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
                **({"source_object": replacement["source_object"]} if "source_object" in replacement else {}),
                "effects": replacement_program_effects,
            }
            recursive_result = apply_program(recursive_state, recursive_program, context=context, _replacement_depth=_replacement_depth + 1)
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
            replacement_still_active = replacement["mode"] != "reduce_damage" or stored_replacement.get("prevent_remaining", 0) > 0
            if replacement_active(current, stored_replacement) and replacement_still_active:
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
        except IllegalOperation as exc:
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": "illegal_operation", "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
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
        event.setdefault("completion", "full" if event.get("outcome") == "applied" else "none")
        if effect.get("target") is not None:
            event.setdefault("target_outcome", "applied_full")
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
        "conditional_triggers": copy.deepcopy(program.get("conditional_triggers", [])),
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
