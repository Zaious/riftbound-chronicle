#!/usr/bin/env python3
"""C-62 (ADR-0016 §3): the coverage debt ledger.

Every clause in the corpus that `clause-grammar.v1` does not parse, ranked by
what it costs to leave unparsed: the deck slots it occupies in the deck lists
this repo actually carries, how many decks play the card, whether the card is
always in play, and the engine capability the clause is missing.

There is no repayment quota. A packet reports what the debt gained, lost or
reclassified, and that is all it is asked to do — a quota would buy movement
with immature semantics.

  python coverage_debt.py build     write the ledger and report the delta
  python coverage_debt.py check     rebuild and diff against what is committed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from pack_locator import pack_files  # noqa: E402

DEBT_VERSION = "coverage-debt.v1"
DATA = SCRIPT_DIR.parent / "data"
LISTS = DATA / "tournament_lists"
OUT = DATA / "coverage_debt" / "coverage_debt.json"

# A card that is always in play leaks its unparsed clause into every game it is
# in; a main-deck card only into the games it is drawn.
RISK_ORDER = {"always_in_play": 0, "main_deck": 1, "unknown": 2}
ALWAYS_IN_PLAY_TYPES = {"legend", "champion", "battlefield"}


def deck_slots() -> dict[str, int]:
    """Copies of each card across every deck list this repo carries. Measured,
    not estimated: a card no list plays scores zero and says so."""
    slots: dict[str, int] = {}
    for path in sorted(LISTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("lists", []) or []:
            for section in ("main_deck", "rune_deck", "sideboard"):
                for row in entry.get(section, []) or []:
                    if isinstance(row, dict) and isinstance(row.get("name"), str):
                        slots[row["name"].strip().lower()] = slots.get(row["name"].strip().lower(), 0) + int(row.get("count", 1))
    return slots


def ledger_index() -> dict[str, dict[str, Any]]:
    """Per card: the decks that play it, its type, and each clause's mechanics
    as the inventory recorded them."""
    index: dict[str, dict[str, Any]] = {}
    for path in pack_files("inventory_ledger.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for card in data.get("cards", []) or []:
            index[card["card_key"]] = {
                "type": (card.get("type") or "").lower(),
                "decks": [d.get("deck_id") for d in card.get("decks", []) or []],
                "clauses": {c["clause_id"]: c for c in card.get("clauses", []) or []},
            }
    return index


def build() -> dict[str, Any]:
    grammar = cg.load_grammar()
    slots, ledger = deck_slots(), ledger_index()
    entries: list[dict[str, Any]] = []
    parsed = 0
    # G-3's promotion rule, made measurable: a clause may be claimed full or
    # partial only once it passes canonical compile, its fixture and this
    # ledger. Everything else claiming full is still a hand-written program.
    promotion = {"grammar_reproduced": 0, "hand_written": 0, "in_debt_but_claimed": 0}
    for path in pack_files("r3a1_programs.json"):
        pack = json.loads(path.read_text(encoding="utf-8"))
        for card in pack["cards"]:
            record = ledger.get(card["card_key"], {})
            card_type = record.get("type", "")
            decks = record.get("decks", [])
            for clause in card["clauses"]:
                result = cg.compile_clause(clause["text"], grammar)
                claimed = clause.get("claim") in {"full", "partial"}
                if not result.get("unsupported"):
                    parsed += 1
                    if claimed:
                        promotion["grammar_reproduced"] += 1
                    continue
                if claimed:
                    promotion["in_debt_but_claimed"] += 1
                    promotion["hand_written"] += 1
                inventory = (record.get("clauses") or {}).get(clause["clause_id"], {})
                mechanics = sorted(inventory.get("mechanics", []) or [])
                entries.append({
                    "clause_id": clause["clause_id"],
                    "card_key": card["card_key"],
                    "card": card.get("card"),
                    "text": clause["text"],
                    "pack": path.parent.name,
                    "deck_slots": slots.get((card.get("card") or "").strip().lower(), 0),
                    "deck_count": len(decks),
                    "decks": decks,
                    "risk": "always_in_play" if card_type in ALWAYS_IN_PLAY_TYPES else ("main_deck" if card_type else "unknown"),
                    "rule_family": mechanics or ["unclassified"],
                    "missing_capability": inventory.get("unblocked_by") or "unknown",
                    "claim_in_pack": clause.get("claim"),
                    "reason_code": result["reason_code"],
                })
    entries.sort(key=lambda e: (-e["deck_slots"], -e["deck_count"], RISK_ORDER[e["risk"]],
                                e["missing_capability"], e["clause_id"]))
    by_family: dict[str, int] = {}
    for entry in entries:
        for family in entry["rule_family"]:
            by_family[family] = by_family.get(family, 0) + 1
    return {
        "schema_version": DEBT_VERSION,
        "grammar_version": grammar["version"],
        "ranking": ["deck_slots", "deck_count", "risk", "missing_capability", "clause_id"],
        "quota": None,
        "note": ("No repayment quota: a packet reports what the debt gained, lost or reclassified. "
                 "deck_slots counts copies in the deck lists this repo carries; a card no list plays scores zero."),
        "counts": {"clauses_parsed": parsed, "clauses_in_debt": len(entries), "promotion": promotion,
                   "by_rule_family": dict(sorted(by_family.items())),
                   "by_risk": {risk: sum(1 for e in entries if e["risk"] == risk) for risk in sorted(RISK_ORDER)}},
        "entries": entries,
    }


def delta(fresh: dict[str, Any], committed: dict[str, Any] | None) -> dict[str, Any]:
    if committed is None:
        return {"baseline": None, "added": [e["clause_id"] for e in fresh["entries"]], "repaid": [],
                "reclassified": []}
    before = {e["clause_id"]: e for e in committed.get("entries", [])}
    after = {e["clause_id"]: e for e in fresh["entries"]}
    reclassified = [cid for cid in sorted(set(before) & set(after))
                    if {k: before[cid].get(k) for k in ("risk", "missing_capability", "rule_family", "deck_slots")}
                    != {k: after[cid].get(k) for k in ("risk", "missing_capability", "rule_family", "deck_slots")}]
    return {
        "baseline": committed.get("grammar_version"),
        "added": sorted(set(after) - set(before)),
        "repaid": sorted(set(before) - set(after)),
        "reclassified": reclassified,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the coverage debt ledger")
    parser.add_argument("command", choices=["build", "check"])
    args = parser.parse_args(argv)
    fresh = build()
    committed = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    movement = delta(fresh, committed)
    if args.command == "check":
        if committed is None:
            print("FAILED: no committed coverage debt; run coverage_debt.py build")
            return 1
        if {k: v for k, v in committed.items() if k != "delta"} != {k: v for k, v in fresh.items() if k != "delta"}:
            print("FAILED: the committed coverage debt is stale; re-run coverage_debt.py build and commit the diff")
            print(f"  added={movement['added']} repaid={movement['repaid']} reclassified={movement['reclassified']}")
            return 1
        print(f"coverage debt is current: {fresh['counts']['clauses_in_debt']} clauses in debt, "
              f"{fresh['counts']['clauses_parsed']} parsed")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fresh["delta"] = movement
    OUT.write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {fresh['counts']['clauses_in_debt']} in debt, {fresh['counts']['clauses_parsed']} parsed; "
          f"added={len(movement['added'])} repaid={len(movement['repaid'])} reclassified={len(movement['reclassified'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
