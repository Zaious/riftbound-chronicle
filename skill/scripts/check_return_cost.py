#!/usr/bin/env python3
"""Regression gate: "As an additional cost to play me, return a friendly gear to its owner's hand." (set 2 package A2:
Legion Quartermaster; Core 356.2.a.1, 357.2, 448.2).

  R1  the one friendly Gear on the board pays it: it is in its owner's hand (a new object, Core 124) and the card enters;
      the receipt records the paid printed component
  R2  two friendly Gears: the payer is asked which; the chosen one is returned, the other stays; an enemy Gear, or a
      friendly Unit, is refused as the payment
  R3  no friendly Gear on the board: the play is refused (Core 203.3); the printed form lowers to the cost
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_printed_costs import component, decisions, declaration, pick, play, state, where  # noqa: E402
from effect_ir import object_identity, validate_state  # noqa: E402

TEXT = "As an additional cost to play me, return a friendly gear to its owner's hand."


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
    fields = (got.get("passive") or {}).get("object_fields") or {}
    if got.get("production_id") != "as_an_additional_cost_to_play_me_return_a_friendly_gear":
        errors.append(f"R3: lowered to {got.get('production_id')}")
    fields = copy.deepcopy(fields)
    for offer in fields.get("printed_additional_costs") or []:
        offer["cost_offer_id"] = "r"
    one = board(fields, [("g1", "p1")])
    if validate_state(one):
        errors.append(f"fixture invalid: {validate_state(one)[:2]}")
    sole = play(one, printed=(4, None))
    if not sole.get("committed"):
        errors.append(f"R1: one friendly gear did not pay: {sole.get('reason_code')} {sole.get('reason')}")
    else:
        after = sole["next_effect_state"]
        if where(after, "g1") != "p1:hand" or object_identity(after, "g1") == object_identity(one, "g1"):
            errors.append(f"R1: the gear is at {where(after, 'g1')}, identity {object_identity(after, 'g1')}")
        paid = component(sole, "self_cost:r")
        if not paid or not paid.get("paid") or paid.get("object_id") != "g1":
            errors.append(f"R1: the receipt does not record the paid return: {paid}")
    two = board(fields, [("g1", "p1"), ("g2", "p1"), ("eg", "p2")])
    asked = play(two, printed=(4, None))
    if asked.get("committed") or asked.get("reason_code") != "card_selection_required":
        errors.append(f"R2: two friendly gears did not ask which: {asked.get('reason_code')}")
    chose = play(two, printed=(4, None), with_decisions=decisions(two, pick(two, "self_cost:r", ["g2"])))
    if not chose.get("committed") or where(chose["next_effect_state"], "g2") != "p1:hand" \
            or where(chose["next_effect_state"], "g1") != "p1:base":
        errors.append(f"R2: the chosen gear was not the one returned: {chose.get('reason_code')} {chose.get('reason')}")
    for label, objects in (("an enemy gear", ["eg"]), ("a friendly unit", ["u1"])):
        bad = play(two, printed=(4, None), with_decisions=decisions(two, pick(two, "self_cost:r", objects)))
        if bad.get("committed"):
            errors.append(f"R2: {label} paid the cost")
    none = board(fields, [("eg", "p2")])
    refused = play(none, printed=(4, None))
    if refused.get("committed"):
        errors.append("R3: with no friendly gear the card was played")
    if errors:
        print("return-to-hand cost checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("return-to-hand cost checks passed: the friendly gear returned to its owner's hand as the cost, asked between two, "
          "an enemy gear or a unit refused, no gear no play; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
