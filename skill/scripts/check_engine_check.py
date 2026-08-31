#!/usr/bin/env python3
"""Regression checks for the shared engine-check.v1 integration envelope."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_effect_ir import base_state, program
from check_rules_core import fixture, item
from effect_ir import apply_program, hash_value, perform_lethal_cleanup
from engine_check import SCHEMA_VERSION, build_engine_check, canonical_hash, validate_engine_check
from resolution_bridge import resolve_with_program
from rules_core import state_hash, validate_timing


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SCHEMA = SKILL_DIR / "schemas" / "engine-check.schema.json"
RUNNER = SCRIPT_DIR / "engine_check.py"


def make_check(kind, result, hashes, *, include_raw=False):
    return build_engine_check(
        kind,
        result,
        input_hashes=hashes,
        assumptions=["fixture assumption"],
        missing_information=["fixture missing fact"],
        include_raw=include_raw,
    )


def main() -> int:
    failures = []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        failures.append("engine-check schema and runner version diverged")
    expected_outcomes = {"supported", "illegal", "unsupported", "decision_required", "invalid_input"}
    schema_outcomes = set(schema.get("properties", {}).get("outcome", {}).get("enum", []))
    if schema_outcomes != expected_outcomes:
        failures.append("engine-check schema outcome vocabulary diverged")

    timing_state = fixture()
    legal_action = {"actor": "p1", "kind": "play_card", "timing": "default", "object_kind": "unit"}
    legal_result = validate_timing(timing_state, legal_action)
    legal = make_check("timing", legal_result, {"timing_state": state_hash(timing_state)})
    if legal.get("outcome") != "supported" or legal.get("coverage", {}).get("id") != "timing_permission_v1":
        failures.append("supported timing did not normalize correctly")
    illegal_result = validate_timing(timing_state, {**legal_action, "actor": "p2"})
    illegal = make_check("timing", illegal_result, {"timing_state": state_hash(timing_state)})
    if illegal.get("outcome") != "illegal":
        failures.append("supported illegal timing did not remain distinct")
    unsupported_timing_result = validate_timing(timing_state, {**legal_action, "kind": "unknown"})
    unsupported_timing = make_check("timing", unsupported_timing_result, {"timing_state": state_hash(timing_state)})
    if unsupported_timing.get("outcome") != "unsupported":
        failures.append("unsupported timing action was mislabeled as illegal")

    effects = base_state()
    draw_program = program("engine-check-draw", {"op": "draw", "player": "p1", "count": 1})
    draw_result = apply_program(effects, draw_program)
    draw = make_check(
        "effect", draw_result,
        {"effect_state": hash_value(effects), "effect_program": canonical_hash(draw_program)},
    )
    if draw.get("outcome") != "supported" or draw.get("authority", {}).get("state_effect") != "none":
        failures.append("supported effect or authority boundary normalized incorrectly")
    counter_program = program("engine-check-counter", {"op": "counter", "chain_item_id": "x"})
    counter = make_check(
        "effect", apply_program(effects, counter_program),
        {"effect_state": hash_value(effects), "effect_program": canonical_hash(counter_program)},
    )
    if counter.get("outcome") != "unsupported":
        failures.append("unsupported effect did not abstain")

    optional_state = base_state()
    optional_state["replacement_effects"] = [{
        "replacement_id": "optional-shield", "controller": "p2", "source_object": "u2",
        "mode": "prevent_event", "event_op": "deal_damage", "optional": True,
        "uses_remaining": 1, "target_object_id": "u2",
    }]
    optional_program = program("engine-check-choice", {"op": "deal_damage", "object_id": "u2", "amount": 2})
    optional = make_check(
        "effect", apply_program(optional_state, optional_program),
        {"effect_state": hash_value(optional_state), "effect_program": canonical_hash(optional_program)},
    )
    if optional.get("outcome") != "decision_required" or optional.get("decision_required", {}).get("kind") != "replacement_choice":
        failures.append("replacement choice did not normalize as decision_required")

    invalid_state = base_state()
    invalid_state["players"]["p1"]["zones"]["hand"].append("u1")
    invalid = make_check(
        "effect", apply_program(invalid_state, draw_program),
        {"effect_state": hash_value(invalid_state), "effect_program": canonical_hash(draw_program)},
    )
    if invalid.get("outcome") != "invalid_input":
        failures.append("malformed effect state did not normalize as invalid_input")

    closed_timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    resolution_result = resolve_with_program(closed_timing, "spell-1", effects, draw_program)
    resolution = make_check(
        "resolution", resolution_result,
        {
            "timing_state": state_hash(closed_timing), "effect_state": hash_value(effects),
            "effect_program": canonical_hash(draw_program),
        },
        include_raw=True,
    )
    if resolution.get("outcome") != "supported" or "raw_result" not in resolution or resolution["trace_summary"]["raw_result_included"] is not True:
        failures.append("combined resolution or include_raw did not normalize correctly")

    simultaneous = base_state()
    for object_id in ("u3", "u4"):
        simultaneous["objects"][object_id] = {
            "owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2,
            "might_modifiers": [], "damage": 0, "exhausted": False,
        }
        simultaneous["players"]["p2"]["zones"]["base"].append(object_id)
    simultaneous["objects"]["u2"]["damage"] = 4
    simultaneous["objects"]["u3"]["damage"] = 2
    simultaneous["replacement_effects"] = [{
        "replacement_id": "guard-all", "controller": "p2", "source_object": "u4",
        "mode": "prevent_event", "event_op": "kill", "optional": False,
        "uses_remaining": None, "target_controller_relation": "friendly",
    }]
    cleanup_result = perform_lethal_cleanup(simultaneous)
    cleanup = make_check("cleanup", cleanup_result, {"effect_state": hash_value(simultaneous)})
    decision = cleanup.get("decision_required", {})
    if cleanup.get("outcome") != "decision_required" or decision.get("replacement_ids") != ["guard-all"] or set(decision.get("event_ids", [])) != {"u2", "u3"}:
        failures.append(f"cleanup ordering decision lost its actionable ids: {decision}")

    duplicate = make_check("timing", legal_result, {"timing_state": state_hash(timing_state)})
    if duplicate.get("check_id") != legal.get("check_id") or duplicate.get("result_hash") != legal.get("result_hash"):
        failures.append("engine-check identity is not deterministic")
    overclaim = copy.deepcopy(legal)
    overclaim["coverage"]["complete_game"] = True
    if not validate_engine_check(overclaim):
        failures.append("validator accepted a complete-game coverage overclaim")

    with tempfile.TemporaryDirectory(prefix="engine-check-") as temp_name:
        temp = Path(temp_name)
        state_path, action_path, output_path = temp / "state.json", temp / "action.json", temp / "check.json"
        state_path.write_text(json.dumps(timing_state), encoding="utf-8")
        action_path.write_text(json.dumps(legal_action), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(RUNNER), "timing", str(state_path), "--payload", str(action_path), "--output", str(output_path)],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0 or not output_path.exists():
            failures.append(f"off-cwd engine-check CLI failed: {completed.stderr}")
        else:
            cli_value = json.loads(output_path.read_text(encoding="utf-8"))
            if cli_value.get("outcome") != "supported" or validate_engine_check(cli_value):
                failures.append("off-cwd engine-check CLI emitted an invalid artifact")
            validated = subprocess.run(
                [sys.executable, str(RUNNER), "validate", str(output_path)],
                cwd=temp, text=True, capture_output=True, check=False,
            )
            if validated.returncode != 0:
                failures.append(f"engine-check CLI validation failed: {validated.stderr}")

    print("[info] engine-check: timing, effect, resolution, cleanup, five outcomes, raw-result option, and off-cwd CLI.")
    if failures:
        print("\n".join(f"FAILED: {failure}" for failure in failures))
        return 1
    print("OK: engine-check.v1 preserves bounded coverage, decisions, hashes, and non-authoritative consumer semantics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
