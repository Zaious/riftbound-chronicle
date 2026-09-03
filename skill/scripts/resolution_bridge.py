#!/usr/bin/env python3
"""Atomic bridge between Chronicle timing state and typed effect programs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from effect_ir import apply_program, hash_value, perform_lethal_cleanup
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
    program: dict[str, Any],
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
    effect_result = apply_program(effect_state, program, decisions=engine_decisions)
    if effect_result.get("committed") is not True:
        return {
            **base,
            "valid": effect_result.get("valid", True),
            "committed": False,
            "stage": "effect",
            "reason": effect_result.get("reason", "; ".join(effect_result.get("errors", [])) or "effect_program_failed"),
            "effect_result": effect_result,
        }
    cleanup_result = perform_lethal_cleanup(
        effect_result["next_state"],
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
    cleanup_triggers = [dict(trigger) for trigger in cleanup_result.get("pending_triggers", [])]
    next_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in cleanup_triggers:
        trigger["batch_sequence"] = trigger.get("batch_sequence", 0) + next_batch
    pending_triggers = effect_triggers + cleanup_triggers
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
            "cleanup": cleanup_result["trace"],
            "trigger_schedule": scheduled_result["transition"],
            "timing": timing_result["transition"],
        },
        "rule_locators": list(dict.fromkeys(
            [locator for event in effect_result["trace"] for locator in event.get("rule_locators", [])]
            + [locator for event in cleanup_result["trace"] for locator in event.get("rule_locators", [])]
            + scheduled_result.get("rule_locators", [])
            + timing_result.get("rule_locators", [])
        )),
    }


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
