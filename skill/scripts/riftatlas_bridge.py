#!/usr/bin/env python3
"""Turn a user-supplied Rift Atlas deck link and decklist into Deck Coach artifacts.

The bridge deliberately does not scrape Rift Atlas or call a private API. The
user supplies the public link for provenance and pastes/exports the decklist.
That keeps the adapter reproducible, respectful of the upstream service, and
usable if Rift Atlas changes its frontend or import format.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from deck_coach_pipeline import (
    CardCatalog,
    PipelineError,
    build_mask,
    build_profile,
    generate_baseline_primer,
    name_key,
    save_json,
)


BRIDGE_SCHEMA = "riftatlas-deck-coach-bridge.v1"
SUPPORTED_HOSTS = {"riftatlas.com", "www.riftatlas.com", "play.riftatlas.com"}
SECTION_ALIASES = {
    "legend": "legend",
    "champion": "chosen_champion",
    "chosen champion": "chosen_champion",
    "chosen_champion": "chosen_champion",
    "main": "main_deck",
    "main deck": "main_deck",
    "mainboard": "main_deck",
    "deck": "main_deck",
    "sideboard": "sideboard",
    "side": "sideboard",
    "battlefield": "battlefields",
    "battlefields": "battlefields",
    "rune": "runes",
    "runes": "runes",
}
HEADER_RE = re.compile(r"^\s{0,3}(?:[-*+]\s+)?(?:#+\s*)?([^:]+?)\s*:\s*(.*?)\s*$", re.I)
MARKDOWN_HEADER_RE = re.compile(r"^\s{0,3}#+\s*(.*?)\s*$")
COUNT_PREFIX_RE = re.compile(r"^\s*(\d+)\s*(?:x|×)?\s+(.+?)\s*$", re.I)
COUNT_SUFFIX_RE = re.compile(r"^\s*(.+?)\s+(?:x|×)\s*(\d+)\s*$", re.I)
SET_SUFFIX_RE = re.compile(r"\s*[\[(](?:[A-Z]{2,4})-\d+[A-Z]?[\])]?\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_source_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc.casefold() not in SUPPORTED_HOSTS:
        raise PipelineError("--source-url must be an https Rift Atlas URL")
    return value


def clean_line(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line.strip())
    line = re.sub(r"\s+#.*$", "", line).strip()
    return SET_SUFFIX_RE.sub("", line).strip()


def section_name(raw: str) -> str | None:
    normalized = re.sub(r"[|—–-]+", " ", raw.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return SECTION_ALIASES.get(normalized)


def parse_counted_card(line: str) -> tuple[int, str] | None:
    line = clean_line(line)
    if not line or line.startswith(("#", "//")):
        return None
    match = COUNT_PREFIX_RE.match(line)
    if match:
        return int(match.group(1)), match.group(2).strip()
    match = COUNT_SUFFIX_RE.match(line)
    if match:
        return int(match.group(2)), match.group(1).strip()
    return 1, line


def append_card(target: list[dict[str, object]], count: int, name: str) -> None:
    if count < 1 or not name:
        return
    key = name_key(name)
    for item in target:
        if name_key(str(item["name"])) == key:
            item["count"] = int(item["count"]) + count
            return
    target.append({"name": name, "count": count})


def parse_decklist(text: str, legend: str | None = None, chosen_champion: str | None = None) -> dict[str, object]:
    current = "main_deck"
    result: dict[str, object] = {
        "legend": legend.strip() if legend else None,
        "chosen_champion": chosen_champion.strip() if chosen_champion else None,
        "main_deck": [],
        "sideboard": [],
        "battlefields": [],
        "runes": {},
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        markdown = MARKDOWN_HEADER_RE.match(line)
        if markdown and section_name(markdown.group(1)):
            current = section_name(markdown.group(1)) or current
            continue
        header = HEADER_RE.match(line)
        if header and section_name(header.group(1)):
            current = section_name(header.group(1)) or current
            value = clean_line(header.group(2))
            if value:
                if current == "legend":
                    result["legend"] = value
                elif current == "chosen_champion":
                    result["chosen_champion"] = value
                elif current == "battlefields":
                    cast = result["battlefields"]
                    assert isinstance(cast, list)
                    cast.append(value)
            continue
        parsed = parse_counted_card(line)
        if not parsed:
            continue
        count, name = parsed
        if current == "legend":
            result["legend"] = name
        elif current == "chosen_champion":
            result["chosen_champion"] = name
        elif current == "battlefields":
            cast = result["battlefields"]
            assert isinstance(cast, list)
            cast.extend([name] * count)
        elif current == "runes":
            runes = result["runes"]
            assert isinstance(runes, dict)
            runes[name] = int(runes.get(name, 0)) + count
        else:
            cast = result[current]
            assert isinstance(cast, list)
            append_card(cast, count, name)
    if not result["legend"]:
        raise PipelineError("decklist needs a Legend: line or --legend")
    if not result["main_deck"]:
        raise PipelineError("decklist did not contain any Main Deck entries")
    return result


def make_input(parsed: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    return {
        "schema_version": "deck-coach-input.v1",
        "deck_id": args.deck_id,
        "environment": args.environment,
        "format": args.format,
        "player_level": args.player_level,
        "legend": parsed["legend"],
        "chosen_champion": parsed["chosen_champion"],
        "runes": parsed["runes"],
        "battlefields": parsed["battlefields"],
        "main_deck": parsed["main_deck"],
        "sideboard": parsed["sideboard"],
        "owned_cards": None,
        "source_environment": args.source_environment,
        "recommendation_candidates": [],
    }


def write_brief(output: Path, bridge: dict[str, object], primer: dict[str, object]) -> None:
    source = bridge["source"]
    assert isinstance(source, dict)
    lines = [
        "# Rift Atlas → Chronicle Deck Coach",
        "",
        f"- Source URL: {source.get('url') or 'not supplied'}",
        "- Extraction: user-pasted decklist; no Rift Atlas page was scraped",
        f"- Environment: {bridge['deck_coach_input']['environment']}",
        f"- Format: {bridge['deck_coach_input']['format']}",
        f"- Player level: {bridge['deck_coach_input']['player_level']}",
        "",
        "This is a deterministic profile scaffold. Heuristic engine, mulligan, sequencing, and matchup claims require cited research or human review.",
        "",
    ]
    primer_body = primer.get("primer", {})
    assert isinstance(primer_body, dict)
    for key, value in primer_body.items():
        lines.extend([f"## {str(key).replace('_', ' ').title()}", "", str(value), ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", default="run", choices=["run"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--decklist", help="Pasted Rift Atlas export or plain-text decklist")
    source.add_argument("--deck-file", type=Path, help="UTF-8 text file containing the decklist")
    parser.add_argument("--source-url", help="Public Rift Atlas deck URL for provenance; never fetched")
    parser.add_argument("--legend", help="Override or supply the Legend when the pasted list has no Legend header")
    parser.add_argument("--chosen-champion", help="Override or supply the Chosen Champion")
    parser.add_argument("--deck-id", default="riftatlas-import")
    parser.add_argument("--environment", required=True, choices=["global-vendetta", "taiwan-set1-banned"])
    parser.add_argument("--format", default="1v1 Constructed", choices=["1v1 Constructed", "2v2 Constructed"])
    parser.add_argument("--player-level", required=True, choices=["new", "intermediate", "advanced"])
    parser.add_argument("--source-environment")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skill-version", default="working-tree")
    parser.add_argument("--model", default="none")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_url = validate_source_url(args.source_url)
        text = args.decklist if args.decklist is not None else args.deck_file.read_text(encoding="utf-8")
        parsed = parse_decklist(text, args.legend, args.chosen_champion)
        deck_input = make_input(parsed, args)
        catalog = CardCatalog()
        profile = build_profile(deck_input, catalog)
        mask = build_mask(deck_input, profile, catalog)
        primer = generate_baseline_primer(deck_input, profile, mask, "riftatlas-bridge", args.skill_version, args.model)
        bridge = {
            "schema_version": BRIDGE_SCHEMA,
            "generated_at": now_iso(),
            "source": {"url": source_url, "extraction": "user_pasted", "upstream": "Rift Atlas"},
            "deck_coach_input": deck_input,
            "artifacts": {"profile": "profile.json", "mask": "mask.json", "primer": "primer.json", "brief": "primer-brief.md"},
            "boundary": "No page scraping, private API access, gameplay automation, or official legality ruling.",
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for filename, value in (("bridge.json", bridge), ("input.json", deck_input), ("profile.json", profile), ("mask.json", mask), ("primer.json", primer)):
            save_json(args.output_dir / filename, value)
        write_brief(args.output_dir / "primer-brief.md", bridge, primer)
        print(f"OK: Rift Atlas decklist bridged; coverage={profile['confidence']['card_resolution_coverage']:.0%}; blocked={mask['deck_legality']['blocked_count']}")
        return 0
    except (OSError, PipelineError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
