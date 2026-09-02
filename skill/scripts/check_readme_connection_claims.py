#!/usr/bin/env python3
"""
Reject README connection claims that diverge from the system artifacts.

The checklist defines "engine connected to a system" as six conditions, and
requires documentation to say "partial" or "planned" until all six pass. The
existing README gate checks routed modes and cited counts; it cannot see a
sentence claiming a system is connected. So the READMEs could say anything
about the engine -- and until this gate they said nothing, which is the quiet
form of the same drift.

Each condition is derived from the artifacts themselves, per system, and the
derivation is what the READMEs must agree with. Where a condition can be tested
by running code, it is run: the validator is handed a real supported check, then
the same check with an overstated coverage, and must accept the first and refuse
the second. Where it can only be read from source, the comment says so.

Three things must then agree exactly: the derived status, the connection table
in all three READMEs, and the checklist's own audit table. Overstating and
understating both fail. A README that stays silent about a connected system is
also a failure: the reader is owed the scope, not the absence of a false claim.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent
READMES = ("README.md", "README.zh-TW.md", "README.ko.md")
CHECKLIST = REPO_ROOT / "docs" / "plans" / "ENGINE_AND_SYSTEMS_COMPLETION_CHECKLIST.md"
FIXTURES = REPO_ROOT / "prototype" / "shared" / "engine-check-fixtures.js"

sys.path.insert(0, str(SCRIPT_DIR))

from engine_check import validate_engine_check  # noqa: E402

CONDITIONS = (
    "artifact_accepts_engine_check",
    "runner_produces_or_imports",
    "validator_rejects_overclaim",
    "ui_renders_outcomes",
    "regressions_cover_supported_and_abstaining",
    "authority_boundary_preserved",
)

# The connection table row every README must carry, language-neutral because
# every cell that matters is a code span or a number. The first cell is
# deliberately not a bare `mode` code span: check_readme_sync.py treats those as
# the routed-system table, and match-analyst is not routed.
ROW = re.compile(
    r"^\|\s*`([a-z0-9-]+)`\s*→\s*`engine-check\.v1`\s*\|\s*`(connected|partial|planned)`\s*\|\s*(\d)\s*/\s*6\s*\|",
    re.M,
)
CHECKLIST_ROW = re.compile(r"^\|\s*(Rule Consult|Deck Coach|Player 2 Agent P2-A|Match Analyst)\s*\|\s*(\d)\s*/\s*6\s*\|", re.M)
CHECKLIST_NAMES = {
    "Rule Consult": "rule-consult",
    "Deck Coach": "deck-coach",
    "Player 2 Agent P2-A": "player2-agent",
    "Match Analyst": "match-analyst",
}


def supported_check() -> dict:
    """A real engine-check.v1 with outcome supported, from the committed fixtures."""
    text = FIXTURES.read_text(encoding="utf-8")
    payload = json.loads(text[text.index("Object.freeze(") + len("Object.freeze("):text.rindex(");")])
    return next(item["check"] for item in payload["fixtures"] if item["check"]["outcome"] == "supported")


def consultation_with(check: dict) -> dict:
    from rule_consult import new_consultation
    value = new_consultation(question_type="specific_interaction", question="Does this validate?",
                             format_name="1v1 Constructed", ruleset_as_of="2026-07-16", created_by="connection-gate")
    value["facts"].append({"text": "A supplied fact.", "origin": "user"})
    value["engine_checks"] = [check]
    return value


def session_with(check: dict) -> dict:
    from p2a_session import verification_requirement
    return {
        "schema_version": "p2a-session.v1", "mode": "player2-agent", "automation_level": "P2-A",
        "p2s_enabled": False, "state_authority": "user_confirmed", "legality_authority": "user_confirmed",
        "session_id": "11111111-2222-3333-4444-555555555555", "created_at": "2026-09-01T00:00:00Z",
        "created_by": "connection-gate", "format": "1v1 Constructed", "ruleset_version": "2026-07-16",
        "decks": {"player1": "unknown", "player2": "fixture"},
        "events": [
            {"seq": 1, "type": "state_confirmed", "recorded_at": "2026-09-01T00:00:01Z",
             "authority": "user_confirmed", "confirmed_by": "operator", "turn": 3, "turn_player": "Player 1",
             "phase": "main", "public_state": "as read", "player2_private_hand": "", "notes": ""},
            {"seq": 2, "type": "action_proposed", "recorded_at": "2026-09-01T00:00:02Z",
             "action_id": "a1", "state_seq": 1, "objective": "contest", "description": "play a unit",
             "reason": "pressure", "alternative": "hold", "assumptions": [], "legality_status": "unverified",
             "engine_checks": [check], "verification_requirement": verification_requirement([check])},
        ],
    }


SYSTEMS = {
    "rule-consult": {
        "schema": "rule-consultation.schema.json",
        "runner": "rule_consult.py",
        "checks": ("check_rule_consult.py", "check_rule_consult_prototype.py"),
        "prototype": "rule-consult",
        "boundary": {"official_status": "unofficial", "state_effect": "none"},
        "validate": lambda check: __import__("rule_consult").validate_consultation(consultation_with(check)),
    },
    "player2-agent": {
        "schema": "p2a-session.schema.json",
        "runner": "p2a_session.py",
        "checks": ("check_p2a_protocol.py", "check_p2a_prototype.py"),
        "prototype": "p2a",
        "boundary": {"legality_authority": "user_confirmed", "state_authority": "user_confirmed"},
        "validate": lambda check: __import__("p2a_session").validate_session(session_with(check)),
    },
    "deck-coach": {
        "schema": "deck-coach-session.schema.json",
        "runner": "deck_coach_pipeline.py",
        "checks": ("check_deck_coach.py", "check_deck_coach_prototype.py"),
        "prototype": "deck-coach",
        # No engine-facing authority constant exists yet; the condition is
        # about preserving a boundary after consuming a check, and there is no
        # consumption to preserve it across.
        "boundary": None,
        "validate": None,
    },
    "match-analyst": {
        "schema": None, "runner": None, "checks": (), "prototype": None, "boundary": None, "validate": None,
    },
}


def derive(system: str, spec: dict) -> dict[str, bool]:
    result = {name: False for name in CONDITIONS}
    schema_path = SKILL_DIR / "schemas" / spec["schema"] if spec["schema"] else None
    schema_text = schema_path.read_text(encoding="utf-8") if schema_path and schema_path.is_file() else ""
    schema = json.loads(schema_text) if schema_text else {}

    # 1. The artifact accepts engine-check.v1: a property somewhere in the
    #    schema references the shared envelope schema.
    result["artifact_accepts_engine_check"] = '"engine-check.schema.json"' in schema_text

    # 2. The runner can produce or import a check without hand-editing JSON.
    runner = SKILL_DIR / "scripts" / spec["runner"] if spec["runner"] else None
    runner_text = runner.read_text(encoding="utf-8") if runner and runner.is_file() else ""
    result["runner_produces_or_imports"] = "build_engine_check" in runner_text and "engine_checks" in runner_text

    # 3. The validator accepts a real supported check and rejects the same
    #    check with an overstated coverage and with a required field missing.
    #    Run, not read.
    if spec["validate"] is not None and result["artifact_accepts_engine_check"]:
        good = supported_check()
        if validate_engine_check(good):
            raise SystemExit("the supported fixture is itself invalid; fix the fixtures before trusting this gate")
        overclaim = copy.deepcopy(good)
        overclaim["coverage"]["complete_game"] = True
        malformed = copy.deepcopy(good)
        del malformed["authority"]
        accepted = not spec["validate"](good)
        refused_overclaim = bool(spec["validate"](overclaim))
        refused_malformed = bool(spec["validate"](malformed))
        result["validator_rejects_overclaim"] = accepted and refused_overclaim and refused_malformed

    # 4. The UI renders the outcomes through the shared read-only viewer, which
    #    check_engine_check_view.py holds to all five outcomes.
    if spec["prototype"]:
        html = (REPO_ROOT / "prototype" / spec["prototype"] / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "prototype" / spec["prototype"] / "app.js").read_text(encoding="utf-8")
        result["ui_renders_outcomes"] = "engine-check-view.js" in html and "RC_ENGINE_CHECK_VIEW.mount" in js

    # 5. Regressions include a supported and an abstaining end-to-end case.
    #    Source evidence only: the system's CI check scripts must build or name
    #    a supported check and name the unsupported outcome.
    sources = [(SKILL_DIR / "scripts" / name).read_text(encoding="utf-8") for name in spec["checks"]
               if (SKILL_DIR / "scripts" / name).is_file()]
    joined = "\n".join(sources)
    result["regressions_cover_supported_and_abstaining"] = bool(sources) and (
        ('"supported"' in joined or "build_engine_check(" in joined) and '"unsupported"' in joined
    )

    # 6. The authority boundary survives consuming a check: the schema still
    #    locks its boundary constants, and the check envelope itself is fixed at
    #    unofficial / consistency_check / none by validate_engine_check.
    if spec["boundary"] and schema:
        props = schema.get("properties", {})
        result["authority_boundary_preserved"] = all(
            props.get(key, {}).get("const") == value for key, value in spec["boundary"].items()
        ) and result["artifact_accepts_engine_check"]
    return result


def status_for(conditions: dict[str, bool]) -> str:
    passed = sum(conditions.values())
    if passed == len(CONDITIONS):
        return "connected"
    return "partial" if passed else "planned"


def main() -> int:
    errors: list[str] = []
    derived = {system: derive(system, spec) for system, spec in SYSTEMS.items()}
    expected = {system: (status_for(flags), sum(flags.values())) for system, flags in derived.items()}

    print("[info] derived engine connection from artifacts:")
    for system, (status, passed) in expected.items():
        failing = [name for name, ok in derived[system].items() if not ok]
        print(f"  {system:<15} {status:<10} {passed}/6" + (f"  missing: {', '.join(failing)}" if failing else ""))

    # The three READMEs must each carry the table, and agree with the derivation.
    claims: dict[str, dict[str, tuple[str, int]]] = {}
    for name in READMES:
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        rows = {system: (status, int(count)) for system, status, count in ROW.findall(text)}
        claims[name] = rows
        if not rows:
            errors.append(f"{name}: has no engine connection table; a reader is owed the scope, not the absence of a claim")
            continue
        for system, (status, passed) in expected.items():
            if system not in rows:
                errors.append(f"{name}: connection table omits {system}")
                continue
            claimed_status, claimed_count = rows[system]
            if (claimed_status, claimed_count) != (status, passed):
                verb = "overstates" if (claimed_count, claimed_status) > (passed, status) else "understates"
                errors.append(f"{name}: {verb} {system}: claims `{claimed_status}` {claimed_count}/6, artifacts give `{status}` {passed}/6")
        for system in rows:
            if system not in expected:
                errors.append(f"{name}: connection table names unknown system {system!r}")

    # The checklist's own audit table is documentation too.
    if CHECKLIST.is_file():
        audit = {CHECKLIST_NAMES[label]: int(count) for label, count in CHECKLIST_ROW.findall(CHECKLIST.read_text(encoding="utf-8"))}
        for system, (_, passed) in expected.items():
            if system in audit and audit[system] != passed:
                errors.append(f"checklist audit table says {system} passes {audit[system]}/6, artifacts give {passed}/6")
        if not audit:
            errors.append("could not read the checklist's connection audit table; its shape changed")

    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} connection-claim mismatch(es).")
        return 1
    print("\nOK: README and checklist connection claims match what the artifacts actually support.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
