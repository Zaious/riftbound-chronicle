#!/usr/bin/env python3
"""Normalize Chronicle engine results into the shared engine-check.v1 envelope."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from effect_ir import (
    CORE_RULESET,
    FAQ_AS_OF,
    PROGRAM_VERSION,
    STATE_VERSION as EFFECT_STATE_VERSION,
    apply_program,
    hash_value,
    perform_lethal_cleanup,
)
from engine_decisions import DECISIONS_VERSION as ENGINE_DECISIONS_VERSION, validate_engine_decisions
from resolution_bridge import CLEANUP_DECISION_VERSION, resolve_with_program, validate_cleanup_decisions
from rules_core import (
    SCHEMA_VERSION as RULES_CORE_VERSION,
    derive_permissions,
    next_procedure,
    state_hash,
    validate_timing,
)


SCHEMA_VERSION = "engine-check.v1"
OUTCOMES = {"supported", "illegal", "unsupported", "decision_required", "invalid_input"}
FEATURE_RULES = {
    "typed_selectors": ["Core 108.6.e", "Core 355.7–355.10.d.2", "Core 359.3.e.1–359.3.e.10"],
    "object_identity": ["Core 124–124.1", "Core 359.3.e.4"],
    "engine_decisions": ["Core 355.1–355.17", "Core 370–373", "Core 402–402.1"],
}
KIND_CONFIG = {
    "timing": {
        "component": ("rules_core", RULES_CORE_VERSION),
        "coverage": "timing_permission_v1",
        "supported": ["four_state_timing", "priority_focus", "hot_fepr"],
        "unsupported": ["arbitrary_card_effects", "complete_game", "complete_legality"],
    },
    "effect": {
        "component": ("effect_ir", PROGRAM_VERSION),
        "coverage": "effect_program_v1",
        "supported": ["typed_atomic_effects", "bounded_replacement", "bounded_cleanup", "typed_selectors", "object_identity", "engine_decisions"],
        "unsupported": ["arbitrary_card_text", "combat", "scoring", "complete_game", "complete_legality"],
    },
    "resolution": {
        "component": ("resolution_bridge", "riftbound-resolution-bridge-result.v1"),
        "coverage": "combined_resolution_v1",
        "supported": ["eligible_chain_item", "typed_effect_program", "bounded_cleanup", "trigger_schedule", "engine_decisions"],
        "unsupported": ["arbitrary_card_text", "complete_game", "complete_legality"],
    },
    "cleanup": {
        "component": ("lethal_cleanup", "riftbound-lethal-cleanup-result.v1"),
        "coverage": "lethal_cleanup_v1",
        "supported": ["lethal_damage", "self_death_triggers", "bounded_simultaneous_prevention"],
        "unsupported": ["full_cleanup", "multi_descriptor_replacement", "complete_game", "complete_legality"],
    },
    # ADR-0003 Phase A. The service classifies caller-supplied candidates
    # against the timing kernel; it generates nothing, so enumeration and a
    # complete action set are declared unsupported here and pinned false in
    # legal-action-result.v1 itself.
    "legal_action": {
        "component": ("legal_action_service", "legal-action-result.v1"),
        "coverage": "legal_action_v1",
        "supported": ["user_supplied_candidates", "timing_permission_classification", "perspective_boundary", "hindsight_isolation"],
        "unsupported": ["engine_enumeration", "complete_action_set", "cost_checks", "target_checks", "effect_prerequisites", "complete_game", "complete_legality"],
    },
}

DECISION_REASON_CODES = {
    "trigger_finalize_choice_required": "trigger_choice",
    "trigger_order_required": "trigger_order",
    "effect_execution_confirmation_required": "effect_confirmation",
    "target_selection_required": "target_choice",
}


class EngineCheckError(ValueError):
    pass


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineCheckError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EngineCheckError(f"{path} must contain a JSON object")
    return value


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first_mapping(value: Any, predicate) -> dict[str, Any] | None:
    return next((item for item in _walk(value) if predicate(item)), None)


def _collect_strings(value: Any, key: str) -> list[str]:
    found = []
    for item in _walk(value):
        candidate = item.get(key)
        if isinstance(candidate, list):
            found.extend(entry for entry in candidate if isinstance(entry, str) and entry)
    return list(dict.fromkeys(found))


def _result_message(result: dict[str, Any]) -> str:
    for key in ("explanation", "reason", "message"):
        if isinstance(result.get(key), str):
            return result[key]
    errors = result.get("errors")
    if isinstance(errors, list):
        return "; ".join(str(error) for error in errors)
    nested = _first_mapping(result, lambda item: isinstance(item.get("reason"), str))
    return nested["reason"] if nested else ""


def _reason_code(result: dict[str, Any]) -> str:
    for key in ("reason_code", "reason", "procedure", "stage"):
        if isinstance(result.get(key), str) and result[key]:
            return result[key]
    nested = _first_mapping(result, lambda item: isinstance(item.get("reason_code"), str) or isinstance(item.get("reason"), str))
    if nested:
        return nested.get("reason_code", nested.get("reason", "unknown"))
    return "ok"


def _decision(result: dict[str, Any]) -> dict[str, Any] | None:
    decision_nodes = [item for item in _walk(result) if item.get("replacement_decision_required") is True]
    if decision_nodes:
        decision_node = max(decision_nodes, key=lambda item: len(item.get("replacement_ids", [])) + len(item.get("event_ids", [])))
        reason = str(decision_node.get("reason", ""))
        kind = "replacement_order" if "order" in reason else "replacement_choice"
        return {
            "kind": kind,
            "controller": decision_node.get("decision_controller"),
            "replacement_ids": [item for item in decision_node.get("replacement_ids", []) if isinstance(item, str)],
            "event_ids": [item for item in decision_node.get("event_ids", []) if isinstance(item, str)],
            "decision_ids": [],
            "decision_schema": CLEANUP_DECISION_VERSION if decision_node.get("event_ids") else None,
        }
    reason_node = _first_mapping(result, lambda item: item.get("reason_code") in DECISION_REASON_CODES)
    if reason_node is not None:
        code = reason_node["reason_code"]
        decision_ids = [item for item in reason_node.get("decision_ids", []) if isinstance(item, str)]
        return {
            "kind": DECISION_REASON_CODES[code],
            "controller": reason_node.get("decision_controller") or reason_node.get("controller"),
            "replacement_ids": [],
            "event_ids": [],
            "decision_ids": decision_ids,
            "decision_schema": ENGINE_DECISIONS_VERSION if decision_ids else None,
        }
    return None


def classify_outcome(kind: str, result: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if kind == "legal_action":
        # The result already carries one verdict per candidate; the envelope
        # summarises and must not invent an outcome the result did not reach.
        if result.get("valid") is False:
            return "invalid_input", None
        if result.get("reason_code") == "legal_action_decision_required":
            pending = [c for c in result.get("candidates", []) if c.get("verdict") == "decision_required"]
            return "decision_required", {
                "kind": "other",
                "controller": None,
                "replacement_ids": [],
                "event_ids": [],
                "decision_ids": [str(c.get("decision_id")) for c in pending if c.get("decision_id")],
                "decision_schema": None,
            }
        if result.get("reason_code") == "unsupported_all_candidates":
            return "unsupported", None
        return "supported", None
    decision = _decision(result)
    if decision is not None:
        return "decision_required", decision
    if result.get("valid") is False:
        return "invalid_input", None
    if _first_mapping(result, lambda item: item.get("unsupported") is True) is not None:
        return "unsupported", None
    reason = _reason_code(result)
    if reason.startswith("unsupported"):
        return "unsupported", None
    if kind == "timing" and result.get("legal") is False:
        return "illegal", None
    if kind == "resolution" and result.get("committed") is not True:
        return ("invalid_input" if result.get("stage") in {"program_binding", "cleanup_decision"} else "illegal"), None
    if result.get("applied") is False:
        return "illegal", None
    if kind in {"effect", "cleanup"} and result.get("committed") is not True:
        return "unsupported", None
    return "supported", None


def _trace_summary(result: dict[str, Any], *, include_raw: bool) -> dict[str, Any]:
    trace = result.get("trace")
    event_count = 0
    if isinstance(trace, list):
        event_count = len(trace)
    elif isinstance(trace, dict):
        event_count = sum(len(value) for value in trace.values() if isinstance(value, list))
    outcomes = []
    for item in _walk(trace):
        if isinstance(item.get("outcome"), str):
            outcomes.append(item["outcome"])
    summary: dict[str, Any] = {
        "event_count": event_count,
        "outcomes": list(dict.fromkeys(outcomes)),
        "raw_result_included": include_raw,
    }
    if isinstance(result.get("stage"), str):
        summary["stage"] = result["stage"]
    if isinstance(result.get("procedure"), str):
        summary["procedure"] = result["procedure"]
    return summary


def build_engine_check(
    kind: str,
    result: dict[str, Any],
    *,
    input_hashes: dict[str, str],
    assumptions: list[str] | None = None,
    missing_information: list[str] | None = None,
    include_raw: bool = False,
    capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in KIND_CONFIG:
        raise EngineCheckError(f"unsupported check kind {kind!r}")
    if not isinstance(result, dict):
        raise EngineCheckError("engine result must be an object")
    outcome, decision = classify_outcome(kind, result)
    config = KIND_CONFIG[kind]
    result_hash = canonical_hash(result)
    identity = canonical_hash({"kind": kind, "result_hash": result_hash, "input_hashes": input_hashes})
    check: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "check_id": f"engine-check:{identity.split(':', 1)[1][:24]}",
        "check_kind": kind,
        "outcome": outcome,
        "authority": {"official_status": "unofficial", "role": "consistency_check", "state_effect": "none"},
        "ruleset": copy.deepcopy(result.get("ruleset", {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF})),
        "component": {"name": config["component"][0], "version": config["component"][1]},
        "coverage": {
            "id": config["coverage"], "complete_game": False, "complete_legality": False,
            "supported_scope": copy.deepcopy(config["supported"]),
            "unsupported_scope": copy.deepcopy(config["unsupported"]),
        },
        "input_hashes": copy.deepcopy(input_hashes),
        "result_hash": result_hash,
        "reason": {"code": _reason_code(result), "message": _result_message(result)},
        "rule_locators": _collect_strings(result, "rule_locators"),
        "trace_summary": _trace_summary(result, include_raw=include_raw),
        "assumptions": list(dict.fromkeys(assumptions or [])),
        "missing_information": list(dict.fromkeys(missing_information or [])),
    }
    state_node = _first_mapping(result, lambda item: isinstance(item.get("state_label"), str))
    if state_node is not None:
        check["state_label"] = state_node["state_label"]
    if decision is not None:
        check["decision_required"] = decision
    if capability is not None:
        # ADR-0002: which capability set and which build produced this check.
        # Optional on purpose -- checks emitted before the manifest existed
        # stay valid, and binding must never change outcome or result_hash.
        problems = _capability_errors(capability)
        if problems:
            raise EngineCheckError("invalid capability binding: " + "; ".join(problems))
        check["capability"] = copy.deepcopy(capability)
    if include_raw:
        check["raw_result"] = copy.deepcopy(result)
    errors = validate_engine_check(check)
    if errors:
        raise EngineCheckError("generated invalid engine check: " + "; ".join(errors))
    return check


def validate_engine_check(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["engine check must be an object"]
    required = {
        "schema_version", "check_id", "check_kind", "outcome", "authority", "ruleset", "component",
        "coverage", "input_hashes", "result_hash", "reason", "rule_locators", "trace_summary",
        "assumptions", "missing_information",
    }
    optional = {"state_label", "decision_required", "raw_result", "capability"}
    errors = []
    if set(value) - required - optional or not required.issubset(value):
        errors.append("engine check top-level fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if value.get("outcome") not in OUTCOMES:
        errors.append("outcome is invalid")
    authority = value.get("authority")
    if authority != {"official_status": "unofficial", "role": "consistency_check", "state_effect": "none"}:
        errors.append("authority boundary is invalid")
    coverage = value.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete_game") is not False or coverage.get("complete_legality") is not False:
        errors.append("coverage must reject complete-game and complete-legality claims")
    hashes = value.get("input_hashes")
    if not isinstance(hashes, dict) or not hashes or any(not isinstance(item, str) or not item.startswith("sha256:") for item in hashes.values()):
        errors.append("input_hashes is invalid")
    decision = value.get("decision_required")
    if (value.get("outcome") == "decision_required") != isinstance(decision, dict):
        errors.append("decision_required must exist only for that outcome")
    elif isinstance(decision, dict):
        required_decision = {"kind", "controller", "replacement_ids", "event_ids", "decision_ids"}
        if not required_decision.issubset(decision):
            errors.append("decision_required is missing actionable id arrays")
        for key in ("replacement_ids", "event_ids", "decision_ids"):
            if not isinstance(decision.get(key), list) or any(not isinstance(item, str) or not item for item in decision.get(key, [])):
                errors.append(f"decision_required.{key} must be a string array")
    for key in ("rule_locators", "assumptions", "missing_information"):
        if not isinstance(value.get(key), list) or any(not isinstance(item, str) or not item for item in value.get(key, [])):
            errors.append(f"{key} must be a string array")
    if "capability" in value:
        errors.extend(_capability_errors(value["capability"]))
    return errors


CAPABILITY_FIELDS = {"manifest_id", "capability_set_id", "implementation_identity"}


def _capability_errors(value: Any) -> list[str]:
    """Shape of the optional ADR-0002 binding; whether it names a real manifest is capability_manifest.verify."""
    if not isinstance(value, dict) or set(value) != CAPABILITY_FIELDS:
        return ["capability must contain exactly manifest_id, capability_set_id, implementation_identity"]
    errors = []
    if not isinstance(value["manifest_id"], str) or not value["manifest_id"].startswith("capability-manifest:"):
        errors.append("capability.manifest_id is invalid")
    for key in ("capability_set_id", "implementation_identity"):
        item = value[key]
        if not isinstance(item, str) or not item.startswith("sha256:") or len(item) != len("sha256:") + 64:
            errors.append(f"capability.{key} must be a sha256 hash")
    return errors


def run_timing(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    state = load_object(args.state)
    if args.operation == "validate-timing":
        if args.payload is None:
            raise EngineCheckError("validate-timing requires --payload")
        result = validate_timing(state, load_object(args.payload))
    elif args.operation == "next":
        result = next_procedure(state)
    else:
        result = derive_permissions(state)
    return result, {"timing_state": state_hash(state)}


def _engine_decisions(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = load_object(path)
    errors = validate_engine_decisions(value)
    if errors:
        raise EngineCheckError("invalid engine-decisions.v1: " + "; ".join(errors))
    return value


def run_effect(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    state, program = load_object(args.state), load_object(args.program)
    decisions = _engine_decisions(getattr(args, "decisions", None))
    hashes = {"effect_state": hash_value(state), "effect_program": canonical_hash(program)}
    if decisions is not None:
        hashes["engine_decisions"] = canonical_hash(decisions)
    return apply_program(state, program, decisions=decisions), hashes


def _cleanup_decisions(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = load_object(path)
    if errors := validate_cleanup_decisions(value):
        raise EngineCheckError("invalid cleanup decisions: " + "; ".join(errors))
    return value


def run_resolution(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    timing_state = load_object(args.timing_state)
    effect_state = load_object(args.effect_state)
    program = load_object(args.program)
    decisions = _cleanup_decisions(args.cleanup_decisions)
    result = resolve_with_program(timing_state, args.item_id, effect_state, program, decisions, engine_decisions=_engine_decisions(getattr(args, "decisions", None)))
    hashes = {
        "timing_state": state_hash(timing_state), "effect_state": hash_value(effect_state),
        "effect_program": canonical_hash(program),
    }
    if decisions is not None:
        hashes["cleanup_decisions"] = canonical_hash(decisions)
    if getattr(args, "decisions", None) is not None:
        hashes["engine_decisions"] = canonical_hash(load_object(args.decisions))
    return result, hashes


def run_cleanup(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str]]:
    state = load_object(args.state)
    decisions = _cleanup_decisions(args.cleanup_decisions)
    result = perform_lethal_cleanup(
        state,
        replacement_event_order=(decisions or {}).get("replacement_event_order"),
        replacement_choices=(decisions or {}).get("replacement_choices"),
    )
    hashes = {"effect_state": hash_value(state)}
    if decisions is not None:
        hashes["cleanup_decisions"] = canonical_hash(decisions)
    return result, hashes


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--decisions", type=Path, help="engine-decisions.v1 envelope (ADR-0005)")
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--assumption", action="append", default=[])
    parser.add_argument("--missing-information", action="append", default=[])
    parser.add_argument("--output", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Chronicle engines and emit engine-check.v1")
    sub = parser.add_subparsers(dest="command", required=True)
    timing = sub.add_parser("timing")
    timing.add_argument("state", type=Path)
    timing.add_argument("--operation", choices=["validate-timing", "next", "permissions"], default="validate-timing")
    timing.add_argument("--payload", type=Path)
    add_common(timing)
    effect = sub.add_parser("effect")
    effect.add_argument("state", type=Path)
    effect.add_argument("program", type=Path)
    add_common(effect)
    resolution = sub.add_parser("resolution")
    resolution.add_argument("timing_state", type=Path)
    resolution.add_argument("item_id")
    resolution.add_argument("effect_state", type=Path)
    resolution.add_argument("program", type=Path)
    resolution.add_argument("--cleanup-decisions", type=Path)
    add_common(resolution)
    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("state", type=Path)
    cleanup.add_argument("--cleanup-decisions", type=Path)
    add_common(cleanup)
    validate = sub.add_parser("validate")
    validate.add_argument("artifact", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            errors = validate_engine_check(load_object(args.artifact))
            if errors:
                raise EngineCheckError("; ".join(errors))
            print("OK: valid engine-check.v1")
            return 0
        runner = {"timing": run_timing, "effect": run_effect, "resolution": run_resolution, "cleanup": run_cleanup}[args.command]
        result, input_hashes = runner(args)
        check = build_engine_check(
            args.command,
            result,
            input_hashes=input_hashes,
            assumptions=args.assumption,
            missing_information=args.missing_information,
            include_raw=args.include_raw,
        )
        payload = json.dumps(check, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    except (EngineCheckError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
