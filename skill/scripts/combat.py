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
             "designations": designations, "combat_chain": [d["trigger_id"] for d in descriptors],
             "state_closed": bool(descriptors), "trigger_schedule": scheduled.get("transition")}
    return _commit(base, final_timing, next_effect, trace=trace,
                   locators=["Core 464.2.b", "Core 464.2.c.1", "Core 464.2.c.1.a", "Core 464.2.c.1.b", "Core 464.2.c.2", "Core 464.2.c.3", "Core 464.2.d", "Core 464.2.e.1", "Core 464.2.f", "Core 345", "Core 383.4.e", "Core 383.4.f"])


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


# ------------------------------------------------------------------------ CLI --

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


STEPS = {"stage": stage_combat, "open": open_combat, "sync": sync_combat_designations}


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
