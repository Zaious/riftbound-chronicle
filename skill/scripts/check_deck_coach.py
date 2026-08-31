#!/usr/bin/env python3
"""Validate the executable Deck Coach closed loop and evaluation suite."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from deck_coach import PRIMER_SECTIONS as LEGACY_PRIMER_SECTIONS
from deck_coach_pipeline import (
    PRIMER_SECTIONS,
    CardCatalog,
    battle,
    build_mask,
    build_profile,
    evaluate_candidate,
    generate_baseline_primer,
    load_cases,
    validate_input,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent
ROLES = SKILL_DIR / "data" / "deck_coach_roles.json"
ENVIRONMENTS = SKILL_DIR / "data" / "deck_coach_environments.json"
CASES = SKILL_DIR / "data" / "deck_coach_cases.json"
PIPELINE_SRC = SKILL_DIR / "scripts" / "deck_coach_pipeline.py"
BRIDGE_SRC = SKILL_DIR / "scripts" / "riftatlas_bridge.py"
METHOD_DOC = SKILL_DIR / "references" / "deck-coach" / "deck-coach.md"
SCHEMAS = {
    "deck-coach-input.schema.json": ("schema_version", "deck-coach-input.v1"),
    "deck-profile.schema.json": ("schema_version", "deck-profile.v1"),
    "recommendation-mask.schema.json": ("schema_version", "recommendation-mask.v1"),
    "deck-coach-evaluation.schema.json": ("schema_version", "deck-coach-evaluation.v1"),
    "primer-battle.schema.json": ("schema_version", "primer-battle.v1"),
}
RUBRIC = {
    "card_and_rule_factual_accuracy", "format_and_region_legality", "deck_identity",
    "core_loop_identification", "recommendation_actionability", "evidence_and_confidence",
    "abstention_correctness",
}
MASK_REASONS = {
    "not_released_in_environment", "banned_in_format", "outside_legend_domain_identity",
    "not_enough_owned_copies", "source_environment_mismatch", "stale_pre_errata_text",
}


def main():
    errors = []
    roles = json.loads(ROLES.read_text(encoding="utf-8"))
    environments = json.loads(ENVIRONMENTS.read_text(encoding="utf-8"))
    suite = json.loads(CASES.read_text(encoding="utf-8"))
    catalog = CardCatalog()

    # C-01 naming guard. The profile's confidence block reports how much of the
    # decklist matched a card in the bundled snapshot *by name*. That is data
    # resolution, and the old key `card_resolution_coverage` read as though it
    # said something about rules-engine coverage of those cards' behaviour --
    # two unrelated things this project keeps deliberately separate. The name is
    # asserted here, and the ambiguous form is banned across the Deck Coach
    # surface, so the confusion cannot reappear by copy-paste.
    banned_name = "card_" + "resolution_coverage"   # split so this guard does not match itself
    for path in (PIPELINE_SRC, BRIDGE_SRC, METHOD_DOC):
        if not path.exists():
            errors.append(f"naming guard cannot read {path.name}")
        elif banned_name in path.read_text(encoding="utf-8"):
            errors.append(f"{path.name} reintroduces the ambiguous {banned_name!r}; use 'card_lookup_coverage' (card-name lookup, not rules-engine coverage)")

    role_ids = [item.get("role_id") for item in roles.get("roles", [])]
    if len(role_ids) != 8 or len(role_ids) != len(set(role_ids)):
        errors.append("role taxonomy must contain eight unique roles")
    if PRIMER_SECTIONS != LEGACY_PRIMER_SECTIONS:
        errors.append("closed-loop and legacy Deck Coach primer contracts diverge")

    if environments.get("official_legality_source") != "https://playriftbound.com/en-us/rules-hub/":
        errors.append("environment registry does not route legality to the official Rules Hub")
    if not environments.get("live_check_required_for_real_event"):
        errors.append("environment registry must require live re-check for real events")
    if set(environments.get("environments", {})) != {"global-vendetta", "taiwan-set1-banned"}:
        errors.append("environment registry must expose the two supported environments")
    standard_bans = set(environments["formats"]["1v1 Constructed"]["banned_names"])
    expected_bans = {"Called Shot", "Draven - Vanquisher", "Fight or Flight", "Scrapheap", "Stealthy Pursuer", "The Arena's Greatest", "Aspirant's Climb", "The Dreaming Tree", "Obelisk of Power", "Reaver's Row"}
    if standard_bans != expected_bans:
        errors.append(f"1v1 ban snapshot differs from the 2026-07-16 official list: {sorted(standard_bans ^ expected_bans)}")
    if "Master Yi - Wuju Bladesman" not in environments["formats"]["2v2 Constructed"]["banned_names"]:
        errors.append("2v2 mask is missing Master Yi - Wuju Bladesman")

    for filename, (field, const) in SCHEMAS.items():
        schema_path = SKILL_DIR / "schemas" / filename
        if not schema_path.is_file():
            errors.append(f"missing schema {filename}")
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        actual = schema.get("properties", {}).get(field, {}).get("const")
        if actual != const:
            errors.append(f"{filename} does not lock {field} to {const}")

    if suite.get("schema_version") != "deck-coach-eval-suite.v2":
        errors.append("eval suite must use deck-coach-eval-suite.v2")
    if set(suite.get("rubric", [])) != RUBRIC or len(suite.get("rubric", [])) != 7:
        errors.append("eval suite must declare exactly the seven required dimensions")

    case_ids, observed_reasons, battle_fixture = [], set(), None
    for case in load_cases():
        case_id = case.get("case_id")
        case_ids.append(case_id)
        required_case = {"case_id", "title", "pass_threshold", "input", "expected", "expert_reference", "sources"}
        if set(case) != required_case:
            errors.append(f"{case_id}: case fields differ from contract")
            continue
        if found := validate_input(case["input"], catalog):
            errors.append(f"{case_id}: invalid input: {found}")
            continue
        expected = case["expected"]
        required_expected = {"identity_tokens", "must_identify_engine", "must_mention_weakness", "forbidden_claims", "acceptable_uncertainty", "expected_mask_reasons", "expected_blocked_deck_entries"}
        if set(expected) != required_expected:
            errors.append(f"{case_id}: expected fields differ from contract")
        if tuple(case["expert_reference"]) != PRIMER_SECTIONS:
            errors.append(f"{case_id}: expert reference must contain the ordered eight-section primer")
        if not case["sources"] or any(not source.get("effective_date") or not source.get("accessed") for source in case["sources"]):
            errors.append(f"{case_id}: every source needs effective_date and accessed")

        profile = build_profile(case["input"], catalog)
        mask = build_mask(case["input"], profile, catalog)
        candidate = generate_baseline_primer(case["input"], profile, mask, f"baseline-{case_id}", "test", "none")
        evaluation = evaluate_candidate(case, candidate, profile, mask)
        if set(evaluation["dimensions"]) != RUBRIC:
            errors.append(f"{case_id}: evaluation does not produce seven rubric dimensions")
        if not evaluation["overall"]["passed"]:
            errors.append(f"{case_id}: deterministic baseline unexpectedly failed: {evaluation['dimensions']}")
        if mask["deck_legality"]["blocked_count"] != expected["expected_blocked_deck_entries"]:
            errors.append(f"{case_id}: blocked deck count {mask['deck_legality']['blocked_count']} != expected {expected['expected_blocked_deck_entries']}")
        case_reasons = {reason for item in mask["deck_legality"]["checks"] + mask["candidate_results"] for reason in item["reasons"]}
        case_reasons.update(mask["deck_legality"]["source_environment_check"]["reasons"])
        observed_reasons.update(case_reasons)
        missing_reasons = set(expected["expected_mask_reasons"]) - case_reasons
        if missing_reasons:
            errors.append(f"{case_id}: expected mask reasons not observed: {sorted(missing_reasons)}")
        required_profile_fields = {"curve", "domain_requirements", "type_distribution", "battlefield_package", "feature_density", "role_distribution", "engine_cards", "confidence"}
        if not required_profile_fields.issubset(profile):
            errors.append(f"{case_id}: profile is missing observation fields")
        if profile["context"]["player_level"] != case["input"]["player_level"]:
            errors.append(f"{case_id}: player level was not preserved in observation")
        if battle_fixture is None:
            battle_fixture = (case, profile, mask, candidate)

    if len(case_ids) < 3 or len(case_ids) != len(set(case_ids)):
        errors.append("eval suite needs at least three unique executable cases")
    if MASK_REASONS - observed_reasons:
        errors.append(f"eval suite does not exercise mask reasons: {sorted(MASK_REASONS - observed_reasons)}")

    if battle_fixture:
        case, profile, mask, good = battle_fixture
        bad = {
            "schema_version": "deck-coach-candidate.v1",
            "candidate_id": "deliberately-bad",
            "metadata": {"skill_version": "old", "model": "fixture", "generator": "bad-fixture", "generated_at": good["metadata"]["generated_at"]},
            "primer": {key: "Tier 1. Fight or Flight is legal. Always keep everything." for key in PRIMER_SECTIONS},
        }
        bad_eval = evaluate_candidate(case, bad, profile, mask)
        if bad_eval["overall"]["passed"] or bad_eval["overall"]["score"] >= evaluate_candidate(case, good, profile, mask)["overall"]["score"]:
            errors.append("eval does not distinguish the deliberately bad primer from the baseline")
        result = battle(case, good, bad, "A")
        if result["automatic_preference"] != "A" or result["expert_preference"] != "A":
            errors.append("primer battle did not prefer the better candidate")
        if not result["blind_labels"]:
            errors.append("primer battle must keep A/B blind labels")

    with tempfile.TemporaryDirectory(prefix="deck-coach-e2e-") as temp_dir:
        result = subprocess.run(
            [sys.executable, str(SKILL_DIR / "scripts" / "deck_coach_pipeline.py"), "suite", "--output-dir", temp_dir, "--skill-version", "test", "--model", "none"],
            cwd=Path(temp_dir), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode:
            errors.append(f"off-cwd one-command suite failed: {result.stderr or result.stdout}")
        else:
            summary = json.loads((Path(temp_dir) / "summary.json").read_text(encoding="utf-8"))
            if len(summary.get("cases", [])) != len(case_ids):
                errors.append("one-command suite summary omitted cases")
            for case_id in case_ids:
                case_dir = Path(temp_dir) / case_id
                expected_files = {"input.json", "profile.json", "mask.json", "primer.json", "evaluation.json"}
                if {path.name for path in case_dir.glob("*.json")} != expected_files:
                    errors.append(f"{case_id}: one-command output files differ from contract")
            if case_ids:
                good_path = Path(temp_dir) / case_ids[0] / "primer.json"
                bad_path = Path(temp_dir) / "bad-primer.json"
                battle_path = Path(temp_dir) / "battle.json"
                bad_path.write_text(json.dumps(bad, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                battle_run = subprocess.run(
                    [sys.executable, str(SKILL_DIR / "scripts" / "deck_coach_pipeline.py"), "battle", "--case-id", case_ids[0], "--candidate-a", str(good_path), "--candidate-b", str(bad_path), "--expert-preference", "A", "--output", str(battle_path)],
                    cwd=Path(temp_dir), capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                if battle_run.returncode:
                    errors.append(f"off-cwd primer battle CLI failed: {battle_run.stderr or battle_run.stdout}")
                else:
                    battle_output = json.loads(battle_path.read_text(encoding="utf-8"))
                    if battle_output.get("automatic_preference") != "A" or battle_output.get("expert_preference") != "A":
                        errors.append("primer battle CLI did not preserve automatic/expert preference")

    print(f"[info] {len(role_ids)} roles; {len(case_ids)} executable cases; {len(RUBRIC)} dimensions; {len(observed_reasons)} mask reasons exercised.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} Deck Coach closed-loop regression(s).")
        return 1
    print("\nOK: profiler, recommendation mask, expert cases, seven-dimension evaluation, primer battle, and off-cwd one-command suite validate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
