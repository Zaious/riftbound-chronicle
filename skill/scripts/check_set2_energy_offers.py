#!/usr/bin/env python3
"""Regression gate: a card's own optional Energy (or Energy and one rune) offer for its play (set 2 package A2).

  O1  "You may pay [1] as an additional cost to play me." lowers to one offer of 1 Energy; "... [1][Fury] ..." to one
      offer of 1 Energy and one Fury Power, one cost together
  O2  played paying it, the Energy (and the Power) is paid on top of the printed cost; declining it, only the printed
      cost; paying it with too little is refused
  O3  the receipt records the offer paid, so "if you paid the additional cost" can read it

The fixture cards are synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def state_with(offer, *, energy, power):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": energy, "power": dict(power)}
    state["objects"]["c1"].update({"kind": "spell", "printed_cost": {"energy": 2, "power": {}}, "play_timing": "action",
                                   "optional_additional_costs": [copy.deepcopy(offer)]})
    return state


def play(state, pay):
    decl = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "action"},
            "cost": {"base": {"energy": 2, "power": {}}}, "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(state), "decisions": [
        {"decision_id": f"self_offer:{state['objects']['c1']['optional_additional_costs'][0]['cost_offer_id']}",
         "kind": "optional_choice", "stage": "play_declaration", "controller": "p1", "value": pay}]}
    return pt.play_card(fixture(), state, decl, engine_decisions=decisions)


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    offers = {}
    for key, text, want in (
            ("energy", "You may pay :rb_energy_1: as an additional cost to play me.",
             {"cost_offer_id": "$clause_id", "payment": {"kind": "energy", "amount": 1}}),
            ("both", "You may pay :rb_energy_1::rb_rune_fury: as an additional cost to play me.",
             {"cost_offer_id": "$clause_id", "energy": 1, "payment": {"kind": "power", "domain": "fury", "amount": 1}})):
        got = ((CG.compile_clause(text, grammar).get("passive") or {}).get("object_fields") or {}).get("optional_additional_costs")
        if got != [want]:
            errors.append(f"O1: {text!r} lowered to {got}")
        offers[key] = {**want, "cost_offer_id": f"own-{key}"}
    for key, power, paid_energy in (("energy", {}, 3), ("both", {"fury": 1}, 3)):
        offer = offers[key]
        paid = play(state_with(offer, energy=3, power=power), True)
        if not paid.get("committed"):
            errors.append(f"O2 {key}: paying the offer was refused: {paid.get('reason_code')} {paid.get('reason')}")
        else:
            left = paid["next_effect_state"]["players"]["p1"]["resources"]
            if left.get("energy") != 0 or any(left.get("power", {}).values()):
                errors.append(f"O2 {key}: paying left {left}")
            receipt = paid.get("cost_receipt") or {}
            if not any(f"self_offer:{offer['cost_offer_id']}" in str(c.get("cost_id")) or offer["cost_offer_id"] in str(c)
                       for c in receipt.get("components") or []):
                errors.append(f"O3 {key}: the receipt does not name the offer paid: {receipt.get('components')}")
        declined = play(state_with(offer, energy=3, power=power), False)
        if not declined.get("committed") or declined["next_effect_state"]["players"]["p1"]["resources"].get("energy") != 1:
            errors.append(f"O2 {key}: declining paid {(declined.get('next_effect_state') or {}).get('players', {}).get('p1', {}).get('resources')} "
                          f"({declined.get('reason_code')})")
        short = play(state_with(offer, energy=2, power={}), True)
        if short.get("committed"):
            errors.append(f"O2 {key}: paying the offer with too little was accepted")
    if errors:
        print("set 2 energy offer checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("set 2 energy offer checks passed: an optional Energy, or Energy and one rune, offer for the card's own play - "
          "lowered, paid on top of the printed cost when chosen, not when declined, refused when short; the receipt names it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
