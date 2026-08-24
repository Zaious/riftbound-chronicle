#!/usr/bin/env python3
"""Validate the offline Rift Atlas → Deck Coach adapter contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from deck_coach_pipeline import CardCatalog, validate_input
from riftatlas_bridge import BRIDGE_SCHEMA, PipelineError, parse_decklist, validate_source_url


SKILL_DIR = Path(__file__).resolve().parent.parent
BRIDGE = SKILL_DIR / "scripts" / "riftatlas_bridge.py"


def main() -> int:
    errors: list[str] = []
    text = BRIDGE.read_text(encoding="utf-8")
    for marker in ("--source-url", "--deck-file", "user_pasted", "deck-coach-input.v1"):
        if marker not in text:
            errors.append(f"bridge is missing {marker}")
    if "urlopen" in text or "requests" in text:
        errors.append("bridge must not scrape Rift Atlas or call a private API")

    fixture = """
Legend: Rengar - Pridestalker
Chosen Champion: Rengar, Trophy Hunter
Battlefields:
3 Emperor's Dais
Runes:
4 Fury
8 Body
Main Deck:
3 Inferna
2 Pit Rookie
Sideboard:
1 Sabotage
"""
    parsed = parse_decklist(fixture)
    if parsed["legend"] != "Rengar - Pridestalker":
        errors.append("fixture Legend was not parsed")
    if parsed["chosen_champion"] != "Rengar, Trophy Hunter":
        errors.append("fixture Chosen Champion was not parsed")
    if parsed["battlefields"] != ["Emperor's Dais", "Emperor's Dais", "Emperor's Dais"]:
        errors.append("battlefield count was not preserved")
    if parsed["runes"] != {"Fury": 4, "Body": 8}:
        errors.append("rune counts were not parsed")
    if parsed["main_deck"] != [{"name": "Inferna", "count": 3}, {"name": "Pit Rookie", "count": 2}]:
        errors.append("main deck counts were not parsed")
    if parsed["sideboard"] != [{"name": "Sabotage", "count": 1}]:
        errors.append("sideboard was not parsed")

    catalog = CardCatalog()
    deck_input = {
        "schema_version": "deck-coach-input.v1",
        "deck_id": "bridge-check",
        "environment": "global-vendetta",
        "format": "1v1 Constructed",
        "player_level": "new",
        "legend": parsed["legend"],
        "chosen_champion": parsed["chosen_champion"],
        "runes": parsed["runes"],
        "battlefields": parsed["battlefields"],
        "main_deck": parsed["main_deck"],
        "sideboard": parsed["sideboard"],
        "owned_cards": None,
        "source_environment": None,
        "recommendation_candidates": [],
    }
    if validate_input(deck_input, catalog):
        errors.append("adapter fixture does not satisfy deck-coach-input.v1")
    try:
        validate_source_url("https://example.com/not-riftatlas")
    except PipelineError:
        pass
    else:
        errors.append("non-Rift Atlas source URL was accepted")
    if BRIDGE_SCHEMA != "riftatlas-deck-coach-bridge.v1":
        errors.append("bridge schema constant drifted")

    print("[info] user-supplied URL provenance + pasted decklist; no upstream fetch")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} Rift Atlas bridge contract error(s).")
        return 1
    print("\nOK: Rift Atlas bridge parses safe decklist input and emits the Deck Coach contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
