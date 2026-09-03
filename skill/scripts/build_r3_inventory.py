#!/usr/bin/env python3
"""
R3-A0: the Annie / Master Yi clause inventory (package C-12).

Reads the selection record, resolves every selected card through the same
CardCatalog Deck Coach uses (same printing preference, same errata, same
current_text_hash), splits each card's rules text into stable clauses, and
labels every clause with the mechanics it needs and the batch that would
unblock it.

Three outputs, all generated, all deterministic:

  inventory.draft.json   a card-behavior-manifest.v1 with status "draft". The
                         validator requires a tested program behind any `full`
                         or `partial` clause, and R3-A0 builds none, by rule —
                         so every clause here is `unsupported` with its missing
                         mechanics named, or `stale` where the bundled snapshot
                         still carries pre-errata wording. That is the honest
                         manifest, not the aspirational one.
  inventory_ledger.json  per card: printings read, errata applied, staleness,
                         and per clause the recommended eventual label
                         (`full` / `partial` / `unsupported`) with its reason.
                         Recommendations live here, never in the manifest.
  INVENTORY.md           the ledger as prose, by deck and by mechanic — what an
                         R3-A1 ruling actually needs to read.

Clause ids are `<card_key>#<8 hex of the clause text hash>`: stable across
reordering and across edits to other clauses, and a clause whose wording
changes becomes a new clause, which is what a changed clause is.

The mechanic map below is deterministic and reviewable. It decides what a
clause *needs*, not what the engine does; a clause that matches nothing is
labelled `unclassified` rather than guessed.

Usage:
    python3 skill/scripts/build_r3_inventory.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PACK = SKILL_DIR / "data" / "card_program_packs" / "global-core-origins-v1"
SELECTION = PACK / "selection.json"
sys.path.insert(0, str(SCRIPT_DIR))

from card_behavior_coverage import card_key, text_hash, validate_manifest  # noqa: E402
from deck_coach_pipeline import CardCatalog, name_key, text_key  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, SUPPORTED_OPS  # noqa: E402

MANIFEST_ID = "global-core-origins-v1-inventory-draft"
SNAPSHOT_SOURCE = "riftcodex-cards-raw-snapshot"
ERRATA_SOURCE = "origins-errata-2025-10-28"

# (regex over the clause text, mechanics needed, IR ops the clause would use, batch)
# Order matters only for readability; every matching rule contributes.
MECHANIC_RULES: list[tuple[str, list[str], list[str], str]] = [
    (r"^\[reaction\]|^\[action\]", ["action_reaction_timing"], [], "E0"),
    (r"\bdeal \d+ to all\b.*\bin combat\b", ["area_damage_in_combat", "combat_state"], ["deal_damage"], "R3-A3-combat"),
    (r"\bdeal \d+ to all\b", ["area_targets"], ["deal_damage"], "R3-A2-play-conditions-continuous"),
    (r"\bdeal \d+ to a unit\b", ["target_choice"], ["deal_damage"], "R3-A1-choices-costs-zones"),
    (r"\bbonus damage\b", ["bonus_damage"], [], "R3-A2-play-conditions-continuous"),
    (r"\bif this kills it\b", ["conditional_effects", "linked_instruction"], ["kill", "draw"], "R3-A2-play-conditions-continuous"),
    (r"\bdo this:", ["linked_instruction"], [], "R3-A2-play-conditions-continuous"),
    (r"\breturn .* from your trash to your hand\b", ["return_trash_to_hand", "target_choice"], [], "R3-A1-choices-costs-zones"),
    (r"\breturn a unit\b.*\bto its owner'?s hand\b", ["return_board_to_hand", "target_choice"], [], "R3-A1-choices-costs-zones"),
    (r"\bwhen you play me\b", ["play_and_move_triggers", "play_lifecycle"], ["emit_reflexive"], "R3-A2-play-conditions-continuous"),
    (r"\bwhen i move\b", ["play_and_move_triggers"], ["emit_reflexive"], "R3-A2-play-conditions-continuous"),
    (r"\bwhen you defend here\b", ["combat_state", "play_and_move_triggers"], [], "R3-A3-combat"),
    (r"\bmove (up to \d+ )?(a |friendly )?units? .*to (its )?base\b|\bmove a unit from a battlefield to its base\b", ["target_choice"], ["move_board_object"], "R3-A1-choices-costs-zones"),
    (r"\bdraw \d+\b", [], ["draw"], "E0"),
    (r"\bdiscard \d+\b", ["discard"], [], "R3-A1-choices-costs-zones"),
    (r"\blook at the top card\b", ["look"], [], "R3-A1-choices-costs-zones"),
    (r"\byou may recycle it\b", ["look", "optional_choice"], ["recycle_one"], "R3-A1-choices-costs-zones"),
    (r"\bchannel \d+ rune", ["channel_rune"], [], "R3-A1-choices-costs-zones"),
    (r"\bif you can'?t\b", ["if_cannot_fallback", "conditional_effects"], [], "R3-A2-play-conditions-continuous"),
    (r"\bas an additional cost\b|\byou may exhaust a friendly unit\b", ["optional_additional_cost"], ["exhaust"], "R3-A1-choices-costs-zones"),
    (r"\bready \d+ runes?\b", [], ["ready"], "E0"),
    (r"\bat the end of your turn\b", ["end_of_turn_trigger"], [], "R3-A2-play-conditions-continuous"),
    (r"\bunits you play this turn enter ready\b|\bi enter ready\b", ["enter_ready"], [], "R3-A2-play-conditions-continuous"),
    (r"\bgive a friendly unit \+\d+", ["target_choice", "duration_expiry"], ["modify_might"], "R3-A1-choices-costs-zones"),
    (r"\bthen an additional \+\d+.*\bif it is the only unit\b", ["conditional_effects"], ["modify_might"], "R3-A2-play-conditions-continuous"),
    (r"\bwhile .* \+\d+ :rb_might:|\bwhile .* i have \+\d+\b|\bit gets \+\d+ :rb_might:\b", ["conditional_might", "continuous_effects"], [], "R3-A2-play-conditions-continuous"),
    (r"\bdefends? alone\b|\battacking or defending alone\b", ["attacking_defending_alone", "combat_state"], [], "R3-A3-combat"),
    (r"\bthey deal damage equal to their mights to each other\b", ["mutual_damage_equal_might", "target_choice"], ["deal_damage"], "R3-A3-combat"),
    (r"\bthe next time it (dies|would die) this turn\b", ["next_death_replacement"], ["heal_damage", "exhaust"], "R3-A2-play-conditions-continuous"),
    (r"\brecall\b", ["recall"], [], "R3-A1-choices-costs-zones"),
    (r"\byou may play me to an open battlefield\b", ["open_battlefield_play", "play_lifecycle"], [], "R3-A2-play-conditions-continuous"),
    (r"^\[tank\]", ["tank", "combat_state"], [], "R3-A3-combat"),
    (r"^\[shield( \d+)?\]|\bgains \[shield \d+\]", ["shield", "combat_state"], [], "R3-A3-combat"),
    (r"^\[ganking\]", ["ganking", "combat_state"], [], "R3-A3-combat"),
    (r"^\[deflect\]", ["deflect"], [], "R3-A2-play-conditions-continuous"),
    (r"^\[vision\]", ["look", "play_and_move_triggers"], ["recycle_one"], "R3-A1-choices-costs-zones"),
    (r"\bchoose (a|an) (friendly |enemy )?unit\b", ["target_choice"], [], "R3-A1-choices-costs-zones"),
    (r"\bspells and abilities affecting units here\b", ["battlefield_passive", "bonus_damage"], [], "R3-A2-play-conditions-continuous"),
    (r"\bthis combat\b", ["combat_state", "duration_expiry"], [], "R3-A3-combat"),
]
BATCH_ORDER = ["E0", "R3-A1-choices-costs-zones", "R3-A2-play-conditions-continuous", "R3-A3-combat"]

def find_errata(catalog: CardCatalog, card: dict[str, Any], origins_ids: list[str]) -> tuple[dict[str, Any] | None, str]:
    """Locate the errata entry for a card and say which route found it.

    Deck Coach's catalog joins by name only. The legend errata is filed under
    its subtitle ("Dark Child, Starter") with a placeholder card id ("OGN-?"),
    so the name join misses it. The inventory tries name, then card id, then
    subtitle, and records which route worked; anything but `name` is a catalog
    miss to report to the overlay's owner, not to paper over here.
    """
    by_name = catalog.errata_by_name.get(name_key(card["name"]))
    if by_name:
        return by_name, "name"
    ids = {"-".join(pid.upper().split("-")[:2]) for pid in origins_ids}
    for entry in catalog.errata["entries"]:
        if ids & {cid.upper() for cid in entry.get("card_ids", [])}:
            return entry, "card_id"
    if " - " in card["name"]:
        # "Dark Child (Starter)" and "Dark Child, Starter" are the same
        # subtitle; name_key turns the comma into " - " but leaves the
        # parenthesis alone, so do that here before comparing.
        subtitle = _subtitle_key(card["name"].split(" - ", 1)[1])
        for entry in catalog.errata["entries"]:
            if _subtitle_key(entry["official_name"]) == subtitle:
                return entry, "subtitle"
    return None, "none"


def _subtitle_key(value: str) -> str:
    return name_key(re.sub(r"\s*\(([^)]*)\)\s*$", r" - \1", value))


def snapshot_is_stale(errata: dict[str, Any] | None, snapshot_text: str) -> bool:
    """Stale = an errata applies and the bundled snapshot does not carry its new wording."""
    return bool(errata) and text_key(errata["new_text"]) not in text_key(snapshot_text)


KEYWORD_BLOCK = re.compile(r"^\[(?P<kw>[A-Za-z]+(?: \d+)?)\]\s*(?:\((?P<reminder>[^)]*)\))?\s*")
TRAILING_REMINDER = re.compile(r"\s*\((?P<reminder>[^)]*)\)\s*$")


def split_clauses(text: str) -> list[dict[str, str]]:
    """Keyword blocks first, then sentences. Reminder text is kept as a note, not a clause."""
    text = " ".join(text.split())
    clauses: list[dict[str, str]] = []
    while True:
        m = KEYWORD_BLOCK.match(text)
        if not m:
            break
        clauses.append({"text": f"[{m.group('kw')}]", "reminder": m.group("reminder") or ""})
        text = text[m.end():]
    body = text.strip()
    if body:
        # A trailing parenthetical on the whole body is reminder text (e.g. Highlander).
        trailing = ""
        tm = TRAILING_REMINDER.search(body)
        if tm and body.count("(") == 1:
            trailing, body = tm.group("reminder"), body[: tm.start()].strip()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
        for i, sentence in enumerate(sentences):
            clauses.append({"text": sentence, "reminder": trailing if i == len(sentences) - 1 else ""})
    if not clauses:
        clauses.append({"text": "", "reminder": ""})
    return clauses


def classify(clause_text: str, is_vanilla: bool) -> tuple[list[str], list[str], str]:
    if is_vanilla:
        return ["vanilla_unit_combat_state", "combat_state"], [], "R3-A3-combat"
    key = clause_text.casefold()
    mechanics: dict[str, None] = {}
    ops: dict[str, None] = {}
    batches: list[str] = []
    for pattern, needs, use_ops, batch in MECHANIC_RULES:
        if re.search(pattern, key):
            for n in needs:
                mechanics.setdefault(n, None)
            for o in use_ops:
                ops.setdefault(o, None)
            batches.append(batch)
    if not mechanics and not ops:
        mechanics["unclassified"] = None
        batches.append("unclassified")
    # The clause unblocks when its *latest* batch lands.
    batch = max(batches, key=lambda b: BATCH_ORDER.index(b) if b in BATCH_ORDER else 99)
    return list(mechanics), [o for o in ops if o in SUPPORTED_OPS], batch


def recommend(mechanics: list[str], ops: list[str], stale: bool) -> tuple[str, str]:
    """What the clause *could* become once its batch lands. A recommendation, not a status."""
    if stale:
        return "stale", "bundled snapshot still carries pre-errata wording; reverify text before any program"
    if mechanics == ["action_reaction_timing"]:
        return "full", "timing keyword only; already covered by the timing kernel (R1)"
    if not mechanics and ops:
        return "full", f"composes from implemented ops {ops} with no missing mechanic"
    if ops:
        return "partial", f"ops {ops} exist; blocked on {mechanics}"
    return "unsupported", f"no implemented op applies; blocked on {mechanics}"


def build() -> tuple[dict[str, Any], dict[str, Any], str]:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    legal_sets = set(selection["global_pack"]["set_ids"])
    catalog = CardCatalog()
    ordered: list[tuple[str, str, str]] = []  # (deck_id, role, name)
    for deck in selection["selected_decks"]:
        ordered.append((deck["deck_id"], "legend", deck["legend"]))
        for row in deck["main_deck"]:
            ordered.append((deck["deck_id"], "main_deck", row["name"]))
        for bf in deck["battlefields"]:
            ordered.append((deck["deck_id"], "battlefield", bf))

    cards: dict[str, dict[str, Any]] = {}
    ledger_cards: list[dict[str, Any]] = []
    for deck_id, role, name in ordered:
        key = card_key(name)
        if key in cards:
            ledger_cards[[c["card_key"] for c in ledger_cards].index(key)]["decks"].append({"deck_id": deck_id, "role": role})
            continue
        chosen = catalog.resolve(name, legal_sets)
        if chosen is None:
            raise SystemExit(f"selected card {name!r} does not resolve in the card snapshot")
        printings = sorted({c["riftbound_id"] for c in catalog.resolve_all(name)})
        origins = [p for p in printings if p.split("-")[0].upper() in legal_sets]
        if not origins:
            raise SystemExit(f"selected card {name!r} has no {sorted(legal_sets)} printing")
        catalog_text, _catalog_errata = catalog.current_text(chosen)
        snapshot_text = chosen.get("text", {}).get("plain") or ""
        errata, errata_join = find_errata(catalog, chosen, origins)
        catalog_join_missed = bool(errata) and errata_join != "name"
        # Clauses split from the best-known current text. The manifest's
        # current_text_hash stays what Deck Coach's catalog computes, because
        # that is the value a future projection compares against.
        current_text = errata["new_text"] if errata else catalog_text
        snapshot_is_pre_errata = snapshot_is_stale(errata, snapshot_text)
        is_vanilla = not snapshot_text.strip() and not errata
        clause_rows: list[dict[str, Any]] = []
        ledger_clauses: list[dict[str, Any]] = []
        for part in split_clauses(current_text if not is_vanilla else ""):
            ctext = part["text"] or "(no rules text)"
            chash = text_hash(ctext)
            cid = f"{key}#{chash.split(':', 1)[1][:8]}"
            mechanics, ops, batch = classify(ctext, is_vanilla)
            stale = snapshot_is_pre_errata
            status = "stale" if stale else "unsupported"
            rec_label, rec_reason = recommend(mechanics, ops, stale)
            clause_rows.append({
                "clause_id": cid,
                "source_id": ERRATA_SOURCE if errata else SNAPSHOT_SOURCE,
                "locator": f"{origins[0]}:{cid.split('#', 1)[1]}",
                "text_hash": chash,
                "status": status,
                "program_id": None,
                "implemented_ops": ops,
                "unsupported_mechanics": (mechanics or (["reverify_text"] if stale else ["unclassified"])) + (["errata_join_missed_by_catalog"] if catalog_join_missed else []),
                "test_ids": [],
                "notes": f"R3-A0 draft. text: {ctext}" + (f" | reminder: {part['reminder']}" if part["reminder"] else "") + f" | unblocked by: {batch} | recommended eventual label: {rec_label}",
            })
            ledger_clauses.append({"clause_id": cid, "text": ctext, "reminder": part["reminder"], "mechanics": mechanics, "implemented_ops": ops,
                                   "unblocked_by": batch, "manifest_status": status, "recommended_label": rec_label, "recommendation_reason": rec_reason})
        statuses = {c["status"] for c in clause_rows}
        card_status = "stale" if "stale" in statuses else "unsupported"
        cards[key] = {"card_key": key, "canonical_name": chosen["name"], "current_text_hash": text_hash(catalog_text),
                      "printing_ids": printings, "behavior_status": card_status, "clauses": clause_rows}
        ledger_cards.append({
            "card_key": key, "canonical_name": chosen["name"], "type": chosen["classification"]["type"],
            "decks": [{"deck_id": deck_id, "role": role}], "printing_read": chosen["riftbound_id"], "origins_printings": origins, "all_printings": printings,
            "snapshot_text": snapshot_text, "current_text": current_text, "current_text_hash": text_hash(catalog_text),
            "inventory_text_hash": text_hash(current_text),
            "errata_applied": bool(errata), "errata_join": errata_join, "catalog_join_missed": catalog_join_missed,
            "errata_official_name": errata["official_name"] if errata else None, "errata_card_ids": list(errata.get("card_ids", [])) if errata else [],
            "errata_document": errata["document"] if errata else None, "errata_verification": errata.get("verification") if errata else None,
            "snapshot_is_pre_errata": snapshot_is_pre_errata, "vanilla": is_vanilla, "clauses": ledger_clauses,
        })

    manifest = {
        "schema_version": "card-behavior-manifest.v1", "manifest_id": MANIFEST_ID, "pack_id": selection["global_pack"]["pack_id"],
        "status": "draft", "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "environment": {"environment_id": selection["global_pack"]["pack_id"], "region": "global", "formats": [selection["global_pack"]["format_scope"]]},
        "verified_at": catalog.errata["last_verified"], "cards": [cards[k] for k in sorted(cards)],
    }
    errors = validate_manifest(manifest)
    if errors:
        raise SystemExit("built manifest is invalid: " + "; ".join(errors))

    by_mechanic: dict[str, list[str]] = {}
    by_batch: dict[str, list[str]] = {}
    for card in ledger_cards:
        for cl in card["clauses"]:
            for m in cl["mechanics"]:
                by_mechanic.setdefault(m, []).append(card["canonical_name"])
            by_batch.setdefault(cl["unblocked_by"], []).append(card["canonical_name"])
    ledger = {
        "schema_version": "r3-inventory-ledger.v1", "batch_id": "R3-A0-inventory", "manifest_id": MANIFEST_ID,
        "selection_id": selection["selection_id"], "snapshot_source": SNAPSHOT_SOURCE, "errata_last_verified": catalog.errata["last_verified"],
        "not_claimed": ["executable programs", "production activation", "deck legality", "full or partial coverage in the manifest"],
        "findings": [
            {"card": c["canonical_name"], "finding": "errata_join_missed_by_catalog", "errata_official_name": c["errata_official_name"],
             "errata_card_ids": c["errata_card_ids"], "joined_by": c["errata_join"],
             "consequence": "Deck Coach's catalog applies errata by name only, so it reads this card's pre-errata text; fix the overlay entry's official_name or card_ids."}
            for c in ledger_cards if c["catalog_join_missed"]
        ],
        "counts": {"cards": len(ledger_cards), "clauses": sum(len(c["clauses"]) for c in ledger_cards),
                   "stale_cards": sum(1 for c in ledger_cards if c["snapshot_is_pre_errata"]), "vanilla_cards": sum(1 for c in ledger_cards if c["vanilla"]),
                   "catalog_join_missed": sum(1 for c in ledger_cards if c["catalog_join_missed"]),
                   "unclassified_clauses": sum(1 for c in ledger_cards for cl in c["clauses"] if "unclassified" in cl["mechanics"])},
        "cards_by_mechanic": {m: sorted(set(v)) for m, v in sorted(by_mechanic.items())},
        "cards_by_unblocking_batch": {b: sorted(set(v)) for b, v in sorted(by_batch.items(), key=lambda kv: BATCH_ORDER.index(kv[0]) if kv[0] in BATCH_ORDER else 99)},
        "cards": ledger_cards,
    }
    ledger["ledger_hash"] = "sha256:" + hashlib.sha256(json.dumps({k: v for k, v in ledger.items() if k != "ledger_hash"}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return manifest, ledger, render_markdown(selection, ledger)


def render_markdown(selection: dict[str, Any], ledger: dict[str, Any]) -> str:
    out = ["# R3-A0 inventory — Annie and Master Yi", "",
           f"Generated from `selection.json` ({ledger['selection_id']}), the bundled card snapshot, and errata verified {ledger['errata_last_verified']}. Draft only: no programs, no activation.", "",
           f"{ledger['counts']['cards']} cards, {ledger['counts']['clauses']} clauses. {ledger['counts']['stale_cards']} cards carry pre-errata text in the snapshot; {ledger['counts']['vanilla_cards']} have no rules text; {ledger['counts']['unclassified_clauses']} clauses matched no mechanic rule; {ledger['counts']['catalog_join_missed']} errata entries are unreachable by the catalog's name join.", ""]
    if ledger["findings"]:
        out += ["## Findings for the overlay owner", ""]
        for f in ledger["findings"]:
            out.append(f"- **{f['card']}**: errata `{f['errata_official_name']}` (card_ids {f['errata_card_ids']}) is reachable only via `{f['joined_by']}`. {f['consequence']}")
        out.append("")
    out += ["## What unblocks how many cards", "", "| Batch | Cards |", "| --- | --- |"]
    for batch, names in ledger["cards_by_unblocking_batch"].items():
        out.append(f"| `{batch}` | {len(names)} — {', '.join(names)} |")
    out += ["", "## Cards by mechanic", "", "| Mechanic | Cards |", "| --- | --- |"]
    for m, names in ledger["cards_by_mechanic"].items():
        out.append(f"| `{m}` | {', '.join(names)} |")
    by_card = {c["card_key"]: c for c in ledger["cards"]}
    for deck in selection["selected_decks"]:
        out += ["", f"## {deck['deck_id']}", ""]
        names = [deck["legend"]] + [r["name"] for r in deck["main_deck"]] + deck["battlefields"]
        for name in names:
            c = by_card[card_key(name)]
            flags = []
            if c["snapshot_is_pre_errata"]:
                flags.append("**STALE snapshot** (pre-errata wording withheld; see inventory_ledger.json)")
            if c["catalog_join_missed"]:
                flags.append(f"**catalog errata join missed** (reached via `{c['errata_join']}`)")
            if c["errata_applied"]:
                flags.append(f"errata: {c['errata_document']} ({c['errata_verification']})")
            if c["vanilla"]:
                flags.append("no rules text")
            out.append(f"### {c['canonical_name']} — {c['type']} · `{c['printing_read']}`" + (" · " + " · ".join(flags) if flags else ""))
            for cl in c["clauses"]:
                out.append(f"- `{cl['clause_id'].split('#')[1]}` {cl['text']}")
                out.append(f"  needs: {', '.join(cl['mechanics']) or '—'} · ops: {', '.join(cl['implemented_ops']) or '—'} · unblocked by `{cl['unblocked_by']}` · recommended: **{cl['recommended_label']}** — {cl['recommendation_reason']}")
            out.append("")
    out += ["## Not claimed", ""] + [f"- {x}" for x in ledger["not_claimed"]] + [""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest, ledger, md = build()
    outputs = {PACK / "inventory.draft.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
               PACK / "inventory_ledger.json": json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
               PACK / "INVENTORY.md": md}
    if args.check:
        stale = [p.name for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != text]
        if stale:
            print(f"FAILED: stale inventory outputs {stale}; re-run build_r3_inventory.py and commit the diff", file=sys.stderr)
            return 1
        print(f"OK: inventory matches the snapshot, errata and selection ({ledger['counts']['cards']} cards, {ledger['counts']['clauses']} clauses)")
        return 0
    for p, text in outputs.items():
        p.write_text(text, encoding="utf-8")
    print(f"wrote {len(outputs)} files: {ledger['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
