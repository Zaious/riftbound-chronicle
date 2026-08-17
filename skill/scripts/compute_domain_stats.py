#!/usr/bin/env python3
"""
Recompute the Domain-personality mechanic percentages from
skill/data/riftcodex_cards_raw.json -- a re-runnable replacement for a
number that was previously computed once, by hand, against a different
(private) dataset with no way for anyone else to reproduce it.

Written 2026-08-17 after an independent audit flagged that gap. This is
a fresh measurement against this repo's own bundled data, not an attempt
to reproduce the old numbers exactly -- different source dataset,
different dedup pass, and keyword regexes calibrated from scratch. Don't
expect an exact match to whatever this replaced; expect a number anyone
with a clean clone of this repo can regenerate and check for themselves.

Population (what counts as "one real card"):
  1. Drop Rune-type cards (Basic runes carry no ability text at all --
     "[NO TEXT]" -- so they can't be classified by any mechanic keyword
     and would only dilute every percentage's denominator).
  2. Drop rows from the promo pools (OPP, PR, JDG) -- these are reprints
     of cards already counted under their original set, per
     skill/data/README.md's own documented coverage note.
  3. Drop rows flagged alternate_art / overnumbered / signature in
     metadata.
  4. Dedupe remaining rows sharing a riftbound_id (a known riftcodex
     data quirk -- duplicate rows for the same physical card with
     different name completeness), preferring the row with a
     tcgplayer_id.
  5. Dedupe remaining rows sharing an exact card *name* -- step 3's
     metadata flags don't catch every variant printing (spot-checked:
     several Vendetta cards have a lettered "a"-suffix riftbound_id,
     e.g. ven-019-166 vs ven-019a-166, both unflagged in metadata but
     clearly the same card printed twice). Keeps whichever row has the
     lexicographically-lowest riftbound_id, which puts the unlettered
     base printing before its "a"/"b" variants in every observed case.

Usage:
    python3 skill/scripts/compute_domain_stats.py

Prints a markdown table to stdout. Keyword regexes are deliberately
simple substring/regex checks on the plain-text rules, documented next
to each one -- read them before trusting a percentage to more precision
than "a reasonable, checkable approximation."
"""

import json
import re
import statistics
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "riftcodex_cards_raw.json"
PROMO_POOL_SETS = {"OPP", "PR", "JDG"}
DOMAINS = ["Fury", "Order", "Mind", "Body", "Chaos", "Calm"]

# Each pattern is checked against the card's plain-text rules with re.search, case-insensitive.
MECHANIC_PATTERNS = {
    "direct_damage": re.compile(r"\bdeal \d+\b", re.I),
    "draw": re.compile(r"\bdraw \d+\b", re.I),
    "destroy_removal": re.compile(r"\bkill\b|\bbanish\b", re.I),
    "death_benefit": re.compile(r"\bdeathknell\b|when .{0,25}\bdies\b", re.I),
    "gear_synergy": re.compile(r"\bgear\b|\bequipment\b", re.I),
    "opponent_weakening": re.compile(r"-\d+\s*:rb_might:", re.I),
    "movement": re.compile(r"\bmove\b|\bmoves\b|\bmoved\b", re.I),
    "trash_recursion": re.compile(r"\btrash\b", re.I),
}


def base_name(name):
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def load_population():
    with open(DATA_PATH, encoding="utf-8") as f:
        cards = json.load(f)

    filtered = [
        c for c in cards
        if c["classification"]["type"] != "Rune"
        and c["set"]["set_id"] not in PROMO_POOL_SETS
        and not (c["metadata"]["alternate_art"] or c["metadata"]["overnumbered"] or c["metadata"]["signature"])
    ]

    by_riftbound_id = {}
    for c in filtered:
        rid = c.get("riftbound_id")
        if rid not in by_riftbound_id:
            by_riftbound_id[rid] = c
        elif c.get("tcgplayer_id") and not by_riftbound_id[rid].get("tcgplayer_id"):
            by_riftbound_id[rid] = c
    filtered = list(by_riftbound_id.values())

    by_name = {}
    for c in filtered:
        name = c["name"]
        if name not in by_name or c["riftbound_id"] < by_name[name]["riftbound_id"]:
            by_name[name] = c
    return list(by_name.values())


def main():
    population = load_population()
    print(f"<!-- population: {len(population)} deduplicated cards (see script docstring for the dedup pipeline) -->")
    print()
    print("| Domain | n | direct-damage | draw | destroy-removal | death-benefit | gear-synergy | opponent-weakening | movement | trash-recursion | 6+ Might units | avg Might |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for domain in DOMAINS:
        in_domain = [c for c in population if domain in c["classification"].get("domain", [])]
        n = len(in_domain)
        if n == 0:
            print(f"| {domain} | 0 | - | - | - | - | - | - | - | - | - |")
            continue

        pcts = {}
        for key, pattern in MECHANIC_PATTERNS.items():
            hits = sum(1 for c in in_domain if pattern.search(c["text"].get("plain") or ""))
            pcts[key] = round(100 * hits / n)

        mights = [c["attributes"]["might"] for c in in_domain if c["attributes"].get("might") is not None]
        six_plus_pct = round(100 * sum(1 for m in mights if m >= 6) / n) if n else 0
        avg_might = round(statistics.mean(mights), 1) if mights else None

        print(
            f"| {domain} | {n} | {pcts['direct_damage']}% | {pcts['draw']}% | {pcts['destroy_removal']}% | "
            f"{pcts['death_benefit']}% | {pcts['gear_synergy']}% | {pcts['opponent_weakening']}% | "
            f"{pcts['movement']}% | {pcts['trash_recursion']}% | {six_plus_pct}% | {avg_might if avg_might is not None else '-'} |"
        )


if __name__ == "__main__":
    main()
