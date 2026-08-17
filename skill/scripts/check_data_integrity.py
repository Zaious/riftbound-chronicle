#!/usr/bin/env python3
"""
Schema and consistency checks for this skill's bundled data files.

Written for CI (see .github/workflows/ci.yml) after an independent audit
found this repo had no automated check that would catch a malformed
errata_overlay.json entry, a dangling document reference, or the raw
dataset silently losing its expected shape after a re-harvest. This
script is deliberately narrow -- it checks structure and internal
consistency, not whether the *content* is correct (that's what
verification-log.md and the errata overlay's own sourcing are for).

Usage:
    python3 skill/scripts/check_data_integrity.py

Exit code 0 if every check passes, 1 otherwise. Prints a report either way.
"""

import json
import sys
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_CARDS_PATH = DATA_DIR / "riftcodex_cards_raw.json"
ERRATA_PATH = DATA_DIR / "errata_overlay.json"

REQUIRED_ERRATA_ENTRY_FIELDS = {"official_name", "document", "card_ids", "old_text", "new_text", "verification"}
VALID_VERIFICATION_VALUES = {"live-fetched", "spot-checked"}
REQUIRED_CARD_FIELDS = {"riftbound_id", "name", "text", "classification"}


def check_raw_cards(errors, warnings):
    if not RAW_CARDS_PATH.exists():
        errors.append(f"Missing {RAW_CARDS_PATH}")
        return []

    with open(RAW_CARDS_PATH, encoding="utf-8") as f:
        cards = json.load(f)

    if not isinstance(cards, list):
        errors.append("riftcodex_cards_raw.json is not a JSON array at the top level")
        return []

    for i, card in enumerate(cards):
        missing = REQUIRED_CARD_FIELDS - card.keys()
        if missing:
            errors.append(f"Card at index {i} (id={card.get('riftbound_id', '?')!r}) missing fields: {sorted(missing)}")

    ids = [c.get("riftbound_id") for c in cards]
    dupes = {rid: n for rid, n in Counter(ids).items() if n > 1}
    print(f"[info] riftcodex_cards_raw.json: {len(cards)} rows, {len(set(ids))} unique riftbound_id, "
          f"{len(dupes)} duplicate-id groups ({sum(dupes.values())} rows) -- duplicates are expected "
          f"(reprint variants) and handled by extract_legend_packets.py's own dedup logic, not an error here.")

    return cards


def check_errata_overlay(errors, warnings):
    if not ERRATA_PATH.exists():
        errors.append(f"Missing {ERRATA_PATH}")
        return

    with open(ERRATA_PATH, encoding="utf-8") as f:
        overlay = json.load(f)

    doc_slugs = {d["slug"] for d in overlay.get("errata_documents", [])}
    if not doc_slugs:
        errors.append("errata_overlay.json has no errata_documents")

    entries = overlay.get("entries", [])
    if not entries:
        errors.append("errata_overlay.json has no entries")

    seen_names = set()
    for i, entry in enumerate(entries):
        missing = REQUIRED_ERRATA_ENTRY_FIELDS - entry.keys()
        if missing:
            errors.append(f"errata entry {i} ({entry.get('official_name', '?')!r}) missing fields: {sorted(missing)}")
            continue

        if entry["document"] not in doc_slugs:
            errors.append(f"errata entry {i} ({entry['official_name']!r}) references unknown document slug {entry['document']!r}")

        if entry["verification"] not in VALID_VERIFICATION_VALUES:
            errors.append(f"errata entry {i} ({entry['official_name']!r}) has unrecognized verification value {entry['verification']!r}")

        if entry["old_text"] == entry["new_text"]:
            errors.append(f"errata entry {i} ({entry['official_name']!r}) has identical old_text and new_text -- likely a copy-paste error")

        if not entry["card_ids"]:
            errors.append(f"errata entry {i} ({entry['official_name']!r}) has an empty card_ids list")

        name = entry["official_name"]
        if name in seen_names:
            warnings.append(f"errata entry for {name!r} appears more than once")
        seen_names.add(name)

    print(f"[info] errata_overlay.json: {len(doc_slugs)} documents, {len(entries)} entries, "
          f"{sum(1 for e in entries if e.get('verification') == 'live-fetched')} live-fetched, "
          f"{sum(1 for e in entries if e.get('verification') == 'spot-checked')} spot-checked.")


def cross_check_errata_against_raw(cards, errors, warnings):
    """Flag errata entries whose card_ids don't resolve to anything in the raw dataset --
    doesn't fail the build (ids are recorded from the official announcement, not always
    resolvable to this specific harvest's id shape), just surfaces it for a human to look at."""
    if not ERRATA_PATH.exists() or not cards:
        return

    with open(ERRATA_PATH, encoding="utf-8") as f:
        overlay = json.load(f)

    raw_ids_upper = set()
    for c in cards:
        s = (c.get("set") or {}).get("set_id")
        cn = c.get("collector_number")
        if s and cn is not None:
            raw_ids_upper.add(f"{s.upper()}-{int(cn):03d}")

    unresolved = 0
    for entry in overlay.get("entries", []):
        resolvable = any(cid in raw_ids_upper for cid in entry.get("card_ids", []) if "?" not in cid)
        placeholder_only = all("?" in cid for cid in entry.get("card_ids", []))
        if not resolvable and not placeholder_only:
            unresolved += 1
    if unresolved:
        warnings.append(f"{unresolved} errata entries have card_ids that don't resolve against the raw dataset's set_id+collector_number shape -- worth a manual look, not necessarily wrong (id shape conventions can differ).")


def main():
    errors = []
    warnings = []

    cards = check_raw_cards(errors, warnings)
    check_errata_overlay(errors, warnings)
    cross_check_errata_against_raw(cards, errors, warnings)

    if warnings:
        print("\n[warnings]")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print("\n[errors]")
        for e in errors:
            print(f"  - {e}")
        print(f"\nFAILED: {len(errors)} error(s).")
        return 1

    print("\nOK: all data integrity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
