#!/usr/bin/env python3
"""Validate the first R3 pack selection without claiming an executable pack."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from deck_coach_pipeline import CardCatalog
from effect_ir import CORE_RULESET, FAQ_AS_OF


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent
SELECTION = SKILL_DIR / "data" / "card_program_packs" / "global-core-origins-v1" / "selection.json"
PLAN = REPO_ROOT / "docs" / "plans" / "R3_FIRST_PACK_SELECTION.md"


def main() -> int:
    errors = []
    value = json.loads(SELECTION.read_text(encoding="utf-8"))
    required = {
        "schema_version", "selection_id", "status", "ruleset", "global_pack",
        "regional_overlays", "sources", "waves", "selected_decks",
        "capability_batches", "activation_gates",
    }
    if set(value) != required:
        errors.append(f"selection fields must be exactly {sorted(required)}")
    if value.get("schema_version") != "r3-pack-selection.v1":
        errors.append("selection schema_version is invalid")
    if value.get("status") != "selected_pending_physical_verification":
        errors.append("selection must remain pending until the candidate lists are independently verified")
    if value.get("ruleset") != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("selection ruleset differs from the executable baseline")

    pack = value.get("global_pack", {})
    if pack.get("pack_id") != "global-core-origins-v1" or pack.get("controlling_locale") != "en-US":
        errors.append("global pack identity/controlling locale is invalid")
    if set(pack.get("set_ids", [])) != {"OGN", "OGS"}:
        errors.append("first global pack must stay inside Origins/Proving Grounds sets")
    if pack.get("format_scope") != "proving_grounds_product_practice":
        errors.append("selection must not masquerade as a Constructed legality claim")
    if pack.get("support_claim") != "selection_only_no_executable_pack":
        errors.append("selection overstates executable support")

    official = [source for source in value.get("sources", []) if source.get("authority") == "official"]
    transcription = [source for source in value.get("sources", []) if source.get("authority") == "community_transcription"]
    if not official or any(source.get("supports_exact_decklists") is not False for source in official):
        errors.append("official product source must not be presented as an exact-list source")
    if not transcription or any(source.get("independent_verification_required") is not True for source in transcription):
        errors.append("community decklist transcription must require independent verification")
    if any(not source.get("accessed_at") or not str(source.get("url", "")).startswith("https://") for source in value.get("sources", [])):
        errors.append("every selection source requires an HTTPS URL and accessed_at date")

    catalog = CardCatalog()
    decks = value.get("selected_decks", [])
    if [deck.get("deck_id") for deck in decks] != ["proving-grounds-annie", "proving-grounds-master-yi"]:
        errors.append("Wave A must contain exactly the selected Annie/Master Yi teaching pair")
    for deck in decks:
        deck_id = deck.get("deck_id", "unknown")
        main = deck.get("main_deck", [])
        if sum(item.get("count", 0) for item in main) != 40:
            errors.append(f"{deck_id}: Main Deck must total 40 including the Chosen Champion")
        if len({item.get("name") for item in main}) != len(main):
            errors.append(f"{deck_id}: duplicate Main Deck rows")
        names = [deck.get("legend"), deck.get("chosen_champion"), *deck.get("battlefields", []), *deck.get("runes", {}), *(item.get("name") for item in main)]
        for name in names:
            card = catalog.resolve(name, {"OGN", "OGS"}) if isinstance(name, str) else None
            if card is None:
                errors.append(f"{deck_id}: {name!r} does not resolve in the OGN/OGS snapshot")
        chosen_count = sum(item["count"] for item in main if item["name"] == deck.get("chosen_champion"))
        if chosen_count < 1:
            errors.append(f"{deck_id}: Chosen Champion is not included in the 40-card Main Deck")
        if sum(deck.get("runes", {}).values()) != 12:
            errors.append(f"{deck_id}: Rune Deck must total 12")
        if len(deck.get("battlefields", [])) != 1:
            errors.append(f"{deck_id}: Proving Grounds product context must retain its one Battlefield")
        if not deck.get("mechanic_requirements"):
            errors.append(f"{deck_id}: mechanic inventory is empty")

    batches = {batch.get("batch_id"): batch for batch in value.get("capability_batches", [])}
    if set(batches) != {"R3-A0-inventory", "R3-A1-choices-costs-zones", "R3-A2-play-conditions-continuous", "R3-A3-combat"}:
        errors.append("selection does not expose the four accepted implementation batches")
    if batches.get("R3-A0-inventory", {}).get("requires_engine_change") is not False:
        errors.append("inventory batch must remain Claude-ready and engine-free")
    if batches.get("R3-A3-combat", {}).get("milestone") != "G1":
        errors.append("Combat batch must bind to G1")
    if len(value.get("activation_gates", [])) < 5:
        errors.append("selection lacks activation gates")

    plan = PLAN.read_text(encoding="utf-8")
    for phrase in ("selected pending physical/independent", "not a strength or metagame ranking", "does not activate a production", "R3-A0", "R3-A3"):
        if phrase.casefold() not in plan.casefold():
            errors.append(f"selection plan is missing boundary phrase {phrase!r}")

    print(f"[info] R3 selection: {len(decks)} Wave-A decks, {sum(len(deck['main_deck']) for deck in decks)} unique deck rows, four capability batches.")
    if errors:
        print("\n".join(f"FAILED: {error}" for error in errors))
        return 1
    print("OK: Annie/Master Yi are selected as a pending-verification teaching pair without an executable or metagame claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
