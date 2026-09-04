#!/usr/bin/env python3
"""
Regression gate for C-15 (ADR-0005 §4–5, §9–10) and its review fixes: the
atomic play/cost transaction, typed cost receipts, optional-cost decisions,
cost predicates, the shared chain, and the Add window.

Must hold:
  - a payable play commits: pool debited, card moved hand → shared chain_items
    with a new identity, pending chain item inserted through the timing kernel
    carrying effect_program_id, receipt valid and paid; inputs untouched;
    deterministic; the result passes validate_play_result;
  - an unpayable supported cost is `illegal` only once the Add window is
    confirmed closed (Core 429.3); before that it is `decision_required`;
    both next hashes equal the inputs;
  - a timing refusal after payment rolls the payment back (Core 358.5);
  - card not in hand → illegal; malformed declaration → invalid_input;
  - effect_program_id must bind to the supplied program's program_id;
  - optional cost without intent → decision_required naming the cost and the
    controller; intent true pays it; intent false leaves it unpaid on the
    receipt and commits; a wrong-controller intent is illegal; a wrong-stage
    intent is invalid_input;
  - an optional cost discounted to zero is still paid (356.4.f.1);
  - total discounts reduce the aggregate Energy including chosen additional
    Energy (356.4.d); component discounts first, each minimum its own
    (356.4.c–e); floor at zero (356.6); the discount order is recorded;
  - payment events are unique; two Power components never share one event's
    full amount; allocations sum to the events;
  - a kill cost prevented by a replacement effect still counts as paid
    (357.2.a); an exhaust cost on an already-exhausted unit is unpayable; a
    replacement that needs a choice during payment is unsupported;
  - a cost kind the engine does not type is `unsupported`;
  - a concrete selector illegal at play is `illegal` (355.9), as is a
    decision-supplied one; a missing target decision is `decision_required`;
    wrong stage / stale selection identity are invalid_input;
  - cost predicates read the receipt; unknown cost_id is invalid_input; other
    predicate kinds are unsupported;
  - the resolution bridge moves a resolved spell chain → trash with a new
    identity before Cleanup, and refuses a Unit on the chain as unsupported;
  - engine-check wraps play results into all five outcomes with
    `cost_choice`; the manifest lists the play component; the CLI runs
    off-cwd; a tampered result is rejected by validate_play_result.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from cost_receipt import validate_cost_receipt  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from engine_check import KIND_CONFIG, build_engine_check, validate_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, RESULT_VERSION, determine_total_cost, play_card, validate_declaration, validate_play_result  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, state_hash  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def effect_state(*, energy=3, power=None, hand=("c1",)):
    state = base_state()
    p1 = state["players"]["p1"]
    for card in hand:
        if card in p1["zones"]["main_deck"]:
            p1["zones"]["main_deck"].remove(card)
        p1["zones"]["hand"].append(card)
    p1["resources"] = {"energy": energy, "power": dict(power or {"fury": 1})}
    return state


CLOSED = {"add_window_closed": True, "confirmed_by": "human"}


def declaration(**overrides):
    # Every non-zero cost needs the human-confirmed Add window (Core 429.3);
    # pass payment_context=None to test the unconfirmed path.
    value = {
        "schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": "play-1", "actor": "p1", "card": "c1",
        "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
        "cost": {"base": {"energy": 2, "power": {"fury": 1}}},
        "payment_context": dict(CLOSED),
    }
    value.update(overrides)
    return {k: v for k, v in value.items() if v is not None}


def decisions(state, *entries):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": list(entries)}


def intent(cost_id, value, controller="p1", stage="play_declaration"):
    return {"decision_id": cost_id, "stage": stage, "kind": "optional_choice", "controller": controller, "value": value}


def comp(result, cost_id):
    return next((c for c in result.get("cost_receipt", {}).get("components", []) if c["cost_id"] == cost_id), {})


def main() -> int:
    errors: list[str] = []
    timing = fixture()  # neutral open, p1 holds priority
    state = effect_state()
    if validate_state(state):
        errors.append(f"fixture state invalid: {validate_state(state)}")

    # --- payable play commits -------------------------------------------------
    snapshot_t, snapshot_e = copy.deepcopy(timing), copy.deepcopy(state)
    prog = program("spell-1-effects", {"op": "draw", "player": "p1", "count": 1})
    ok = play_card(timing, state, declaration(effect_program_id="spell-1-effects"), effect_program=prog)
    if not ok.get("committed") or ok.get("stage") != "commit":
        errors.append(f"payable play did not commit: {ok.get('stage')} {ok.get('reason')}")
    else:
        nxt = ok["next_effect_state"]
        p1 = nxt["players"]["p1"]
        if p1["resources"] != {"energy": 1, "power": {"fury": 0}}:
            errors.append(f"pool not debited correctly: {p1['resources']}")
        if "c1" in p1["zones"]["hand"] or "chain" in p1["zones"] or nxt.get("chain_items") != {"spell-1": {"card": "c1", "controller": "p1", "effect_program_id": "spell-1-effects"}} or object_identity(nxt, "c1") != "c1@1":
            errors.append(f"card did not move hand → shared chain with a new identity: {nxt.get('chain_items')}")
        if validate_state(nxt):
            errors.append(f"next effect state invalid: {validate_state(nxt)}")
        items = ok["next_timing_state"]["chain"]["items"]
        if len(items) != 1 or items[0]["id"] != "spell-1" or items[0]["status"] != "pending" or items[0]["controller"] != "p1" or items[0].get("effect_program_id") != "spell-1-effects":
            errors.append(f"chain item not inserted as pending with its program: {items}")
        receipt = ok["cost_receipt"]
        if validate_cost_receipt(receipt) or not receipt["paid"] or receipt["total"] != {"energy": 2, "power": {"fury": 1}}:
            errors.append(f"receipt wrong: {validate_cost_receipt(receipt)} total={receipt.get('total')}")
        if [e["event_id"] for e in receipt["payment_events"]] != ["pay:energy", "pay:power:fury"]:
            errors.append(f"payment events not unique/ordered: {[e['event_id'] for e in receipt['payment_events']]}")
        if validate_play_result(ok):
            errors.append(f"committed result failed its own validator: {validate_play_result(ok)}")
    if timing != snapshot_t or state != snapshot_e:
        errors.append("play_card mutated its inputs")
    if play_card(timing, state, declaration(effect_program_id="spell-1-effects"), effect_program=prog) != ok:
        errors.append("play_card is not deterministic")

    # --- regression: effect_program_id must bind ---------------------------------------
    unbound = play_card(timing, state, declaration(), effect_program=prog)
    if unbound.get("valid") is not False or "does not bind" not in unbound.get("reason", ""):
        errors.append("a program supplied without a matching effect_program_id was accepted")

    # --- Add window (429.3): short pool → decision_required, then illegal ------------------
    poor = effect_state(energy=1)
    ask = play_card(timing, poor, declaration(payment_context=None))
    if ask.get("committed") or ask.get("reason_code") != "add_window_confirmation_required" or ask.get("decision_controller") != "p1" or ask.get("decision_ids") != ["add_window:play-1"]:
        errors.append(f"short pool without add-window confirmation was not decision_required: {ask.get('reason_code')}")
    rich_unconfirmed = play_card(timing, state, declaration(payment_context=None))
    if rich_unconfirmed.get("committed") or rich_unconfirmed.get("reason_code") != "add_window_confirmation_required":
        errors.append("a sufficient pool was paid without the Add window being confirmed closed (429.3)")
    free = play_card(timing, state, declaration(cost={"base": {"energy": 0, "power": {}}}, payment_context=None))
    if not free.get("committed"):
        errors.append(f"a zero-cost play should need no Add window: {free.get('reason_code')}")
    bad = play_card(timing, poor, declaration(payment_context=CLOSED))
    if bad.get("committed") or bad.get("reason_code") != "cost_unpayable" or bad.get("stage") != "payment":
        errors.append(f"unpayable cost with the window closed was not illegal: {bad.get('stage')} {bad.get('reason_code')}")
    for r in (ask, bad):
        if r.get("next_effect_state_hash") != hash_value(poor) or r.get("next_timing_state_hash") != state_hash(timing) or r.get("rolled_back") is not True or validate_play_result(r):
            errors.append(f"short-pool play did not roll back cleanly: {validate_play_result(r)}")
    if bad.get("trace", [{}])[-1].get("outcome") != "rolled_back":
        errors.append("rollback not recorded in the trace")

    # --- timing refusal after payment rolls back (358.5) -------------------------
    closed = fixture(priority="p2", items=[item("spell-0", "p2", "spell", "default")], passes=[])
    refused = play_card(closed, state, declaration())
    if refused.get("committed") or refused.get("stage") != "legality" or refused.get("valid") is not True:
        errors.append(f"timing refusal did not stop at legality: {refused.get('stage')} {refused.get('reason_code')}")
    if refused.get("next_effect_state_hash") != hash_value(state) or not any(t.get("stage") == "payment" for t in refused.get("trace", [])):
        errors.append("payment was not undone after the timing kernel refused the play")

    # --- card not in hand / malformed / collisions ------------------------------------
    if play_card(timing, state, declaration(card="c2")).get("reason_code") != "card_not_in_hand":
        errors.append("card not in hand was not refused")
    malformed = play_card(timing, state, declaration(cost={"base": {"energy": -1, "power": {}}}))
    if malformed.get("valid") is not False or malformed.get("reason_code") != "invalid_input" or validate_play_result(malformed):
        errors.append(f"malformed declaration was not a clean invalid_input: {validate_play_result(malformed)}")
    if not validate_declaration({**declaration(), "cost": {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "base:energy", "mandatory": True, "payment": {"kind": "energy", "amount": 1}}]}}):
        errors.append("a cost_id colliding with the base namespace was accepted")
    if not validate_declaration(declaration(cost={"base": {"energy": 1, "power": {}}, "discounts": [{"id": "x", "applies_to": "optional_additional", "amount": 1}]})):
        errors.append("an optional_additional discount without a resource was accepted")
    if play_card(timing, state, declaration(chain_item={"id": "spell-0", "object_kind": "spell", "timing": "default"}) , ).get("reason_code") == "ok":
        pass
    collide_state = copy.deepcopy(state); collide_state["chain_items"] = {"spell-1": {"card": "c2", "controller": "p1"}}
    collide_state["players"]["p1"]["zones"]["main_deck"].remove("c2")
    if play_card(timing, collide_state, declaration()).get("reason_code") != "invalid_input":
        errors.append("a chain item id already on the shared chain was accepted")

    # --- optional cost: intent decision --------------------------------------------
    optional = declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "opt-exhaust", "mandatory": False, "payment": {"kind": "exhaust", "object_id": "u1"}}]})
    missing = play_card(timing, state, optional)
    if missing.get("reason_code") != "optional_cost_intent_required" or missing.get("decision_ids") != ["opt-exhaust"] or missing.get("decision_controller") != "p1" or missing.get("stage") != "choices":
        errors.append(f"missing optional intent did not return decision_required: {missing.get('reason_code')}")
    yes = play_card(timing, state, optional, engine_decisions=decisions(state, intent("opt-exhaust", True)))
    if not yes.get("committed") or not yes["next_effect_state"]["objects"]["u1"]["exhausted"] or comp(yes, "opt-exhaust").get("paid") is not True or comp(yes, "opt-exhaust").get("intent") is not True:
        errors.append(f"optional intent true did not pay the exhaust cost: {yes.get('reason')} {comp(yes, 'opt-exhaust')}")
    no = play_card(timing, state, optional, engine_decisions=decisions(state, intent("opt-exhaust", False)))
    if not no.get("committed") or no["next_effect_state"]["objects"]["u1"]["exhausted"] or comp(no, "opt-exhaust").get("paid") is not False or comp(no, "opt-exhaust").get("intent") is not False or no["cost_receipt"]["paid"] is not True:
        errors.append(f"optional intent false did not commit with the cost unpaid on the receipt: {no.get('reason')} {comp(no, 'opt-exhaust')}")
    wrong_owner = play_card(timing, state, optional, engine_decisions=decisions(state, intent("opt-exhaust", True, controller="p2")))
    if wrong_owner.get("valid") is not True or wrong_owner.get("committed") or wrong_owner.get("reason_code") != "decision_controller_mismatch":
        errors.append("an opponent's intent decision was not illegal")
    wrong_stage = play_card(timing, state, optional, engine_decisions=decisions(state, intent("opt-exhaust", True, stage="resolution")))
    if wrong_stage.get("valid") is not False:
        errors.append("a resolution-stage intent was accepted at play")
    if play_card(timing, state, optional, engine_decisions=decisions(poor, intent("opt-exhaust", True))).get("valid") is not False:
        errors.append("a decision envelope for another state was accepted")

    # --- optional cost discounted to zero is still paid (356.4.f.1) -----------------
    keeper = declaration(cost={"base": {"energy": 2, "power": {}},
                               "additional": [{"cost_id": "keeper", "mandatory": False, "payment": {"kind": "energy", "amount": 1}}],
                               "discounts": [{"id": "units-cost-less", "applies_to": "optional_additional", "resource": "energy", "amount": 1}]})
    two = effect_state(energy=2, power={})
    paid_zero = play_card(timing, two, keeper, engine_decisions=decisions(two, intent("keeper", True)))
    k = comp(paid_zero, "keeper")
    if not paid_zero.get("committed") or k.get("final") != 0 or k.get("paid") is not True or k.get("payment_refs") != [] or paid_zero["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
        errors.append(f"optional cost reduced to 0 was not 'paid' by decision: {k} {paid_zero.get('reason')}")

    # --- regression: total discount on the aggregate Energy (356.4.d) --------------------
    agg = declaration(cost={"base": {"energy": 2, "power": {}},
                            "additional": [{"cost_id": "extra", "mandatory": False, "payment": {"kind": "energy", "amount": 2}}],
                            "discounts": [{"id": "cost-less", "applies_to": "total", "amount": 3}]})
    one = effect_state(energy=1, power={})
    aggregated = play_card(timing, one, agg, engine_decisions=decisions(one, intent("extra", True)))
    rec = aggregated.get("cost_receipt", {})
    if not aggregated.get("committed") or rec.get("total", {}).get("energy") != 1 or rec.get("aggregate", {}).get("energy", {}).get("before_total_discounts") != 4 or aggregated["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
        errors.append(f"total discount did not reduce the aggregate Energy including the chosen additional cost: {aggregated.get('reason')} {rec.get('aggregate')}")
    elif sum(r["amount"] for c in rec["components"] for r in c["payment_refs"]) != 1 or [o["id"] for o in rec["discount_order"]] != ["cost-less"]:
        errors.append(f"aggregate payment allocation or discount order wrong: {rec['components']} {rec['discount_order']}")

    # --- discount ordering and minimums (356.4.c–e), floor (356.6) -----------------
    sky = {"base": {"energy": 8, "power": {}},
           "discounts": [{"id": "eager-apprentice", "applies_to": "energy", "amount": 1, "minimum": 1}, {"id": "sky-splitter", "applies_to": "total", "amount": 7}]}
    skel = determine_total_cost(sky, {})
    if skel["total"]["energy"] != 0 or [o["id"] for o in skel["discount_order"]] != ["eager-apprentice", "sky-splitter"]:
        errors.append(f"component-before-total order or minimum wrong: {skel['total']} {skel['discount_order']}")
    reversed_skel = determine_total_cost({"base": {"energy": 8, "power": {}}, "discounts": [{"id": "sky-splitter", "applies_to": "energy", "amount": 7}, {"id": "eager-apprentice", "applies_to": "energy", "amount": 1, "minimum": 1}]}, {})
    if reversed_skel["total"]["energy"] != 1:
        errors.append("a discount's minimum did not apply to that discount alone (356.4.e)")
    if determine_total_cost({"base": {"energy": 2, "power": {}}, "discounts": [{"id": "big", "applies_to": "total", "amount": 5}]}, {})["total"]["energy"] != 0:
        errors.append("energy cost went below zero (356.6)")
    ignore = determine_total_cost({"base": {"energy": 2, "power": {"fury": 1}}, "base_modifications": [{"kind": "ignore_all"}],
                                   "additional": [{"cost_id": "acc", "mandatory": False, "payment": {"kind": "energy", "amount": 1}}]}, {"acc": True})
    if ignore["total"] != {"energy": 1, "power": {}}:
        errors.append(f"ignoring base costs must leave a chosen additional cost payable (356.1.b.3): {ignore['total']}")

    # --- regression: unique power payment events with exact allocation ------------------
    dual = effect_state(energy=1, power={"fury": 1, "calm": 2})
    dual_play = play_card(timing, dual, declaration(cost={"base": {"energy": 1, "power": {"fury": 1, "calm": 1}},
                                                          "additional": [{"cost_id": "more-calm", "mandatory": True, "payment": {"kind": "power", "domain": "calm", "amount": 1}}]}))
    rec = dual_play.get("cost_receipt", {})
    ev_ids = [e["event_id"] for e in rec.get("payment_events", [])]
    if not dual_play.get("committed") or ev_ids != ["pay:energy", "pay:power:calm", "pay:power:fury"]:
        errors.append(f"power payment events are not one per domain: {ev_ids} {dual_play.get('reason')}")
    else:
        calm_refs = [(c["cost_id"], r["amount"]) for c in rec["components"] for r in c["payment_refs"] if r["event_id"] == "pay:power:calm"]
        if calm_refs != [("base:power:calm", 1), ("more-calm", 1)]:
            errors.append(f"calm event not allocated exactly across its two components: {calm_refs}")

    # --- non-standard costs: replacement still paid; exhausted unit unpayable; choice → unsupported
    guarded = effect_state(energy=2, power={})
    guarded["replacement_effects"] = [{"replacement_id": "guard", "controller": "p1", "source_object": "u1", "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"}]
    kill_cost = declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "sacrifice", "mandatory": True, "payment": {"kind": "kill", "object_id": "u1"}}]})
    replaced = play_card(timing, guarded, kill_cost)
    c = comp(replaced, "sacrifice")
    if not replaced.get("committed") or c.get("paid") is not True or "u1" not in replaced["next_effect_state"]["players"]["p1"]["zones"]["base"] or "Core 357.2.a" not in c.get("rule_locators", []):
        errors.append(f"a prevented kill cost was not treated as paid (357.2.a): {replaced.get('reason')} {c}")
    plain_kill = play_card(timing, effect_state(energy=2, power={}), kill_cost)
    if not plain_kill.get("committed") or "u1" not in plain_kill["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append("a mandatory kill cost did not kill the unit")
    optional_guard = copy.deepcopy(guarded); optional_guard["replacement_effects"][0]["optional"] = True
    choice = play_card(timing, optional_guard, kill_cost)
    if choice.get("committed") or choice.get("unsupported") is not True or choice.get("reason_code") != "payment_replacement_decision_not_modelled" or validate_play_result(choice):
        errors.append(f"a replacement choice during payment was not unsupported: {choice.get('reason_code')} {validate_play_result(choice)}")
    tired = effect_state(energy=2, power={}); tired["objects"]["u1"]["exhausted"] = True
    unpayable = play_card(timing, tired, declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "tap", "mandatory": True, "payment": {"kind": "exhaust", "object_id": "u1"}}]}))
    if unpayable.get("committed") or unpayable.get("reason_code") != "cost_unpayable" or unpayable.get("next_effect_state_hash") != hash_value(tired):
        errors.append(f"exhausting an exhausted unit was accepted as payment: {unpayable.get('reason_code')}")
    if play_card(timing, effect_state(energy=2, power={}), declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "tap", "mandatory": True, "payment": {"kind": "exhaust", "object_id": "u2"}}]})).get("reason_code") != "cost_unpayable":
        errors.append("exhausting an enemy unit was accepted as a cost")

    # --- unknown cost mechanic → unsupported ------------------------------------------
    discard = play_card(timing, state, declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "d", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]}))
    if discard.get("unsupported") is not True or discard.get("reason_code") != "unsupported_cost_kind" or validate_play_result(discard):
        errors.append(f"discard cost was not unsupported: {discard.get('reason_code')}")
    if not play_card(timing, state, declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "d", "mandatory": False, "payment": {"kind": "discard", "amount": 1}}]}), engine_decisions=decisions(state, intent("d", False))).get("committed"):
        errors.append("declining an optional cost of an unknown kind must not block the play")

    # --- targets at play (355.5 / 355.9): decision-supplied and concrete ---------------------
    tprog = program("spell-1-effects", {"op": "deal_damage", "amount": 1, "target": {"decision_ref": "t", "chosen_zone_class": "board", "controller_relation": "enemy"}})
    tdecl = declaration(effect_program_id="spell-1-effects")
    no_target = play_card(timing, state, tdecl, effect_program=tprog)
    if no_target.get("reason_code") != "target_selection_required" or no_target.get("decision_ids") != ["t"]:
        errors.append(f"missing play-time target was not decision_required: {no_target.get('reason_code')}")
    sel = lambda ids, **kw: {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ids, "selection_identities": {i: f"{i}@0" for i in ids}, **kw}
    illegal_target = play_card(timing, state, tdecl, effect_program=tprog, engine_decisions=decisions(state, sel(["u1"])))
    if illegal_target.get("reason_code") != "target_illegal_at_play" or illegal_target.get("stage") != "choices" or illegal_target.get("valid") is not True:
        errors.append(f"illegal decision-supplied target at play was not illegal: {illegal_target.get('reason_code')}")
    if not play_card(timing, state, tdecl, effect_program=tprog, engine_decisions=decisions(state, sel(["u2"]))).get("committed"):
        errors.append("legal play-time target blocked the play")
    stale_id = play_card(timing, state, tdecl, effect_program=tprog, engine_decisions=decisions(state, {**sel(["u2"]), "selection_identities": {"u2": "u2@7"}}))
    if stale_id.get("valid") is not False or stale_id.get("reason_code") != "invalid_input":
        errors.append("a selection bound to a stale identity was accepted")
    wrong_stage_sel = play_card(timing, state, tdecl, effect_program=tprog, engine_decisions=decisions(state, {**sel(["u2"]), "stage": "trigger_finalization"}))
    if wrong_stage_sel.get("valid") is not False:
        errors.append("a trigger-stage target selection was accepted for a play")
    concrete = program("spell-1-effects", {"op": "deal_damage", "amount": 1, "object_id": "u1", "target": {"object_id": "u1", "chosen_zone_class": "board", "controller_relation": "enemy"}})
    concrete_illegal = play_card(timing, state, tdecl, effect_program=concrete)
    if concrete_illegal.get("reason_code") != "target_illegal_at_play":
        errors.append(f"regression: a concrete selector illegal at play was not refused (355.9): {concrete_illegal.get('reason_code')}")
    concrete_ok = program("spell-1-effects", {"op": "deal_damage", "amount": 1, "object_id": "u2", "target": {"object_id": "u2", "chosen_zone_class": "board", "controller_relation": "enemy"}})
    if not play_card(timing, state, tdecl, effect_program=concrete_ok).get("committed"):
        errors.append("a legal concrete selector blocked the play")

    # --- cost predicates on the receipt ------------------------------------------------
    if not (yes.get("committed") and no.get("committed")):
        print("FAILED: play transaction checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors + ["optional-cost plays did not commit; predicate checks skipped"]))
        return 1
    receipt_yes, receipt_no = yes["cost_receipt"], no["cost_receipt"]
    after_yes, after_no = yes["next_effect_state"], no["next_effect_state"]
    gated = {**program("keeper-effects", {"op": "draw", "player": "p1", "count": 1, "predicate": {"kind": "cost_paid", "cost_id": "opt-exhaust"}}), "cost_receipt": receipt_yes}
    drew = apply_program(after_yes, gated)
    if not drew.get("committed") or drew["trace"][0].get("outcome") != "applied" or len(drew["next_state"]["players"]["p1"]["zones"]["hand"]) != 1:
        errors.append(f"cost_paid predicate did not let the draw through: {drew.get('reason') or drew.get('errors')}")
    skipped = apply_program(after_no, {**gated, "cost_receipt": receipt_no})
    ev = skipped["trace"][0] if skipped.get("committed") else {}
    if ev.get("outcome") != "skipped_linked_dependency" or ev.get("predicate", {}).get("kind") != "cost_paid" or ev.get("completion") != "none":
        errors.append(f"cost_paid predicate on an unpaid cost did not skip: {ev}")
    otherwise = apply_program(after_no, {**program("keeper-otherwise", {"op": "draw", "player": "p1", "count": 1, "predicate": {"kind": "cost_not_paid", "cost_id": "opt-exhaust"}}), "cost_receipt": receipt_no})
    if not otherwise.get("committed") or otherwise["trace"][0].get("outcome") != "applied":
        errors.append("cost_not_paid predicate did not fire on a declined cost")
    if not any("not on the receipt" in e for e in validate_program({**gated, "effects": [{**gated["effects"][0], "predicate": {"kind": "cost_paid", "cost_id": "nope"}}]})):
        errors.append("unknown predicate cost_id was not invalid_input")
    if not any("cost_receipt" in e for e in validate_program({k: v for k, v in gated.items() if k != "cost_receipt"})):
        errors.append("a cost predicate without a receipt was accepted")
    tampered = copy.deepcopy(receipt_yes); tampered["components"][0]["payment_refs"] = []
    if not any("allocates" in e for e in validate_program({**gated, "cost_receipt": tampered})):
        errors.append("a receipt whose allocations do not sum to its events was accepted")
    later = apply_program(after_yes, {**program("mobilize", {"op": "deal_damage", "object_id": "u2", "amount": 1, "effect_id": "x"}, {"op": "draw", "player": "p1", "count": 1, "predicate": {"kind": "caused_kill", "effect_id": "x"}}), "cost_receipt": receipt_yes})
    if later.get("committed") or later.get("unsupported") is not True:
        errors.append("a recognized-but-unimplemented predicate kind was not unsupported")

    # --- resolution: spell leaves the chain for the trash before Cleanup ----------------------
    res_prog = {**program("spell-1-effects", {"op": "draw", "player": "p1", "count": 1}), "cost_receipt": ok["cost_receipt"]}
    res_timing = copy.deepcopy(ok["next_timing_state"])
    res_timing["chain"]["items"][0]["status"] = "finalized"; res_timing["priority"] = "p2"; res_timing["chain"]["consecutive_passes"] = ["p1", "p2"]
    resolved = resolve_with_program(res_timing, "spell-1", ok["next_effect_state"], res_prog)
    if not resolved.get("committed"):
        errors.append(f"spell resolution from the shared chain did not commit: {resolved.get('stage')} {resolved.get('reason')}")
    else:
        fin = resolved["next_effect_state"]
        if "chain_items" in fin or "c1" not in fin["players"]["p1"]["zones"]["trash"] or object_identity(fin, "c1") != "c1@2" or resolved["trace"].get("chain_card", [{}])[0].get("destination") != "p1.trash":
            errors.append(f"resolved spell did not go chain → trash with a new identity: {fin.get('chain_items')} {resolved['trace'].get('chain_card')}")
    unit_state = copy.deepcopy(ok["next_effect_state"]); unit_state["objects"]["c1"]["kind"] = "unit"
    unit_res = resolve_with_program(res_timing, "spell-1", unit_state, res_prog)
    # C-19: a unit on the chain now enters by the entry procedure; one without
    # the entry_location chosen at play (355.2) is malformed, not a spell.
    if unit_res.get("committed") or unit_res.get("valid") is not False or unit_res.get("stage") != "permanent_entry":
        errors.append(f"a unit chain entry without entry_location resolved or was not invalid_input: {unit_res.get('stage')} {unit_res.get('reason')}")

    # --- engine-check wrapping, manifest scope, result validator -----------------------------
    hashes = {"timing_state": state_hash(timing), "effect_state": hash_value(state), "play_declaration": "sha256:" + "0" * 64}
    for outcome, result in {"supported": ok, "illegal": bad, "unsupported": discard, "decision_required": missing, "invalid_input": malformed}.items():
        check = build_engine_check("play", result, input_hashes=hashes)
        if validate_engine_check(check) or check["outcome"] != outcome or check["component"]["version"] != RESULT_VERSION:
            errors.append(f"engine-check for {outcome} came out as {check['outcome']}")
        if outcome == "decision_required" and (check["decision_required"]["kind"] != "cost_choice" or check["decision_required"]["decision_ids"] != ["opt-exhaust"]):
            errors.append(f"cost decision did not wrap as cost_choice: {check['decision_required']}")
    ask_check = build_engine_check("play", ask, input_hashes=hashes)
    if ask_check["outcome"] != "decision_required" or ask_check["decision_required"]["kind"] != "cost_choice" or ask_check["decision_required"]["controller"] != "p1":
        errors.append("add-window confirmation did not wrap as a cost_choice decision")
    if "play" not in KIND_CONFIG or "payment_stage_replacement_decisions" not in KIND_CONFIG["play"]["unsupported"]:
        errors.append("KIND_CONFIG play scope is missing the declared exclusions")
    manifest = json.loads((SKILL_DIR / "data" / "engine_capability_manifest" / "manifest.json").read_text(encoding="utf-8"))
    if not any(c.get("check_kind") == "play" for c in manifest.get("components", [])):
        errors.append("committed capability manifest does not list the play component; rebuild it")
    forged = copy.deepcopy(ok); del forged["cost_receipt"]
    if not validate_play_result(forged):
        errors.append("a committed result without a receipt passed validation")
    forged2 = copy.deepcopy(bad); forged2["next_effect_state_hash"] = hash_value(state)
    if not any("358.5" in e for e in validate_play_result(forged2)):
        errors.append("an uncommitted result pointing at a different state passed validation")

    # --- CLI off-cwd ---------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="play-transaction-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(timing), encoding="utf-8")
        (temp / "e.json").write_text(json.dumps(state), encoding="utf-8")
        (temp / "d.json").write_text(json.dumps(optional), encoding="utf-8")
        (temp / "x.json").write_text(json.dumps(decisions(state, intent("opt-exhaust", True))), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "play", str(temp / "t.json"), str(temp / "e.json"), str(temp / "d.json"), "--decisions", str(temp / "x.json"), "--output", str(temp / "out.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0:
            errors.append(f"engine_check play failed off-cwd: {run.stderr.strip()}")
        else:
            written = json.loads((temp / "out.json").read_text(encoding="utf-8"))
            if written["outcome"] != "supported" or "engine_decisions" not in written["input_hashes"] or "play_declaration" not in written["input_hashes"]:
                errors.append(f"CLI play produced {written['outcome']} / {sorted(written['input_hashes'])}")
        run2 = subprocess.run([sys.executable, str(RUNNER), "play", str(temp / "t.json"), str(temp / "e.json"), str(temp / "d.json"), "--output", str(temp / "out2.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run2.returncode != 0 or json.loads((temp / "out2.json").read_text(encoding="utf-8"))["outcome"] != "decision_required":
            errors.append("CLI play without the intent decision did not report decision_required")
        run3 = subprocess.run([sys.executable, str(SCRIPT_DIR / "play_transaction.py"), str(temp / "t.json"), str(temp / "e.json"), str(temp / "d.json"), "--decisions", str(temp / "x.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run3.returncode != 0 or json.loads(run3.stdout).get("committed") is not True:
            errors.append(f"play_transaction.py CLI failed off-cwd: {run3.stderr.strip()}")

    if errors:
        print("FAILED: play transaction checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: the play transaction commits or restores the pre-play state whole (Core 358.5); costs are typed in Core 356/357 order with total discounts on the aggregate Energy and per-discount minimums; payment events are unique with exact allocations; an optional cost is paid by decision even at zero (356.4.f.1) and a replaced payment is paid (357.2.a); a short pool waits for the Add window (429.3) before it is illegal; every play-time target is checked (355.9); the played card sits on the shared chain and a resolved spell goes chain → trash before Cleanup; cost_paid / cost_not_paid read the validated receipt; it wraps as engine-check kind play and runs off-cwd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
