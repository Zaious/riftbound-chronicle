#!/usr/bin/env python3
"""
Extract one clean, deduplicated data packet per Legend from skill/data/riftcodex_cards_raw.json.

Written because this exact logic was hand-derived three separate times while building
legend-construction-logic.md, and the same bugs got re-discovered each time:

- riftcodex has duplicate rows for the same physical card (same riftbound_id) with
  different `name` completeness -- one properly named ("Akali - Rogue Assassin"),
  one bare ("Rogue Assassin"). Dedup by riftbound_id first, preferring the row with
  a tcgplayer_id (the curated one) when they collide.
- Metal/Starter/Overnumbered/Alternate-Art reprints are separate rows entirely (real
  riftbound_ids of their own, not just name-suffix duplicates) -- filter by the actual
  metadata flags (`overnumbered`, `alternate_art`, `signature`), not by string-matching
  "(Metal)" etc. in the name, or reprint rows slip through.
- The `tags` field carries the real champion identity (e.g. "Akali") even on the bare-
  named duplicate rows, and is more reliable than the display name for merging
  reprints of the same Legend/Champion together.
- At least one Legend's tag (Kennen, tagged "Yordle") pulls in Champion cards from
  entirely unrelated Legends (Rumble, Vex, Poppy) whose Domains don't match Kennen's
  own -- a source-data mispairing, not a real Champion option. Filter candidate
  Champions to ones whose Domain is actually one of the Legend's own two Domains;
  don't assume every tag-matched card is a legitimate Champion for that Legend.

Usage:
    python3 skill/scripts/extract_legend_packets.py [--data PATH] [--out PATH]

Output: a JSON array, one object per Legend:
    {
      "legend_name": str,
      "champion_tag": str,
      "domains": [str, str],
      "legend_ability": str,   # icon tokens converted to {name} form, e.g. {energy_1}
      "champions": [ {"name": str, "domain": [str], "text": str}, ... ]
    }

This is the input format legend-construction-logic.md's generation prompts expect.
It is deliberately just a data-shaping step -- no judgment, no archetype classification,
no text generation. That part stays a live, per-Legend reasoning task (see
skill/references/deckbuilding/deckbuilding.md, "Deriving a specific Legend's identity"),
not something this script should ever attempt.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "riftcodex_cards_raw.json"
DEFAULT_OUT_PATH = Path(__file__).resolve().parent.parent / "legend_packets.json"


def base_name(name):
    """Strip a trailing parenthetical variant marker, e.g. 'X (Metal)' -> 'X'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def clean_text(text):
    """Convert riftcodex's :rb_x: icon tokens and HTML entities into a readable form."""
    if not text:
        return ""
    text = re.sub(r":rb_[a-z_0-9]+:", lambda m: "{" + m.group(0)[4:-1] + "}", text)
    text = text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    return text


def is_reprint_variant(card):
    """True if this row is a Metal/Alternate-Art/Signature/Overnumbered reprint --
    determined from the real metadata flags, never from string-matching the name."""
    meta = card.get("metadata") or {}
    return bool(meta.get("alternate_art") or meta.get("overnumbered") or meta.get("signature"))


def dedupe_by_riftbound_id(cards):
    """Collapse duplicate rows sharing a riftbound_id, preferring the one with a
    tcgplayer_id (the curated entry) over a bare-named duplicate row."""
    by_id = {}
    for card in cards:
        rid = card.get("riftbound_id")
        if rid not in by_id:
            by_id[rid] = card
        elif card.get("tcgplayer_id") and not by_id[rid].get("tcgplayer_id"):
            by_id[rid] = card
    return list(by_id.values())


def dedupe_by_identity(cards):
    """Collapse cross-set/promo reprints of the same character down to one entry,
    using the `tags` field (the real champion identity) when present, falling back
    to the parenthetical-stripped display name otherwise. Prefers whichever row has
    the fuller 'Champion - Title' name when two share an identity key."""
    by_key = {}
    for card in cards:
        tags = card.get("tags") or []
        key = tags[0] if tags else base_name(card["name"])
        if key not in by_key:
            by_key[key] = card
        else:
            existing = by_key[key]
            if " - " in card["name"] and " - " not in existing["name"]:
                by_key[key] = card
    return list(by_key.values())


def extract_legends(all_cards):
    legends = [c for c in all_cards if c["classification"].get("type") == "Legend"]
    legends = [c for c in legends if not is_reprint_variant(c)]
    legends = dedupe_by_riftbound_id(legends)
    legends = dedupe_by_identity(legends)
    return sorted(legends, key=lambda c: base_name(c["name"]))


def index_champions_by_tag(all_cards):
    """Group real (non-reprint) Champion-supertype Unit cards by their tag, so each
    Legend's champion_tag can look up its two Champion options directly."""
    by_tag = {}
    for card in all_cards:
        classification = card["classification"]
        if classification.get("type") != "Unit" or classification.get("supertype") != "Champion":
            continue
        if is_reprint_variant(card):
            continue
        for tag in card.get("tags") or []:
            by_tag.setdefault(tag, []).append(card)
    return by_tag


def build_packets(all_cards):
    legends = extract_legends(all_cards)
    champions_by_tag = index_champions_by_tag(all_cards)

    packets = []
    for legend in legends:
        tag = (legend.get("tags") or [None])[0]
        legend_domains = set(legend["classification"].get("domain", []))
        candidates = champions_by_tag.get(tag, [])

        # Discard tag-matched cards whose Domain isn't actually one of the Legend's
        # own two Domains -- a real mispairing seen in the source data (see Kennen
        # in the module docstring), not a legitimate Champion option.
        candidates = [
            c for c in candidates
            if set(c["classification"].get("domain", [])) <= legend_domains
        ]

        # A Legend has exactly two Champion options, one per Domain. Some data sets
        # carry more than two rows per tag (further reprints); keep the first row
        # seen per distinct Domain combination so exactly one entry per real option
        # survives, regardless of how many reprints exist.
        seen_domains = set()
        champions = []
        for card in candidates:
            domain_key = tuple(sorted(card["classification"].get("domain", [])))
            if domain_key in seen_domains:
                continue
            seen_domains.add(domain_key)
            champions.append({
                "name": base_name(card["name"]),
                "domain": card["classification"].get("domain"),
                "text": clean_text(card["text"].get("plain")),
            })

        packets.append({
            "legend_name": base_name(legend["name"]),
            "champion_tag": tag,
            "domains": legend["classification"].get("domain"),
            "legend_ability": clean_text(legend["text"].get("plain")),
            "champions": champions,
        })
    return packets


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="Path to riftcodex_cards_raw.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH, help="Where to write legend_packets.json")
    args = parser.parse_args()

    with open(args.data, encoding="utf-8") as f:
        all_cards = json.load(f)

    packets = build_packets(all_cards)

    irregular = [p for p in packets if len(p["champions"]) != 2]
    if irregular:
        print(f"[WARN] {len(irregular)} Legend(s) without exactly 2 Champions (source data gap or mispairing, not necessarily a bug in this script):", file=sys.stderr)
        for p in irregular:
            print(f"  - {p['legend_name']}: {len(p['champions'])} found -> {[c['name'] for c in p['champions']]}", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(packets, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(packets)} Legend packets to {args.out}")


if __name__ == "__main__":
    main()
