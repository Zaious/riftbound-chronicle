#!/usr/bin/env python3
"""Regression checks for the R3 card behavior manifest and Deck Coach projection."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from card_behavior_coverage import card_key, summarize_profile_coverage, validate_manifest
from deck_coach_pipeline import CardCatalog, build_profile, case_input, generate_baseline_primer, build_mask, load_cases
from effect_ir import CORE_RULESET, FAQ_AS_OF


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "card_behavior_coverage.py"
PIPELINE = SCRIPT_DIR / "deck_coach_pipeline.py"


def clause(clause_id, status, *, op=None, missing=None):
    return {
        "clause_id": clause_id, "source_id": "card-snapshot-fixture", "locator": f"fixture:{clause_id}",
        "text_hash": "sha256:" + clause_id[-1] * 64, "status": status,
        "program_id": f"program:{clause_id}" if status in {"full", "partial"} else None,
        "implemented_ops": [op] if op else [], "unsupported_mechanics": missing or [],
        "test_ids": [f"test:{clause_id}"] if status in {"full", "partial"} else [], "notes": "fixture",
    }


def manifest_for(profile):
    entries = profile["resolution"]["resolved_entries"][:3]
    statuses = [
        ("full", [clause("clause-1", "full", op="exhaust")]),
        ("partial", [clause("clause-2", "partial", op="draw", missing=["conditional_choice"])]),
        ("unsupported", [clause("clause-3", "unsupported", missing=["attachment"])]),
    ]
    cards = []
    for entry, (status, clauses) in zip(entries, statuses):
        cards.append({
            "card_key": card_key(entry["canonical_name"]), "canonical_name": entry["canonical_name"],
            "current_text_hash": entry["current_text_hash"],
            "printing_ids": [entry["riftbound_id"]] if entry.get("riftbound_id") else [],
            "behavior_status": status, "clauses": clauses,
        })
    return {
        "schema_version": "card-behavior-manifest.v1", "manifest_id": "fixture-manifest",
        "pack_id": "fixture-pack", "status": "active",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "environment": {
            "environment_id": profile["context"]["environment"], "region": profile["context"]["region"],
            "formats": [profile["context"]["format"]],
        },
        "verified_at": "2026-09-01", "cards": cards,
    }


def main() -> int:
    failures = []
    catalog = CardCatalog()
    deck_input = case_input(load_cases()[0])
    profile = build_profile(deck_input, catalog)
    if profile.get("behavior_coverage", {}).get("status") != "unavailable":
        failures.append("Deck Coach without a manifest did not report behavior coverage unavailable")
    manifest = manifest_for(profile)
    if found := validate_manifest(manifest):
        failures.append(f"valid fixture manifest failed: {found}")
    covered_profile = build_profile(deck_input, catalog, manifest)
    coverage = covered_profile["behavior_coverage"]
    if coverage.get("status") != "available" or coverage.get("strategy_evidence") != "not_established_by_engine_coverage":
        failures.append("compatible manifest did not produce bounded available coverage")
    weighted = coverage.get("copy_weighted", {})
    expected_counts = {
        status: next(entry["count"] for entry in profile["resolution"]["resolved_entries"] if card_key(entry["canonical_name"]) == manifest["cards"][index]["card_key"])
        for index, status in enumerate(("full", "partial", "unsupported"))
    }
    for status, count in expected_counts.items():
        if weighted.get(status) != count:
            failures.append(f"copy-weighted {status} coverage {weighted.get(status)} != {count}")
    if weighted.get("total") != sum(entry["count"] for entry in profile["resolution"]["resolved_entries"] + profile["resolution"]["unknown_entries"]):
        failures.append("behavior coverage total does not match resolved Main Deck copies")
    lookup_gap_profile = copy.deepcopy(profile)
    removed = lookup_gap_profile["resolution"]["resolved_entries"].pop()
    lookup_gap_profile["resolution"]["unknown_entries"].append({
        "name": removed["input_name"], "count": removed["count"], "reason": "not_found_in_snapshot",
    })
    lookup_gap = summarize_profile_coverage(lookup_gap_profile, manifest)
    if lookup_gap["copy_weighted"]["total"] != weighted["total"] or lookup_gap["copy_weighted"]["uncovered"] < removed["count"]:
        failures.append("card lookup failure disappeared from the behavior coverage denominator")

    stale_text = copy.deepcopy(manifest)
    stale_text["cards"][0]["current_text_hash"] = "sha256:" + "f" * 64
    stale = summarize_profile_coverage(profile, stale_text)
    if stale["copy_weighted"]["stale"] != expected_counts["full"]:
        failures.append("current card text drift did not stale the behavior entry")
    incompatible = copy.deepcopy(manifest)
    incompatible["environment"]["environment_id"] = "other-environment"
    if summarize_profile_coverage(profile, incompatible).get("status") != "incompatible":
        failures.append("environment mismatch did not reject behavior coverage")
    stale_manifest = copy.deepcopy(manifest)
    stale_manifest["status"] = "stale"
    if summarize_profile_coverage(profile, stale_manifest).get("status") != "stale":
        failures.append("stale manifest was treated as active")
    overclaim = copy.deepcopy(manifest)
    overclaim["cards"][0]["clauses"][0]["test_ids"] = []
    if not any("full coverage requires" in error for error in validate_manifest(overclaim)):
        failures.append("full behavior coverage was allowed without a behavior test")

    primer = generate_baseline_primer(deck_input, covered_profile, build_mask(deck_input, covered_profile, catalog), "fixture", "test", "none")
    ledger = primer["primer"]["evidence_ledger"]
    if "does not establish deck strategy" not in ledger or "Executable behavior coverage" not in ledger:
        failures.append("Deck Coach primer widened behavior coverage into strategy evidence or omitted it")

    with tempfile.TemporaryDirectory(prefix="behavior-coverage-") as temp_name:
        temp = Path(temp_name)
        profile_path, manifest_path, output_path = temp / "profile.json", temp / "manifest.json", temp / "coverage.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        run = subprocess.run(
            [sys.executable, str(RUNNER), "summarize", str(profile_path), str(manifest_path), "--output", str(output_path)],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if run.returncode != 0 or not output_path.is_file():
            failures.append(f"off-cwd behavior coverage CLI failed: {run.stderr}")

    print("[info] behavior coverage: unavailable, compatible, stale-text, stale-manifest, incompatible, and overclaim cases.")
    if failures:
        print("\n".join(f"FAILED: {failure}" for failure in failures))
        return 1
    print("OK: card lookup, executable clauses, and strategy evidence remain distinct contracts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
