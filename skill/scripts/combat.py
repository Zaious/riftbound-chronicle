#!/usr/bin/env python3
"""
Combat procedures — ADR-0008 §1–3 (C-26): staging, opening, and designation
synchronization for the G1 Combat milestone.

The timing state carries one optional `combat` record (stable `combat_id`,
Battlefield identity, status, attacker, defender, the identities whose
Attack/Defend triggers already fired). The effect state carries each Unit's
`combat_designation` {combat_id, role}. Every procedure here is pure: it takes
both states, returns both next states with their hashes, or a refusal.

Absence of the record means no Combat is staged or open. It is never treated
as an unknown Combat fact: a caller that claims a Combat but cannot supply the
Battlefield identity, participants and designations gets `unsupported`.

Decisions for these two-state procedures use engine-decisions.v1 with
`input_hash` = combined_input_hash(timing_state, effect_state); the result
carries that hash as `input_hash` so a caller knows what to decide against.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as _ed  # noqa: E402
from effect_ir import battlefield_identity, find_location, hash_value, object_identity, same_side, validate_state, zone_class  # noqa: E402
from rules_core import COMBAT_STATUSES, schedule_triggered_items, state_hash, validate_state as validate_timing_state  # noqa: E402

COMBAT_STEP_VERSION = "riftbound-combat-step-result.v1"
ROLES = ("attacker", "defender")
TRIGGER_FIELDS = {"attacker": "attack_triggers", "defender": "defend_triggers"}
# Statuses during which a Cleanup keeps designations in step with presence (323.2).
IN_PROGRESS = {"open", "damage_assigned", "damage_dealt", "cleanup_done", "result_determined"}
LOCATION_DECISION_ID = "combat_location"


def combined_input_hash(timing_state: dict[str, Any], effect_state: dict[str, Any]) -> str:
    """The input of a two-state procedure is the pair; decisions bind to it."""
    return hash_value({"timing_state": timing_state, "effect_state": effect_state})


def _base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": COMBAT_STEP_VERSION, "step": step,
            "input_timing_state_hash": state_hash(timing_state), "input_effect_state_hash": hash_value(effect_state),
            "input_hash": combined_input_hash(timing_state, effect_state)}


def _refuse(base: dict[str, Any], code: str, reason: str, locators: list[str], **extra: Any) -> dict[str, Any]:
    return {**base, "valid": True, "committed": False, "applied": False, "reason_code": code, "reason": reason, "rule_locators": locators, **extra}


def _unsupported(base: dict[str, Any], code: str, reason: str, locators: list[str], **extra: Any) -> dict[str, Any]:
    return {**base, "valid": True, "committed": False, "unsupported": True, "reason_code": code, "reason": reason, "rule_locators": locators, **extra}


def _invalid(base: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    return {**base, "valid": False, "committed": False, "errors": errors, "reason": "; ".join(errors)}


def _validate_both(base: dict[str, Any], timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None) -> dict[str, Any] | None:
    errors = [f"timing: {e}" for e in validate_timing_state(timing_state)] + [f"effect: {e}" for e in validate_state(effect_state)]
    if not errors and engine_decisions is not None:
        errors += _ed.validate_engine_decisions(engine_decisions)
        if not errors and engine_decisions.get("input_hash") != base["input_hash"]:
            errors.append("engine_decisions.input_hash does not match the combined timing/effect input of this procedure")
    return _invalid(base, errors) if errors else None


def _commit(base: dict[str, Any], next_timing: dict[str, Any], next_effect: dict[str, Any], *, trace: dict[str, Any], locators: list[str], **extra: Any) -> dict[str, Any]:
    problems = [f"timing: {e}" for e in validate_timing_state(next_timing)] + [f"effect: {e}" for e in validate_state(next_effect)]
    if problems:
        return _invalid(base, ["procedure produced an invalid state: " + "; ".join(problems)])
    return {**base, "valid": True, "committed": True, "applied": True, "reason_code": "ok",
            "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
            "next_effect_state": next_effect, "next_effect_state_hash": hash_value(next_effect),
            "trace": trace, "rule_locators": locators, **extra}


# ------------------------------------------------------------------ board reads --

def units_at(effect_state: dict[str, Any], battlefield_id: str) -> dict[str, list[str]]:
    """controller -> Units present at the Battlefield (Units only, 461)."""
    present: dict[str, list[str]] = {}
    for object_id in effect_state["battlefields"][battlefield_id]["objects"]:
        obj = effect_state["objects"].get(object_id, {})
        if obj.get("kind") == "unit":
            present.setdefault(obj["controller"], []).append(object_id)
    return present


def combat_candidates(effect_state: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Battlefields where Combat is Staged (323.9, 461): Contested was applied
    and Units of exactly two opposing players are present. A Battlefield with
    three or more controllers is reported, never reduced to a pair (462.3)."""
    candidates: list[str] = []
    considered: list[dict[str, Any]] = []
    for battlefield_id in sorted(effect_state["battlefields"]):
        battlefield = effect_state["battlefields"][battlefield_id]
        present = units_at(effect_state, battlefield_id)
        controllers = sorted(present)
        record = {"battlefield": battlefield_id, "controllers": controllers, "contested": bool(battlefield.get("contested"))}
        if len(controllers) < 2:
            record["verdict"] = "fewer_than_two_controllers"
        elif len(controllers) > 2:
            record["verdict"] = "more_than_two_controllers"
        elif same_side(effect_state, controllers[0], controllers[1]):
            record["verdict"] = "controllers_are_not_opposing"
        elif not battlefield.get("contested"):
            record["verdict"] = "not_contested"
        else:
            record["verdict"] = "staged"
            candidates.append(battlefield_id)
        considered.append(record)
    return candidates, considered


def _quiet(timing_state: dict[str, Any]) -> str | None:
    if timing_state.get("phase") != "main":
        return "combat_requires_main_phase"
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"]:
        return "combat_requires_quiet_cleanup_boundary"
    return None


# --------------------------------------------------------------------- staging --

def stage_combat(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 323.9 / 323.13 / 323.14, 461–462: from a quiet Cleanup boundary,
    mark the Combat that will open. Zero candidates is a supported no-op. Two
    or more in a Neutral Open State need the Turn Player's location_selection;
    during a Showdown only that Showdown's Battlefield can stage (323.14)."""
    base = _base("stage_combat", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if code := _quiet(timing_state):
        return _refuse(base, code, "Combat is staged during a Cleanup with nothing on the chain and no outstanding task (460)", ["Core 460", "Core 323.13"])
    existing = timing_state.get("combat")
    if existing is not None and existing["status"] not in {"staged", "closed"}:
        return _refuse(base, "combat_in_progress", f"a Combat ({existing['combat_id']}) is in progress; no other Combat opens while it lasts (460)", ["Core 460"])
    showdown = timing_state["showdown"]
    if showdown["active"] and not showdown.get("battlefield"):
        return _unsupported(base, "showdown_location_unknown", "the active Showdown does not say which Battlefield it is at; the staged Combat cannot be matched to it (323.14)", ["Core 323.14", "Core 464.1"])
    candidates, considered = combat_candidates(effect_state)
    crowded = [c["battlefield"] for c in considered if c["verdict"] == "more_than_two_controllers"]
    if crowded:
        return _unsupported(base, "multi_player_battlefield", f"Units of three or more players are at {crowded}; Combat between more than two players is not modelled and is never reduced to a pair (462, 462.3)", ["Core 462", "Core 462.3"], battlefields=crowded)
    turn_player = timing_state["turn_player"]
    selection = "none"
    if showdown["active"]:
        candidates = [bf for bf in candidates if bf == showdown["battlefield"]]
        selection = "showdown_battlefield"
    trace = {"considered": considered, "candidates": candidates}
    if not candidates:
        next_timing = copy.deepcopy(timing_state)
        if existing is not None and existing["status"] == "staged":
            del next_timing["combat"]  # 461.2: a Combat that stopped being staged is not resolved
        trace.update({"chosen": None, "selection": selection, "outcome": "no_staged_combat"})
        return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=["Core 323.9", "Core 461", "Core 461.2"])
    if len(candidates) == 1:
        chosen = candidates[0]
        selection = selection if selection != "none" else "sole_candidate"
    else:
        entry = next((e for e in _ed.entries(engine_decisions, kind="location_selection") if e["decision_id"] == LOCATION_DECISION_ID), None)
        if entry is None:
            return {**base, "valid": True, "committed": False, "reason_code": "location_selection_required",
                    "reason": f"Combats are staged at {candidates}; the Turn Player {turn_player} chooses which opens first (461.1, 323.13)",
                    "decision_ids": [LOCATION_DECISION_ID], "decision_controller": turn_player, "options": candidates,
                    "rule_locators": ["Core 461.1", "Core 323.13"], "trace": trace}
        if entry["controller"] != turn_player:
            return _refuse(base, "decision_controller_mismatch", f"the Combat location was chosen by {entry['controller']!r}; it is the Turn Player's choice (461.1)", ["Core 461.1"])
        if entry["value"] not in candidates:
            return _invalid(base, [f"location_selection {LOCATION_DECISION_ID} names {entry['value']!r}; the staged Battlefields are {candidates}"])
        chosen = entry["value"]
        selection = "turn_player_decision"
    present = units_at(effect_state, chosen)
    record = {
        "combat_id": f"combat:{chosen}:{base['input_hash'][7:19]}",
        "battlefield": chosen, "battlefield_identity": battlefield_identity(effect_state, chosen) or f"{chosen}@0",
        "status": "staged", "attacker": None, "defender": None, "participants": sorted(present),
        "triggered_identities": {"attacker": [], "defender": []},
    }
    next_timing = copy.deepcopy(timing_state)
    next_timing["combat"] = record
    trace.update({"chosen": chosen, "selection": selection, "outcome": "staged", "combat_id": record["combat_id"], "participants": record["participants"]})
    return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=["Core 323.9", "Core 323.13", "Core 461", "Core 461.1", "Core 462"])


# --------------------------------------------------------------------- opening --

def _designation_triggers(effect_state: dict[str, Any], record: dict[str, Any], object_id: str, role: str, batch_id: str, batch_sequence: int) -> tuple[list[dict[str, Any]], str | None]:
    """Attack/Defend triggers of one Unit that just gained a designation, at
    most once per object identity per Combat (383.4.e.2.a, 383.4.f.2.a).
    Returns (descriptors, newly recorded identity or None)."""
    identity = object_identity(effect_state, object_id) or f"{object_id}@0"
    if identity in record["triggered_identities"][role]:
        return [], None
    obj = effect_state["objects"][object_id]
    descriptors = []
    location = find_location(effect_state, object_id)
    for descriptor in obj.get(TRIGGER_FIELDS[role], []) or []:
        condition = descriptor.get("condition")
        if condition is not None and condition["kind"] == "at_battlefield" and (location is None or location[0] != "battlefield"):
            continue  # 383.4.e.2.b: an unmet extra requirement means no trigger this Combat
        copied = {k: v for k, v in descriptor.items() if k != "condition"}
        copied.update({"trigger_kind": "triggered", "batch_id": batch_id, "batch_sequence": batch_sequence,
                       "combat_id": record["combat_id"], "role": role, "battlefield_identity": record["battlefield_identity"], "source_identity": identity})
        descriptors.append(copied)
    return descriptors, identity


def open_combat(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 464.2: open the staged Combat — attacker is the player who applied
    Contested (464.2.c.1), the defender the other participant; a new Combat
    Showdown gives the attacker Focus, an existing Showdown at that Battlefield
    keeps its Focus (464.2.c.1.a–b); Units present gain designations; their
    Attack/Defend triggers go on the Combat Chain attacker first, then the
    defender (464.2.e.1); the State closes only when an item was scheduled."""
    base = _base("open_combat", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    record = timing_state.get("combat")
    if record is None or record["status"] != "staged":
        return _refuse(base, "combat_not_staged", "open_combat needs a staged Combat record from stage_combat (461, 464.1)", ["Core 461", "Core 464.1"])
    if code := _quiet(timing_state):
        return _refuse(base, code, "Combat opens during a Cleanup with nothing on the chain and no outstanding task (460)", ["Core 460", "Core 464.1"])
    battlefield_id = record["battlefield"]
    battlefield = effect_state["battlefields"].get(battlefield_id)
    if battlefield is None or (battlefield_identity(effect_state, battlefield_id) or f"{battlefield_id}@0") != record["battlefield_identity"]:
        return _refuse(base, "combat_battlefield_changed", f"the staged Battlefield {battlefield_id} is not the same entity any more", ["Core 461.2"])
    present = units_at(effect_state, battlefield_id)
    candidates, _ = combat_candidates(effect_state)
    if battlefield_id not in candidates or sorted(present) != record["participants"]:
        return _refuse(base, "combat_no_longer_staged", f"Units of exactly the two staged players are no longer present at {battlefield_id}; the Combat is not resolved (461.2, 462)", ["Core 461.2", "Core 462"], participants_now=sorted(present))
    attacker = battlefield.get("contested_by")
    if not battlefield.get("contested") or attacker not in record["participants"]:
        return _unsupported(base, "attacker_attribution_missing", f"the player who applied Contested to {battlefield_id} is not recorded among the participants {record['participants']} (contested_by={attacker!r}); the attacker is not guessed (464.2.c.1)", ["Core 464.2.c.1", "Core 464.2.c.2"])
    defender = next(p for p in record["participants"] if p != attacker)
    showdown = timing_state["showdown"]
    if showdown["active"]:
        if showdown.get("battlefield") != battlefield_id:
            return _refuse(base, "showdown_elsewhere", f"a Showdown is ongoing at {showdown.get('battlefield')!r}; Combat cannot open at {battlefield_id} while it lasts (460)", ["Core 460", "Core 464.1"])
        opened_with, focus = "existing_showdown", showdown["focus"]
    else:
        opened_with, focus = "new_showdown", attacker
    next_effect = copy.deepcopy(effect_state)
    next_record = copy.deepcopy(record)
    next_record.update({"status": "open", "attacker": attacker, "defender": defender, "opened_with": opened_with})
    designations = []
    descriptors: list[dict[str, Any]] = []
    for role, player in (("attacker", attacker), ("defender", defender)):
        for object_id in present.get(player, []):
            next_effect["objects"][object_id]["combat_designation"] = {"combat_id": record["combat_id"], "role": role}
            group = 0 if role == "attacker" else 2
            found, identity = _designation_triggers(next_effect, next_record, object_id, role, f"combat:{record['combat_id']}:open:{role}", group)
            if identity is not None:
                next_record["triggered_identities"][role].append(identity)
            descriptors += found
            designations.append({"object_id": object_id, "role": role, "identity": object_identity(next_effect, object_id) or f"{object_id}@0", "triggers": [d["trigger_id"] for d in found]})
    # ADR-0008 §4 / Core 190.6: the Battlefield's own "When you attack/defend
    # here" — "you" is the Battlefield's controller, who must be the player
    # gaining that designation; uncontrolled, "you" refers to no one (190.6.d).
    battlefield_triggers = []
    next_record["battlefield_triggered"] = []
    for role, player in (("attacker", attacker), ("defender", defender)):
        descriptors_here = battlefield.get(TRIGGER_FIELDS[role], []) or []
        if not descriptors_here:
            continue
        controller = battlefield.get("controller")
        if controller is None:
            battlefield_triggers.append({"role": role, "fired": False, "reason": "battlefield uncontrolled: 'you' refers to no one (190.6.d)"})
            continue
        if controller != player:
            battlefield_triggers.append({"role": role, "fired": False, "reason": f"the Battlefield's controller {controller} did not gain the {role} designation (190.6.d)"})
            continue
        group = 0 if role == "attacker" else 2
        for descriptor in descriptors_here:
            descriptors.append({**descriptor, "controller": controller, "source_object": battlefield_id, "trigger_kind": "triggered",
                                "batch_id": f"combat:{record['combat_id']}:open:{role}", "batch_sequence": group,
                                "combat_id": record["combat_id"], "role": role, "battlefield_identity": record["battlefield_identity"], "source_identity": record["battlefield_identity"]})
        next_record["battlefield_triggered"].append(role)
        battlefield_triggers.append({"role": role, "fired": True, "controller": controller, "triggers": [d["trigger_id"] for d in descriptors_here]})
    from resolution_bridge import _settle_trigger_orders  # local: resolution_bridge imports this module lazily too
    failure = _settle_trigger_orders(descriptors, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    next_timing["combat"] = next_record
    next_timing["showdown"] = {"active": True, "kind": "combat", "focus": focus, "battlefield": battlefield_id}
    next_timing["priority"] = focus
    scheduled = schedule_triggered_items(next_timing, descriptors)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "the Combat Chain could not be built", ["Core 464.2.e"], trigger_result=scheduled)
    final_timing = scheduled["next_state"]
    trace = {"attacker": attacker, "defender": defender, "opened_with": opened_with, "focus": focus,
             "designations": designations, "battlefield_triggers": battlefield_triggers, "combat_chain": [d["trigger_id"] for d in descriptors],
             "state_closed": bool(descriptors), "trigger_schedule": scheduled.get("transition")}
    return _commit(base, final_timing, next_effect, trace=trace,
                   locators=["Core 464.2.b", "Core 464.2.c.1", "Core 464.2.c.1.a", "Core 464.2.c.1.b", "Core 464.2.c.2", "Core 464.2.c.3", "Core 464.2.d", "Core 464.2.e.1", "Core 464.2.f", "Core 345", "Core 383.4.e", "Core 383.4.f", "Core 190.6.a", "Core 190.6.d"])


# ------------------------------------------------------------- designation sync --

def sync_designations(record: dict[str, Any], effect_state: dict[str, Any], batch_id: str, batch_sequence: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Core 323.2 on one effect state: Units of the participants present at the
    Combat Battlefield carry their controller's designation; Units elsewhere
    (or of another Combat) carry none. Newly designated Units raise their
    Attack/Defend triggers once per identity. Returns (next_effect, next_record,
    trace, descriptors)."""
    next_effect = copy.deepcopy(effect_state)
    next_record = copy.deepcopy(record)
    battlefield_id = record["battlefield"]
    roles = {record["attacker"]: "attacker", record["defender"]: "defender"}
    gained, lost, descriptors = [], [], []
    for object_id in sorted(next_effect["objects"]):
        obj = next_effect["objects"][object_id]
        location = find_location(next_effect, object_id)
        at_combat = obj.get("kind") == "unit" and location == ("battlefield", battlefield_id, None)
        desired = {"combat_id": record["combat_id"], "role": roles[obj["controller"]]} if at_combat and obj["controller"] in roles else None
        current = obj.get("combat_designation")
        if current == desired:
            continue
        if desired is None:
            del obj["combat_designation"]
            lost.append({"object_id": object_id, "was": current, "reason": "not_at_combat_battlefield" if zone_class(location) == "board" else "left_the_board"})
            continue
        obj["combat_designation"] = desired
        found, identity = _designation_triggers(next_effect, next_record, object_id, desired["role"], batch_id, batch_sequence)
        if identity is not None:
            next_record["triggered_identities"][desired["role"]].append(identity)
        descriptors += found
        gained.append({"object_id": object_id, "role": desired["role"], "was": current, "identity": object_identity(next_effect, object_id) or f"{object_id}@0",
                       "triggers": [d["trigger_id"] for d in found], "already_triggered_identity": identity is None})
    return next_effect, next_record, {"gained": gained, "lost": lost}, descriptors


def sync_combat_designations(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """The Cleanup task of 323.2 as a standalone procedure for a Combat in
    progress; resolve_with_program runs the same synchronization after its
    own Cleanup. Triggers raised here form one batch."""
    base = _base("sync_combat_designations", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    record = timing_state.get("combat")
    if record is None or record["status"] not in IN_PROGRESS:
        return _refuse(base, "combat_not_in_progress", "designations are synchronized only while a Combat is in progress (323.2)", ["Core 323.2"])
    sync_index = int(record.get("sync_count", 0))
    next_effect, next_record, trace, descriptors = sync_designations(record, effect_state, f"combat:{record['combat_id']}:sync:{sync_index}", 0)
    next_record["sync_count"] = sync_index + 1
    from resolution_bridge import _settle_trigger_orders
    failure = _settle_trigger_orders(descriptors, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    next_timing["combat"] = next_record
    scheduled = schedule_triggered_items(next_timing, descriptors)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "designation triggers could not be scheduled", ["Core 383.4.e.2"], trigger_result=scheduled)
    trace.update({"scheduled_triggers": [d["trigger_id"] for d in descriptors], "trigger_schedule": scheduled.get("transition")})
    return _commit(base, scheduled["next_state"], next_effect, trace=trace, locators=["Core 323.2", "Core 323.2.a", "Core 323.2.b", "Core 323.2.c", "Core 464.2.c.3.a", "Core 383.4.e.2.a", "Core 383.4.f.2.a"])


# ------------------------------------------------------ Combat Damage assignment --

ASSIGNMENT_RECEIPT_VERSION = "riftbound-combat-assignment-receipt.v1"
PREVIEW_MODES = {"reduce_damage"}


def combat_sides(record: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, list[str]]:
    """The Units of each role that are at the Combat Battlefield and carry
    this Combat's designation (the only Units that fight, 465.1–465.2)."""
    sides: dict[str, list[str]] = {"attacker": [], "defender": []}
    for object_id in effect_state["battlefields"][record["battlefield"]]["objects"]:
        obj = effect_state["objects"][object_id]
        designation = obj.get("combat_designation")
        if obj.get("kind") == "unit" and designation is not None and designation.get("combat_id") == record["combat_id"]:
            sides[designation["role"]].append(object_id)
    return sides


def available_combat_damage(effect_state: dict[str, Any], units: list[str]) -> tuple[int, list[dict[str, Any]]]:
    """Core 465.2.a–b: the side's Might summed, each Unit's rules-facing Might
    read as at least 0 (143.2.b); a Stunned Unit contributes nothing (423.1.b)."""
    from effect_ir import effective_might
    parts, total = [], 0
    for unit in units:
        might = effective_might(effect_state, unit)
        stunned = bool(effect_state["objects"][unit].get("stunned"))
        contributed = 0 if stunned else might
        parts.append({"unit": unit, "might": might, "stunned": stunned, "contributed": contributed})
        total += contributed
    return total, parts


def _preview_replacements(effect_state: dict[str, Any], unit: str, event_id: str, engine_decisions: dict[str, Any] | None):
    """The deal_damage replacements that would apply to damage Dealt to the
    Unit, considered at assignment instead (465.2.c.5). Only descriptors the
    preview can evaluate (reduce_damage) are allowed; a Unit's controller
    orders several by the existing replacement_order decision for the
    assignment event and answers optional ones by replacement_choice.
    Returns (ordered descriptors, problem) where problem is a result stub."""
    from effect_ir import _applicable_replacements
    applicable = _applicable_replacements(effect_state, {"op": "deal_damage", "object_id": unit})
    if not applicable:
        return [], None
    unknown = [r["replacement_id"] for r in applicable if r["mode"] not in PREVIEW_MODES]
    if unknown:
        return None, {"unsupported": True, "reason_code": "assignment_replacement_not_previewable",
                      "reason": f"replacement(s) {unknown} on {unit} would alter the damage Dealt in a way the assignment preview cannot evaluate (465.2.c.5); the assignment is not guessed", "replacement_ids": unknown}
    controller = effect_state["objects"][unit]["controller"]
    order_map, choice_map = _ed.replacement_maps(engine_decisions)
    ids = [r["replacement_id"] for r in applicable]
    if len(applicable) > 1:
        supplied = (order_map or {}).get(event_id)
        if supplied is None:
            return None, {"replacement_decision_required": True, "reason": f"{controller} orders the replacements {ids} that apply to damage assigned to {unit} (465.2.c.5)",
                          "replacement_ids": ids, "event_ids": [event_id], "decision_controller": controller}
        if sorted(supplied) != sorted(ids):
            return None, {"invalid": [f"replacement order for {event_id} must list exactly {sorted(ids)}"]}
        by_id = {r["replacement_id"]: r for r in applicable}
        applicable = [by_id[i] for i in supplied]
    chosen = []
    for descriptor in applicable:
        if descriptor.get("optional"):
            choice = ((choice_map or {}).get(descriptor["replacement_id"], {}) or {}).get(event_id)
            if not isinstance(choice, bool):
                return None, {"replacement_decision_required": True, "reason": f"{controller} decides whether the optional replacement {descriptor['replacement_id']} applies to damage assigned to {unit}",
                              "replacement_ids": [descriptor["replacement_id"]], "event_ids": [event_id], "decision_controller": controller}
            if choice is False:
                continue
        chosen.append(descriptor)
    return chosen, None


def preview_assignment(descriptors: list[dict[str, Any]], raw: int) -> tuple[int, int, list[dict[str, Any]]]:
    """Applied damage for a raw assignment under the previewed descriptors,
    each consumed at most once: (applied, prevented, consumed)."""
    remaining, prevented, consumed = raw, 0, []
    for descriptor in descriptors:
        take = min(remaining, descriptor.get("prevent_remaining", 0))
        if take > 0:
            consumed.append({"replacement_id": descriptor["replacement_id"], "mode": descriptor["mode"], "prevented": take})
            remaining -= take
            prevented += take
    return remaining, prevented, consumed


def assignment_candidates(record: dict[str, Any], effect_state: dict[str, Any], role: str, engine_decisions: dict[str, Any] | None) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Per opposing Unit: identity, Might, marked damage, the minimum raw
    assignment that is lethal once replacements are previewed
    (465.2.c.4.a, 465.2.c.5), and its assignment requirements (Tank first,
    Backline last; both is a per-Unit choice, 465.2.c.6–c.9)."""
    from effect_ir import effective_might, has_keyword, object_identity
    opposing = combat_sides(record, effect_state)["defender" if role == "attacker" else "attacker"]
    candidates = []
    for unit in opposing:
        obj = effect_state["objects"][unit]
        event_id = f"assign:{record['combat_id']}:{unit}"
        descriptors, problem = _preview_replacements(effect_state, unit, event_id, engine_decisions)
        if problem is not None:
            return None, {**problem, "unit": unit}
        might, damage = effective_might(effect_state, unit), obj["damage"]
        need = might - damage if might > damage else (0 if damage > 0 else 1)  # 143.2.a: nonzero damage at or above Might
        raw = need
        while need > 0 and preview_assignment(descriptors, raw)[0] < need:
            raw += 1
            if raw > need + 64:
                return None, {"unsupported": True, "reason_code": "assignment_lethal_not_reachable", "reason": f"no raw assignment within 64 above the need makes {unit} take lethal damage under its replacements", "unit": unit}
        requirements = [k for k in ("tank", "backline") if has_keyword(effect_state, unit, k)]
        candidates.append({"unit": unit, "identity": object_identity(effect_state, unit) or f"{unit}@0", "might": might, "damage": damage,
                           "min_lethal_applied": need, "min_lethal_raw": raw, "requirements": requirements, "event_id": event_id,
                           "replacements": [d["replacement_id"] for d in descriptors], "_descriptors": descriptors})
    return candidates, None


def _tier(candidate: dict[str, Any], choices: dict[str, str]) -> int:
    reqs = candidate["requirements"]
    if "tank" in reqs and "backline" in reqs:
        return {"tank": 0, "backline": 2}[choices[candidate["unit"]]]
    return 0 if "tank" in reqs else 2 if "backline" in reqs else 1


def validate_assignment(candidates: list[dict[str, Any]], available: int, amounts: dict[str, int], choices: dict[str, str]) -> list[str]:
    """Core 465.2.c.3–c.9 over one complete raw assignment. Returns problems."""
    problems = []
    units = {c["unit"]: c for c in candidates}
    if set(amounts) != set(units):
        return [f"the assignment must name every opposing Unit exactly once: {sorted(units)}"]
    if sum(amounts.values()) != available:
        return [f"assigned {sum(amounts.values())}, but the side's Combat Damage is {available} (465.2.c)"]
    for c in candidates:
        if "tank" in c["requirements"] and "backline" in c["requirements"] and c["unit"] not in choices:
            return [f"{c['unit']} has both Tank and Backline; the assigning player chooses which applies (465.2.c.8)"]
    tiers: dict[int, list[dict[str, Any]]] = {}
    for c in candidates:
        tiers.setdefault(_tier(c, choices), []).append(c)
    lethal = {c["unit"]: amounts[c["unit"]] >= c["min_lethal_raw"] for c in candidates}
    first_open = None
    for tier in sorted(tiers):
        members = tiers[tier]
        if first_open is None:
            if all(lethal[m["unit"]] for m in members):
                continue
            first_open = tier
            partial = [m for m in members if 0 < amounts[m["unit"]] < m["min_lethal_raw"]]
            if len(partial) > 1:
                problems.append(f"lethal damage must be assigned in full before another Unit receives any: {[m['unit'] for m in partial]} are both partial (465.2.c.3)")
        else:
            for m in members:
                if amounts[m["unit"]] > 0:
                    problems.append(f"{m['unit']} received damage while a Unit that must be assigned first still lacks lethal damage (465.2.c.6–c.7)")
    for c in candidates:
        others_open = any(not lethal[o["unit"]] for o in candidates if o["unit"] != c["unit"])
        if amounts[c["unit"]] > c["min_lethal_raw"] and others_open:
            problems.append(f"{c['unit']} was assigned {amounts[c['unit']]}, above the minimum lethal {c['min_lethal_raw']}, while another Unit still lacks lethal damage (465.2.c.4)")
    return problems


def _legal_assignment_count(candidates: list[dict[str, Any]], available: int, choices: dict[str, str], limit: int = 2) -> int | None:
    """Count legal assignments up to `limit` by bounded enumeration; None when
    the space is too large to enumerate honestly (then the player decides)."""
    if len(candidates) > 4 or available > 12:
        return None
    units = [c["unit"] for c in candidates]
    count = 0

    def rec(index: int, remaining: int, partial: dict[str, int]):
        nonlocal count
        if count >= limit:
            return
        if index == len(units):
            if remaining == 0 and not validate_assignment(candidates, available, partial, choices):
                count += 1
            return
        for amount in range(remaining + 1):
            partial[units[index]] = amount
            rec(index + 1, remaining - amount, partial)
        partial.pop(units[index], None)

    rec(0, available, {})
    return count


def assign_combat_damage(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0008 §8–9 / Core 465.2: once the Combat Showdown has closed, if
    both sides still have designated Units at the Battlefield, sum each
    side's Might and, starting with the attacker, take each player's complete
    damage_assignment; validate 465.2.c in full with replacements previewed
    (465.2.c.5); record a receipt per side. Nothing is Dealt here (465.2.c.1)
    and no replacement is consumed yet — the Deal step does that from the
    receipt, exactly once."""
    from effect_ir import object_identity
    base = _base("assign_combat_damage", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    record = timing_state.get("combat")
    if record is None or record["status"] != "showdown_closed":
        return _refuse(base, "combat_showdown_not_closed", "Combat Damage is assigned when the Combat Showdown closes (348.1, 465.2); the Combat is not at that step", ["Core 348.1", "Core 465.2"])
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"]:
        return _refuse(base, "combat_requires_quiet_cleanup_boundary", "the chain and outstanding tasks must be finished before damage is assigned", ["Core 465.1"])
    sides = combat_sides(record, effect_state)
    next_timing = copy.deepcopy(timing_state)
    next_record = next_timing["combat"]
    if not sides["attacker"] or not sides["defender"]:
        next_record["status"] = "damage_dealt"
        next_record["assignments"] = None
        next_record["damage_step_skipped"] = True
        return _commit(base, next_timing, copy.deepcopy(effect_state), trace={"sides": sides, "damage_step": "skipped", "reason": "both Attacking and Defending Units must remain for the Combat Damage Step (465.1)"}, locators=["Core 465.1", "Core 466"])
    receipts: dict[str, Any] = {}
    trace_sides = {}
    for role in ("attacker", "defender"):
        player = record[role]
        available, parts = available_combat_damage(effect_state, sides[role])
        candidates, problem = assignment_candidates(record, effect_state, role, engine_decisions)
        if problem is not None:
            if problem.get("unsupported"):
                return _unsupported(base, problem["reason_code"], problem["reason"], ["Core 465.2.c.5", "Core 465.2.c.10"], unit=problem.get("unit"), replacement_ids=problem.get("replacement_ids", []))
            if problem.get("replacement_decision_required"):
                return {**base, "valid": True, "committed": False, "replacement_decision_required": True, "reason": problem["reason"], "replacement_ids": problem["replacement_ids"],
                        "event_ids": problem["event_ids"], "decision_controller": problem["decision_controller"], "rule_locators": ["Core 465.2.c.5"]}
            return _invalid(base, problem.get("invalid", ["assignment preview failed"]))
        public = [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
        decision_id = f"damage_assignment:{record['combat_id']}:{role}"
        entry = next((e for e in _ed.entries(engine_decisions, kind="damage_assignment") if e["decision_id"] == decision_id), None)
        if entry is None:
            auto = None
            if available == 0:
                auto = {c["unit"]: 0 for c in candidates}
            elif len(candidates) == 1:
                auto = {candidates[0]["unit"]: available}
            elif not any(len(c["requirements"]) == 2 for c in candidates) and _legal_assignment_count(candidates, available, {}) == 1:
                for c in candidates:
                    pass
                # exactly one legal assignment: find it by the same bounded enumeration
                units = [c["unit"] for c in candidates]

                def find(index: int, remaining: int, partial: dict[str, int]):
                    if index == len(units):
                        return dict(partial) if remaining == 0 and not validate_assignment(candidates, available, partial, {}) else None
                    for amount in range(remaining + 1):
                        partial[units[index]] = amount
                        found = find(index + 1, remaining - amount, partial)
                        if found is not None:
                            return found
                    partial.pop(units[index], None)
                    return None
                auto = find(0, available, {})
            if auto is None:
                return {**base, "valid": True, "committed": False, "reason_code": "damage_assignment_required",
                        "reason": f"{player} assigns {available} Combat Damage among {[c['unit'] for c in candidates]} (465.2.c); the engine only proceeds when exactly one assignment is legal",
                        "decision_ids": [decision_id], "decision_controller": player, "role": role, "available": available, "candidates": public,
                        "rule_locators": ["Core 465.2.c", "Core 465.2.c.3", "Core 465.2.c.4", "Core 465.2.c.6"]}
            amounts, choices, how = auto, {}, "sole_legal_assignment"
        else:
            if entry["controller"] != player:
                return _refuse(base, "decision_controller_mismatch", f"the {role}'s assignment was supplied by {entry['controller']!r}, not {player}", ["Core 465.2.c"])
            value = entry["value"]
            amounts = dict(value["amounts"]) if isinstance(value, dict) and "amounts" in value else dict(value)
            choices = dict(value.get("requirement_choices", {})) if isinstance(value, dict) and "amounts" in value else {}
            for unit, identity in (entry.get("selection_identities") or {}).items():
                if unit in effect_state["objects"] and identity != (object_identity(effect_state, unit) or f"{unit}@0"):
                    return _invalid(base, [f"damage_assignment {decision_id} binds {unit} to {identity!r}; it is now {object_identity(effect_state, unit) or f'{unit}@0'!r}"])
            if set(amounts) != {c["unit"] for c in candidates} or sum(amounts.values()) != available:
                return _invalid(base, [f"damage_assignment {decision_id} must name every opposing Unit {sorted(c['unit'] for c in candidates)} exactly once and sum to {available} (465.2.c); got {amounts}"])
            problems = validate_assignment(candidates, available, amounts, choices)
            if problems:
                return _refuse(base, "damage_assignment_illegal", "; ".join(problems), ["Core 465.2.c.3", "Core 465.2.c.4", "Core 465.2.c.6", "Core 465.2.c.7", "Core 465.2.c.8"], role=role, candidates=public)
            how = "player_decision"
        entries = []
        for c in candidates:
            applied, prevented, consumed = preview_assignment(c["_descriptors"], amounts[c["unit"]])
            entries.append({"unit": c["unit"], "identity": c["identity"], "raw_assigned": amounts[c["unit"]], "prevented": prevented, "applied": applied,
                            "lethal": amounts[c["unit"]] >= c["min_lethal_raw"], "min_lethal_raw": c["min_lethal_raw"], "might": c["might"], "marked_damage": c["damage"],
                            "requirement_applied": choices.get(c["unit"]) or (c["requirements"][0] if c["requirements"] else None), "consumed_replacements": consumed, "event_id": c["event_id"]})
        receipts[role] = {"schema_version": ASSIGNMENT_RECEIPT_VERSION, "assigning_player": player, "available": available, "contributions": parts,
                          "sources": sides[role], "entries": entries, "selection": how, "rule_locators": ["Core 465.2.a", "Core 465.2.b", "Core 465.2.c", "Core 465.2.c.5", "Core 465.2.c.1"]}
        trace_sides[role] = {"available": available, "selection": how, "amounts": amounts}
    next_record["status"] = "damage_assigned"
    next_record["assignments"] = receipts
    return _commit(base, next_timing, copy.deepcopy(effect_state), trace={"sides": sides, "assignments": trace_sides, "dealt": False},
                   locators=["Core 465.1", "Core 465.2.a", "Core 465.2.b", "Core 465.2.c", "Core 465.2.c.1", "Core 465.2.c.3", "Core 465.2.c.4", "Core 465.2.c.4.a", "Core 465.2.c.5", "Core 465.2.c.6", "Core 465.2.c.7", "Core 465.2.c.8", "Core 465.2.c.9", "Core 423.1.b", "Core 143.2.b"])


# ---------------------------------------------------------------- Standard Move --

STANDARD_MOVE_VERSION = "riftbound-standard-move-result.v1"
STANDARD_MOVE_DECLARATION_VERSION = "riftbound-standard-move-declaration.v1"


def _declaration_errors(declaration: Any, effect_state: dict[str, Any]) -> list[str]:
    if not isinstance(declaration, dict):
        return ["declaration must be an object"]
    errors = []
    if declaration.get("schema_version") != STANDARD_MOVE_DECLARATION_VERSION:
        errors.append(f"declaration.schema_version must be {STANDARD_MOVE_DECLARATION_VERSION}")
    if set(declaration) - {"schema_version", "actor", "units", "unit_identities", "destination", "cost_confirmation"}:
        errors.append("declaration carries unsupported fields")
    if not isinstance(declaration.get("actor"), str) or declaration.get("actor") not in effect_state["players"]:
        errors.append("declaration.actor must be a player")
    units = declaration.get("units")
    if not isinstance(units, list) or not units or any(not isinstance(u, str) or not u for u in units) or len(units) != len(set(units)):
        errors.append("declaration.units must be a non-empty unique array of object ids")
    elif any(u not in effect_state["objects"] for u in units):
        errors.append("declaration.units names an unknown object")
    identities = declaration.get("unit_identities")
    if identities is not None and (not isinstance(identities, dict) or any(not isinstance(v, str) or "@" not in v for v in identities.values())):
        errors.append("declaration.unit_identities must map object ids to identity tokens")
    destination = declaration.get("destination")
    if not isinstance(destination, dict) or destination.get("kind") not in {"base", "battlefield"} or set(destination) - {"kind", "battlefield"}:
        errors.append("declaration.destination must be {kind: base} or {kind: battlefield, battlefield}")
    elif destination["kind"] == "battlefield" and destination.get("battlefield") not in effect_state["battlefields"]:
        errors.append("declaration.destination names an unknown battlefield")
    elif destination["kind"] == "base" and "battlefield" in destination:
        errors.append("declaration.destination base carries no battlefield")
    confirmation = declaration.get("cost_confirmation")
    if confirmation is not None and (not isinstance(confirmation, dict) or set(confirmation) != {"exhaust_confirmed"} or not isinstance(confirmation["exhaust_confirmed"], bool)):
        errors.append("declaration.cost_confirmation must be {exhaust_confirmed: bool}")
    return errors


def standard_move(timing_state: dict[str, Any], effect_state: dict[str, Any], declaration: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0008 §6 / Core 144, 810: one game action moving one or more of the
    actor's ready Units to one destination, exhausting them all at once as the
    cost (144.2–144.3.c). Base→Battlefield and Battlefield→own Base are the
    normal routes (144.4.a–b); Battlefield→Battlefield needs active Ganking,
    which adds that permission and nothing else (144.4.c, 810.1.c). The
    relocation itself is the existing Move operation, so Move triggers and
    Cleanup stay one implementation."""
    from effect_ir import apply_program, has_keyword, perform_lethal_cleanup
    from rules_core import validate_timing
    base = {"schema_version": STANDARD_MOVE_VERSION, "input_timing_state_hash": state_hash(timing_state), "input_effect_state_hash": hash_value(effect_state),
            "input_hash": combined_input_hash(timing_state, effect_state)}
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if found := _declaration_errors(declaration, effect_state):
        return _invalid(base, found)
    actor, units, destination = declaration["actor"], list(declaration["units"]), declaration["destination"]
    verdict = validate_timing(timing_state, {"actor": actor, "kind": "standard_move", "timing": "default"})
    if verdict.get("legal") is not True:
        return _refuse(base, verdict.get("reason_code", "standard_move_timing_illegal"), verdict.get("explanation", "the timing kernel refused the Standard Move"), verdict.get("rule_locators", []), timing_verdict=verdict)
    identities = declaration.get("unit_identities") or {}
    for unit in units:
        obj = effect_state["objects"][unit]
        if obj.get("kind") != "unit" or obj.get("controller") != actor or zone_class(find_location(effect_state, unit)) != "board":
            return _refuse(base, "unit_not_controlled_board_unit", f"{unit!r} is not a Unit {actor} controls on the board (144)", ["Core 144"])
        if unit in identities and identities[unit] != (object_identity(effect_state, unit) or f"{unit}@0"):
            return _invalid(base, [f"declaration.unit_identities binds {unit} to {identities[unit]!r}; it is now {object_identity(effect_state, unit) or f'{unit}@0'!r}"])
    # destination legality per Unit (144.4)
    routes = []
    if destination["kind"] == "battlefield":
        target_id = destination["battlefield"]
        others = {effect_state["objects"][o]["controller"] for o in effect_state["battlefields"][target_id]["objects"] if effect_state["objects"][o].get("kind") == "unit"} - {actor}
        if len(others) >= 2:
            return _refuse(base, "destination_has_two_other_players", f"{target_id} already has Units of two other players; it is not a valid destination (144.4.a.1)", ["Core 144.4.a.1", "Core 447.2"])
        for unit in units:
            origin = find_location(effect_state, unit)
            if origin[0] == "battlefield":
                if origin[1] == target_id:
                    return _refuse(base, "already_at_destination", f"{unit!r} is already at {target_id}", ["Core 144.4"])
                if not has_keyword(effect_state, unit, "ganking"):
                    return _refuse(base, "ganking_required", f"{unit!r} may move from a Battlefield to another Battlefield only with Ganking (144.4.c, 810.1.b)", ["Core 144.4.c", "Core 810.1.b"])
                routes.append({"unit": unit, "from": f"battlefield:{origin[1]}", "to": f"battlefield:{target_id}", "permission": "ganking"})
            else:
                routes.append({"unit": unit, "from": f"base:{origin[1]}", "to": f"battlefield:{target_id}", "permission": "144.4.a"})
        move_destination = {"kind": "battlefield", "battlefield": target_id}
    else:
        for unit in units:
            origin = find_location(effect_state, unit)
            if origin[0] != "battlefield":
                return _refuse(base, "already_at_base", f"{unit!r} is already at a Base; a Standard Move goes from a Battlefield to the Unit's own Base (144.4.b)", ["Core 144.4.b"])
            routes.append({"unit": unit, "from": f"battlefield:{origin[1]}", "to": f"base:{actor}", "permission": "144.4.b"})
        move_destination = {"kind": "base", "player": actor}
    # the cost: every selected Unit exhausts, simultaneously (144.2, 144.3.c)
    exhausted = [unit for unit in units if effect_state["objects"][unit].get("exhausted")]
    if exhausted:
        return _refuse(base, "unit_exhausted", f"{exhausted} cannot pay the exhaust cost of a Standard Move (144.2)", ["Core 144.2"])
    confirmation = declaration.get("cost_confirmation")
    if not confirmation or confirmation.get("exhaust_confirmed") is not True:
        return {**base, "valid": True, "committed": False, "reason_code": "cost_confirmation_required",
                "reason": f"{actor} exhausts {units} as the cost of this Standard Move (144.2); the declaration must confirm the cost",
                "decision_ids": ["standard_move:cost"], "decision_controller": actor, "rule_locators": ["Core 144.2", "Core 144.3.c"], "routes": routes}
    working = copy.deepcopy(effect_state)
    for unit in units:
        working["objects"][unit]["exhausted"] = True
    program = {"schema_version": "riftbound-effect-program.v1", "ruleset": copy.deepcopy(effect_state["ruleset"]), "program_id": f"standard-move:{actor}:{base['input_hash'][7:19]}",
               "controller": actor, "effects": [{"op": "move_board_object", "effect_id": f"mv:{unit}", "object_id": unit, "destination": dict(move_destination)} for unit in units]}
    moved = apply_program(working, program)
    if moved.get("committed") is not True:
        return _invalid(base, [moved.get("reason", "; ".join(moved.get("errors", [])) or "the Move operation failed")])
    cleanup = perform_lethal_cleanup(moved["next_state"])
    if cleanup.get("committed") is not True:
        return {**base, "valid": cleanup.get("valid", True), "committed": False, "unsupported": cleanup.get("unsupported", False), "reason": cleanup.get("reason", "cleanup failed"), "cleanup_result": cleanup}
    triggers = [dict(t) for t in moved.get("pending_triggers", [])]
    for index, trigger in enumerate(triggers):
        trigger.setdefault("batch_sequence", 0)
        trigger.setdefault("batch_id", f"standard-move:{actor}")
    cleanup_triggers = [dict(t) for t in cleanup.get("pending_triggers", [])]
    for trigger in cleanup_triggers:
        trigger["batch_sequence"] = trigger.get("batch_sequence", 0) + 1
    from resolution_bridge import _settle_trigger_orders
    failure = _settle_trigger_orders(triggers + cleanup_triggers, engine_decisions, base)
    if failure is not None:
        return failure
    scheduled = schedule_triggered_items(timing_state, triggers + cleanup_triggers)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "Move triggers could not be scheduled", ["Core 383.1"], trigger_result=scheduled)
    trace = {"actor": actor, "cost": {"exhausted": units, "simultaneous": True}, "routes": routes, "destination": move_destination,
             "ganking_used": [r["unit"] for r in routes if r["permission"] == "ganking"], "move": moved["trace"], "cleanup": cleanup["trace"],
             "scheduled_triggers": [t["trigger_id"] for t in triggers + cleanup_triggers], "trigger_schedule": scheduled.get("transition")}
    return _commit(base, scheduled["next_state"], cleanup["next_state"], trace=trace,
                   locators=["Core 144.1", "Core 144.2", "Core 144.3", "Core 144.3.a", "Core 144.3.c", "Core 144.4.a", "Core 144.4.b", "Core 144.4.c", "Core 810.1.b", "Core 810.1.c", "Core 446", "Core 383.1"] + list(dict.fromkeys(l for e in moved["trace"] for l in e.get("rule_locators", []))))


# ------------------------------------------------------------------------ CLI --

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


STEPS = {"stage": stage_combat, "open": open_combat, "sync": sync_combat_designations, "assign": assign_combat_damage}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicle Combat procedures (ADR-0008)")
    parser.add_argument("step", choices=sorted(STEPS))
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("effect_state", type=Path)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args(argv)
    try:
        decisions = _load(args.decisions) if args.decisions else None
        output = STEPS[args.step](_load(args.timing_state), _load(args.effect_state), decisions)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
