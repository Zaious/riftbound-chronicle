#!/usr/bin/env python3
"""Regression gate for `self_card_conditional_fixed_energy_reduction.v1`
(Round H, Codex's narrow exception to DP-88).

A card's own text may say it costs a fixed amount of Energy less, gated by a
condition. That is all this capability is. Codex fixed the scope, and this gate
is where the scope is enforced rather than described:

  - only the card being played, from its own text;
  - only a fixed Energy amount — no X, no value read off the board, no Power
    or Domain, no other card and no continuous effect;
  - the condition must be a registered `condition.v1` leaf whose facts are all
    on the state; a missing fact is `cost_condition_not_observed`, never a
    guess;
  - the first leaf is the score distance to the Victory Score, tested on both
    sides of its threshold, abstaining for teams and for more than one
    opponent;
  - **the reduced cost is one number**: the payment path and the enumeration
    call the same function and must agree, and neither may go below the legal
    minimum;
  - no card-name special cases: the fixture cards here are synthetic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import legal_action as la  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import ConditionUnsupported, evaluate_cost_modification, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

CONDITION = {"kind": "score_within_of_victory", "count": 3}


def state_with(*, points=5, amount=2, condition=CONDITION, energy=4, pool=4):
    """A synthetic spell in hand whose own text reduces its Energy cost."""
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": pool, "power": {}}
    state["players"]["p2"]["points"] = points
    modification = {"modification_id": "own-text", "kind": "energy_reduction", "amount": amount}
    if condition is not None:
        modification["condition"] = copy.deepcopy(condition)
    state["objects"]["c1"].update({"kind": "spell", "printed_cost": {"energy": energy, "power": {}},
                                   "printed_cost_modifications": [modification]})
    return state


def declaration(card="c1", energy=4):
    return {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": card,
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "action"},
            "cost": {"base": {"energy": energy, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def enumerated_total(state, card="c1"):
    obj = state["objects"][card]
    return la._cost_total({"base": obj["printed_cost"]}, effect_state=state, card_id=card, actor="p1")


def paid_energy(result):
    return next((c["final"] for c in result["cost_receipt"]["components"] if c["cost_id"] == "base:energy"), None)


def main() -> int:
    errors: list[str] = []

    # --- the condition, on both sides of its threshold -------------------------------------------
    met = state_with(points=5)      # 8 - 5 = 3, within 3
    unmet = state_with(points=4)    # 8 - 4 = 4, outside 3
    if found := validate_state(met):
        errors.append(f"a card carrying its own printed reduction is invalid: {found}")
    if evaluate_cost_modification(met, {"amount": 2, "condition": CONDITION}, "p1")["applies"] is not True:
        errors.append("the reduction did not apply at the threshold")
    if evaluate_cost_modification(unmet, {"amount": 2, "condition": CONDITION}, "p1")["applies"] is not False:
        errors.append("the reduction applied one point outside the threshold")

    # --- the payment path and the enumeration are the same number ---------------------------------
    for label, state, expected in (("met", met, 2), ("unmet", unmet, 4)):
        played = pt.play_card(fixture(), state, declaration())
        if not played.get("committed"):
            errors.append(f"({label}) the play did not commit: {played.get('reason_code')} {played.get('reason')}")
            continue
        charged = paid_energy(played)
        total, problem = enumerated_total(state)
        if problem is not None:
            errors.append(f"({label}) the enumeration refused a cost the payment path computed: {problem}")
        elif charged != expected or total["energy"] != expected:
            errors.append(f"({label}) payment charged {charged} and enumeration said {total['energy']}, expected {expected}")
        if played["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 4 - expected:
            errors.append(f"({label}) the pool was not reduced by what the receipt charged")

    # --- never below the legal minimum --------------------------------------------------------------
    huge = state_with(points=5, amount=99, energy=2, pool=0)
    played = pt.play_card(fixture(), huge, declaration(energy=2))
    if not played.get("committed"):
        errors.append(f"a reduction larger than the cost did not simply floor it: {played.get('reason')}")
    elif paid_energy(played) != 0:
        errors.append(f"a reduction larger than the cost went below zero: {paid_energy(played)}")
    total, _ = enumerated_total(huge)
    if total["energy"] != 0:
        errors.append(f"the enumeration went below zero: {total}")
    floored = state_with(points=5, amount=3, energy=4)
    floored["objects"]["c1"]["printed_cost_modifications"][0]["condition"] = CONDITION
    minimum = pt.determine_total_cost({"base": {"energy": 4, "power": {}},
                                       "discounts": [{"id": "self:own-text", "applies_to": "energy", "amount": 3, "minimum": 2}]}, {})
    if minimum["total"]["energy"] != 2:
        errors.append(f"a discount's own minimum was not honoured (356.4.e): {minimum['total']}")

    # --- a fact the state does not carry is named, not guessed ---------------------------------------
    blind = state_with(points=5)
    del blind["mode"]
    played = pt.play_card(fixture(), blind, declaration())
    if played.get("committed") or played.get("reason_code") != "cost_condition_not_observed":
        errors.append(f"a missing Victory Score was not named as unobserved: {played.get('reason_code')}")
    total, problem = enumerated_total(blind)
    if total is not None or problem != "cost_condition_not_observed":
        errors.append(f"the enumeration guessed a cost it could not condition: {total} {problem}")
    teamed = state_with(points=5)
    teamed["mode"] = {"victory_score": 8, "teams": True}
    if pt.play_card(fixture(), teamed, declaration()).get("reason_code") != "cost_condition_not_observed":
        errors.append("a team mode was decided rather than abstained")
    crowded = state_with(points=5)
    crowded["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [],
                                          "rune_deck": []}, "resources": {"energy": 0, "power": {}}, "points": 0}
    if pt.play_card(fixture(), crowded, declaration()).get("reason_code") != "cost_condition_not_observed":
        errors.append("more than one opponent was decided rather than abstained")

    # --- the scope is enforced, not merely written down ------------------------------------------------
    for bad, why in (
        ({"modification_id": "x", "kind": "power_reduction", "amount": 1}, "a Power reduction"),
        ({"modification_id": "x", "kind": "energy_reduction", "amount": 0}, "a zero amount"),
        ({"modification_id": "x", "kind": "energy_reduction", "amount": "X"}, "a variable amount"),
        ({"modification_id": "x", "kind": "energy_reduction", "amount": 1, "per_each": {"kind": "controls_units"}}, "a per-each count"),
        ({"modification_id": "x", "kind": "energy_reduction", "amount": 1, "condition": {"kind": "moon_phase"}}, "an unregistered leaf"),
    ):
        state = state_with()
        state["objects"]["c1"]["printed_cost_modifications"] = [bad]
        if not validate_state(state):
            errors.append(f"{why} was accepted as a self-card reduction")

    # --- another card's text is not this capability -----------------------------------------------------
    elsewhere = state_with(points=5)
    elsewhere["objects"]["c2"]["printed_cost_modifications"] = copy.deepcopy(
        elsewhere["objects"]["c1"]["printed_cost_modifications"])
    if pt.self_cost_reductions(elsewhere, "c1") != pt.self_cost_reductions(state_with(points=5), "c1"):
        errors.append("another card's printed reduction leaked into this one's cost")
    if not pt.self_cost_reductions(elsewhere, "c2") or pt.self_cost_reductions(elsewhere, "nope"):
        errors.append("self_cost_reductions did not read exactly the card it was asked about")

    # --- negative mutation: without the card's own text there is no discount --------------------------
    plain = state_with(points=5)
    del plain["objects"]["c1"]["printed_cost_modifications"]
    played = pt.play_card(fixture(), plain, declaration())
    if not played.get("committed") or paid_energy(played) != 4:
        errors.append(f"negative mutation failed: the discount appeared without the card's text: {paid_energy(played)}")
    total, _ = enumerated_total(plain)
    if total["energy"] != 4:
        errors.append("negative mutation failed: the enumeration discounted a card with no printed reduction")

    if errors:
        print("FAILED: self-card cost reduction checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("self-card cost reduction checks passed: one number for the payment path and the enumeration, floored at the "
          "legal minimum, abstaining by name when a fact is missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
