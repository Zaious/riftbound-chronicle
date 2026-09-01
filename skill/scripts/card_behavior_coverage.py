#!/usr/bin/env python3
"""Validate R3 card behavior manifests and summarize bounded Deck Coach coverage."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from effect_ir import CORE_RULESET, FAQ_AS_OF, SUPPORTED_OPS

MANIFEST_VERSION = "card-behavior-manifest.v1"
COVERAGE_VERSION = "deck-behavior-coverage.v1"
STATUSES = {"full", "partial", "unsupported", "stale"}


class BehaviorCoverageError(ValueError):
    pass


def text_hash(text: str) -> str:
    normalized = " ".join(text.split())
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def card_key(name: str) -> str:
    return " ".join(name.casefold().replace("–", "-").replace("—", "-").split())


def validate_manifest(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["behavior manifest must be an object"]
    required = {"schema_version", "manifest_id", "pack_id", "status", "ruleset", "environment", "verified_at", "cards"}
    errors = []
    if set(value) != required:
        errors.append(f"manifest fields must be exactly {sorted(required)}")
    if value.get("schema_version") != MANIFEST_VERSION:
        errors.append(f"schema_version must be {MANIFEST_VERSION}")
    if value.get("status") not in {"draft", "active", "stale"}:
        errors.append("manifest status is invalid")
    if value.get("ruleset") != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("manifest ruleset does not match the executable baseline")
    environment = value.get("environment")
    if not isinstance(environment, dict) or set(environment) != {"environment_id", "region", "formats"}:
        errors.append("manifest environment shape is invalid")
    elif not isinstance(environment.get("formats"), list) or not environment["formats"]:
        errors.append("manifest environment formats must be non-empty")
    cards = value.get("cards")
    if not isinstance(cards, list):
        errors.append("manifest cards must be an array")
        cards = []
    seen_cards = set()
    for index, card in enumerate(cards):
        label = f"cards[{index}]"
        required_card = {"card_key", "canonical_name", "current_text_hash", "printing_ids", "behavior_status", "clauses"}
        if not isinstance(card, dict) or set(card) != required_card:
            errors.append(f"{label} has invalid fields")
            continue
        if card.get("card_key") != card_key(card.get("canonical_name", "")):
            errors.append(f"{label}.card_key must derive from canonical_name")
        if card.get("card_key") in seen_cards:
            errors.append(f"{label}.card_key is duplicated")
        seen_cards.add(card.get("card_key"))
        if card.get("behavior_status") not in STATUSES:
            errors.append(f"{label}.behavior_status is invalid")
        clauses = card.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            errors.append(f"{label}.clauses must be non-empty")
            continue
        seen_clauses = set()
        clause_statuses = []
        for clause_index, clause in enumerate(clauses):
            clause_label = f"{label}.clauses[{clause_index}]"
            fields = {"clause_id", "source_id", "locator", "text_hash", "status", "program_id", "implemented_ops", "unsupported_mechanics", "test_ids", "notes"}
            if not isinstance(clause, dict) or set(clause) != fields:
                errors.append(f"{clause_label} has invalid fields")
                continue
            clause_id, status = clause.get("clause_id"), clause.get("status")
            if not isinstance(clause_id, str) or not clause_id or clause_id in seen_clauses:
                errors.append(f"{clause_label}.clause_id is invalid or duplicated")
            seen_clauses.add(clause_id)
            if status not in STATUSES:
                errors.append(f"{clause_label}.status is invalid")
                continue
            clause_statuses.append(status)
            ops = clause.get("implemented_ops")
            unsupported = clause.get("unsupported_mechanics")
            tests = clause.get("test_ids")
            if not isinstance(ops, list) or any(op not in SUPPORTED_OPS for op in ops):
                errors.append(f"{clause_label}.implemented_ops contains unsupported IR operations")
            if not isinstance(unsupported, list) or not isinstance(tests, list):
                errors.append(f"{clause_label} unsupported_mechanics/test_ids must be arrays")
                continue
            if status == "full" and (not clause.get("program_id") or not tests or unsupported):
                errors.append(f"{clause_label} full coverage requires a program, tests, and no unsupported mechanics")
            if status == "partial" and (not clause.get("program_id") or not tests or not unsupported):
                errors.append(f"{clause_label} partial coverage requires a tested program and explicit unsupported mechanics")
            if status == "unsupported" and (clause.get("program_id") is not None or not unsupported):
                errors.append(f"{clause_label} unsupported coverage requires no program and explicit missing mechanics")
        expected_card_status = (
            "stale" if "stale" in clause_statuses else
            "full" if clause_statuses and set(clause_statuses) == {"full"} else
            "unsupported" if clause_statuses and set(clause_statuses) == {"unsupported"} else "partial"
        )
        if card.get("behavior_status") != expected_card_status:
            errors.append(f"{label}.behavior_status must be {expected_card_status!r} for its clauses")
    return errors


def empty_coverage(status: str, manifest_id: str | None, warning: str, total: int) -> dict[str, Any]:
    return {
        "schema_version": COVERAGE_VERSION, "scope": "main_deck_current_text_clauses",
        "status": status, "manifest_id": manifest_id, "cards": [],
        "copy_weighted": {"total": total, "full": 0, "partial": 0, "unsupported": 0, "stale": 0, "uncovered": total},
        "strategy_evidence": "not_established_by_engine_coverage", "warnings": [warning],
    }


def summarize_profile_coverage(profile: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    entries = profile.get("resolution", {}).get("resolved_entries", [])
    unknown_entries = profile.get("resolution", {}).get("unknown_entries", [])
    total = sum(entry.get("count", 0) for entry in entries + unknown_entries)
    if manifest is None:
        return empty_coverage("unavailable", None, "No R3 card behavior manifest was supplied.", total)
    errors = validate_manifest(manifest)
    if errors:
        raise BehaviorCoverageError("invalid behavior manifest: " + "; ".join(errors))
    context = profile.get("context", {})
    if (
        manifest["ruleset"] != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
        or manifest["environment"]["environment_id"] != context.get("environment")
        or context.get("format") not in manifest["environment"]["formats"]
        or manifest["environment"]["region"] != context.get("region")
    ):
        return empty_coverage("incompatible", manifest["manifest_id"], "Behavior manifest does not match this ruleset/environment/format/region.", total)
    if manifest["status"] != "active":
        return empty_coverage("stale", manifest["manifest_id"], f"Behavior manifest status is {manifest['status']!r}, not active.", total)
    by_key = {card["card_key"]: card for card in manifest["cards"]}
    counts = {status: 0 for status in ("full", "partial", "unsupported", "stale", "uncovered")}
    cards = []
    warnings = []
    for entry in entries:
        count = entry.get("count", 0)
        covered = by_key.get(card_key(entry.get("canonical_name", "")))
        if covered is None:
            status, mechanics, clauses = "uncovered", [], []
        elif covered["current_text_hash"] != entry.get("current_text_hash"):
            status, mechanics, clauses = "stale", ["current_card_text_changed"], []
        else:
            status = covered["behavior_status"]
            clauses = [clause["clause_id"] for clause in covered["clauses"]]
            mechanics = list(dict.fromkeys(
                mechanic for clause in covered["clauses"] for mechanic in clause["unsupported_mechanics"]
            ))
        counts[status] += count
        cards.append({
            "canonical_name": entry.get("canonical_name"), "count": count, "status": status,
            "covered_clause_ids": clauses, "unsupported_mechanics": mechanics,
        })
    for entry in unknown_entries:
        count = entry.get("count", 0)
        counts["uncovered"] += count
        cards.append({
            "canonical_name": None, "input_name": entry.get("name"), "count": count,
            "status": "uncovered", "covered_clause_ids": [],
            "unsupported_mechanics": ["card_name_not_found_in_snapshot"],
        })
    if counts["uncovered"]:
        warnings.append("Some resolved Main Deck cards have no behavior manifest entry.")
    if counts["stale"]:
        warnings.append("Some behavior entries do not match current card text or are stale.")
    return {
        "schema_version": COVERAGE_VERSION, "scope": "main_deck_current_text_clauses",
        "status": "available", "manifest_id": manifest["manifest_id"], "cards": cards,
        "copy_weighted": {"total": total, **counts},
        "strategy_evidence": "not_established_by_engine_coverage", "warnings": warnings,
    }


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BehaviorCoverageError(f"{path} must contain an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    summarize = sub.add_parser("summarize")
    summarize.add_argument("profile", type=Path)
    summarize.add_argument("manifest", type=Path)
    summarize.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_object(args.manifest)
        errors = validate_manifest(manifest)
        if errors:
            raise BehaviorCoverageError("; ".join(errors))
        if args.command == "validate":
            print("OK: valid card-behavior-manifest.v1")
            return 0
        result = summarize_profile_coverage(load_object(args.profile), manifest)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    except (OSError, json.JSONDecodeError, BehaviorCoverageError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
