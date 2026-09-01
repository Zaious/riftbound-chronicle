#!/usr/bin/env python3
"""
Regenerate the Deck Coach behavior-coverage viewer fixtures from the real
projection.

`deck-behavior-coverage.v1` has four availability statuses, and a prototype that
only ever renders one of them is a prototype that will look fine right up until
the day the others occur. These fixtures are produced by running the genuine
`summarize_profile_coverage` against a real Deck Coach profile, so what the page
displays is what the projection actually emits.

The manifests here are **demonstration manifests, not an R3 pack**. They exist
to produce the four statuses; they claim executable behavior for three cards
with invented clause ids and fixture text hashes. Nothing in this file is a
production card-behavior manifest, and no ordinary Deck Coach run reads it: the
real answer for a real deck today is `unavailable`, which is why that is the
fixture the page shows before anything is imported.

The output is committed as JavaScript, not JSON, because the prototype pages
open straight from disk and make no network requests.

Usage:
    python3 skill/scripts/build_behavior_coverage_fixtures.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent
OUT = REPO_ROOT / "prototype" / "shared" / "behavior-coverage-fixtures.js"

sys.path.insert(0, str(SCRIPT_DIR))

from card_behavior_coverage import card_key, summarize_profile_coverage, validate_manifest  # noqa: E402
from deck_coach_pipeline import CardCatalog, build_profile, load_cases  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF  # noqa: E402

BANNER = """// GENERATED FILE -- do not edit by hand.
// Produced by skill/scripts/build_behavior_coverage_fixtures.py from the real
// deck-behavior-coverage.v1 projection, using demonstration manifests that are
// NOT an R3 card behavior pack. Read-only display data for the Deck Coach
// prototype. Regenerate and commit after any projection change.
"""


def clause(clause_id: str, status: str, *, op: str | None = None, missing: list[str] | None = None) -> dict:
    """One demonstration clause. The ids and hashes are invented on purpose."""
    return {
        "clause_id": clause_id,
        "source_id": "demonstration-fixture",
        "locator": f"demonstration:{clause_id}",
        "text_hash": "sha256:" + clause_id[-1] * 64,
        "status": status,
        "program_id": f"program:{clause_id}" if status in {"full", "partial"} else None,
        "implemented_ops": [op] if op else [],
        "unsupported_mechanics": missing or [],
        "test_ids": [f"test:{clause_id}"] if status in {"full", "partial"} else [],
        "notes": "demonstration entry; not a production R3 program",
    }


def demonstration_manifest(profile: dict, *, status: str = "active", environment: str | None = None) -> dict:
    """A manifest shaped like an R3 pack, covering three cards of one real deck.

    Three cards, not the whole list, so the projection has to report `uncovered`
    copies alongside covered ones -- a manifest that happens to cover everything
    would hide the count the page most needs to show honestly.
    """
    entries = profile["resolution"]["resolved_entries"][:3]
    assignments = [
        ("full", [clause("clause-a", "full", op="exhaust")]),
        ("partial", [clause("clause-b", "partial", op="draw", missing=["conditional_choice"])]),
        ("unsupported", [clause("clause-c", "unsupported", missing=["attachment"])]),
    ]
    cards = []
    for entry, (card_status, clauses) in zip(entries, assignments):
        cards.append({
            "card_key": card_key(entry["canonical_name"]),
            "canonical_name": entry["canonical_name"],
            "current_text_hash": entry["current_text_hash"],
            "printing_ids": [entry["riftbound_id"]] if entry.get("riftbound_id") else [],
            "behavior_status": card_status,
            "clauses": clauses,
        })
    context = profile["context"]
    return {
        "schema_version": "card-behavior-manifest.v1",
        "manifest_id": "demonstration-manifest",
        "pack_id": "demonstration-pack",
        "status": status,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "environment": {
            "environment_id": environment or context["environment"],
            "region": context["region"],
            "formats": [context["format"]],
        },
        "verified_at": "2026-09-01",
        "cards": cards,
    }


def stale_entry_manifest(profile: dict) -> dict:
    """An active manifest with one entry bound to text that has since changed.

    This is the difference between a stale *manifest* (status not active) and a
    stale *entry* (the card was re-worded). Both are called stale and they mean
    different things, so the page has to be able to show each.
    """
    manifest = demonstration_manifest(profile)
    manifest["cards"][0]["current_text_hash"] = "sha256:" + "e" * 64
    return manifest


def build_fixtures() -> dict:
    catalog = CardCatalog()
    case = next(item for item in load_cases() if item["case_id"] == "DC-RNG-GLOBAL-001")
    profile = build_profile(case["input"], catalog)

    active = demonstration_manifest(profile)
    if errors := validate_manifest(active):
        raise SystemExit(f"demonstration manifest is invalid: {errors}")

    # One fixture per availability status, each from the real projection.
    variants = [
        ("unavailable", "unavailable", None,
         "The ordinary case today: no R3 pack is bundled, so no card in this deck has an executable behavior claim."),
        ("available", "available", active,
         "A demonstration manifest covers three cards of this list. The remaining copies stay uncovered, which is the number that matters."),
        ("stale_manifest", "stale", demonstration_manifest(profile, status="draft"),
         "The manifest exists but is not active, so nothing in it may be consumed as a current executable claim."),
        ("incompatible", "incompatible", demonstration_manifest(profile, environment="taiwan-set1-banned"),
         "The manifest was built for a different environment. Coverage from it says nothing about this deck here."),
        # An active manifest whose entry no longer matches the card's current
        # text. Without this the `stale` copy count is zero everywhere and the
        # page would ship a counter nobody had ever seen render.
        ("available_stale_entry", "available", stale_entry_manifest(profile),
         "The manifest is active, but one card's text has changed since it was verified, so those copies count as stale rather than covered."),
    ]

    fixtures = []
    for fixture_id, expected_status, manifest, note in variants:
        coverage = summarize_profile_coverage(copy.deepcopy(profile), copy.deepcopy(manifest) if manifest else None)
        if coverage["status"] != expected_status:
            raise SystemExit(f"variant {fixture_id!r} produced status {coverage['status']!r}, expected {expected_status!r}")
        if coverage["strategy_evidence"] != "not_established_by_engine_coverage":
            raise SystemExit(f"variant {fixture_id!r} lost its strategy_evidence marker")
        fixtures.append({
            "fixture_id": fixture_id,
            "note": note,
            "deck_id": case["input"]["deck_id"],
            "coverage": coverage,
        })

    covered = {item["coverage"]["status"] for item in fixtures}
    expected = {"unavailable", "available", "stale", "incompatible"}
    if covered != expected:
        raise SystemExit(f"fixtures cover {sorted(covered)}; all of {sorted(expected)} are required")
    # Every copy counter the page shows must be non-zero somewhere, or it ships
    # a number that has never been seen rendered.
    ids = [item["fixture_id"] for item in fixtures]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"fixture ids are not unique: {ids}")
    for key in ("full", "partial", "unsupported", "stale", "uncovered"):
        if not any(item["coverage"]["copy_weighted"][key] for item in fixtures):
            raise SystemExit(f"no fixture exercises a non-zero {key!r} copy count")

    return {
        "schema_version": "behavior-coverage-view-fixtures.v1",
        "generated_by": "skill/scripts/build_behavior_coverage_fixtures.py",
        "note": ("Read-only demonstration data from the real deck-behavior-coverage.v1 projection. "
                 "The manifests behind it are demonstrations, not an R3 card behavior pack, and this is "
                 "not evidence about any deck's strategy."),
        "fixtures": fixtures,
    }


def render_module(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"{BANNER}window.RC_BEHAVIOR_COVERAGE_FIXTURES = Object.freeze({body});\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the committed fixture file is stale")
    args = parser.parse_args()

    rendered = render_module(build_fixtures())
    if args.check:
        if not OUT.exists():
            print(f"FAILED: {OUT.relative_to(REPO_ROOT)} does not exist; run this script without --check")
            return 1
        if OUT.read_text(encoding="utf-8") != rendered:
            print(f"FAILED: {OUT.relative_to(REPO_ROOT)} is stale; re-run build_behavior_coverage_fixtures.py and commit the diff")
            return 1
        print("OK: behavior-coverage fixtures are current.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
