#!/usr/bin/env python3
"""Atomic bridge between Chronicle timing state and typed effect programs."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from effect_ir import DEFAULT_TURN_ID, TURN_EFFECT_KINDS, _bump_identity, action_performed, apply_program, find_location, hash_value, perform_lethal_cleanup, validate_state, zone_class
from rules_core import complete_resolution, schedule_triggered_items, state_hash
from rules_core import validate_state as validate_timing_state

CLEANUP_DECISION_VERSION = "riftbound-cleanup-decisions.v1"

import engine_decisions as _ed  # noqa: E402


def validate_cleanup_decisions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["cleanup_decisions must be an object"]
    if value.get("schema_version") != CLEANUP_DECISION_VERSION:
        return [f"cleanup_decisions.schema_version must be {CLEANUP_DECISION_VERSION}"]
    if set(value) - {"schema_version", "replacement_event_order", "replacement_choices"}:
        return ["cleanup_decisions contains unsupported fields"]
    event_order = value.get("replacement_event_order", {})
    if not isinstance(event_order, dict) or any(
        not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or any(not isinstance(item, str) or not item for item in ids)
        for ids in event_order.values()
    ):
        return ["cleanup_decisions.replacement_event_order must map ids to non-empty unique string arrays"]
    choices = value.get("replacement_choices", {})
    if not isinstance(choices, dict) or any(
        not isinstance(by_event, dict) or any(not isinstance(event_id, str) or not isinstance(choice, bool) for event_id, choice in by_event.items())
        for by_event in choices.values()
    ):
        return ["cleanup_decisions.replacement_choices must map replacement and event ids to booleans"]
    return []


def resolve_with_program(
    timing_state: dict[str, Any],
    item_id: str,
    effect_state: dict[str, Any],
    program: dict[str, Any] | None,
    cleanup_decisions: dict[str, Any] | None = None,
    engine_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": "riftbound-resolution-bridge-result.v1",
        "item_id": item_id,
        "input_timing_state_hash": state_hash(timing_state),
        "input_effect_state_hash": hash_value(effect_state),
    }
    chain_item = next((item for item in timing_state.get("chain", {}).get("items", []) if item.get("id") == item_id), None)
    if chain_item is None:
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "chain_item_not_found"}
    # ADR-0007 §1: a permanent with no rules text to execute resolves with no
    # program; its resolution is the entry procedure. A spell always needs one.
    if program is None:
        if chain_item.get("object_kind") not in {"unit", "gear"} or chain_item.get("effect_program_id"):
            return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_required"}
        program = {}
    bound_program = chain_item.get("effect_program_id")
    if bound_program is not None and program.get("program_id") != bound_program:
        return {
            **base,
            "valid": True,
            "committed": False,
            "stage": "program_binding",
            "reason": "effect_program_id_mismatch",
            "expected_program_id": bound_program,
            "received_program_id": program.get("program_id"),
        }
    if program.get("controller") is not None and program.get("controller") != chain_item.get("controller"):
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_controller_mismatch"}
    if program.get("source_object") is not None and chain_item.get("source_object") is not None and program.get("source_object") != chain_item.get("source_object"):
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_source_mismatch"}
    # Both components are pure. Probe timing first so an effect program is never
    # exposed as committed for an item that is not next to resolve.
    timing_result = complete_resolution(timing_state, item_id, effect_execution_confirmed=True)
    if timing_result.get("applied") is not True:
        return {
            **base,
            "valid": timing_result.get("valid", True),
            "committed": False,
            "stage": "timing",
            "reason": timing_result.get("reason_code", "timing_resolution_failed"),
            "timing_result": timing_result,
        }
    if decision_errors := validate_cleanup_decisions(cleanup_decisions):
        return {**base, "valid": False, "committed": False, "stage": "cleanup_decision", "errors": decision_errors, "reason": "; ".join(decision_errors)}
    # ADR-0005 §2 / ADR-0002 migration: the legacy cleanup-decisions object is
    # still read, converted into resolution-stage entries; writers emit only
    # engine-decisions.v1. Supplying both is ambiguous and refused.
    if engine_decisions is not None and cleanup_decisions is not None:
        return {**base, "valid": False, "committed": False, "stage": "cleanup_decision", "errors": ["supply engine_decisions or cleanup_decisions, not both"], "reason": "ambiguous decision envelopes"}
    if engine_decisions is None and cleanup_decisions is not None:
        engine_decisions = _ed.from_cleanup_decisions(cleanup_decisions, input_hash=hash_value(effect_state), controller=program.get("controller") or chain_item.get("controller") or "unknown")
    if decision_errors := _ed.validate_engine_decisions(engine_decisions):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": decision_errors, "reason": "; ".join(decision_errors)}
    if engine_decisions is not None and engine_decisions.get("input_hash") != hash_value(effect_state):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": ["engine_decisions.input_hash does not match the effect state"], "reason": "stale decision envelope"}
    if engine_decisions is not None and engine_decisions.get("chain_item_id") not in (None, item_id):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": ["engine_decisions.chain_item_id does not match the resolving item"], "reason": "decision envelope for another chain item"}
    order_map, choice_map = _ed.replacement_maps(engine_decisions)
    # ADR-0008 §5: a 'this combat' grant binds to the Combat in progress, which
    # only the timing state knows.
    combat_in_progress = timing_state.get("combat")
    context = {"combat": {"combat_id": combat_in_progress["combat_id"], "battlefield": combat_in_progress["battlefield"], "battlefield_identity": combat_in_progress["battlefield_identity"]}} if combat_in_progress and combat_in_progress.get("status") in ("open", "damage_assigned", "damage_dealt", "cleanup_done", "result_determined") else None
    if program:
        effect_result = apply_program(effect_state, program, decisions=engine_decisions, context=context)
    else:
        effect_result = {"committed": True, "next_state": copy.deepcopy(effect_state), "trace": [], "pending_triggers": []}
    if effect_result.get("committed") is not True:
        return {
            **base,
            "valid": effect_result.get("valid", True),
            "committed": False,
            "stage": "effect",
            "reason": effect_result.get("reason", "; ".join(effect_result.get("errors", [])) or "effect_program_failed"),
            "effect_result": effect_result,
        }
    # Core 157 / Codex ruling on C-15: after its instructions, a spell goes to
    # its owner's trash as a new object (124) and leaves the chain, and only
    # then does Cleanup run. A Unit or Gear on the chain enters the board at
    # finalization (359.2) by a procedure this bridge does not have.
    after_effect = effect_result["next_state"]
    chain_card_trace = []
    entry_triggers: list[dict[str, Any]] = []
    chain_entry = (after_effect.get("chain_items") or {}).get(item_id)
    if chain_entry is not None and after_effect["objects"][chain_entry["card"]]["kind"] in {"unit", "gear"}:
        # ADR-0007 §1–2: the permanent entry procedure, then "When you play me".
        after_effect, entry_trace, entry_triggers = complete_permanent_play(after_effect, item_id, engine_decisions)
        if entry_trace.get("replacement_decision_required"):
            return {
                **base, "valid": True, "committed": False, "stage": "permanent_entry",
                "replacement_decision_required": True,
                "reason": entry_trace["reason"],
                "replacement_ids": entry_trace["replacement_ids"],
                "event_ids": entry_trace["event_ids"],
                "decision_controller": entry_trace["decision_controller"],
                "effect_result": effect_result,
            }
        if entry_trace.get("error"):
            return {**base, "valid": False, "committed": False, "stage": "permanent_entry", "errors": [entry_trace["error"]], "reason": entry_trace["error"], "effect_result": effect_result}
        chain_card_trace.append(entry_trace)
        chain_entry = None
    if chain_entry is not None:
        card = chain_entry["card"]
        after_effect = copy.deepcopy(after_effect)
        del after_effect["chain_items"][item_id]
        if not after_effect["chain_items"]:
            del after_effect["chain_items"]
        owner = after_effect["objects"][card]["owner"]
        after_effect["players"][owner]["zones"]["trash"].append(card)
        chain_card_trace.append({"card": card, "chain_item_id": item_id, "destination": f"{owner}.trash",
                                 "identity_after": _bump_identity(after_effect, card), "rule_locators": ["Core 157", "Core 124"]})
    # ADR-0008 §3 / Core 323.2: the Cleanup's step 2 comes before 3a/3b — while
    # a Combat is in progress, designations follow presence first, so a Unit
    # that just arrived is a Defender (Shield, alone) before lethal damage is
    # judged. Its Attack/Defend triggers batch before the death triggers.
    combat_sync_trace = None
    combat_sync_triggers: list[dict[str, Any]] = []
    next_timing_for_schedule = timing_result["next_state"]
    combat_record = timing_state.get("combat")
    if combat_record is not None and combat_record.get("status") in ("open", "damage_assigned", "damage_dealt", "cleanup_done", "result_determined"):
        from combat import sync_designations
        sync_index = int(combat_record.get("sync_count", 0))
        after_effect, next_record, combat_sync_trace, combat_sync_triggers = sync_designations(
            combat_record, after_effect, f"combat:{combat_record['combat_id']}:sync:{sync_index}", 0)
        next_record["sync_count"] = sync_index + 1
        next_timing_for_schedule = copy.deepcopy(next_timing_for_schedule)
        next_timing_for_schedule["combat"] = next_record
    cleanup_result = perform_lethal_cleanup(
        after_effect,
        attributed_sources=[program.get("source_object")] if program.get("source_object") else [],
        replacement_event_order=order_map,
        replacement_choices=choice_map,
    )
    if cleanup_result.get("committed") is not True:
        return {
            **base,
            "valid": cleanup_result.get("valid", True),
            "committed": False,
            "stage": "cleanup",
            "reason": cleanup_result.get("reason", "; ".join(cleanup_result.get("errors", [])) or "lethal_cleanup_failed"),
            "effect_result": effect_result,
            "cleanup_result": cleanup_result,
        }
    final_effect_state = cleanup_result["next_state"]
    effect_triggers = [dict(trigger) for trigger in effect_result.get("pending_triggers", [])]
    # Play-completion triggers form one batch after the item's own effect
    # triggers and before anything the board-entry Cleanup raises (419.4.a).
    play_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in entry_triggers:
        trigger["batch_sequence"] = play_batch
        trigger["batch_id"] = f"play:{item_id}"
    effect_triggers += entry_triggers
    # step 2 designation triggers precede the Cleanup's 3a death triggers (323.2, 323.4)
    sync_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in combat_sync_triggers:
        trigger["batch_sequence"] = sync_batch
    effect_triggers += combat_sync_triggers
    cleanup_triggers = [dict(trigger) for trigger in cleanup_result.get("pending_triggers", [])]
    next_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in cleanup_triggers:
        trigger["batch_sequence"] = trigger.get("batch_sequence", 0) + next_batch
    # ADR-0005 §5 / Codex Q4 (b): "If this kills it" is a conditional reflexive
    # trigger. The spell has left the chain, Cleanup has killed (or not), and
    # 428.5.c attributes a Cleanup kill to the spell that dealt the damage
    # immediately before it. Only then is the Pending reflexive item built
    # (387–388); a death a replacement prevented builds nothing.
    conditional_trace = []
    conditional_triggers = []
    events = {e.get("effect_id"): e for e in effect_result.get("trace", [])}
    # Codex Round B, point 5: a caused-kill reflexive trigger and the death
    # triggers of the same Cleanup kill are simultaneously triggered — one
    # chronological batch, ordered by controller in Turn Order (383.3.d). The
    # batch is the Cleanup iteration that killed the object; for a Kill
    # instruction (428.5.b) it is the instruction's own batch.
    cleanup_kill_iteration = {e.get("object_id"): e.get("cleanup_iteration") for e in cleanup_result.get("trace", []) if e.get("op") == "kill" and e.get("outcome") in {"applied", "augmented_applied"}}
    cleanup_prefix = f"lethal-cleanup:{hash_value(after_effect).split(':', 1)[1][:12]}"
    all_batches = effect_triggers + cleanup_triggers

    def batch_for(killed_ids: list[str], event: dict[str, Any]) -> tuple[int, str]:
        if event.get("op") == "kill":
            return event.get("index", 0), f"{program.get('program_id')}:{event.get('effect_id')}"
        iteration = min(cleanup_kill_iteration.get(o, 0) for o in killed_ids)
        return iteration + next_batch, f"{cleanup_prefix}:{iteration}"

    for ct in program.get("conditional_triggers", []) or []:
        event = events.get(ct["condition"]["effect_id"], {})
        performed = action_performed(event)
        touched = [event["object_id"]] if isinstance(event.get("object_id"), str) else [x.get("object_id") for x in event.get("expansion_trace", []) if action_performed(x)]
        if event.get("op") == "kill":
            killed = [o for o in touched if performed]  # 428.5.b: a Kill instruction kills directly
            locators = ["Core 428.5.b", "Core 387.2", "Core 388.1"]
        else:
            killed = [o for o in touched if performed and o in cleanup_result.get("killed_objects", [])]
            locators = ["Core 428.5.c", "Core 428.5.c.1", "Core 387.2", "Core 388.1"]
        prevented = [o for o in touched if o in cleanup_result.get("stable_prevented_objects", [])]
        held = bool(killed)
        conditional_trace.append({
            "trigger_id": ct["trigger_id"], "condition": dict(ct["condition"]), "held": held,
            "action_performed": performed, "touched_objects": touched, "killed_objects": killed, "prevented_objects": prevented,
            "attributed_to": program.get("source_object"), "responsible_player": program.get("controller"), "rule_locators": locators,
        })
        if held:
            descriptor = {k: ct[k] for k in ("trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize")}
            batch_sequence, batch_id = batch_for(killed, event)
            descriptor.update({"trigger_kind": "reflexive", "batch_sequence": batch_sequence, "batch_id": batch_id,
                               "condition": dict(ct["condition"]), "killed_objects": killed})
            conditional_triggers.append(descriptor)
    pending_triggers = effect_triggers + cleanup_triggers + conditional_triggers
    # Core 383.3.d.1: when one controller has several abilities triggered at
    # once, that controller orders them. The engine never picks: a missing or
    # colliding controller_order inside one batch is a decision_required
    # naming the controller, the batch and the trigger ids; a supplied
    # trigger_order decision (engine-decisions.v1) assigns 0..n-1 and the
    # resolution retries. Different controllers in one batch need no
    # decision — Turn Order settles them.
    ordering_failure = _settle_trigger_orders(pending_triggers, engine_decisions, base)
    if ordering_failure is not None:
        return ordering_failure
    scheduled_result = schedule_triggered_items(next_timing_for_schedule, pending_triggers)
    if scheduled_result.get("applied") is not True:
        return {
            **base,
            "valid": scheduled_result.get("valid", True),
            "committed": False,
            "stage": "trigger_schedule",
            "reason": scheduled_result.get("reason_code", "; ".join(scheduled_result.get("errors", [])) or "trigger_schedule_failed"),
            "effect_result": effect_result,
            "cleanup_result": cleanup_result,
            "trigger_result": scheduled_result,
        }
    final_timing_state = scheduled_result["next_state"]
    return {
        **base,
        "valid": True,
        "committed": True,
        "next_timing_state": final_timing_state,
        "next_timing_state_hash": scheduled_result["next_state_hash"],
        "next_effect_state": final_effect_state,
        "next_effect_state_hash": hash_value(final_effect_state),
        "trace": {
            "effect": effect_result["trace"],
            "chain_card": chain_card_trace,
            "cleanup": cleanup_result["trace"],
            "conditional_triggers": conditional_trace,
            "combat_designations": combat_sync_trace,
            "trigger_schedule": scheduled_result["transition"],
            "timing": timing_result["transition"],
        },
        "rule_locators": list(dict.fromkeys(
            [locator for event in effect_result["trace"] for locator in event.get("rule_locators", [])]
            + [locator for event in cleanup_result["trace"] for locator in event.get("rule_locators", [])]
            + [locator for event in conditional_trace for locator in event.get("rule_locators", [])]
            + scheduled_result.get("rule_locators", [])
            + timing_result.get("rule_locators", [])
        )),
    }


def _settle_trigger_orders(pending_triggers: list[dict[str, Any]], engine_decisions: dict[str, Any] | None, base: dict[str, Any]) -> dict[str, Any] | None:
    """Core 383.3.d.1: one controller's simultaneously triggered abilities are
    ordered by that controller. Missing or colliding controller_order inside
    one batch is a decision_required; a supplied trigger_order decision
    assigns 0..n-1. Returns a failure result or None."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trigger in pending_triggers:
        groups.setdefault((trigger.get("batch_id"), trigger.get("controller")), []).append(trigger)
    for (batch_id, controller), members in sorted(groups.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        if len(members) < 2:
            continue
        orders = [t.get("controller_order") for t in members]
        if all(isinstance(o, int) for o in orders) and len(set(orders)) == len(orders):
            continue
        trigger_ids = [t["trigger_id"] for t in members]
        decision = _ed.trigger_order(engine_decisions, batch_id, controller)
        decision_id = f"trigger_order:{batch_id}:{controller}"
        if decision is None:
            return {
                **base, "valid": True, "committed": False, "stage": "trigger_order",
                "reason_code": "trigger_order_required",
                "reason": f"{controller} has {len(members)} abilities triggered together in batch {batch_id}; their order is {controller}'s choice (Core 383.3.d.1)",
                "decision_ids": [decision_id], "decision_controller": controller,
                "batch_id": batch_id, "trigger_ids": trigger_ids,
                "rule_locators": ["Core 383.3.d", "Core 383.3.d.1"],
            }
        if decision["controller"] != controller:
            return {**base, "valid": True, "committed": False, "applied": False, "stage": "trigger_order", "reason_code": "decision_controller_mismatch",
                    "reason": f"trigger order for {controller} was supplied by {decision['controller']!r}", "batch_id": batch_id, "trigger_ids": trigger_ids}
        if sorted(decision["value"]) != sorted(trigger_ids):
            return {**base, "valid": False, "committed": False, "stage": "engine_decision",
                    "errors": [f"trigger_order {decision_id} must list exactly {sorted(trigger_ids)}, once each; got {decision['value']}"],
                    "reason": "trigger order decision does not match the batch"}
        for position, trigger_id in enumerate(decision["value"]):
            next(t for t in members if t["trigger_id"] == trigger_id)["controller_order"] = position
    return None


def entry_state_for(
    state: dict[str, Any], card: str, controller: str, event_id: str,
    engine_decisions: dict[str, Any] | None = None,
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
    """Core 143.4 / 359.2.c–d defaults, then entry replacements (369.3): the
    object's own `entry_replacements` and this turn's `turn_effects` that set
    the entry state for units the controller plays (ADR-0007 §6). Returns
    (default, final, applied replacements)."""
    obj = state["objects"][card]
    default = "exhausted" if obj["kind"] == "unit" else "ready"
    candidates: list[dict[str, Any]] = []
    for index, replacement in enumerate(obj.get("entry_replacements", []) or []):
        if replacement.get("mode") == "entry_state" and replacement.get("value") in {"ready", "exhausted"}:
            candidates.append({"replacement_id": replacement.get("replacement_id", f"entry:{card}:{index}"),
                               "source": card, "mode": "entry_state", "value": replacement["value"], "rule_locators": ["Core 369.3"]})
    current_turn = state.get("turn_id", DEFAULT_TURN_ID)
    for effect in state.get("turn_effects", []) or []:
        if (effect.get("kind") == "entry_state_for_played_units" and effect.get("controller") == controller
                and effect.get("turn_id") == current_turn and obj["kind"] == "unit"
                and effect.get("value") in {"ready", "exhausted"}):
            candidates.append({"replacement_id": effect["effect_id"], "source": effect.get("source"),
                               "mode": "entry_state_for_played_units", "value": effect["value"],
                               "turn_id": effect.get("turn_id"), "rule_locators": ["Core 369.3"]})
    if len({candidate["value"] for candidate in candidates}) > 1:
        order_map, _ = _ed.replacement_maps(engine_decisions)
        replacement_ids = [candidate["replacement_id"] for candidate in candidates]
        supplied = (order_map or {}).get(event_id)
        if supplied is None:
            return default, default, [], {
                "replacement_decision_required": True,
                "reason": f"conflicting entry-state replacements for {card} require {controller} to choose their order",
                "replacement_ids": replacement_ids, "event_ids": [event_id], "decision_controller": controller,
            }
        if len(supplied) != len(replacement_ids) or set(supplied) != set(replacement_ids):
            return default, default, [], {"error": f"replacement order for {event_id} must list exactly {replacement_ids}, once each"}
        by_id = {candidate["replacement_id"]: candidate for candidate in candidates}
        candidates = [by_id[replacement_id] for replacement_id in supplied]
    final = default
    applied: list[dict[str, Any]] = []
    for candidate in candidates:
        final = candidate["value"]
        applied.append(candidate)
    return default, final, applied, None


def complete_permanent_play(
    state: dict[str, Any], item_id: str, engine_decisions: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """ADR-0007 §1 (Core 359.2): the permanent leaves the chain and becomes a
    new object on the board (124); entry replacements apply; a Unit enters the
    location chosen at play, a Non-Unit Gear its controller's Base (359.2.d);
    the play is then complete and "When you play me" triggers are collected
    (419.4.a) for the caller to schedule before the board-entry Cleanup."""
    working = copy.deepcopy(state)
    entry = working["chain_items"][item_id]
    card, controller = entry["card"], entry["controller"]
    obj = working["objects"][card]
    location = entry.get("entry_location")
    if obj["kind"] == "unit" and location is None:
        return state, {"error": f"unit {card!r} on the chain has no entry_location; it is chosen at play (Core 355.2)"}, []
    if obj["kind"] == "gear" and location is not None and location.get("kind") != "base":
        return state, {"error": f"gear {card!r} may only enter its controller's Base (Core 359.2.d)"}, []
    del working["chain_items"][item_id]
    if not working["chain_items"]:
        del working["chain_items"]
    event_id = f"enter_board:{item_id}"
    default, final, replacements, entry_problem = entry_state_for(working, card, controller, event_id, engine_decisions)
    if entry_problem is not None:
        return state, entry_problem, []
    obj["exhausted"] = final == "exhausted"
    trace: dict[str, Any] = {"card": card, "chain_item_id": item_id, "kind": obj["kind"], "default_entry_state": default,
                             "entry_replacements": replacements, "entry_state": final, "not_a_move": True,
                             "rule_locators": ["Core 359.2", "Core 359.2.a", "Core 143.4", "Core 124", "Core 446.2"]}
    if obj["kind"] == "unit" and location["kind"] == "battlefield":
        battlefield = working["battlefields"][location["battlefield"]]
        battlefield["objects"].append(card)
        trace["destination"] = f"battlefield:{location['battlefield']}"
        trace["rule_locators"].append("Core 359.2.c")
        if battlefield.get("controller") != controller:
            battlefield["contested"] = True
            battlefield["contested_by"] = controller
            trace["contested"] = {"battlefield": location["battlefield"], "contested_by": controller}
            trace["rule_locators"].append("Core 190.3.a.1")
    else:
        working["players"][controller]["zones"]["base"].append(card)
        trace["destination"] = f"{controller}.base"
        trace["rule_locators"].append("Core 359.2.c" if obj["kind"] == "unit" else "Core 359.2.d")
    trace["identity_after"] = _bump_identity(working, card)
    triggers = []
    for descriptor in obj.get("play_triggers", []) or []:
        copied = copy.deepcopy(descriptor)
        copied.setdefault("trigger_kind", "triggered")
        copied["play_completion"] = item_id
        triggers.append(copied)
    trace["play_triggers"] = [t["trigger_id"] for t in triggers]
    trace["rule_locators"] += ["Core 419.4.a"] if triggers else []
    return working, trace, triggers


TURN_STEP_VERSION = "riftbound-turn-step-result.v1"


def _turn_base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": TURN_STEP_VERSION, "step": step,
            "input_timing_state_hash": state_hash(timing_state), "input_effect_state_hash": hash_value(effect_state)}


def begin_ending_step(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0007 §8 / Core 317.1: enter the Ending Step, evaluate "At the end of
    your turn" triggers of the turn player's board objects (383.1, with the
    383.2.a.1 condition checked now) and schedule them as one batch. Nothing
    expires here; that is run_expiration_step once the chain has emptied."""
    base = _turn_base("begin_ending_step", timing_state, effect_state)
    errors = [f"timing: {e}" for e in validate_timing_state(timing_state)] + [f"effect: {e}" for e in validate_state(effect_state)]
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "reason": "; ".join(errors)}
    if timing_state.get("phase") != "main":
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "ending_step_requires_main_phase", "reason": f"the Ending Step follows the Main Phase (316.9.b); phase is {timing_state.get('phase')!r}", "rule_locators": ["Core 316.9.b", "Core 317.1"]}
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"] or timing_state["showdown"]["active"]:
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "turn_not_quiet", "reason": "the chain, outstanding tasks and any showdown must be finished before the turn ends (316.9)", "rule_locators": ["Core 316.9", "Core 317.1"]}
    turn_player = timing_state["turn_player"]
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    descriptors: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    for object_id in sorted(effect_state["objects"]):
        obj = effect_state["objects"][object_id]
        for descriptor in obj.get("end_of_turn_triggers", []) or []:
            record = {"trigger_id": descriptor["trigger_id"], "source_object": object_id, "controller": descriptor["controller"], "scheduled": False}
            if obj.get("controller") != turn_player or zone_class(find_location(effect_state, object_id)) != "board":
                record["reason"] = "not the turn player's board object"
                evaluated.append(record); continue
            condition = descriptor.get("condition")
            if condition is not None and condition["kind"] == "at_battlefield":
                location = find_location(effect_state, object_id)
                if location is None or location[0] != "battlefield":
                    record["reason"] = "condition at_battlefield not met (383.2.a.1)"
                    evaluated.append(record); continue
            copied = {k: v for k, v in descriptor.items() if k != "condition"}
            copied.update({"trigger_kind": "triggered", "batch_sequence": 0, "batch_id": f"ending:{turn_id}", "ending_step": turn_id})
            descriptors.append(copied)
            record["scheduled"] = True
            evaluated.append(record)
    failure = _settle_trigger_orders(descriptors, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    next_timing["phase"] = "ending"
    next_timing["priority"] = None
    next_timing["ending_step"] = {"status": "triggers_scheduled", "turn_id": turn_id, "scheduled_triggers": [d["trigger_id"] for d in descriptors]}
    scheduled = schedule_triggered_items(next_timing, descriptors)
    if scheduled.get("applied") is not True:
        return {**base, "valid": scheduled.get("valid", True), "committed": False, "applied": False, "reason_code": scheduled.get("reason_code", "trigger_schedule_failed"), "reason": "; ".join(scheduled.get("errors", [])) or scheduled.get("reason_code", "trigger_schedule_failed"), "trigger_result": scheduled}
    final_timing = scheduled["next_state"]
    return {**base, "valid": True, "committed": True, "applied": True, "reason_code": "ok",
            "next_timing_state": final_timing, "next_timing_state_hash": state_hash(final_timing),
            "next_effect_state": copy.deepcopy(effect_state), "next_effect_state_hash": hash_value(effect_state),
            "turn_id": turn_id, "trace": {"ending_triggers": evaluated, "trigger_schedule": scheduled.get("transition")},
            "rule_locators": ["Core 316.9.b", "Core 317.1", "Core 317.1.a", "Core 383.1", "Core 383.2.a.1"]}


def run_expiration_step(timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    """ADR-0007 §8 / Core 317.2: one Ending Special Cleanup, only once the
    Ending Step's triggers are done, the chain is empty and no task is
    outstanding — 3c heal all Units, 3d every "this turn" effect of this
    turn expires at once, 3e every pool empties. Follow-up cleanups are
    normal Cleanups (324.2). The next Beginning Phase is not modelled."""
    base = _turn_base("run_expiration_step", timing_state, effect_state)
    errors = [f"timing: {e}" for e in validate_timing_state(timing_state)] + [f"effect: {e}" for e in validate_state(effect_state)]
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "reason": "; ".join(errors)}
    ending = timing_state.get("ending_step") or {}
    if timing_state.get("phase") != "ending" or ending.get("status") != "triggers_scheduled":
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "expiration_requires_ending_step", "reason": "the Expiration Step follows the Ending Step (317.2); begin_ending_step has not run for this turn", "rule_locators": ["Core 317.1", "Core 317.2"]}
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"]:
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "ending_triggers_unfinished", "reason": "end-of-turn chain items and outstanding tasks must finish before anything expires (317.1, 320)", "rule_locators": ["Core 317.1", "Core 320", "Core 317.2"]}
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    if ending.get("turn_id") not in (None, turn_id):
        return {**base, "valid": False, "committed": False, "errors": [f"ending_step is for turn {ending.get('turn_id')!r}, the effect state is turn {turn_id!r}"], "reason": "turn mismatch"}
    for effect in effect_state.get("turn_effects", []) or []:
        if effect["kind"] not in TURN_EFFECT_KINDS and effect.get("turn_id") == turn_id:
            return {**base, "valid": True, "committed": False, "unsupported": True, "reason": f"turn effect kind {effect['kind']!r} is not modelled; it cannot be expired safely"}
    working = copy.deepcopy(effect_state)
    healed = []
    for object_id, obj in working["objects"].items():
        if obj.get("kind") == "unit" and obj.get("damage", 0) > 0 and zone_class(find_location(working, object_id)) == "board":
            healed.append({"object_id": object_id, "damage": obj["damage"]})
            obj["damage"] = 0
    expired_modifiers = []
    for object_id, obj in working["objects"].items():
        kept = []
        for modifier in obj.get("might_modifiers", []):
            if modifier.get("duration") == "this_turn" and modifier.get("turn_id", turn_id) == turn_id:
                expired_modifiers.append({"object_id": object_id, **modifier})
            else:
                kept.append(modifier)
        obj["might_modifiers"] = kept
    expired_granted = [r["replacement_id"] for r in working["replacement_effects"] if "granted" in r and r["granted"].get("turn_id") == turn_id]
    working["replacement_effects"] = [r for r in working["replacement_effects"] if not ("granted" in r and r["granted"].get("turn_id") == turn_id)]
    expired_effects = [e for e in working.get("turn_effects", []) if e.get("turn_id") == turn_id]
    remaining = [e for e in working.get("turn_effects", []) if e.get("turn_id") != turn_id]
    if remaining:
        working["turn_effects"] = remaining
    else:
        working.pop("turn_effects", None)
    emptied = {}
    for player_id, player in working["players"].items():
        emptied[player_id] = copy.deepcopy(player["resources"])
        player["resources"] = {"energy": 0, "power": {}}
    next_timing = copy.deepcopy(timing_state)
    next_timing["ending_step"] = {**ending, "status": "expired"}
    return {**base, "valid": True, "committed": True, "applied": True, "reason_code": "ok", "turn_id": turn_id,
            "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
            "next_effect_state": working, "next_effect_state_hash": hash_value(working),
            "trace": {"heal_all_units": healed, "expire_this_turn": {"might_modifiers": expired_modifiers, "turn_effects": expired_effects, "granted_replacements": expired_granted}, "empty_rune_pools": emptied,
                      "simultaneous": True, "follow_up_cleanup": "normal (324.2)"},
            "rule_locators": ["Core 317.2", "Core 317.2.a", "Core 317.2.b", "Core 317.2.c", "Core 317.2.d", "Core 324.2"]}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve one Chronicle Chain Item with a typed effect program")
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("item_id")
    parser.add_argument("effect_state", type=Path)
    parser.add_argument("program", type=Path)
    parser.add_argument("--cleanup-decisions", type=Path)
    args = parser.parse_args()
    try:
        result = resolve_with_program(
            _load(args.timing_state), args.item_id, _load(args.effect_state), _load(args.program),
            _load(args.cleanup_decisions) if args.cleanup_decisions else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("valid") and result.get("committed") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
