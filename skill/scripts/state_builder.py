#!/usr/bin/env python3
"""Build the minimum engine state a rules question needs, and nothing more.

A producer — an LLM, in service use — emits a *state draft*: a flat object whose
keys come from a closed slot vocabulary. This module is the contract between
that producer and the engine. It does three things, and refuses a fourth.

  1. A key the vocabulary does not recognize is an error. The draft is refused
     whole. Nothing is stripped, cleaned, or salvaged, because a draft carrying
     a field we do not understand is a draft we cannot say we understood.
  2. What the builder assumed rather than read becomes an artifact the user can
     see and correct. A correction re-runs the whole build. The artifact is
     never patched in place, so a corrected answer is never half of an old one.
  3. A question whose required slots are not all present gets no guessed state.
     It gets a downgrade that names the slot that was missing.

The fourth thing, which this module does not do: rebuild a whole game from
prose. It builds the minimum the question needs, and the engine's own
validate_state decides whether that minimum is a state at all. A draft this
module accepts but the engine rejects is a failed build, reported with the
engine's own words.

Order of checks, first stage to fail wins, all failures within a stage reported
together:

    kind recognized -> keys in vocabulary -> keys in this kind -> slot types
    -> required slots -> cross-slot consistency -> engine validate_state

Two of those refuse at tier C and the rest at tier B, on one distinction: a
violation of the contract's shape (an unknown key, an unknown kind) leaves us
unable to trust the producer at all, so we abstain. Missing or unusable
information inside a well-formed draft still leaves the official text citable,
so we downgrade to B.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import effect_ir
import rules_core


SCHEMA_VERSION = "state-assumption.v1"
CORE_RULESET = rules_core.CORE_RULESET
FAQ_AS_OF = rules_core.FAQ_AS_OF

if (effect_ir.CORE_RULESET, effect_ir.FAQ_AS_OF) != (CORE_RULESET, FAQ_AS_OF):  # pragma: no cover
    raise RuntimeError("the timing and effect kernels disagree on the ruleset baseline")

CHAIN_TIMINGS = {"default", "action", "reaction"}

# S-01b. What a Combat procedure reads, and nothing it does not. The record's
# statuses and the designation roles are the kernels' own vocabularies, so a
# draft cannot name a Combat state the engine does not have; the keywords a
# unit may carry are the object keywords the assignment path actually consults
# (Tank first, Backline last, 465.2.c.6-c.9), taken from effect_ir rather than
# restated here.
COMBAT_STATUSES = frozenset(rules_core.COMBAT_STATUSES)
COMBAT_ROLES = frozenset(effect_ir.COMBAT_ROLES)
UNIT_KEYWORDS = frozenset(effect_ir.OBJECT_KEYWORDS)
CHAIN_STATUSES = {"pending", "finalized"}
TIERS = {"B", "C"}

# reason -> the tier it downgrades to. Hand-writing a different tier on a reason
# is rejected by the validator; the mapping is the contract, not a convention.
DOWNGRADE_TIERS = {
    "unrecognized_question_kind": "C",
    "schema_outside_field": "C",
    "slot_not_in_question_kind": "C",
    "slot_type_invalid": "B",
    "missing_required_slot": "B",
    "slot_value_out_of_scope": "B",
    "engine_rejected_state": "B",
}
DOWNGRADE_REASONS = frozenset(DOWNGRADE_TIERS)
NAMES_MISSING = {"missing_required_slot"}
NAMES_REJECTED = {"schema_outside_field", "slot_not_in_question_kind", "slot_type_invalid", "slot_value_out_of_scope"}


class StateBuilderError(ValueError):
    pass


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_players(value: Any) -> str | None:
    if not isinstance(value, list) or len(value) < 2 or not all(_is_id(v) for v in value):
        return "players must list at least two non-empty player ids"
    if len(set(value)) != len(value):
        return "players must not repeat a player id"
    return None


def _check_phase(value: Any) -> str | None:
    return None if value in rules_core.PHASES else f"phase must be one of {list(rules_core.PHASES)}"


def _check_optional_id(value: Any) -> str | None:
    return None if value is None or _is_id(value) else "must be a player id or null"


def _check_bool(value: Any) -> str | None:
    return None if isinstance(value, bool) else "must be true or false"


def _check_chain_items(value: Any) -> str | None:
    if not isinstance(value, list):
        return "chain_items must be an array"
    seen: set[str] = set()
    for index, entry in enumerate(value):
        label = f"chain_items[{index}]"
        if not isinstance(entry, dict):
            return f"{label} must be an object"
        unknown = set(entry) - {"item_id", "controller", "object_kind", "timing", "status"}
        if unknown:
            return f"{label} carries fields outside the vocabulary: {sorted(unknown)}"
        missing = {"item_id", "controller", "object_kind", "timing"} - set(entry)
        if missing:
            return f"{label} is missing {sorted(missing)}"
        if not _is_id(entry["item_id"]) or entry["item_id"] in seen:
            return f"{label}.item_id must be a non-empty id used once"
        seen.add(entry["item_id"])
        if not _is_id(entry["controller"]):
            return f"{label}.controller must be a player id"
        if entry["object_kind"] not in rules_core.OBJECT_KINDS:
            return f"{label}.object_kind must be one of {sorted(rules_core.OBJECT_KINDS)}"
        if entry["timing"] not in CHAIN_TIMINGS:
            return f"{label}.timing must be one of {sorted(CHAIN_TIMINGS)}"
        if "status" in entry and entry["status"] not in CHAIN_STATUSES:
            return f"{label}.status must be one of {sorted(CHAIN_STATUSES)}"
    return None


def _check_units(value: Any) -> str | None:
    if not isinstance(value, list):
        return "units must be an array"
    seen: set[str] = set()
    for index, entry in enumerate(value):
        label = f"units[{index}]"
        if not isinstance(entry, dict):
            return f"{label} must be an object"
        unknown = set(entry) - {"object_id", "controller", "might", "damage", "exhausted", "location", "keywords"}
        if unknown:
            return f"{label} carries fields outside the vocabulary: {sorted(unknown)}"
        missing = {"object_id", "controller"} - set(entry)
        if missing:
            return f"{label} is missing {sorted(missing)}"
        if not _is_id(entry["object_id"]) or entry["object_id"] in seen:
            return f"{label}.object_id must be a non-empty id used once"
        seen.add(entry["object_id"])
        if not _is_id(entry["controller"]):
            return f"{label}.controller must be a player id"
        for field in ("might", "damage"):
            if field in entry and not _is_count(entry[field]):
                return f"{label}.{field} must be a non-negative integer"
        if "exhausted" in entry and not isinstance(entry["exhausted"], bool):
            return f"{label}.exhausted must be true or false"
        if "location" in entry and not _is_id(entry["location"]):
            return f"{label}.location must be 'base' or a battlefield id"
        if "keywords" in entry:
            keywords = entry["keywords"]
            if not isinstance(keywords, list) or any(k not in UNIT_KEYWORDS for k in keywords) \
                    or len(set(keywords)) != len(keywords):
                return f"{label}.keywords must be distinct entries from {sorted(UNIT_KEYWORDS)}"
    return None


def _check_combat(value: Any) -> str | None:
    """The Combat record a Combat procedure reads. Every field is stated; none is guessed."""
    fields = {"combat_id", "battlefield", "status", "attacker", "defender"}
    if not isinstance(value, dict):
        return "combat must be an object"
    if unknown := set(value) - fields:
        return f"combat carries fields outside the vocabulary: {sorted(unknown)}"
    if missing := fields - set(value):
        return f"combat is missing {sorted(missing)}"
    for field in ("combat_id", "battlefield", "attacker", "defender"):
        if not _is_id(value[field]):
            return f"combat.{field} must be a non-empty id"
    if value["status"] not in COMBAT_STATUSES:
        return f"combat.status must be one of {sorted(COMBAT_STATUSES)}"
    if value["attacker"] == value["defender"]:
        return "combat.attacker and combat.defender must be different players (Core 464.2.c)"
    return None


def _check_combat_designations(value: Any) -> str | None:
    """Which units fight, on which side, in which Combat. Stated per unit."""
    if not isinstance(value, list) or not value:
        return "combat_designations must be a non-empty array; which units fight is never assumed"
    seen: set[str] = set()
    for index, entry in enumerate(value):
        label = f"combat_designations[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"object_id", "combat_id", "role"}:
            return f"{label} must carry exactly object_id, combat_id, role"
        if not _is_id(entry["object_id"]) or entry["object_id"] in seen:
            return f"{label}.object_id must be a unit id designated once"
        seen.add(entry["object_id"])
        if not _is_id(entry["combat_id"]):
            return f"{label}.combat_id must be a non-empty id"
        if entry["role"] not in COMBAT_ROLES:
            return f"{label}.role must be one of {sorted(COMBAT_ROLES)}"
    return None


def _check_energy(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return "energy must map every player to an energy total"
    for player, amount in value.items():
        if not _is_id(player) or not _is_count(amount):
            return f"energy.{player} must be a non-negative integer"
    return None


def _check_power(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return "power must map every player to their Power by domain"
    for player, pools in value.items():
        if not _is_id(player) or not isinstance(pools, dict):
            return f"power.{player} must map domains to counts"
        for domain, amount in pools.items():
            if not _is_id(domain) or not _is_count(amount):
                return f"power.{player}.{domain} must be a non-negative integer"
    return None


def _check_battlefields(value: Any) -> str | None:
    if not isinstance(value, list):
        return "battlefields must be an array"
    seen: set[str] = set()
    for index, entry in enumerate(value):
        label = f"battlefields[{index}]"
        if not isinstance(entry, dict):
            return f"{label} must be an object"
        unknown = set(entry) - {"battlefield_id", "controller"}
        if unknown:
            return f"{label} carries fields outside the vocabulary: {sorted(unknown)}"
        if not _is_id(entry.get("battlefield_id")) or entry["battlefield_id"] in seen:
            return f"{label}.battlefield_id must be a non-empty id used once"
        seen.add(entry["battlefield_id"])
        if "controller" in entry and entry["controller"] is not None and not _is_id(entry["controller"]):
            return f"{label}.controller must be a player id or null"
    return None


# The closed slot vocabulary. `default` is the value used when the slot is
# optional for a question kind and the draft did not supply it; `material` says
# whether defaulting it can change the answer, which is what makes the
# assumption worth showing the user rather than burying.
SLOTS: dict[str, dict[str, Any]] = {
    "players": {"check": _check_players, "family": "both", "default": None, "material": True,
                "text": lambda v: f"The players are {', '.join(v)}."},
    "turn_player": {"check": lambda v: None if _is_id(v) else "turn_player must be a player id",
                    "family": "timing", "default": None, "material": True,
                    "text": lambda v: f"It is {v}'s turn."},
    "phase": {"check": _check_phase, "family": "timing", "default": None, "material": True,
              "text": lambda v: f"The turn is in its {v} phase."},
    "priority": {"check": _check_optional_id, "family": "timing", "default": None, "material": True,
                 "text": lambda v: "No player holds Priority." if v is None else f"{v} holds Priority."},
    "showdown_active": {"check": _check_bool, "family": "timing", "default": False, "material": True,
                        "text": lambda v: "A Showdown is open." if v else "No Showdown is open."},
    "showdown_focus": {"check": _check_optional_id, "family": "timing", "default": None, "material": True,
                       "text": lambda v: "No player holds Focus." if v is None else f"{v} holds Focus."},
    "chain_items": {"check": _check_chain_items, "family": "timing", "default": [], "material": True,
                    "text": lambda v: "The chain is empty." if not v else f"The chain holds {len(v)} item(s)."},
    "units": {"check": _check_units, "family": "effect", "default": [], "material": True,
              "text": lambda v: "No units are in play." if not v else f"{len(v)} unit(s) are in play."},
    "energy": {"check": _check_energy, "family": "effect", "default": None, "material": True,
               "text": lambda v: "Energy: " + ", ".join(f"{p}={n}" for p, n in sorted(v.items())) + "."},
    "power": {"check": _check_power, "family": "effect", "default": None, "material": True,
              "text": lambda v: "Power: " + ", ".join(
                  f"{p}=" + ("none" if not pools else "/".join(f"{d}:{n}" for d, n in sorted(pools.items())))
                  for p, pools in sorted(v.items())) + "."},
    "battlefields": {"check": _check_battlefields, "family": "effect", "default": [], "material": True,
                     "text": lambda v: "No Battlefield is in play." if not v else f"{len(v)} Battlefield(s) are in play."},
    # No default on either: a Combat that was not stated is not a Combat that
    # is assumed to be staged, and units that were not designated are not
    # assumed to fight. A kind that needs them requires them.
    "combat": {"check": _check_combat, "family": "timing", "default": None, "material": True,
               "text": lambda v: (f"A Combat ({v['status']}) is in progress at {v['battlefield']}: "
                                  f"{v['attacker']} attacking, {v['defender']} defending.")},
    "combat_designations": {"check": _check_combat_designations, "family": "effect", "default": None,
                            "material": True,
                            "text": lambda v: f"{len(v)} unit(s) carry a Combat designation."},
}

# Slots that are never assumed. A kind that names one must require it; the
# builder refuses to default one, and the gate checks no kind lists one as
# optional. Codex's S-01b rule, made mechanical: a Combat that was not stated
# is not a Combat, and units that were not designated do not fight.
UNDEFAULTABLE = frozenset({"combat", "combat_designations"})

# Slots whose default is computed from the players list rather than fixed.
PLAYER_KEYED_DEFAULTS = {"energy": lambda players: {p: 0 for p in players},
                         "power": lambda players: {p: {} for p in players}}

QUESTION_KINDS: dict[str, dict[str, Any]] = {
    "timing_priority": {
        "family": "timing",
        "required": {"players", "turn_player", "phase"},
        "optional": {"priority", "showdown_active", "showdown_focus", "chain_items"},
    },
    "chain_resolution": {
        "family": "timing",
        "required": {"players", "turn_player", "phase", "chain_items"},
        "optional": {"priority", "showdown_active", "showdown_focus"},
    },
    "showdown_focus": {
        "family": "timing",
        "required": {"players", "turn_player", "phase", "showdown_active", "showdown_focus"},
        "optional": {"priority", "chain_items"},
    },
    "unit_damage": {
        "family": "effect",
        "required": {"players", "units"},
        "optional": {"energy", "power", "battlefields"},
    },
    "resource_payment": {
        "family": "effect",
        "required": {"players", "energy", "power"},
        "optional": {"units", "battlefields"},
    },
    # S-01b. The two halves of the position a Combat procedure runs over: the
    # timing side carries the record and the open Combat Showdown, the effect
    # side carries the board with its designated units. Every Combat fact is
    # required; the only optional slots are the ones every timing or effect
    # state has anyway.
    "combat_step": {
        "family": "timing",
        "required": {"players", "turn_player", "phase", "showdown_active", "showdown_focus", "combat"},
        "optional": {"priority", "chain_items"},
    },
    "combat_board": {
        "family": "effect",
        "required": {"players", "units", "battlefields", "combat_designations"},
        "optional": {"energy", "power"},
    },
}

# What materialization adds that no producer supplied. These are shown to the
# user with the same weight as a defaulted slot, because a reader who cannot see
# them cannot tell whether the answer turned on one of them.
DERIVED_SLOTS = {
    "turn_order": "Turn order follows the order the players were listed.",
    "outstanding_tasks": "No Outstanding Tasks are pending.",
    "consecutive_passes": "No player has passed yet on the current chain.",
    "showdown_kind": "The open Showdown is a Combat Showdown.",
    "chain_initiated_by": "The chain was initiated by a played card.",
    "object_owner": "Each unit is owned by the player who controls it.",
    "empty_zones": "Every deck, hand, trash, and banishment is empty.",
    "replacement_effects": "No replacement effects are in play.",
    # The Combat record fields the kernel requires that a draft cannot state
    # because they are bookkeeping rather than facts about the position. Each
    # is what the kernel itself uses when nothing has happened yet.
    "combat_participants": "The Combat's participants are its attacker and its defender.",
    "combat_battlefield_identity": "The Combat Battlefield is at its first generation.",
    "combat_triggered_identities": "No Attack or Defend trigger has fired in this Combat yet.",
    "showdown_at_combat_battlefield": "The open Showdown is the Combat Showdown at the Combat's Battlefield.",
}

ORIGINS = {"stated", "default", "derived"}


def _downgrade(reason: str, *, missing: list[str] | None = None, rejected: list[str] | None = None,
               engine_errors: list[str] | None = None, detail: str) -> dict[str, Any]:
    return {
        "tier": DOWNGRADE_TIERS[reason],
        "reason": reason,
        "missing_fields": sorted(missing or []),
        "rejected_fields": sorted(rejected or []),
        "engine_errors": list(engine_errors or []),
        "detail": detail,
    }


def _shell(question: str, question_kind: str, draft: Any, family: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "question": question,
        "question_kind": question_kind,
        "state_family": family,
        "input_draft": copy.deepcopy(draft),
        "buildable": False,
        "supplied": [],
        "assumptions": [],
        "state": None,
        "state_hash": None,
        "downgrade": None,
    }


def _materialize_timing(values: dict[str, Any]) -> dict[str, Any]:
    items = [{
        "id": entry["item_id"],
        "controller": entry["controller"],
        "object_kind": entry["object_kind"],
        "timing": entry["timing"],
        "status": entry.get("status", "finalized"),
        "ability_kind": None,
    } for entry in values["chain_items"]]
    active = values["showdown_active"]
    showdown = {"active": active, "kind": "combat" if active else None, "focus": values["showdown_focus"]}
    state = {
        "schema_version": rules_core.SCHEMA_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "players": list(values["players"]),
        "turn_order": list(values["players"]),
        "turn_player": values["turn_player"],
        "phase": values["phase"],
        "showdown": showdown,
        "priority": values["priority"],
        "outstanding_tasks": [],
        "chain": {
            "initiated_by": "played_card" if items else None,
            "items": items,
            "consecutive_passes": [],
        },
    }
    combat = values.get("combat")
    if combat is not None:
        # Exactly the record rules_core validates and combat.py reads. The
        # participants, identity and trigger bookkeeping are the kernel's own
        # starting values, and each is listed as a derived assumption.
        showdown["battlefield"] = combat["battlefield"]
        state["combat"] = {
            "combat_id": combat["combat_id"],
            "battlefield": combat["battlefield"],
            "battlefield_identity": f"{combat['battlefield']}@0",
            "status": combat["status"],
            "attacker": combat["attacker"],
            "defender": combat["defender"],
            "participants": [combat["attacker"], combat["defender"]],
            "triggered_identities": {"attacker": [], "defender": []},
        }
    return state


def _materialize_effect(values: dict[str, Any]) -> dict[str, Any]:
    players = list(values["players"])
    battlefields = {entry["battlefield_id"]: {"controller": entry.get("controller"), "objects": []}
                    for entry in values["battlefields"]}
    objects: dict[str, Any] = {}
    base: dict[str, list[str]] = {player: [] for player in players}
    for unit in values["units"]:
        object_id = unit["object_id"]
        controller = unit["controller"]
        objects[object_id] = {
            "owner": controller,
            "controller": controller,
            "kind": "unit",
            "base_might": unit.get("might", 0),
            "might_modifiers": [],
            "damage": unit.get("damage", 0),
            "exhausted": unit.get("exhausted", False),
        }
        if unit.get("keywords"):
            objects[object_id]["keywords"] = list(unit["keywords"])
        location = unit.get("location", "base")
        if location == "base":
            base[controller].append(object_id)
        else:
            battlefields[location]["objects"].append(object_id)
    for entry in values.get("combat_designations") or []:
        objects[entry["object_id"]]["combat_designation"] = {"combat_id": entry["combat_id"],
                                                             "role": entry["role"]}
    return {
        "schema_version": effect_ir.STATE_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "players": {player: {
            "zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [],
                      "base": base[player], "rune_deck": []},
            "resources": {"energy": values["energy"][player], "power": dict(values["power"][player])},
        } for player in players},
        "objects": objects,
        "battlefields": battlefields,
        "replacement_effects": [],
    }


def _derived_for(family: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    if family == "timing":
        entries = [
            ("turn_order", list(values["players"])),
            ("outstanding_tasks", []),
            ("consecutive_passes", []),
        ]
        if values["showdown_active"]:
            entries.append(("showdown_kind", "combat"))
        if values["chain_items"]:
            entries.append(("chain_initiated_by", "played_card"))
        if values.get("combat") is not None:
            combat = values["combat"]
            entries.extend([
                ("combat_participants", [combat["attacker"], combat["defender"]]),
                ("combat_battlefield_identity", f"{combat['battlefield']}@0"),
                ("combat_triggered_identities", {"attacker": [], "defender": []}),
                ("showdown_at_combat_battlefield", combat["battlefield"]),
            ])
    else:
        entries = [
            ("object_owner", None),
            ("empty_zones", None),
            ("replacement_effects", []),
        ]
    return [{"slot": name, "origin": "derived", "value": value, "material": True,
             "text": DERIVED_SLOTS[name]} for name, value in entries]


def build_state_assumption(*, question: str, question_kind: str, draft: Any) -> dict[str, Any]:
    """Build the minimum state for one question, or say what stopped it."""
    if not _is_id(question):
        raise StateBuilderError("question must be a non-empty string")

    profile = QUESTION_KINDS.get(question_kind)
    if profile is None:
        artifact = _shell(question, question_kind, draft, None)
        artifact["downgrade"] = _downgrade(
            "unrecognized_question_kind",
            detail=f"{question_kind!r} is not a question kind this builder covers; "
                   f"known kinds are {sorted(QUESTION_KINDS)}")
        return artifact

    family = profile["family"]
    artifact = _shell(question, question_kind, draft, family)

    if not isinstance(draft, dict):
        artifact["downgrade"] = _downgrade("schema_outside_field", rejected=["$draft"],
                                           detail="the state draft must be a JSON object")
        return artifact

    # Stage 2. A key outside the vocabulary refuses the draft whole. It is not
    # dropped: a producer that emits a field we do not model has told us it
    # believes something about this position that we cannot check.
    outside = sorted(set(draft) - set(SLOTS))
    if outside:
        artifact["downgrade"] = _downgrade(
            "schema_outside_field", rejected=outside,
            detail="the draft carries keys outside the slot vocabulary; the draft is refused, not cleaned")
        return artifact

    # Stage 3. In the vocabulary, but not part of this question kind.
    allowed = profile["required"] | profile["optional"]
    off_kind = sorted(set(draft) - allowed)
    if off_kind:
        artifact["downgrade"] = _downgrade(
            "slot_not_in_question_kind", rejected=off_kind,
            detail=f"question kind {question_kind!r} does not read {off_kind}; "
                   "an unread slot is refused rather than ignored")
        return artifact

    # Stage 4. Types, all offenders at once.
    bad_types: list[str] = []
    details: list[str] = []
    for slot in sorted(draft):
        message = SLOTS[slot]["check"](draft[slot])
        if message:
            bad_types.append(slot)
            details.append(message)
    if bad_types:
        artifact["downgrade"] = _downgrade("slot_type_invalid", rejected=bad_types,
                                           detail="; ".join(details))
        return artifact

    # Stage 5. Required slots.
    missing = sorted(profile["required"] - set(draft))
    if missing:
        artifact["downgrade"] = _downgrade(
            "missing_required_slot", missing=missing,
            detail=f"question kind {question_kind!r} cannot be answered without {missing}")
        return artifact

    # Stage 6. Cross-slot consistency, including the conditionally required
    # slots. An open Showdown without a named Focus is the case that matters:
    # the Focus holder is not guessable, so the slot is named as missing.
    players = list(draft["players"])
    conditional_missing: list[str] = []
    out_of_scope: list[str] = []
    scope_details: list[str] = []

    if draft.get("showdown_active") is True and draft.get("showdown_focus") is None:
        conditional_missing.append("showdown_focus")
    combat = draft.get("combat")
    if combat is not None:
        # A Combat in progress is a Combat Showdown (464.2). A draft that
        # states a Combat and no open Showdown has left out a fact the record
        # depends on, so the slot is named as missing rather than switched on.
        if draft.get("showdown_active") is not True:
            conditional_missing.append("showdown_active")
        for role in ("attacker", "defender"):
            if combat[role] not in players:
                out_of_scope.append(f"combat.{role}")
                scope_details.append(f"combat.{role} names {combat[role]!r}, who is not a player")
    designations = draft.get("combat_designations")
    if designations is not None:
        by_id = {unit["object_id"]: unit for unit in draft.get("units", []) or []}
        for index, entry in enumerate(designations):
            unit = by_id.get(entry["object_id"])
            if unit is None:
                out_of_scope.append(f"combat_designations[{index}].object_id")
                scope_details.append(f"combat_designations[{index}] designates {entry['object_id']!r}, "
                                     f"which is not one of the units")
            elif unit.get("location", "base") == "base":
                # A designated unit that is not at a Battlefield is not in the
                # fight (465.1); saying it is designated and leaving it at base
                # is a position the kernel would read as "no combatant here".
                out_of_scope.append(f"combat_designations[{index}].object_id")
                scope_details.append(f"combat_designations[{index}] designates {entry['object_id']!r}, "
                                     f"which is at base rather than at a Battlefield")
        if len({entry["combat_id"] for entry in designations}) > 1:
            out_of_scope.append("combat_designations")
            scope_details.append("combat_designations name more than one Combat; a board carries one")
    if family == "effect":
        for slot in ("energy", "power"):
            if slot in draft and set(draft[slot]) != set(players):
                out_of_scope.append(slot)
                scope_details.append(f"{slot} must name exactly the players {sorted(players)}")
    for slot, id_fields in (("chain_items", ("controller",)), ("units", ("controller",))):
        for index, entry in enumerate(draft.get(slot, []) or []):
            for field in id_fields:
                if entry[field] not in players:
                    out_of_scope.append(f"{slot}[{index}].{field}")
                    scope_details.append(f"{slot}[{index}].{field} names {entry[field]!r}, who is not a player")
    for slot in ("turn_player", "priority", "showdown_focus"):
        if slot in draft and draft[slot] is not None and draft[slot] not in players:
            out_of_scope.append(slot)
            scope_details.append(f"{slot} names {draft[slot]!r}, who is not a player")
    known_battlefields = {entry["battlefield_id"] for entry in draft.get("battlefields", []) or []}
    for index, unit in enumerate(draft.get("units", []) or []):
        location = unit.get("location", "base")
        if location != "base" and location not in known_battlefields:
            out_of_scope.append(f"units[{index}].location")
            scope_details.append(f"units[{index}].location names Battlefield {location!r}, which is not in play")
    for index, entry in enumerate(draft.get("battlefields", []) or []):
        controller = entry.get("controller")
        if controller is not None and controller not in players:
            out_of_scope.append(f"battlefields[{index}].controller")
            scope_details.append(f"battlefields[{index}].controller names {controller!r}, who is not a player")

    if conditional_missing:
        reasons = {
            "showdown_focus": "an open Showdown has a Focus holder, and who holds it is not "
                              "derivable from the rest of the draft",
            "showdown_active": "a Combat in progress is a Combat Showdown (Core 464.2); a draft "
                               "that states a Combat and no open Showdown has left that out",
        }
        artifact["downgrade"] = _downgrade(
            "missing_required_slot", missing=conditional_missing,
            detail="; ".join(reasons[slot] for slot in sorted(set(conditional_missing))))
        return artifact
    if out_of_scope:
        artifact["downgrade"] = _downgrade("slot_value_out_of_scope", rejected=out_of_scope,
                                           detail="; ".join(scope_details))
        return artifact

    # Stage 7. Fill the optional slots, record every fill, and let the engine
    # decide whether what we built is a state.
    values: dict[str, Any] = {}
    supplied: list[dict[str, str]] = []
    assumptions: list[dict[str, Any]] = []
    for slot in sorted(profile["required"] | profile["optional"]):
        if slot in draft:
            values[slot] = copy.deepcopy(draft[slot])
            supplied.append({"slot": slot, "origin": "stated"})
            continue
        if slot in PLAYER_KEYED_DEFAULTS:
            value = PLAYER_KEYED_DEFAULTS[slot](players)
        else:
            value = copy.deepcopy(SLOTS[slot]["default"])
            if value is None and slot in UNDEFAULTABLE:
                # A slot with no default is one the contract says is never
                # assumed. Reaching here means a kind listed it as optional,
                # which is a contract error in this module, not in the draft.
                raise StateBuilderError(
                    f"slot {slot!r} has no default and cannot be optional; the "
                    f"{question_kind!r} kind must require it or not name it")
        values[slot] = value
        assumptions.append({"slot": slot, "origin": "default", "value": value,
                            "material": SLOTS[slot]["material"], "text": SLOTS[slot]["text"](value)})

    if family == "timing":
        state = _materialize_timing(values)
        engine_errors = rules_core.validate_state(state)
        state_hash = rules_core.state_hash(state)
    else:
        state = _materialize_effect(values)
        engine_errors = effect_ir.validate_state(state)
        state_hash = effect_ir.hash_value(state)

    if engine_errors:
        artifact["downgrade"] = _downgrade(
            "engine_rejected_state", engine_errors=list(engine_errors),
            detail="the draft was well formed but the engine refused the state it describes")
        return artifact

    artifact["buildable"] = True
    artifact["supplied"] = supplied
    artifact["assumptions"] = assumptions + _derived_for(family, values)
    artifact["state"] = state
    artifact["state_hash"] = state_hash
    return artifact


def apply_correction(artifact: dict[str, Any], corrections: dict[str, Any], *,
                     drop: tuple[str, ...] = ()) -> dict[str, Any]:
    """Re-run the whole build with the user's corrections. Nothing is patched.

    The input artifact is not touched. What comes back is a fresh build from a
    corrected draft, so a corrected answer never carries a stale half of the
    previous one.
    """
    problems = validate_assumption_artifact(artifact)
    if problems:
        raise StateBuilderError(f"cannot correct an invalid artifact: {problems}")
    if not isinstance(corrections, dict):
        raise StateBuilderError("corrections must be an object")
    draft = copy.deepcopy(artifact["input_draft"])
    if not isinstance(draft, dict):
        draft = {}
    for slot in drop:
        draft.pop(slot, None)
    draft.update(copy.deepcopy(corrections))
    return build_state_assumption(question=artifact["question"],
                                  question_kind=artifact["question_kind"],
                                  draft=draft)


REQUIRED_TOP = {"schema_version", "ruleset", "question", "question_kind", "state_family",
                "input_draft", "buildable", "supplied", "assumptions", "state", "state_hash",
                "downgrade"}
DOWNGRADE_FIELDS = {"tier", "reason", "missing_fields", "rejected_fields", "engine_errors", "detail"}


def validate_assumption_artifact(value: Any) -> list[str]:
    """Check a state-assumption artifact, including that the engine still accepts its state."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["artifact must be a JSON object"]
    missing = REQUIRED_TOP - set(value)
    unknown = set(value) - REQUIRED_TOP
    if missing:
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    if missing:
        return errors

    if value["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if value["ruleset"] != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("ruleset must match the kernel baseline")
    if not _is_id(value["question"]):
        errors.append("question must be a non-empty string")
    if not isinstance(value["buildable"], bool):
        errors.append("buildable must be boolean")

    kind = value["question_kind"]
    profile = QUESTION_KINDS.get(kind)
    if profile is None:
        if value["state_family"] is not None:
            errors.append("an unrecognized question kind has no state family")
        if value["buildable"]:
            errors.append("an unrecognized question kind cannot be buildable")
    elif value["state_family"] != profile["family"]:
        errors.append(f"state_family must be {profile['family']!r} for question kind {kind!r}")

    supplied = value["supplied"]
    if not isinstance(supplied, list) or any(
            not isinstance(item, dict) or set(item) != {"slot", "origin"} or item["origin"] != "stated"
            or item["slot"] not in SLOTS for item in supplied):
        errors.append("supplied must list {slot, origin: 'stated'} entries over known slots")
        supplied = []
    supplied_slots = [item["slot"] for item in supplied if isinstance(item, dict)]
    if len(set(supplied_slots)) != len(supplied_slots):
        errors.append("supplied names a slot more than once")

    assumptions = value["assumptions"]
    assumed_slots: list[str] = []
    if not isinstance(assumptions, list):
        errors.append("assumptions must be an array")
        assumptions = []
    for index, entry in enumerate(assumptions):
        label = f"assumptions[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"slot", "origin", "value", "material", "text"}:
            errors.append(f"{label} must carry slot, origin, value, material, text")
            continue
        if entry["origin"] not in {"default", "derived"}:
            errors.append(f"{label}.origin must be default or derived")
        elif entry["origin"] == "default" and entry["slot"] not in SLOTS:
            errors.append(f"{label} defaults an unknown slot {entry['slot']!r}")
        elif entry["origin"] == "derived" and entry["slot"] not in DERIVED_SLOTS:
            errors.append(f"{label} derives an unknown slot {entry['slot']!r}")
        if not isinstance(entry["material"], bool):
            errors.append(f"{label}.material must be boolean")
        if not _is_id(entry["text"]):
            errors.append(f"{label}.text must be a non-empty string the user can read and correct")
        if entry.get("origin") == "default":
            assumed_slots.append(entry["slot"])
    overlap = sorted(set(assumed_slots) & set(supplied_slots))
    if overlap:
        errors.append(f"a slot cannot be both stated and assumed: {overlap}")

    downgrade = value["downgrade"]
    if value["buildable"]:
        if downgrade is not None:
            errors.append("a buildable artifact carries no downgrade")
        if value["state"] is None or not _is_id(value["state_hash"]):
            errors.append("a buildable artifact carries a state and its hash")
        elif profile is not None:
            # The claim is checked, not trusted: the engine's own validator
            # decides, and the hash must be the hash of the state that is here.
            if profile["family"] == "timing":
                engine_errors = rules_core.validate_state(value["state"])
                expected_hash = rules_core.state_hash(value["state"])
            else:
                engine_errors = effect_ir.validate_state(value["state"])
                expected_hash = effect_ir.hash_value(value["state"])
            if engine_errors:
                errors.append(f"the engine rejects this artifact's state: {engine_errors}")
            if value["state_hash"] != expected_hash:
                errors.append("state_hash is not the hash of the state carried here")
        if profile is not None:
            covered = set(supplied_slots) | set(assumed_slots)
            expected = profile["required"] | profile["optional"]
            if covered != expected:
                errors.append(f"a buildable artifact accounts for every slot of its kind; "
                              f"missing {sorted(expected - covered)}, extra {sorted(covered - expected)}")
            unmet = sorted(profile["required"] - set(supplied_slots))
            if unmet:
                errors.append(f"a required slot was assumed rather than stated: {unmet}")
    else:
        if value["state"] is not None or value["state_hash"] is not None:
            errors.append("an unbuildable artifact carries no state and no hash")
        if supplied or assumptions:
            errors.append("an unbuildable artifact makes no assumptions and reports no supplied slots")
        if not isinstance(downgrade, dict) or set(downgrade) != DOWNGRADE_FIELDS:
            errors.append(f"downgrade must carry exactly {sorted(DOWNGRADE_FIELDS)}")
            return errors
        reason = downgrade["reason"]
        if reason not in DOWNGRADE_REASONS:
            errors.append(f"downgrade.reason must be one of {sorted(DOWNGRADE_REASONS)}")
        elif downgrade["tier"] != DOWNGRADE_TIERS[reason]:
            errors.append(f"downgrade.reason {reason!r} downgrades to tier "
                          f"{DOWNGRADE_TIERS[reason]!r}, not {downgrade['tier']!r}")
        if downgrade["tier"] not in TIERS:
            errors.append(f"downgrade.tier must be one of {sorted(TIERS)}")
        for field in ("missing_fields", "rejected_fields", "engine_errors"):
            if not isinstance(downgrade[field], list) or any(not _is_id(v) for v in downgrade[field]):
                errors.append(f"downgrade.{field} must be an array of non-empty strings")
        if not _is_id(downgrade["detail"]):
            errors.append("downgrade.detail must say what stopped the build")
        if reason in NAMES_MISSING and not downgrade["missing_fields"]:
            errors.append(f"downgrade.reason {reason!r} must name the missing field")
        if reason in NAMES_REJECTED and not downgrade["rejected_fields"]:
            errors.append(f"downgrade.reason {reason!r} must name the rejected field")
        if reason == "engine_rejected_state" and not downgrade["engine_errors"]:
            errors.append("an engine refusal carries the engine's own errors")
        if reason != "engine_rejected_state" and downgrade["engine_errors"]:
            errors.append("only an engine refusal carries engine errors")
        if reason == "unrecognized_question_kind" and (downgrade["missing_fields"] or downgrade["rejected_fields"]):
            errors.append("an unrecognized question kind names no field")

    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate a state-assumption.v1 artifact.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build the minimum state for one question")
    build.add_argument("--question", required=True)
    build.add_argument("--kind", required=True)
    build.add_argument("--draft", required=True, help="path to the producer's state draft")

    check = sub.add_parser("validate", help="validate an artifact, including its state")
    check.add_argument("artifact")

    correct = sub.add_parser("correct", help="re-run a build with the user's corrections")
    correct.add_argument("artifact")
    correct.add_argument("--corrections", required=True)
    correct.add_argument("--drop", nargs="*", default=[])

    kinds = sub.add_parser("kinds", help="list the question kinds and their slots")
    kinds.set_defaults(_kinds=True)

    args = parser.parse_args(argv)
    if args.command == "kinds":
        json.dump({kind: {"family": p["family"], "required": sorted(p["required"]),
                          "optional": sorted(p["optional"])} for kind, p in sorted(QUESTION_KINDS.items())},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    if args.command == "build":
        artifact = build_state_assumption(question=args.question, question_kind=args.kind,
                                          draft=_load(args.draft))
    elif args.command == "correct":
        artifact = apply_correction(_load(args.artifact), _load(args.corrections), drop=tuple(args.drop))
    else:
        problems = validate_assumption_artifact(_load(args.artifact))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("valid" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    json.dump(artifact, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if artifact["buildable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
