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

import datetime
import json
import sys
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_CARDS_PATH = DATA_DIR / "riftcodex_cards_raw.json"
ERRATA_PATH = DATA_DIR / "errata_overlay.json"
FRESHNESS_WARNING_DAYS = 90

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


def check_freshness(overlay, warnings):
    """Warn (don't fail the build) when the overlay's own last_verified date is stale --
    an old date isn't necessarily wrong, but it's a signal a human should go re-check
    the Rules Hub for a new errata wave before trusting local data blindly, per this
    project's own 'route, don't snapshot' rule."""
    last_verified = overlay.get("last_verified")
    if not last_verified:
        warnings.append("errata_overlay.json has no top-level last_verified date")
        return
    try:
        verified_date = datetime.date.fromisoformat(last_verified)
    except ValueError:
        warnings.append(f"errata_overlay.json's last_verified value {last_verified!r} isn't a valid ISO date")
        return
    age_days = (datetime.date.today() - verified_date).days
    if age_days > FRESHNESS_WARNING_DAYS:
        warnings.append(
            f"errata_overlay.json was last verified {age_days} days ago ({last_verified}) -- "
            f"over the {FRESHNESS_WARNING_DAYS}-day threshold; check the Rules Hub for a newer errata wave before trusting this file as current"
        )
    else:
        print(f"[info] errata_overlay.json last verified {age_days} day(s) ago ({last_verified}), within the {FRESHNESS_WARNING_DAYS}-day freshness window.")


def check_errata_overlay(errors, warnings):
    if not ERRATA_PATH.exists():
        errors.append(f"Missing {ERRATA_PATH}")
        return

    with open(ERRATA_PATH, encoding="utf-8") as f:
        overlay = json.load(f)

    check_freshness(overlay, warnings)

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


SKILL_DIR = Path(__file__).resolve().parent.parent


def check_errata_residue_in_docs(errors, warnings):
    """Fail if any derived Markdown file still contains an errata entry's old_text
    verbatim -- this is exactly the failure mode a re-audit caught by hand
    (reksai.md's Legend ability line kept 2026-01-14's pre-errata wording after
    the entry's Champion text was fixed but the Legend text, sharing the same
    errata entry under the card's own title, was missed). A grep a human runs
    once doesn't stay run; this runs every time."""
    if not ERRATA_PATH.exists():
        return

    with open(ERRATA_PATH, encoding="utf-8") as f:
        overlay = json.load(f)

    md_files = [p for p in SKILL_DIR.rglob("*.md")]
    hits = 0
    for entry in overlay.get("entries", []):
        old_text = entry.get("old_text", "")
        if not old_text:
            continue
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            if old_text in content:
                hits += 1
                errors.append(
                    f"{md_file.relative_to(SKILL_DIR.parent)} still contains the pre-errata text for "
                    f"{entry['official_name']!r} ({entry['document']}) verbatim -- should be the errata_overlay.json new_text instead"
                )

    print(f"[info] errata residue check: scanned {len(md_files)} markdown files against {len(overlay.get('entries', []))} old_text strings, {hits} hit(s).")


def check_domain_population_matches_prose(errors, warnings):
    """Fail if the Domain-personality population compute_domain_stats.py actually
    computes from the bundled data doesn't match the number the deckbuilding book's
    prose quotes for it. The number is a property of the data snapshot, not of the
    script -- so it *should* change when the snapshot is refreshed, and when it
    does, every prose reference has to move with it or the book is quoting a
    stale figure as current (which is exactly what a prior audit found with the
    retired 965-card number). Asserting the literal value in CI would be the wrong
    fix (it'd just re-encode the snapshot); asserting code and prose agree is the
    right one."""
    import re
    import sys as _sys
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    try:
        from compute_domain_stats import load_population
    except Exception as e:  # noqa: BLE001
        warnings.append(f"could not import compute_domain_stats to cross-check population: {e}")
        return

    computed = len(load_population())
    book = SKILL_DIR / "references" / "deckbuilding" / "deckbuilding.md"
    if not book.exists():
        warnings.append("deckbuilding.md not found; skipping population cross-check")
        return
    text = book.read_text(encoding="utf-8")
    # Only the figures the book states as *the population itself* -- matched by
    # the specific phrasings the book uses for that ("N deduplicated cards",
    # "N real distinct cards", "N-card population", "(N cards, this repo's own
    # data)"), not any bare "N cards" (which would also catch per-category counts
    # like "115 cards use gear" or the 109 dual-domain count, neither of which is
    # the population). The retired 965 figure is deliberately excluded: the book
    # mentions it only as a historical number that was replaced.
    patterns = [
        r"\b(\d{3,4}) deduplicated cards\b",
        r"\b(\d{3,4}) real distinct cards\b",
        r"\b(\d{3,4})-card population\b",
        r"\((\d{3,4}) cards, this repo's own data\)",
    ]
    quoted = {int(m) for pat in patterns for m in re.findall(pat, text)}
    quoted.discard(965)
    if not quoted:
        warnings.append("deckbuilding.md quotes no population figure to cross-check against compute_domain_stats.py")
        return
    mismatched = sorted(q for q in quoted if q != computed)
    if mismatched:
        errors.append(
            f"deckbuilding.md quotes Domain-population figure(s) {mismatched} but compute_domain_stats.py "
            f"currently computes {computed} from the bundled snapshot -- update the prose (every occurrence) "
            f"or the snapshot changed without the book being told"
        )
    print(f"[info] domain population cross-check: script computes {computed}, deckbuilding.md quotes {sorted(quoted)}.")


def main():
    errors = []
    warnings = []

    cards = check_raw_cards(errors, warnings)
    check_errata_overlay(errors, warnings)
    cross_check_errata_against_raw(cards, errors, warnings)
    check_errata_residue_in_docs(errors, warnings)
    check_domain_population_matches_prose(errors, warnings)

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
