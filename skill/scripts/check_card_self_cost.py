#!/usr/bin/env python3
"""Regression gate for card-self optional additional costs (Round H).

Accelerate was the first card-printed optional additional cost; this is the
general shape behind it, and Clockwork Keeper is the first card to use it
without a keyword: "You may pay [C] as additional cost to play me. When you
play me, if you paid additional cost, draw 1."

**What [C] means, and how that was established.** Not by reading the symbol -
by three independent renderings of the same corpus:

  - Blazing Scorcher prints ":rb_energy_1::rb_rune_fury:" and is rendered
    "[1][C]"; its Domain is Fury.
  - Clockwork Keeper printed ":rb_rune_calm:" and its erratum writes "[C]";
    its Domain is Calm.
  - ":rb_rune_rainbow:" is rendered "[A]", on Qiyana and on Zhonya's
    Hourglass.

So [C] is one Power of the card's *own* Domain and [A] is any Domain. A card
whose Domains the state does not record abstains - "we cannot tell" is not
"no Domain", and the difference decides whether the cost is payable.

Codex's contract for this shape, checked below:

  - paying is an **explicit choice**. A pool that could pay never pays by
    itself, and the declined component stays on the receipt unpaid;
  - `cost_paid` binds **source_object, chain_item and cost_offer_id**. A
    program reading a receipt for another card, another play, or another
    offer is refused before it runs, not after;
  - the enumerator and the payment path read the same offer.

Every fixture here is synthetic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import legal_action as la  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, validate_program, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

OFFER_ID = "clockwork-keeper-draw"
COST_ID = f"{pt.CARD_SELF_OFFER_PREFIX}:{OFFER_ID}"


def keeper_state(*, domains=("calm",), pool_power=("calm",), offers=1):
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 5, "power": {d: 2 for d in pool_power}}
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, "printed_cost": {"energy": 2, "power": {}}})
    if domains is not None:
        state["objects"]["c1"]["domains"] = list(domains)
    state["objects"]["c1"]["optional_additional_costs"] = [
        {"cost_offer_id": f"{OFFER_ID}-{i}" if i else OFFER_ID,
         "payment": {"kind": "power_own_domain", "amount": 1}}
        for i in range(offers)]
    return state


def declaration():
    return {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}},
            "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def play(state, *, paid=None):
    engine_decisions = None
    if paid is not None:
        engine_decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                            "decisions": [{"decision_id": COST_ID, "kind": "optional_choice",
                                           "stage": "play_declaration", "controller": "p1", "value": paid}]}
    return pt.play_card(fixture(), state, declaration(), engine_decisions=engine_decisions)


def component(result, cost_id=COST_ID):
    receipt = result.get("cost_receipt") or {}
    return next((c for c in receipt.get("components", []) if c["cost_id"] == cost_id), None)


def draw_program(*, card="c1", chain_item="unit-1", offer=OFFER_ID, receipt=None):
    program = {"schema_version": pt.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "keeper-draw", "controller": "p1", "source_object": card, "chain_item": chain_item,
               "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1,
                            "predicate": {"kind": "cost_paid", "cost_id": COST_ID, "cost_offer_id": offer}}]}
    if receipt is not None:
        program["cost_receipt"] = receipt
    return program


def main() -> int:
    errors: list[str] = []

    # --- the offer is made, and paying it is a choice ---------------------------------------------
    declined = play(keeper_state(), paid=False)
    paid = play(keeper_state(), paid=True)
    for label, result in (("declined", declined), ("paid", paid)):
        if not result.get("committed"):
            errors.append(f"the {label} play did not commit: {result.get('errors') or result.get('reason_code')}")
    if declined.get("committed") and paid.get("committed"):
        left = component(declined)
        right = component(paid)
        if left is None or right is None:
            errors.append(f"the printed offer never reached the receipt: {left} {right}")
        else:
            if left["paid"] or left["intent"] is not False:
                errors.append(f"a declined offer was recorded as paid: {left}")
            if not right["paid"] or right["intent"] is not True:
                errors.append(f"an accepted offer was not recorded as paid: {right}")
            if right.get("cost_offer_id") != OFFER_ID or right.get("offered_by") != "c1":
                errors.append(f"the component does not name its offer and its object: {right}")
            if right.get("domain") != "calm":
                errors.append(f"[C] was not resolved to the card's own Domain: {right.get('domain')!r}")
        spent = declined["next_effect_state"]["players"]["p1"]["resources"]["power"].get("calm")
        if spent != 2:
            errors.append(f"a declined optional cost still spent Power ({spent} left of 2); "
                          "a full pool must never pay an optional cost by itself (356.2.b.1)")

    # --- no decision at all is not a decision to pay ----------------------------------------------
    undecided = play(keeper_state())
    if undecided.get("committed"):
        errors.append("the play committed without the player ever choosing about the printed offer")

    # --- [C] is the card's own Domain, not any ---------------------------------------------------
    wrong_domain = play(keeper_state(pool_power=("fury",)), paid=True)
    if wrong_domain.get("committed"):
        errors.append("a pool holding only another Domain's Power paid a [C] cost; "
                      "[C] is the card's Domain, not [A]")

    # --- the Domains not being observed is an abstention, not "no cost" ---------------------------
    entries, abstentions = pt.card_self_cost_offers(keeper_state(domains=None), "c1")
    if entries or [a["reason"] for a in abstentions] != ["offer_domain_not_observed"]:
        errors.append(f"a card whose Domains are unobserved was still offered a payable cost: {entries} {abstentions}")
    entries, abstentions = pt.card_self_cost_offers(keeper_state(domains=()), "c1")
    if entries or [a["reason"] for a in abstentions] != ["offer_has_no_domain"]:
        errors.append(f"a card with no Domain was offered a [C] cost anyway: {entries} {abstentions}")
    entries, abstentions = pt.card_self_cost_offers(keeper_state(domains=("calm", "body")), "c1")
    if entries or [a["reason"] for a in abstentions] != ["offer_domain_not_single"]:
        errors.append(f"a two-Domain card's [C] was resolved without the player choosing: {entries} {abstentions}")

    # --- the three-way binding ---------------------------------------------------------------------
    receipt = paid.get("cost_receipt")
    if receipt is None:
        errors.append("the paid play produced no receipt to bind against")
    else:
        if validate_program(draw_program(receipt=receipt)):
            errors.append(f"the correctly bound program was refused: {validate_program(draw_program(receipt=receipt))}")
        for label, program in (
            ("another card", draw_program(card="c2", receipt=receipt)),
            ("another play", draw_program(chain_item="unit-2", receipt=receipt)),
            ("another offer", draw_program(offer="some-other-offer", receipt=receipt)),
            ("no receipt at all", draw_program()),
        ):
            if not validate_program(program):
                errors.append(f"a cost_paid predicate bound to {label} was accepted; "
                              "one card's additional cost must not satisfy another's")

    # --- enumeration and payment read the same offer -----------------------------------------------
    state = keeper_state()
    enumerated = la.enumerate_actions(state, "p1") if hasattr(la, "enumerate_actions") else None
    if enumerated is not None:
        found = [a for a in enumerated.get("actions", []) if a.get("card") == "c1"]
        for action in found:
            ids = {c.get("cost_id") for c in (action.get("cost", {}) or {}).get("additional", []) or []}
            if COST_ID not in ids:
                errors.append(f"the enumerator did not offer the printed cost the payment path charges: {ids}")

    # --- the state validator holds the offer to its shape ------------------------------------------
    bad = keeper_state()
    bad["objects"]["c1"]["optional_additional_costs"] = [{"cost_offer_id": "x", "payment": {"kind": "power", "amount": 1}}]
    if not validate_state(bad):
        errors.append("an offer naming a Domain the card does not print was accepted")
    duplicated = keeper_state(offers=2)
    duplicated["objects"]["c1"]["optional_additional_costs"][1]["cost_offer_id"] = OFFER_ID
    if not validate_state(duplicated):
        errors.append("two offers with the same cost_offer_id were accepted")

    # --- the grammar: the offer, and the clause that reads it ---------------------------------------
    grammar = cg.load_grammar()
    card = cg.compile_card([{"text": "You may pay [C] as additional cost to play me."},
                            {"text": "When you play me, if you paid additional cost, draw 1."}], grammar)
    if any(c.get("unsupported") for c in card["clauses"]):
        errors.append(f"Clockwork Keeper did not compile: {card['unsupported_clauses']}")
    else:
        predicate = card["program_effects"][0].get("predicate", {})
        if predicate.get("kind") != "cost_paid" or predicate.get("cost_offer_id") is None:
            errors.append(f"the linked clause did not read the declared offer: {predicate}")
    orphan = cg.compile_card([{"text": "When you play me, if you paid additional cost, draw 1."}], grammar)
    if orphan["clauses"][0].get("reason_code") != "cost_offer_not_declared":
        errors.append(f"a cost link with no declared offer was compiled anyway: {orphan['clauses'][0]}")
    two = cg.compile_card([{"text": "You may pay [C] as additional cost to play me."},
                           {"text": "You may pay [C] as additional cost to play me."},
                           {"text": "When you play me, if you paid additional cost, draw 1."}], grammar)
    if two["clauses"][2].get("reason_code") != "cost_offer_not_declared":
        errors.append("with two offers declared, 'the additional cost' was resolved to one of them anyway")

    if errors:
        print("FAILED: card-self optional additional cost checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("card-self optional additional cost checks passed: [C] resolves to the card's own Domain and "
          "abstains when the Domains are not observed, paying is an explicit choice, and cost_paid is bound "
          "to this card, this play and this offer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
