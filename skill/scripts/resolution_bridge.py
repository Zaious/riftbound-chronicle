#!/usr/bin/env python3
"""Atomic bridge between Chronicle timing state and typed effect programs."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from effect_ir import _bump_identity, action_performed, apply_program, hash_value, perform_lethal_cleanup
from rules_core import complete_resolution, schedule_triggered_items, state_hash

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
    if program:
        effect_result = apply_program(effect_state, program, decisions=engine_decisions)
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
        after_effect, entry_trace, entry_triggers = complete_permanent_play(after_effect, item_id)
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
    scheduled_result = schedule_triggered_items(timing_result["next_state"], pending_triggers)
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
        "next_effect_state_hash": cleanup_result["next_state_hash"],
        "trace": {
            "effect": effect_result["trace"],
            "chain_card": chain_card_trace,
            "cleanup": cleanup_result["trace"],
            "conditional_triggers": conditional_trace,
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


def entry_state_for(state: dict[str, Any], card: str, controller: str) -> tuple[str, str, list[dict[str, Any]]]:
    """Core 143.4 / 359.2.c–d defaults, then entry replacements (369.3): the
    object's own `entry_replacements` and this turn's `turn_effects` that set
    the entry state for units the controller plays (ADR-0007 §6). Returns
    (default, final, applied replacements)."""
    obj = state["objects"][card]
    default = "exhausted" if obj["kind"] == "unit" else "ready"
    final = default
    applied: list[dict[str, Any]] = []
    for replacement in obj.get("entry_replacements", []) or []:
        if replacement.get("mode") == "entry_state" and replacement.get("value") in {"ready", "exhausted"}:
            final = replacement["value"]
            applied.append({"source": card, "mode": "entry_state", "value": final, "rule_locators": ["Core 369.3"]})
    for effect in state.get("turn_effects", []) or []:
        if effect.get("kind") == "entry_state_for_played_units" and effect.get("controller") == controller and obj["kind"] == "unit" and effect.get("value") in {"ready", "exhausted"}:
            final = effect["value"]
            applied.append({"source": effect.get("source"), "mode": "entry_state_for_played_units", "value": final, "turn_id": effect.get("turn_id"), "rule_locators": ["Core 369.3"]})
    return default, final, applied


def complete_permanent_play(state: dict[str, Any], item_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
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
    default, final, replacements = entry_state_for(working, card, controller)
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
