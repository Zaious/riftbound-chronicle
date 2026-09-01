#!/usr/bin/env python3
"""Deterministic regression checks for the P2-A authority boundary."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from engine_check import build_engine_check
from p2a_session import (
    VERIFICATION_REQUIREMENTS,
    add_confirmation,
    add_proposal,
    add_state,
    new_session,
    save_session,
    validate_session,
    verification_requirement,
)
from rules_core import CORE_RULESET, FAQ_AS_OF, summarize_result


SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER = SCRIPT_DIR / "p2a_session.py"
SCHEMA = SCRIPT_DIR.parent / "schemas" / "p2a-session.schema.json"


def make_check(outcome):
    input_hash = "sha256:" + {
        "supported": "1", "illegal": "2", "unsupported": "3",
        "decision_required": "4", "invalid_input": "5",
    }[outcome] * 64
    ruleset = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
    if outcome in {"supported", "illegal"}:
        result = {
            "schema_version": "riftbound-rules-core-result.v1", "valid": True,
            "legal": outcome == "supported", "ruleset": ruleset,
            "input_state_hash": input_hash, "state_label": "neutral_open",
            "reason_code": "ok" if outcome == "supported" else "priority_required",
            "rule_locators": ["Core 312"],
        }
        return build_engine_check("timing", result, input_hashes={"timing_state": input_hash})
    if outcome == "unsupported":
        result = {
            "schema_version": "riftbound-effect-result.v1", "valid": True,
            "committed": False, "unsupported": True, "ruleset": ruleset,
            "input_state_hash": input_hash, "reason": "unsupported fixture operation",
            "trace": [], "rule_locators": [],
        }
        return build_engine_check(
            "effect", result,
            input_hashes={"effect_state": input_hash, "effect_program": "sha256:" + "6" * 64},
        )
    if outcome == "decision_required":
        result = {
            "schema_version": "riftbound-lethal-cleanup-result.v1", "valid": True,
            "committed": False, "replacement_decision_required": True,
            "ruleset": ruleset, "input_state_hash": input_hash,
            "reason": "replacement controller must order every qualifying simultaneous event",
            "batch_result": {
                "replacement_decision_required": True, "decision_controller": "p2",
                "replacement_ids": ["guard-all"], "event_ids": ["u2", "u3"],
                "reason": "replacement controller must order every qualifying simultaneous event",
            },
            "trace": [],
        }
        return build_engine_check("cleanup", result, input_hashes={"effect_state": input_hash})
    result = {
        "schema_version": "riftbound-effect-result.v1", "valid": False,
        "committed": False, "ruleset": ruleset, "input_state_hash": input_hash,
        "errors": ["invalid fixture input"], "trace": [],
    }
    return build_engine_check(
        "effect", result,
        input_hashes={"effect_state": input_hash, "effect_program": "sha256:" + "7" * 64},
    )


def expect_invalid(name, session, needle, failures):
    errors = validate_session(session)
    if not errors:
        failures.append(f"{name}: expected invalid, but validation passed")
    elif needle and not any(needle in error for error in errors):
        failures.append(f"{name}: expected error containing {needle!r}, got {errors}")


def main():
    failures = []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    proposal_parts = schema.get("$defs", {}).get("proposalEvent", {}).get("allOf", [])
    proposal_properties = proposal_parts[-1].get("properties", {}) if proposal_parts else {}
    if proposal_properties.get("engine_checks", {}).get("items", {}).get("$ref") != "engine-check.schema.json":
        failures.append("P2-A schema does not consume engine-check.v1")
    if set(proposal_properties.get("verification_requirement", {}).get("enum", [])) != VERIFICATION_REQUIREMENTS:
        failures.append("P2-A schema verification vocabulary diverged from the runtime")
    session = new_session(
        player1_deck="Human deck",
        player2_deck="Agent deck",
        format_name="1v1 Constructed",
        ruleset_version="test fixture",
        created_by="human operator",
    )
    session = add_state(
        session,
        turn=1,
        turn_player="Player 2",
        phase="Main",
        public_state="Human-confirmed public board",
        player2_private_hand="Player 2's own hand",
        confirmed_by="human operator",
    )
    supported_check = make_check("supported")
    session = add_proposal(
        session,
        action_id="p2-001",
        objective="Develop the board",
        description="Take the candidate action supplied to the Agent",
        reason="It advances the stated deck plan",
        alternative="Pass and preserve resources",
        assumptions=["The human will confirm legality"],
        engine_checks=[supported_check],
    )
    session = add_confirmation(
        session,
        action_id="p2-001",
        legal=True,
        confirmed_by="human operator",
        resolution_summary="Human physically resolved the action",
    )

    if validate_session(session):
        failures.append(f"valid P2-A flow failed: {validate_session(session)}")

    updated = add_state(
        session,
        turn=1,
        turn_player="Player 2",
        phase="Main",
        public_state="Human-confirmed resulting board",
        player2_private_hand="Updated Player 2 hand",
        confirmed_by="human operator",
    )
    if validate_session(updated):
        failures.append(f"post-resolution state failed: {validate_session(updated)}")

    expected_requirements = {
        "supported": "standard_human_confirmation",
        "unsupported": "heightened_manual_verification",
        "decision_required": "controller_decision_and_recheck",
        "invalid_input": "input_repair_and_recheck",
        "illegal": "official_source_review_before_override",
    }
    for outcome, expected in expected_requirements.items():
        check = make_check(outcome)
        if verification_requirement([check]) != expected:
            failures.append(f"{outcome} mapped to {verification_requirement([check])!r}, expected {expected!r}")
    if verification_requirement([]) != "heightened_manual_verification":
        failures.append("proposal without an engine check did not require heightened manual verification")

    illegal_session = new_session(
        player1_deck="Human deck", player2_deck="Agent deck", format_name="1v1 Constructed",
        ruleset_version="test fixture", created_by="human operator",
    )
    illegal_session = add_state(
        illegal_session, turn=1, turn_player="Player 2", phase="Main",
        public_state="Human-confirmed public board", player2_private_hand="Player 2 hand",
        confirmed_by="human operator",
    )
    illegal_session = add_proposal(
        illegal_session, action_id="override-001", objective="Audit an engine disagreement",
        description="Candidate rejected by the bounded timing check",
        reason="The human will compare the check against controlling official sources",
        engine_checks=[make_check("illegal")],
    )
    illegal_session = add_confirmation(
        illegal_session, action_id="override-001", legal=True, confirmed_by="human operator",
        resolution_summary="Human overrode the consistency check after official-source review",
    )
    if validate_session(illegal_session):
        failures.append("engine-check illegal outcome became binding legality authority")
    undocumented_override = copy.deepcopy(illegal_session)
    undocumented_override["events"][-1]["resolution_summary"] = ""
    expect_invalid("undocumented engine-check override", undocumented_override, "must record the human verification", failures)

    legacy_session = new_session(
        player1_deck="Human deck", player2_deck="Agent deck", format_name="1v1 Constructed",
        ruleset_version="test fixture", created_by="human operator",
    )
    legacy_session = add_state(
        legacy_session, turn=1, turn_player="Player 2", phase="Main",
        public_state="Legacy state", player2_private_hand="Player 2 hand", confirmed_by="human operator",
    )
    legacy_session = add_proposal(
        legacy_session, action_id="legacy-001", objective="Compatibility",
        description="Legacy proposal", reason="Legacy fixture",
        rules_core_check=summarize_result({
            "valid": True, "legal": True,
            "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "input_state_hash": "sha256:" + "0" * 64, "state_label": "neutral_open",
            "reason_code": "ok", "rule_locators": ["Core 310.1.a"],
        }),
    )
    if validate_session(legacy_session):
        failures.append("legacy rules_core_check proposal no longer validates")

    bad = copy.deepcopy(session)
    bad["p2s_enabled"] = True
    expect_invalid("P2-S activation", bad, "p2s_enabled", failures)

    bad = copy.deepcopy(session)
    bad["state_authority"] = "engine_derived"
    expect_invalid("engine-derived state", bad, "state_authority", failures)

    bad = copy.deepcopy(session)
    bad["legality_authority"] = "rules_engine"
    expect_invalid("rules-engine legality", bad, "legality_authority", failures)

    bad = copy.deepcopy(session)
    bad["events"][1]["legality_status"] = "legal"
    expect_invalid("pre-confirmed proposal", bad, "legality_status", failures)

    bad = copy.deepcopy(session)
    bad["events"][1]["verification_requirement"] = "heightened_manual_verification"
    expect_invalid("mismatched verification burden", bad, "verification_requirement", failures)

    bad = copy.deepcopy(session)
    bad["events"][1]["engine_checks"].append(copy.deepcopy(bad["events"][1]["engine_checks"][0]))
    expect_invalid("duplicate engine check", bad, "duplicates check_id", failures)

    bad = copy.deepcopy(session)
    raw_check = copy.deepcopy(bad["events"][1]["engine_checks"][0])
    raw_check["raw_result"] = {"players": {"p1": {"hand": ["hidden-card"]}}}
    bad["events"][1]["engine_checks"] = [raw_check]
    expect_invalid("raw engine state at P2-A boundary", bad, "must omit raw_result", failures)

    bad = copy.deepcopy(session)
    bad["events"][0]["opponent_private_hand"] = "forbidden"
    expect_invalid("opponent hidden information", bad, "hidden information", failures)

    bad = copy.deepcopy(session)
    bad["events"].append(copy.deepcopy(bad["events"][1]))
    bad["events"][-1]["seq"] = len(bad["events"])
    bad["events"][-1]["action_id"] = "p2-002"
    expect_invalid("proposal before post-resolution snapshot", bad, "must be state_confirmed", failures)

    bad = copy.deepcopy(updated)
    bad["events"][2]["state_transition"] = "engine_derived"
    expect_invalid("derived transition", bad, "state_transition", failures)

    with tempfile.TemporaryDirectory(prefix="p2a-engine-") as temp_name:
        temp = Path(temp_name)
        session_path = temp / "session.json"
        check_path = temp / "engine-check.json"
        base_cli = new_session(
            player1_deck="Human deck", player2_deck="Agent deck", format_name="1v1 Constructed",
            ruleset_version="test fixture", created_by="human operator",
        )
        base_cli = add_state(
            base_cli, turn=1, turn_player="Player 2", phase="Main",
            public_state="CLI state", player2_private_hand="Player 2 hand", confirmed_by="human operator",
        )
        save_session(session_path, base_cli)
        check_path.write_text(json.dumps(make_check("unsupported")), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable, str(RUNNER), "propose", str(session_path),
                "--action-id", "cli-001", "--objective", "Test CLI",
                "--description", "Attach an unsupported check", "--reason", "Fixture",
                "--engine-check", str(check_path),
            ],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0:
            failures.append(f"off-cwd P2-A engine-check proposal failed: {completed.stderr}")
        else:
            imported = json.loads(session_path.read_text(encoding="utf-8"))
            proposal = imported["events"][-1]
            if proposal.get("verification_requirement") != "heightened_manual_verification":
                failures.append("P2-A CLI did not persist the derived unsupported verification burden")

        legacy_cli_path = temp / "legacy-cli-session.json"
        raw_core_path = temp / "raw-core-result.json"
        save_session(legacy_cli_path, base_cli)
        raw_core = {
            "schema_version": "riftbound-rules-core-result.v1", "valid": True, "legal": True,
            "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "input_state_hash": "sha256:" + "8" * 64, "state_label": "neutral_open",
            "reason_code": "ok", "rule_locators": ["Core 310.1.a"],
        }
        raw_core_path.write_text(json.dumps(raw_core), encoding="utf-8")
        converted = subprocess.run(
            [
                sys.executable, str(RUNNER), "propose", str(legacy_cli_path),
                "--action-id", "legacy-cli-001", "--objective", "Compatibility",
                "--description", "Normalize raw timing output", "--reason", "Fixture",
                "--rules-core-result", str(raw_core_path),
            ],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if converted.returncode != 0:
            failures.append(f"legacy P2-A core-result conversion failed: {converted.stderr}")
        else:
            converted_session = json.loads(legacy_cli_path.read_text(encoding="utf-8"))
            converted_proposal = converted_session["events"][-1]
            if converted_proposal.get("rules_core_check") is not None or converted_proposal.get("engine_checks", [{}])[0].get("schema_version") != "engine-check.v1":
                failures.append("legacy --rules-core-result did not normalize to engine_checks")

    if failures:
        print("[errors]")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\nFAILED: {len(failures)} P2-A protocol regression(s).")
        return 1

    print("OK: P2-A protocol accepts the manual flow and rejects automated authority, hidden opponent data, and skipped human snapshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
