#!/usr/bin/env python3
"""Validate Rule Consult registry, cases, schema, and authority behavior."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_effect_ir import base_state, program
from effect_ir import apply_program, hash_value, perform_lethal_cleanup
from engine_check import build_engine_check
from rule_consult import ConsultationError, attach_engine_check, new_consultation, now_iso, save, validate_consultation
from rules_core import CORE_RULESET, FAQ_AS_OF, summarize_result


SKILL_DIR = Path(__file__).resolve().parent.parent
REGISTRY = SKILL_DIR / "data" / "rules_source_registry.json"
CASES = SKILL_DIR / "data" / "rule_consult_cases.json"
SCHEMA = SKILL_DIR / "schemas" / "rule-consultation.schema.json"
RUNNER = SKILL_DIR / "scripts" / "rule_consult.py"
REQUIRED_KINDS = {"discovery", "core_rules", "tournament_rules", "official_clarification", "errata", "judge_guidance", "community_rulings"}
REQUIRED_SOURCE_FIELDS = {
    "source_id", "title", "authority", "kind", "document_class", "locale", "region",
    "status", "superseded_by", "scope", "url", "version", "effective_date",
    "resolve_at_query_time", "controlling_language",
}
QUESTION_TYPES = {"general_mechanic", "specific_interaction", "tournament_procedure", "source_conflict"}


def expect_invalid(name, value, needle, errors):
    found = validate_consultation(value)
    if not found:
        errors.append(f"{name}: expected invalid, validation passed")
    elif needle and not any(needle in item for item in found):
        errors.append(f"{name}: expected {needle!r}, got {found}")


def main():
    errors = []
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    sources = registry.get("sources", [])
    source_ids = [item.get("source_id") for item in sources]
    if len(source_ids) != len(set(source_ids)):
        errors.append("rules source registry has duplicate source_id values")
    if registry.get("live_entrypoint") not in source_ids:
        errors.append("registry live_entrypoint does not resolve")
    if registry.get("schema_version") != "riftbound-rules-source-registry.v2":
        errors.append("registry must use v2 source metadata")
    if registry.get("controlling_locale") != "en-US":
        errors.append("registry must record English as the controlling locale")
    kinds = {item.get("kind") for item in sources}
    if missing := REQUIRED_KINDS - kinds:
        errors.append(f"registry missing source kinds: {sorted(missing)}")
    for index, source in enumerate(sources):
        if missing := REQUIRED_SOURCE_FIELDS - set(source):
            errors.append(f"registry source {index} missing fields: {sorted(missing)}")
        if source.get("authority") not in {"official", "judge_guidance", "community"}:
            errors.append(f"registry source {index} has invalid authority")
        if source.get("status") not in {"active", "superseded", "supporting"}:
            errors.append(f"registry source {index} has invalid status")
        if not str(source.get("url", "")).startswith("https://"):
            errors.append(f"registry source {index} has non-HTTPS URL")
        if source.get("authority") == "community" and source.get("kind") != "community_rulings":
            errors.append(f"community source {source.get('source_id')} has an official-looking kind")
        if source.get("authority") == "judge_guidance" and source.get("document_class") != "judge_faq":
            errors.append(f"judge guidance {source.get('source_id')} must be labeled judge_faq")
        successor = source.get("superseded_by")
        if source.get("status") == "superseded" and not successor:
            errors.append(f"superseded source {source.get('source_id')} lacks superseded_by")
        if successor and successor not in source_ids:
            errors.append(f"source {source.get('source_id')} has unknown successor {successor}")
        if successor == source.get("source_id"):
            errors.append(f"source {source.get('source_id')} supersedes itself")
        if source.get("locale") != "en-US" and source.get("controlling_language") is True:
            errors.append(f"translated source {source.get('source_id')} cannot be controlling")

    case_ids = []
    category_seen = set()
    for index, case in enumerate(cases.get("cases", [])):
        case_id = case.get("case_id")
        case_ids.append(case_id)
        category_seen.add(case.get("category"))
        if case.get("category") not in QUESTION_TYPES:
            errors.append(f"case {case_id} has invalid category")
        if not case.get("facts"):
            errors.append(f"case {case_id} has no facts")
        expected = case.get("expected", {})
        if expected.get("confidence") not in {"High", "Medium", "Low"}:
            errors.append(f"case {case_id} has invalid expected confidence")
        if not expected.get("conclusion_contains"):
            errors.append(f"case {case_id} has no semantic conclusion tokens")
        unknown = set(case.get("source_ids", [])) - set(source_ids)
        if unknown:
            errors.append(f"case {case_id} references unknown sources {sorted(unknown)}")
        if not case.get("locator"):
            errors.append(f"case {case_id} has no source locator")
    if len(case_ids) != len(set(case_ids)):
        errors.append("Rule Consult cases have duplicate case_id values")
    if not {"general_mechanic", "specific_interaction", "tournament_procedure", "source_conflict"}.issubset(category_seen):
        errors.append("case corpus does not cover all initial question categories")

    if schema.get("properties", {}).get("official_status", {}).get("const") != "unofficial":
        errors.append("Rule Consult schema does not lock official_status to unofficial")
    if schema.get("properties", {}).get("state_effect", {}).get("const") != "none":
        errors.append("Rule Consult schema does not lock state_effect to none")
    if schema.get("properties", {}).get("engine_checks", {}).get("items", {}).get("$ref") != "engine-check.schema.json":
        errors.append("Rule Consult schema does not consume engine-check.v1")

    valid = new_consultation(
        question_type="specific_interaction",
        question="Fixture interaction?",
        format_name="1v1 Constructed",
        ruleset_as_of="test fixture",
        created_by="test",
    )
    valid["facts"].append({"text": "A supplied fact", "origin": "user"})
    valid["sources"].append({"source_id": "core-rules-2026-07-16", "locator": "fixture clause", "accessed_at": now_iso()})
    valid["rules_core_check"] = summarize_result({
        "valid": True,
        "legal": True,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": "sha256:" + "0" * 64,
        "state_label": "neutral_open",
        "reason_code": "ok",
        "rule_locators": ["Core 310.1.a"],
    })
    valid["status"] = "final"
    valid["answer"] = {
        "conclusion": "Most likely fixture answer.",
        "conditional": False,
        "analysis_steps": ["Apply the cited clause to the supplied fact."],
        "confidence": "High",
        "confidence_reason": "The official source directly covers the supplied fact.",
        "escalation_required": False,
        "escalation_target": "none",
        "escalation_reason": "",
    }
    if found := validate_consultation(valid):
        errors.append(f"valid final consultation failed: {found}")

    raw_timing_result = {
        "schema_version": "riftbound-rules-core-result.v1",
        "valid": True,
        "legal": True,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": "sha256:" + "1" * 64,
        "state_label": "neutral_open",
        "reason_code": "ok",
        "rule_locators": ["Core 310.1.a"],
    }
    normalized = build_engine_check("timing", raw_timing_result, input_hashes={"timing_state": raw_timing_result["input_state_hash"]})
    modern = new_consultation(
        question_type="specific_interaction", question="Modern engine fixture?",
        format_name="1v1 Constructed", ruleset_as_of="test fixture", created_by="test",
    )
    modern = attach_engine_check(modern, normalized)
    if found := validate_consultation(modern):
        errors.append(f"modern engine-check consultation failed: {found}")
    if modern.get("rules_core_check") is not None or modern.get("engine_checks") != [normalized]:
        errors.append("new consultation did not use engine_checks as its primary executable evidence")
    try:
        attach_engine_check(modern, normalized)
        errors.append("duplicate engine check was accepted")
    except ConsultationError:
        pass

    unsupported_raw = {
        "schema_version": "riftbound-effect-result.v1",
        "valid": True,
        "committed": False,
        "unsupported": True,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": "sha256:" + "2" * 64,
        "reason": "unsupported fixture operation",
        "trace": [],
        "rule_locators": [],
    }
    unsupported_check = build_engine_check(
        "effect", unsupported_raw,
        input_hashes={"effect_state": unsupported_raw["input_state_hash"], "effect_program": "sha256:" + "3" * 64},
    )
    modern_with_abstention = attach_engine_check(modern, unsupported_check)
    if validate_consultation(modern_with_abstention) or modern_with_abstention["engine_checks"][-1].get("outcome") != "unsupported":
        errors.append("Rule Consult did not preserve an unsupported engine abstention")

    # Effect-layer and replacement fixtures, from the real engines rather than
    # hand-written result dicts. Rule Consult must carry a supported effect
    # check beside its timing check, and must carry a decision_required check
    # without the artifact resolving the decision -- the consultation presents
    # the choice; it does not make it.
    effect_state = base_state()
    draw_program = program("rule-consult-draw", {"op": "draw", "player": "p1", "count": 1})
    effect_check = build_engine_check(
        "effect", apply_program(copy.deepcopy(effect_state), draw_program),
        input_hashes={"effect_state": hash_value(effect_state), "effect_program": "sha256:" + "4" * 64},
    )
    with_effect = attach_engine_check(modern, effect_check)
    if validate_consultation(with_effect) or with_effect["engine_checks"][-1].get("outcome") != "supported":
        errors.append("Rule Consult did not accept a supported effect-layer engine check")
    if with_effect["engine_checks"][-1].get("coverage", {}).get("id") != "effect_program_v1":
        errors.append("effect-layer check lost its bounded coverage id in the consultation")

    replacement_state = base_state()
    for object_id in ("u3", "u4"):
        replacement_state["objects"][object_id] = {
            "owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2,
            "might_modifiers": [], "damage": 0, "exhausted": False,
        }
        replacement_state["players"]["p2"]["zones"]["base"].append(object_id)
    replacement_state["objects"]["u2"]["damage"] = 4
    replacement_state["objects"]["u3"]["damage"] = 2
    replacement_state["replacement_effects"] = [{
        "replacement_id": "guard-all", "controller": "p2", "source_object": "u4",
        "mode": "prevent_event", "event_op": "kill", "optional": False,
        "uses_remaining": None, "target_controller_relation": "friendly",
    }]
    decision_check = build_engine_check(
        "cleanup", perform_lethal_cleanup(copy.deepcopy(replacement_state)),
        input_hashes={"effect_state": hash_value(replacement_state)},
    )
    if decision_check.get("outcome") != "decision_required":
        errors.append(f"simultaneous replacement fixture did not produce decision_required: {decision_check.get('outcome')}")
    with_decision = attach_engine_check(with_effect, decision_check)
    if validate_consultation(with_decision):
        errors.append("Rule Consult rejected a decision_required replacement-ordering check")
    stored = with_decision["engine_checks"][-1]
    if stored.get("outcome") != "decision_required" or set(stored.get("decision_required", {}).get("event_ids", [])) != {"u2", "u3"}:
        errors.append("the pending replacement decision was not preserved intact in the consultation")
    if any(key in with_decision for key in ("cleanup_decisions", "replacement_event_order")):
        errors.append("the consultation artifact resolved a controller decision on the player's behalf")

    optional_state = base_state()
    optional_state["replacement_effects"] = [{
        "replacement_id": "optional-shield", "controller": "p2", "source_object": "u2",
        "mode": "prevent_event", "event_op": "deal_damage", "optional": True,
        "uses_remaining": 1, "target_object_id": "u2",
    }]
    optional_program = program("rule-consult-optional", {"op": "deal_damage", "object_id": "u2", "amount": 2})
    choice_check = build_engine_check(
        "effect", apply_program(copy.deepcopy(optional_state), optional_program),
        input_hashes={"effect_state": hash_value(optional_state), "effect_program": "sha256:" + "5" * 64},
    )
    if choice_check.get("outcome") != "decision_required" or choice_check.get("decision_required", {}).get("kind") != "replacement_choice":
        errors.append("optional replacement fixture did not produce a replacement_choice decision")
    elif validate_consultation(attach_engine_check(with_decision, choice_check)):
        errors.append("Rule Consult rejected a replacement_choice decision check")

    bad_engine = copy.deepcopy(modern)
    bad_engine["engine_checks"][0]["coverage"]["complete_game"] = True
    expect_invalid("engine complete-game overclaim", bad_engine, "complete-game", errors)

    bad = copy.deepcopy(valid)
    bad["rules_core_check"]["coverage"] = "complete_game"
    expect_invalid("overstated executable coverage", bad, "coverage", errors)

    bad = copy.deepcopy(valid)
    bad["official_status"] = "official"
    expect_invalid("official impersonation", bad, "official_status", errors)
    bad = copy.deepcopy(valid)
    bad["state_transition"] = "apply"
    expect_invalid("state mutation", bad, "state", errors)
    bad = copy.deepcopy(valid)
    bad["sources"] = [{"source_id": "riftjudge-community", "locator": "fixture", "accessed_at": now_iso()}]
    expect_invalid("community-only High confidence", bad, "official source", errors)
    bad = copy.deepcopy(valid)
    bad["assumptions"] = [{"text": "A missing fact that changes the answer", "material": True}]
    expect_invalid("High confidence with material assumption", bad, "material assumption", errors)
    bad = copy.deepcopy(valid)
    bad["answer"]["escalation_required"] = True
    expect_invalid("escalation without target", bad, "cannot use escalation_target", errors)

    with tempfile.TemporaryDirectory(prefix="rule-consult-engine-") as temp_name:
        temp = Path(temp_name)
        consultation_path = temp / "consultation.json"
        check_path = temp / "engine-check.json"
        save(consultation_path, new_consultation(
            question_type="specific_interaction", question="CLI engine fixture?",
            format_name="1v1 Constructed", ruleset_as_of="test fixture", created_by="test",
        ))
        check_path.write_text(json.dumps(normalized), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(RUNNER), "engine-check", str(consultation_path), "--check", str(check_path)],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0:
            errors.append(f"off-cwd Rule Consult engine-check import failed: {completed.stderr}")
        else:
            imported = json.loads(consultation_path.read_text(encoding="utf-8"))
            if imported.get("engine_checks", [{}])[0].get("check_id") != normalized["check_id"]:
                errors.append("Rule Consult CLI did not persist imported engine check")

        legacy_path = temp / "legacy-core-consultation.json"
        raw_path = temp / "raw-rules-core.json"
        save(legacy_path, new_consultation(
            question_type="specific_interaction", question="Legacy CLI fixture?",
            format_name="1v1 Constructed", ruleset_as_of="test fixture", created_by="test",
        ))
        raw_path.write_text(json.dumps(raw_timing_result), encoding="utf-8")
        converted = subprocess.run(
            [sys.executable, str(RUNNER), "core-check", str(legacy_path), "--result", str(raw_path)],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if converted.returncode != 0:
            errors.append(f"legacy core-check conversion failed: {converted.stderr}")
        else:
            converted_value = json.loads(legacy_path.read_text(encoding="utf-8"))
            if converted_value.get("rules_core_check") is not None or len(converted_value.get("engine_checks", [])) != 1:
                errors.append("legacy core-check command did not migrate output to engine_checks")

    print(f"[info] source registry: {len(sources)} sources across {len(kinds)} kinds; cases: {len(case_ids)} across {len(category_seen)} categories.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} Rule Consult regression(s).")
        return 1
    print("\nOK: Rule Consult registry, cases, schema locks, confidence calibration, and no-state-effect boundary validate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
