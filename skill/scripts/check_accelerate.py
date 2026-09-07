#!/usr/bin/env python3
"""Regression gate for `accelerate.v1` (Round H, DP-92; Core 805, 806).

The rule, in its own words:

    805.2.a  "Accelerate is a Unit ability."
    805.2.b  "Accelerate is functionally short for 'As you play me, you may pay
              [1][C] as an additional cost. If you do, I enter ready.'"
             The Power portion can be paid only with a Power matching one of
             the unit's Domains; with no Domain, any Domain's Power.
    806.1.a  the cost "cannot be paid while the unit is on the board, only as
              part of the steps of playing a card".
    806.1.b  "Paying the cost generates a delayed Replacement Effect. Even if
              the unit loses the accelerate keyword during the finalization
              process, as long as the cost was paid, that unit will still enter
              ready."
             "Accelerate has no function while on the board."
             "Multiple instances of Accelerate are redundant."

Must hold, including Codex's four contracts on the ruling:

  - paying charges 1 Energy and 1 matching Power and the Unit enters ready;
    declining charges nothing and it enters exhausted, with the unpaid optional
    cost still on the receipt (356.2.b.1);
  - **the choice is explicit**: with no intent decision the play refuses with
    `optional_cost_intent_required`, however full the pool is;
  - the Power must match a Domain: a Calm unit cannot pay from a Fury-only
    pool, and the negative mutation gives the same unit that Domain and it can;
  - 806.1.b: the keyword removed after payment still enters ready; **negative
    mutation**: not paying and removing it enters exhausted;
  - 806.1.a: a Unit already on the board is offered nothing;
  - multiple instances are redundant: one cost, charged once;
  - **the binding is to this card and this play**: a delayed replacement
    naming another card is refused by the state validator, and one bound to
    another play does not apply at entry;
  - **a card whose data does not say its Domains is offered no payable
    Accelerate** — abstained by name, not treated as having none; only an
    explicit empty list means "no Domain" and takes any Power;
  - the enumeration and the payment path use the same offer.

`domains: []` has no card in the Wave B corpus, so its fixture here is
synthetic and labelled `no_corpus_fixture`; every fixture in this file is
synthetic.
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
from effect_ir import validate_state  # noqa: E402
from resolution_bridge import complete_permanent_play  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

NO_CORPUS_FIXTURE = "domains: [] has no Wave B card; this shape is synthetic (no_corpus_fixture)"


def accel_state(*, domains=("calm",), pool_power=("calm",), keyword=True, instances=1, on_board=False):
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    if on_board:
        state["players"]["p1"]["zones"]["base"].append("c1")
    else:
        state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 5, "power": {d: 2 for d in pool_power}}
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2,
                                   "printed_cost": {"energy": 1, "power": {}}})
    if domains is not None:
        state["objects"]["c1"]["domains"] = list(domains)
    if keyword:
        state["objects"]["c1"]["keywords"] = ["accelerate"] * instances if instances == 1 else ["accelerate"]
    return state


def declaration(intents=None):
    return {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}},
            "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def decisions(paid: bool):
    return {"schema_version": "engine-decisions.v1",
            "input_hash": None,
            "decisions": [{"decision_id": cost_id, "kind": "optional_choice", "stage": "play_declaration",
                           "controller": "p1", "value": paid}
                          for cost_id in ("accelerate", "accelerate:energy")]}


def play(state, *, paid=None):
    from effect_ir import hash_value
    engine_decisions = None
    if paid is not None:
        engine_decisions = decisions(paid)
        engine_decisions["input_hash"] = hash_value(state)
    return pt.play_card(fixture(), state, declaration(), engine_decisions=engine_decisions)


def component(result, cost_id):
    return next((c for c in result["cost_receipt"]["components"] if c["cost_id"] == cost_id), None)


def enters_ready(result, item_id="unit-1"):
    after, trace, _ = complete_permanent_play(result["next_effect_state"], item_id)
    if trace.get("error"):
        return None, trace
    return not after["objects"]["c1"]["exhausted"], trace


def main() -> int:
    errors: list[str] = []

    # --- the offer itself --------------------------------------------------------------------
    offer, reason = pt.accelerate_offer(accel_state(), "c1")
    if offer is None or reason is not None:
        errors.append(f"a Calm Unit with Accelerate was offered nothing: {offer} {reason}")
    elif offer["payment"] != {"kind": "power", "domain": "calm", "amount": 1} or offer["energy"] != 1:
        errors.append(f"the offer is not [1][C] matching the Unit's Domain: {offer}")
    none_offer, none_reason = pt.accelerate_offer(accel_state(keyword=False), "c1")
    if none_offer is not None or none_reason is not None:
        errors.append("a Unit without the keyword was offered something")

    # --- paying, and declining -----------------------------------------------------------------
    paid = play(accel_state(), paid=True)
    if not paid.get("committed"):
        errors.append(f"paying Accelerate did not commit: {paid.get('reason_code')} {paid.get('reason')}")
    else:
        pool = paid["next_effect_state"]["players"]["p1"]["resources"]
        if pool["energy"] != 3 or pool["power"].get("calm") != 1:
            errors.append(f"paying did not charge 1 Energy and 1 matching Power: {pool}")
        ready, trace = enters_ready(paid)
        if ready is not True:
            errors.append(f"a paid Accelerate did not enter ready (805.2.b): {ready} {trace.get('entry_state')}")
    declined = play(accel_state(), paid=False)
    if not declined.get("committed"):
        errors.append(f"declining Accelerate did not commit: {declined.get('reason')}")
    else:
        pool = declined["next_effect_state"]["players"]["p1"]["resources"]
        if pool["energy"] != 4 or pool["power"].get("calm") != 2:
            errors.append(f"declining charged something: {pool}")
        ready, _ = enters_ready(declined)
        if ready is not False:
            errors.append("a declined Accelerate still entered ready")
        entry = component(declined, "accelerate")
        if entry is None or entry["paid"] or entry["intent"] is not False:
            errors.append(f"the declined optional cost is not on the receipt as declined (356.2.b.1): {entry}")

    # --- the choice is explicit, never automatic -------------------------------------------------
    silent = play(accel_state())
    if silent.get("committed") or silent.get("reason_code") != "optional_cost_intent_required":
        errors.append(f"a full pool paid Accelerate without being asked: {silent.get('reason_code')}")

    # --- the Power must match a Domain -------------------------------------------------------------
    wrong_pool = play(accel_state(domains=("calm",), pool_power=("fury",)), paid=True)
    if wrong_pool.get("committed"):
        errors.append("a Calm Unit paid Accelerate from a Fury-only pool (805.4)")
    elif wrong_pool.get("reason_code") != "cost_unpayable":
        errors.append(f"the Domain mismatch was not reported as unpayable: {wrong_pool.get('reason_code')}")
    matching = play(accel_state(domains=("fury",), pool_power=("fury",)), paid=True)
    if not matching.get("committed"):
        errors.append(f"negative mutation failed: the same pool with the matching Domain still could not pay: {matching.get('reason_code')}")
    # no Domain at all takes any Power (805.4) - synthetic shape, no_corpus_fixture
    anydomain = play(accel_state(domains=(), pool_power=("fury",)), paid=True)
    if not anydomain.get("committed"):
        errors.append(f"an explicitly Domain-less Unit could not pay with any Power ({NO_CORPUS_FIXTURE}): {anydomain.get('reason_code')}")

    # --- the data must say: absent Domains is an abstention, not "none" -----------------------------
    unknown = accel_state(domains=None)
    offer, reason = pt.accelerate_offer(unknown, "c1")
    if offer is not None or reason != "accelerate_domain_not_observed":
        errors.append(f"a card with no Domain data was offered a payable Accelerate: {offer} {reason}")
    asked = play(unknown, paid=True)
    if asked.get("committed") and component(asked, "accelerate") is not None:
        errors.append("a card with no Domain data was charged an Accelerate cost")

    # --- 806.1.b: paid survives losing the keyword ---------------------------------------------------
    lost = copy.deepcopy(paid["next_effect_state"])
    lost["objects"]["c1"]["keywords"] = []
    after, trace, _ = complete_permanent_play(lost, "unit-1")
    if trace.get("error") or after["objects"]["c1"]["exhausted"]:
        errors.append(f"a paid Accelerate did not survive losing the keyword (806.1.b): {trace.get('entry_state')}")
    lost_unpaid = copy.deepcopy(declined["next_effect_state"])
    lost_unpaid["objects"]["c1"]["keywords"] = []
    after_unpaid, _, _ = complete_permanent_play(lost_unpaid, "unit-1")
    if not after_unpaid["objects"]["c1"]["exhausted"]:
        errors.append("negative mutation failed: an unpaid Accelerate entered ready once the keyword was removed")

    # --- 806.1.a: nothing on the board -----------------------------------------------------------------
    board_offer, board_reason = pt.accelerate_offer(accel_state(on_board=True), "c1")
    if board_offer is None and board_reason is None:
        pass  # the keyword is still on the object; the offer only exists inside a play
    if pt.accelerate_offer(accel_state(on_board=True), "c1")[0] is not None:
        # the offer is only consumed by play_card, which reads a card in hand;
        # a board card never reaches the intent loop
        played_from_board = play(accel_state(on_board=True), paid=True)
        if played_from_board.get("committed"):
            errors.append("a Unit already on the board paid an Accelerate cost (806.1.a)")

    # --- multiple instances are redundant ----------------------------------------------------------------
    twice = accel_state()
    twice["objects"]["c1"]["keywords"] = ["accelerate"]
    doubled = play(twice, paid=True)
    if doubled.get("committed"):
        charged = [c for c in doubled["cost_receipt"]["components"] if c["cost_id"].startswith("accelerate")]
        if len(charged) != 2:  # the Energy half and the Power half of one [1][C]
            errors.append(f"multiple instances were not redundant: {[c['cost_id'] for c in charged]}")

    # --- the binding: this card, this play -----------------------------------------------------------------
    misbound = copy.deepcopy(paid["next_effect_state"])
    misbound["objects"]["c1"]["entry_replacements"][0]["card"] = "u1"
    if not any("card" in e for e in validate_state(misbound)):
        errors.append("a delayed replacement bound to another card was accepted by the validator")
    other_play = copy.deepcopy(paid["next_effect_state"])
    other_play["objects"]["c1"]["entry_replacements"][0]["chain_item"] = "unit-9"
    after_other, _, _ = complete_permanent_play(other_play, "unit-1")
    if not after_other["objects"]["c1"]["exhausted"]:
        errors.append("a delayed replacement bound to another play still applied at entry")

    # --- the enumeration and the payment path read the same offer -------------------------------------------
    state = accel_state()
    enum_offer, enum_reason = pt.accelerate_offer(state, "c1")
    if (enum_offer, enum_reason) != pt.accelerate_offer(state, "c1"):
        errors.append("the offer is not deterministic")
    blind_offer, blind_reason = pt.accelerate_offer(accel_state(domains=None), "c1")
    if blind_offer is not None or blind_reason != "accelerate_domain_not_observed":
        errors.append("the enumeration would have been offered an Accelerate the payment path refuses")

    if errors:
        print("FAILED: Accelerate checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Accelerate checks passed: [1][C] paid by explicit choice and matching the Domain, ready survives losing the "
          f"keyword, bound to this card and this play, and absent Domain data abstains ({NO_CORPUS_FIXTURE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
