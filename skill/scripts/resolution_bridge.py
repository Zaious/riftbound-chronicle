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


def resolve_with_program(
    timing_state: dict[str, Any],
    item_id: str,
    effect_state: dict[str, Any],
    program: dict[str, Any],
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
    effect_result = apply_program(effect_state, program)
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
    pending_triggers = effect_result.get("pending_triggers", []) + cleanup_result.get("pending_triggers", [])
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
    args = parser.parse_args()
    try:
        result = resolve_with_program(
            _load(args.timing_state), args.item_id, _load(args.effect_state), _load(args.program)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("valid") and result.get("committed") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
