#!/usr/bin/env python3
"""Regression gate: "You may kill a friendly gear as an additional cost to play me." (set 2 package A2: Zaun Punk;
Core 356.2.b, 357.2, 429.1.a.1).

  K1  chosen, with one friendly Gear: it is killed (in its owner's trash) and the receipt's self_offer component is paid
  K2  declined: nothing is killed and the component is on the receipt, unpaid
  K3  chosen, with only an enemy Gear: the play is refused (nothing of p1's can pay it, Core 203.3); the printed form
      lowers to an optional kill of a Gear
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_printed_costs import component, decisions, intent, play, state, where  # noqa: E402
from effect_ir import validate_state  # noqa: E402

TEXT = "You may kill a friendly gear as an additional cost to play me."


def gear(owner):
    return {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(fields, gears):
    s = state(fields, energy=6, printed=(4, None))
    for oid, owner in gears:
        s["objects"][oid] = gear(owner)
        s["players"][owner]["zones"]["base"].append(oid)
    return s


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    fields = copy.deepcopy((got.get("passive") or {}).get("object_fields") or {})
    if got.get("production_id") != "you_may_kill_a_friendly_gear_as_an_additional_cost_to_play_me" \
            or (fields.get("printed_additional_costs") or [{}])[0].get("payment") != {"kind": "kill", "amount": 1, "object_kind": "gear"}:
        errors.append(f"K3: lowered to {got.get('production_id')} {fields}")
    for offer in fields.get("printed_additional_costs") or []:
        offer["cost_offer_id"] = "k"
    one = board(fields, [("g1", "p1"), ("eg", "p2")])
    if validate_state(one):
        errors.append(f"fixture invalid: {validate_state(one)[:2]}")
    paid = play(one, printed=(4, None), with_decisions=decisions(one, intent("self_offer:k", True)))
    if not paid.get("committed") or where(paid["next_effect_state"], "g1") != "p1:trash" \
            or where(paid["next_effect_state"], "eg") != "p2:base":
        errors.append(f"K1: chosen: {paid.get('reason_code')} g1 {where(paid.get('next_effect_state') or one, 'g1')}")
    elif not (component(paid, "self_offer:k") or {}).get("paid"):
        errors.append(f"K1: the offer is not paid on the receipt: {component(paid, 'self_offer:k')}")
    declined = play(one, printed=(4, None), with_decisions=decisions(one, intent("self_offer:k", False)))
    if not declined.get("committed") or where(declined["next_effect_state"], "g1") != "p1:base":
        errors.append(f"K2: declined: {declined.get('reason_code')} g1 {where(declined.get('next_effect_state') or one, 'g1')}")
    elif (component(declined, "self_offer:k") or {}).get("paid"):
        errors.append("K2: a declined offer is paid on the receipt")
    theirs = board(fields, [("eg", "p2")])
    refused = play(theirs, printed=(4, None), with_decisions=decisions(theirs, intent("self_offer:k", True)))
    if refused.get("committed"):
        errors.append("K3: chosen with only an enemy gear, the card was played")
    if errors:
        print("kill-a-friendly-gear offer checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("kill-a-friendly-gear offer checks passed: chosen, the friendly gear killed and the offer paid; declined, nothing; "
          "only an enemy gear, refused; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
