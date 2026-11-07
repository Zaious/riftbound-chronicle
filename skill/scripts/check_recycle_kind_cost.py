#!/usr/bin/env python3
"""Regression gate: a Recycle-from-trash cost limited to one card kind (set 2 package A2: Assembly Rig, "Recycle a unit
from your trash"). Only cards of that kind can pay it (Core 417.3: the whole action must be completable).

  K1  p1's trash holds spells c3, c2 and a unit tu: the cost is paid with tu (forced - the only unit); tu leaves the trash
  K2  choosing the spell c3 is refused
  K3  a trash with no unit: the play is refused (cost_unpayable)
  V   card_kind on a discard, or a kind outside unit / gear / spell, does not validate
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_costs_and_activation import declaration, envelope, event, hand_state, pick  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from play_transaction import play_card, validate_declaration  # noqa: E402

COST = {"base": {"energy": 1, "power": {}},
        "additional": [{"cost_id": "r", "mandatory": True, "payment": {"kind": "recycle_trash", "amount": 1, "card_kind": "unit"}}]}


def board(with_unit=True):
    s = hand_state("c1")
    s["players"]["p1"]["zones"]["main_deck"] = []
    s["players"]["p1"]["zones"]["trash"] = ["c3", "c2"]
    if with_unit:
        s["objects"]["tu"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
        s["players"]["p1"]["zones"]["trash"].append("tu")
    return s


def main() -> int:
    errors: list[str] = []
    s = board()
    paid = play_card(fixture(), s, declaration(cost=COST))
    ev = event(paid, "pay_recycle_trash") if paid.get("committed") else None
    if not paid.get("committed") or not ev or ev.get("objects") != ["tu"] \
            or "tu" in paid["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append(f"K1: {paid.get('reason_code')} {paid.get('reason')} {ev}")
    spell = play_card(fixture(), s, declaration(cost=COST), engine_decisions=envelope(s, pick("cost:play-1:r", ["c3"], s)))
    if spell.get("committed") and (event(spell, "pay_recycle_trash") or {}).get("objects") == ["c3"]:
        errors.append("K2: the spell paid a unit-only recycle cost")
    none = play_card(fixture(), board(with_unit=False), declaration(cost=COST))
    if none.get("committed") or none.get("reason_code") != "cost_unpayable":
        errors.append(f"K3: {none.get('committed')} {none.get('reason_code')}")
    for label, pay in (("a discard with a card_kind", {"kind": "discard", "amount": 1, "card_kind": "unit"}),
                       ("a rune kind", {"kind": "recycle_trash", "amount": 1, "card_kind": "rune"})):
        bad = declaration(cost={"base": {"energy": 1, "power": {}},
                                "additional": [{"cost_id": "r", "mandatory": True, "payment": pay}]})
        if not validate_declaration(bad):
            errors.append(f"V: {label} validated")
    if errors:
        print("recycle-kind cost checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("recycle-kind cost checks passed: only a card of the named kind pays it, another kind is refused, a trash with "
          "none cannot pay; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
