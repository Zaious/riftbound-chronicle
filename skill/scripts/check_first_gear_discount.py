#!/usr/bin/env python3
"""Regression gate: "While you control this battlefield, the first friendly non-token gear played each turn costs [1]
less." (set 2 package A2: Ornn's Forge). A Battlefield's static (first_gear_cost_reduction N): while the actor controls it,
the first non-token Gear card the actor plays each turn costs N Energy less (Core 356.4.b) - "played" read off the cards
the player finalized this turn, the ledger "cards you've played this turn" reads.

  F1  p1 controls bf1 (the static); p1 plays a Gear printed [2]: 1 Energy paid
  F2  a second Gear the same turn: 2 paid
  F3  bf1 controlled by p2: the first Gear pays 2
  F4  a spell (not a Gear) first, then a Gear: the Gear pays 1
  V   a non-positive amount does not validate
  G   the printed line lowers to exactly that field
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402

TEXT = "While you control this battlefield, the first friendly non-token gear played each turn costs :rb_energy_1: less."


def board(controller="p1", amount=1):
    s = base_state()
    s["battlefields"]["bf1"].update({"controller": controller, "first_gear_cost_reduction": amount})
    for gid in ("g1", "g2"):
        s["objects"][gid] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False, "printed_cost": {"energy": 2, "power": {}}}
        s["players"]["p1"]["zones"]["hand"].append(gid)
    s["players"]["p1"]["resources"] = {"energy": 6, "power": {}}
    return s


def play(s, card, kind="gear", energy=2):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": f"p-{card}", "actor": "p1", "card": card,
            "chain_item": {"id": f"{kind}-{card}", "object_kind": kind, "timing": "default"},
            "cost": {"base": {"energy": energy, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return play_card(fixture(), s, decl)


def spent(before, played):
    return before["players"]["p1"]["resources"]["energy"] - played["next_effect_state"]["players"]["p1"]["resources"]["energy"]


def main() -> int:
    errors: list[str] = []
    s = board()
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    first = play(s, "g1")
    if not first.get("committed") or spent(s, first) != 1:
        errors.append(f"F1: {first.get('reason_code')} spent {spent(s, first) if first.get('committed') else None}")
    else:
        after = first["next_effect_state"]
        second = play(after, "g2")
        if not second.get("committed") or spent(after, second) != 2:
            errors.append(f"F2: {second.get('reason_code')} spent {spent(after, second) if second.get('committed') else None}")
    theirs = board(controller="p2")
    got = play(theirs, "g1")
    if not got.get("committed") or spent(theirs, got) != 2:
        errors.append(f"F3: {got.get('reason_code')} spent {spent(theirs, got) if got.get('committed') else None}")
    s4 = board()
    s4["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s4["players"]["p1"]["zones"]["hand"].append("c1")
    spell = play(s4, "c1", kind="spell", energy=0)
    if not spell.get("committed"):
        errors.append(f"F4: the spell was refused: {spell.get('reason_code')} {spell.get('reason')}")
    else:
        after = spell["next_effect_state"]
        gear = play(after, "g1")
        if not gear.get("committed") or spent(after, gear) != 1:
            errors.append(f"F4: {gear.get('reason_code')} spent {spent(after, gear) if gear.get('committed') else None}")
    if not any("first_gear_cost_reduction" in p for p in IR.validate_state(board(amount=0))):
        errors.append("V: an amount of 0 validated")
    lowered = CG.compile_clause(TEXT, CG.load_grammar())
    if (lowered.get("passive") or {}).get("battlefield_fields") != {"first_gear_cost_reduction": 1}:
        errors.append(f"G: lowered to {lowered.get('production_id')} {lowered.get('passive')}")
    if errors:
        print("first-gear discount checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("first-gear discount checks passed: the first non-token Gear its controller plays this turn costs 1 less, the "
          "second does not, a spell before it does not spend it, the opponent's Battlefield gives nothing; validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
