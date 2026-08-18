#!/usr/bin/env python3
"""
Validate skill/data/tournament_lists/*.json against the rules in that folder's
README -- shape, environment, date-vs-environment, count sums, per-Legend cap,
provenance, card-name resolvability -- and report staleness against the same
FORMAT_EVENTS list check_tier2_freshness.py uses.

What this script deliberately cannot do (and must never grow to do): compute
any rate, share, or ranking from the lists. It can enumerate ("which lists
contain card X, with sources") -- see --find -- and that is the ceiling. See
the folder README's "What this folder must never do."

Usage:
    python3 skill/scripts/check_tournament_lists.py            # validate all
    python3 skill/scripts/check_tournament_lists.py --find "Card Name"
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
LISTS_DIR = SKILL_DIR / "data" / "tournament_lists"
CARDS = SKILL_DIR / "data" / "riftcodex_cards_raw.json"

sys.path.insert(0, str(HERE))
from check_tier2_freshness import FORMAT_EVENTS, FUTURE_EVENTS  # noqa: E402
from extract_legend_packets import base_name, champion_identity_key  # noqa: E402

ENVIRONMENTS = {
    # environment: (earliest legal event_date, human label)
    "global-vendetta": (datetime.date(2026, 7, 31), "Global Standard, Vendetta legal (OGS/OGN/SFD/UNL/VEN + current bans)"),
    "taiwan-set1-banned": (None, "Taiwan pool: OGN+OGS with the global ban list applied"),
}
CAP_PER_LEGEND_PER_ENV = 8
REQUIRED = ["environment", "event", "event_date", "placement", "source_url", "source_name", "accessed",
            "chosen_champion", "runes", "battlefields", "main_deck"]


def load_card_names():
    if not CARDS.exists():
        return None
    with open(CARDS, encoding="utf-8") as f:
        cards = json.load(f)
    return {champion_identity_key(c["name"]) for c in cards}


def check_list(legend_file, i, lst, card_keys, errors, warnings):
    tag = f"{legend_file.name}[{i}]"
    for k in REQUIRED:
        if k not in lst:
            errors.append(f"{tag}: missing required field {k!r}")
    if any(k not in lst for k in REQUIRED):
        return

    env = lst["environment"]
    if env not in ENVIRONMENTS:
        errors.append(f"{tag}: environment {env!r} not one of {sorted(ENVIRONMENTS)} -- see tournament_lists/README.md, don't collect first and tag later")
        return
    try:
        ev_date = datetime.date.fromisoformat(lst["event_date"])
    except ValueError:
        errors.append(f"{tag}: event_date {lst['event_date']!r} is not YYYY-MM-DD")
        return
    floor, _ = ENVIRONMENTS[env]
    if floor and ev_date < floor:
        errors.append(f"{tag}: environment {env} requires event_date >= {floor} (set release), got {ev_date} -- this list belongs to an earlier environment and is out of scope")

    if not re.match(r"^https?://", lst["source_url"]):
        errors.append(f"{tag}: source_url must be a real URL")
    try:
        datetime.date.fromisoformat(lst["accessed"])
    except ValueError:
        errors.append(f"{tag}: accessed {lst['accessed']!r} is not YYYY-MM-DD")

    main_total = sum(int(c.get("count", 0)) for c in lst["main_deck"])
    if main_total != 40:
        errors.append(f"{tag}: main_deck sums to {main_total}, must be 40 (Chosen Champion included, Tournament Rules 601.1)")
    rune_total = sum(int(v) for v in lst["runes"].values())
    if rune_total != 12:
        errors.append(f"{tag}: runes sum to {rune_total}, must be 12")
    if len(lst["battlefields"]) != 3:
        errors.append(f"{tag}: {len(lst['battlefields'])} battlefields, must be 3")
    sb = lst.get("sideboard", [])
    sb_total = sum(int(c.get("count", 0)) for c in sb)
    if sb_total > 10:
        errors.append(f"{tag}: sideboard sums to {sb_total}, Tournament Rules 601.1.c.1 caps it at 10")

    chosen_in_main = any(champion_identity_key(c["name"]) == champion_identity_key(lst["chosen_champion"]) for c in lst["main_deck"])
    if not chosen_in_main:
        errors.append(f"{tag}: chosen_champion {lst['chosen_champion']!r} does not appear in main_deck (it must -- it's one of the 40)")

    if card_keys is not None:
        for c in lst["main_deck"] + sb + [{"name": b} for b in lst["battlefields"]]:
            if champion_identity_key(c["name"]) not in card_keys:
                warnings.append(f"{tag}: card {c['name']!r} not found in riftcodex_cards_raw.json by name -- typo, casing, or a known local-data gap (see data/README.md)")


def staleness(all_lists, as_of):
    # FORMAT_EVENTS rows are (date, label, kind, scope); scope is an environment tag or "*".
    events = [(datetime.date.fromisoformat(d), l, s) for d, l, _, s in FORMAT_EVENTS if datetime.date.fromisoformat(d) <= as_of]
    if not events:
        return

    def latest_for(env):
        rel = [e for e in events if e[2] in ("*", env)]
        return max(rel) if rel else None

    stale = []
    for f, i, l in all_lists:
        le = latest_for(l["environment"])
        if le and datetime.date.fromisoformat(l["event_date"]) < le[0]:
            stale.append((f, i, l, le))
    if stale:
        print(f"\n[warn] {len(stale)} list(s) predate the last format event for their own environment -- still true historical records, but a primer/Tier 2 row citing them should say the environment has moved:")
        for f, i, l, le in stale:
            print(f"  - {f.name}[{i}] {l['environment']} {l['event_date']} {l['event']} {l['placement']}  (event: {le[0]} {le[1]})")
    fut = [(datetime.date.fromisoformat(d), l, s) for d, l, _, s in FUTURE_EVENTS if datetime.date.fromisoformat(d) > as_of]
    if fut:
        nxt = min(fut)
        n = sum(1 for _, _, l in all_lists if nxt[2] in ("*", l["environment"]))
        print(f"[info] next known event {nxt[0]} ({nxt[1]}, scope {nxt[2]}) will make {n} current list(s) in that scope stale.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--find", help="enumerate lists containing this card name (exact-ish match); prints sources, never counts")
    ap.add_argument("--as-of", type=datetime.date.fromisoformat, default=datetime.date.today())
    args = ap.parse_args()

    if not LISTS_DIR.exists():
        print(f"[info] {LISTS_DIR.relative_to(SKILL_DIR.parent)} does not exist; nothing to validate.")
        return 0
    files = sorted(LISTS_DIR.glob("*.json"))
    card_keys = load_card_names()
    errors, warnings, all_lists = [], [], []

    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        if "legend" not in data or "lists" not in data:
            errors.append(f"{f.name}: top level must have 'legend' and 'lists'")
            continue
        per_env = {}
        for i, lst in enumerate(data["lists"]):
            check_list(f, i, lst, card_keys, errors, warnings)
            per_env[lst.get("environment")] = per_env.get(lst.get("environment"), 0) + 1
            all_lists.append((f, i, lst))
        for env, n in per_env.items():
            if n > CAP_PER_LEGEND_PER_ENV:
                errors.append(f"{f.name}: {n} lists for environment {env}, cap is {CAP_PER_LEGEND_PER_ENV} -- this is a citation store, not a sample")

    if args.find:
        key = champion_identity_key(args.find)
        hits = [(f, i, l) for f, i, l in all_lists if any(champion_identity_key(c["name"]) == key for c in l["main_deck"] + l.get("sideboard", []))]
        print(f"[find] {args.find!r} appears in {len(hits)} stored list(s) (enumeration, not a rate -- there are {len(all_lists)} lists total and that ratio is deliberately not computed here):")
        for f, i, l in hits:
            print(f"  - {f.name}[{i}] {l['environment']} {l['event']} {l['event_date']} {l['placement']} -- {l['source_url']}")
        return 0

    print(f"[info] {len(files)} Legend file(s), {len(all_lists)} list(s) validated; environments: {sorted({l['environment'] for _, _, l in all_lists})}.")
    staleness(all_lists, args.as_of)
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
    print("\nOK: tournament lists validate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
