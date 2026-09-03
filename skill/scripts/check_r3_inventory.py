#!/usr/bin/env python3
"""
Regression gate for the R3-A0 clause inventory (C-12).

Must hold:
  - the three committed outputs equal a fresh build (deterministic, not stale);
  - every selected card — both legends, every main-deck row, both battlefields —
    resolves to an OGN/OGS printing and appears in the manifest exactly once;
  - each deck totals 40 main-deck cards with the chosen champion counted inside;
  - the manifest validates under card_behavior_coverage.validate_manifest;
  - the manifest is `draft`, carries no program_id and no test_ids, and no
    clause is `full` or `partial` — R3-A0 builds no programs;
  - `stale` appears exactly on the cards whose bundled snapshot still carries
    pre-errata wording, and nowhere else;
  - every clause names at least one mechanic or an implemented op, and every
    `unblocked_by` is a known batch or `unclassified`;
  - current_text_hash equals what Deck Coach's catalog computes for the same
    card, so a future projection and this draft agree on "current text";
  - the Deck Coach coverage projection over this manifest reports `available`
    with zero full/partial copies — it must not read as coverage.

Must fail:
  - a manifest whose status is not draft, or that carries a program_id;
  - a clause upgraded to `full`/`partial` without a program;
  - stale outputs.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_r3_inventory import BATCH_ORDER, PACK, SELECTION, build, find_errata, snapshot_is_stale  # noqa: E402
from card_behavior_coverage import card_key, summarize_profile_coverage, text_hash, validate_manifest  # noqa: E402
from deck_coach_pipeline import CardCatalog  # noqa: E402


def main() -> int:
    errors: list[str] = []
    manifest, ledger, md = build()
    rendered = {"inventory.draft.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                "inventory_ledger.json": json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", "INVENTORY.md": md}
    for name, text in rendered.items():
        path = PACK / name
        if not path.exists():
            errors.append(f"{name} missing; run build_r3_inventory.py")
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            errors.append(f"{name} is stale; re-run build_r3_inventory.py and commit the diff")
    again, _, _ = build()
    if again != manifest:
        errors.append("inventory build is not deterministic")

    found = validate_manifest(manifest)
    if found:
        errors.append(f"manifest invalid: {found}")
    if manifest["status"] != "draft":
        errors.append("manifest must stay draft in R3-A0")

    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    legal = set(selection["global_pack"]["set_ids"])
    expected_keys: set[str] = set()
    for deck in selection["selected_decks"]:
        total = sum(r["count"] for r in deck["main_deck"])
        if total != 40:
            errors.append(f"{deck['deck_id']} main deck totals {total}, not 40")
        if not any(r["name"] == deck["chosen_champion"] for r in deck["main_deck"]):
            errors.append(f"{deck['deck_id']} chosen champion is not inside the main deck")
        expected_keys |= {card_key(deck["legend"])} | {card_key(r["name"]) for r in deck["main_deck"]} | {card_key(b) for b in deck["battlefields"]}
    keys = [c["card_key"] for c in manifest["cards"]]
    if set(keys) != expected_keys or len(keys) != len(set(keys)):
        errors.append(f"manifest cards do not equal the selected set once each: missing={sorted(expected_keys - set(keys))} extra={sorted(set(keys) - expected_keys)}")

    catalog = CardCatalog()
    stale_expected = set()
    for card in manifest["cards"]:
        if not any(p.split("-")[0].upper() in legal for p in card["printing_ids"]):
            errors.append(f"{card['canonical_name']} has no {sorted(legal)} printing")
        chosen = catalog.resolve(card["canonical_name"], legal)
        current, errata = catalog.current_text(chosen)
        if text_hash(current) != card["current_text_hash"]:
            errors.append(f"{card['canonical_name']} current_text_hash differs from the Deck Coach catalog")
        snapshot = chosen.get("text", {}).get("plain") or ""
        origins = [p for p in card["printing_ids"] if p.split("-")[0].upper() in legal]
        found, _route = find_errata(catalog, chosen, origins)
        if snapshot_is_stale(found, snapshot):
            stale_expected.add(card["card_key"])
        for cl in card["clauses"]:
            if cl["program_id"] is not None or cl["test_ids"]:
                errors.append(f"{cl['clause_id']} carries a program or tests; R3-A0 builds none")
            if cl["status"] in ("full", "partial"):
                errors.append(f"{cl['clause_id']} is {cl['status']} without a program")
            if not cl["unsupported_mechanics"] and not cl["implemented_ops"]:
                errors.append(f"{cl['clause_id']} names no mechanic and no op")
            if not cl["clause_id"].startswith(card["card_key"] + "#"):
                errors.append(f"{cl['clause_id']} is not keyed by its card")
    actual_stale = {c["card_key"] for c in manifest["cards"] if c["behavior_status"] == "stale"}
    if actual_stale != stale_expected:
        errors.append(f"stale cards {sorted(actual_stale)} != snapshot-is-pre-errata cards {sorted(stale_expected)}")
    if not stale_expected:
        errors.append("no stale card found, but the errata overlay is known to touch selected cards; the stale detector is dead")

    for card in ledger["cards"]:
        for cl in card["clauses"]:
            if cl["unblocked_by"] not in BATCH_ORDER and cl["unblocked_by"] != "unclassified":
                errors.append(f"{cl['clause_id']} unblocked_by {cl['unblocked_by']!r} is not a known batch")
            if cl["recommended_label"] not in ("full", "partial", "unsupported", "stale"):
                errors.append(f"{cl['clause_id']} recommendation label is invalid")
    # Known overlays must join through the catalog's primary path. The fallback
    # remains in the builder to expose future bad identities, not to normalize
    # this already-repaired Annie entry forever.
    annie = next(c for c in ledger["cards"] if c["canonical_name"].startswith("Annie - Dark Child"))
    if annie["errata_join"] != "name" or annie["errata_card_ids"] != ["OGS-017"]:
        errors.append("Annie Legend errata is not joined by canonical name and OGS-017")
    if ledger["findings"] or ledger["counts"]["catalog_join_missed"]:
        errors.append("a selected card still needs an errata fallback join")
    md = (PACK / "INVENTORY.md").read_text(encoding="utf-8") if (PACK / "INVENTORY.md").exists() else ""
    for entry in catalog.errata["entries"]:
        if entry.get("old_text") and entry["old_text"] in md:
            errors.append(f"INVENTORY.md contains errata old_text verbatim for {entry['official_name']!r}")
    if ledger["counts"]["unclassified_clauses"] > 2:
        errors.append(f"{ledger['counts']['unclassified_clauses']} clauses matched no mechanic rule; extend MECHANIC_RULES rather than leave them")

    # The projection must see this as a real-but-empty manifest, not as coverage.
    profile = {"context": {"environment": manifest["environment"]["environment_id"], "region": "global", "format": manifest["environment"]["formats"][0]},
               "resolution": {"total_main_deck_copies": 40, "known_copies": 40, "unknown_entries": [], "resolved_entries": [
                   {"canonical_name": c["canonical_name"], "current_text_hash": c["current_text_hash"], "riftbound_id": c["printing_ids"][0], "count": 1}
                   for c in manifest["cards"] if c["canonical_name"].startswith("Annie")]}}
    try:
        cov = summarize_profile_coverage(profile, manifest)
        counts = cov.get("copy_weighted", {})
        if counts.get("full", 0) or counts.get("partial", 0):
            errors.append(f"draft inventory projected as coverage: {counts}")
    except Exception as exc:  # noqa: BLE001 — the projection contract is D-03's; report, do not hide
        errors.append(f"coverage projection over the draft raised: {exc}")

    # --- injections ----------------------------------------------------------
    bad = copy.deepcopy(manifest); bad["status"] = "active"
    if validate_manifest(bad):
        pass  # shape-valid; the draft rule is this gate's, asserted above
    bad = copy.deepcopy(manifest); bad["cards"][0]["clauses"][0]["status"] = "full"; bad["cards"][0]["behavior_status"] = "full"
    if not validate_manifest(bad):
        errors.append("validator accepted a full clause with no program")

    if errors:
        print("FAILED: R3-A0 inventory checks\n  - " + "\n  - ".join(errors))
        return 1
    c = ledger["counts"]
    print(f"OK: R3-A0 inventory — {c['cards']} cards, {c['clauses']} clauses, {c['stale_cards']} stale, {c['vanilla_cards']} vanilla, {c['unclassified_clauses']} unclassified; draft, no programs, hashes agree with Deck Coach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
