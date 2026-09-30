#!/usr/bin/env python3
"""Regression gate for a card's printed NON-RESOURCE additional costs (package 6, 2026-09-27).

Core 356.2.a.1 and 356.7 use "As an additional cost to play me, kill a friendly unit." as their
example of a mandatory additional cost; 356.2.b.1 uses "As you play me, you may discard 1 as an
additional cost. If you do, reduce my cost by [2]." as its example of an optional one. The card
prints them (objects.printed_additional_costs) and, for an optional one, what paying it switches on
(objects.offer_linked_cost_modifications). The play transaction pays them with its own cost
machinery: the Unit or card that pays is the payer's choice as the card is played (355.1.a;
357.2.a's own example chooses the unit before the cost is paid), a cost that cannot be paid stops
the play (203.3, 358.5), and a linked modification applies only when the offer was chosen.

Must hold (each has a failing case below):
  mandatory kill    one friendly Unit dies as the cost; one candidate is used, two need a choice;
                    an enemy Unit, a wrong stage, the wrong chooser or a stale identity is refused;
                    no friendly Unit on the board: the play is refused and nothing moved
  optional discard  paying it is an explicit choice (undecided: asked); paid: the chosen card is
                    discarded and the Energy cost is reduced; declined: full cost, the component on
                    the receipt unpaid; paid with no other card in hand: refused; a later
                    "If you do, draw N" reads that decision (356.4.f.1) and nothing else
  spend a buff      paid: the buff is gone and the base cost is ignored (356.1.b.1); an enemy's
                    buffed Unit cannot pay (702.2.b.2); no buffed Unit: refused
  any number        each chosen Unit is killed and the Power cost falls by one per Unit, never
                    below 0 (356.6); a "paid" offer naming none is refused
  shapes            validate_state holds the fields to their contract
  enumerator        a play whose mandatory cost nothing can pay is not offered; a card affordable
                    only with its own discount still is
  grammar           the two productions and the linked clauses lower to these fields; near misses
                    do not
Every fixture is synthetic.
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
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

KILL = {"printed_additional_costs": [{"cost_offer_id": "k", "mandatory": True, "payment": {"kind": "kill", "amount": 1}}]}
DISCARD = {"printed_additional_costs": [{"cost_offer_id": "d", "mandatory": False, "payment": {"kind": "discard", "amount": 1}}],
           "offer_linked_cost_modifications": [{"cost_offer_id": "d", "kind": "energy_reduction", "amount": 2}]}
BUFF = {"printed_additional_costs": [{"cost_offer_id": "b", "mandatory": False, "payment": {"kind": "spend_buff", "amount": 1}}],
        "offer_linked_cost_modifications": [{"cost_offer_id": "b", "kind": "ignore_base_cost"}]}
MANY = {"printed_additional_costs": [{"cost_offer_id": "m", "mandatory": False, "payment": {"kind": "kill", "any_number": True}}],
        "offer_linked_cost_modifications": [{"cost_offer_id": "m", "kind": "power_reduction_per_paid", "domain": "order", "amount": 1}]}


def unit(owner, *, exhausted=False, buffed=False, might=2):
    obj = {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
           "exhausted": exhausted}
    if buffed:
        obj["buffed"] = True
    return obj


def state(fields, *, kind="unit", energy=6, power=None, printed=(6, None), extra_units=(), hand_extra=True):
    s = base_state()
    s["turn_id"] = "turn-3"
    zones = s["players"]["p1"]["zones"]
    zones["main_deck"].remove("c1")
    zones["hand"].append("c1")
    if hand_extra:
        zones["main_deck"].remove("c2")
        zones["hand"].append("c2")
    s["players"]["p1"]["resources"] = {"energy": energy, "power": dict(power or {})}
    s["objects"]["c1"].update({"kind": kind, "base_might": 5 if kind == "unit" else 0,
                               "printed_cost": {"energy": printed[0], "power": dict(printed[1] or {})},
                               "domains": ["order"], **copy.deepcopy(fields)})
    for object_id, owner, where, extra in extra_units:
        s["objects"][object_id] = unit(owner, **extra)
        if where == "base":
            s["players"][owner]["zones"]["base"].append(object_id)
        else:
            s["battlefields"][where]["objects"].append(object_id)
    return s


def declaration(*, kind="unit", printed=(6, None)):
    out = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
           "play_id": "play-1", "actor": "p1", "card": "c1",
           "chain_item": {"id": "item-1", "object_kind": kind, "timing": "default"},
           "cost": {"base": {"energy": printed[0], "power": dict(printed[1] or {})}},
           "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if kind == "unit":
        out["entry_location"] = {"kind": "base"}
    return out


def decisions(s, *entries):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": list(entries)}


def intent(cost_id, value, *, controller="p1", stage="play_declaration"):
    return {"decision_id": cost_id, "kind": "optional_choice", "stage": stage, "controller": controller, "value": value}


def pick(s, cost_id, objects, *, controller="p1", stage="play_declaration", identities=None):
    return {"decision_id": f"cost:play-1:{cost_id}", "kind": "card_selection", "stage": stage, "controller": controller,
            "value": list(objects), "selection_identities": identities or {o: object_identity(s, o) for o in objects}}


def play(s, *, kind="unit", printed=(6, None), with_decisions=None):
    return pt.play_card(fixture(), s, declaration(kind=kind, printed=printed), engine_decisions=with_decisions)


def where(s, object_id):
    for player, data in s["players"].items():
        for zone, items in data["zones"].items():
            if object_id in items:
                return f"{player}:{zone}"
    for bf, data in s["battlefields"].items():
        if object_id in data.get("objects", []):
            return f"battlefield:{bf}"
    return None


def component(result, cost_id):
    return next((c for c in (result.get("cost_receipt") or {}).get("components", []) if c["cost_id"] == cost_id), None)


def main() -> int:
    errors: list[str] = []

    # --- mandatory: "kill a friendly unit" ------------------------------------------------------------
    s = state(KILL, energy=6, printed=(4, None))
    sole = play(s, printed=(4, None))
    if not sole.get("committed"):
        errors.append(f"the one friendly unit did not pay the mandatory kill: {sole.get('reason_code')} {sole.get('reason')}")
    else:
        after = sole["next_effect_state"]
        if where(after, "u1") != "p1:trash" or where(after, "u2") != "p2:base":
            errors.append(f"the mandatory kill did not kill exactly the friendly unit: u1 {where(after, 'u1')}, u2 {where(after, 'u2')}")
        if after["players"]["p1"]["resources"]["energy"] != 2:
            errors.append("the mandatory cost changed the Energy paid")
        paid = component(sole, "self_cost:k")
        if not paid or not paid["paid"] or paid["object_id"] != "u1" or paid.get("offered_by") != "c1" or paid["intent"] is not None:
            errors.append(f"the receipt does not record the mandatory kill as a paid, printed component: {paid}")
    two = state(KILL, printed=(4, None), extra_units=[("u5", "p1", "bf1", {}), ("e5", "p2", "base", {})])
    two["battlefields"]["bf1"]["controller"] = "p1"
    asked = play(two, printed=(4, None))
    if asked.get("committed") or asked.get("reason_code") != "card_selection_required" \
            or asked.get("decision_ids") != ["cost:play-1:self_cost:k"]:
        errors.append(f"two friendly units did not ask which one pays: {asked.get('reason_code')}")
    chose = play(two, printed=(4, None), with_decisions=decisions(two, pick(two, "self_cost:k", ["u5"])))
    if not chose.get("committed") or where(chose["next_effect_state"], "u5") != "p1:trash" \
            or where(chose["next_effect_state"], "u1") != "p1:base":
        errors.append(f"the chosen friendly unit was not the one killed: {chose.get('reason_code')} {chose.get('reason')}")
    for label, entry in (("an enemy unit", pick(two, "self_cost:k", ["e5"])),
                         ("two units", pick(two, "self_cost:k", ["u1", "u5"])),
                         ("the opponent's choice", pick(two, "self_cost:k", ["u5"], controller="p2")),
                         ("a resolution-stage choice", pick(two, "self_cost:k", ["u5"], stage="resolution")),
                         ("a stale identity", pick(two, "self_cost:k", ["u5"], identities={"u5": "u5@9"}))):
        refused = play(two, printed=(4, None), with_decisions=decisions(two, entry))
        if refused.get("committed"):
            errors.append(f"the mandatory kill was paid with {label}")
    none = state(KILL, printed=(4, None))
    none["players"]["p1"]["zones"]["base"].remove("u1")
    del none["objects"]["u1"]
    blocked = play(none, printed=(4, None))
    if blocked.get("committed") or blocked.get("reason_code") != "cost_unpayable" \
            or blocked.get("next_effect_state_hash") != hash_value(none):
        errors.append(f"with no friendly unit the mandatory cost did not stop the play whole: {blocked.get('reason_code')}")
    stripped = state({}, printed=(4, None))
    plain = play(stripped, printed=(4, None))
    if not plain.get("committed") or where(plain["next_effect_state"], "u1") != "p1:base":
        errors.append("without the printed cost the same play killed a unit anyway")

    # --- optional discard, linked Energy reduction ---------------------------------------------------
    s = state(DISCARD)
    undecided = play(s)
    if undecided.get("committed") or undecided.get("reason_code") != "optional_cost_intent_required":
        errors.append(f"an optional printed cost was settled without the player's choice: {undecided.get('reason_code')}")
    paid = play(s, with_decisions=decisions(s, intent("self_offer:d", True)))
    if not paid.get("committed"):
        errors.append(f"the paid discard offer did not commit: {paid.get('reason_code')} {paid.get('reason')}")
    else:
        after = paid["next_effect_state"]
        if after["players"]["p1"]["resources"]["energy"] != 2 or where(after, "c2") != "p1:trash":
            errors.append(f"paying the discard did not discard the card and reduce the cost by 2: "
                          f"{after['players']['p1']['resources']} c2 at {where(after, 'c2')}")
    declined = play(s, with_decisions=decisions(s, intent("self_offer:d", False)))
    if not declined.get("committed") or declined["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0 \
            or where(declined["next_effect_state"], "c2") != "p1:hand":
        errors.append("declining the discard offer did not pay the full cost and keep the card")
    else:
        unpaid = component(declined, "self_offer:d")
        if not unpaid or unpaid["paid"] or unpaid["intent"] is not False or unpaid.get("cost_offer_id") != "d":
            errors.append(f"the declined offer is not on the receipt unpaid: {unpaid}")
    short = state(DISCARD, energy=4)
    if play(short, with_decisions=decisions(short, intent("self_offer:d", False))).get("committed"):
        errors.append("four Energy paid a six-Energy card with the discount declined")
    if not play(short, with_decisions=decisions(short, intent("self_offer:d", True))).get("committed"):
        errors.append("four Energy did not pay a six-Energy card with the discount paid")
    empty = state(DISCARD, hand_extra=False)
    nothing = play(empty, with_decisions=decisions(empty, intent("self_offer:d", True)))
    if nothing.get("committed") or nothing.get("reason_code") != "cost_unpayable":
        errors.append(f"a discard offer was paid with no other card in hand: {nothing.get('reason_code')}")
    # "If you do, draw 2" after the offer reads the decision, bound to this card, play and offer
    linked = cg.compile_card([{"text": "As you play this, you may discard 1 as an additional cost."},
                              {"text": "If you do, draw 2."}, {"text": "Otherwise, draw 1."}], cg.load_grammar())
    if linked["unsupported_clauses"]:
        errors.append(f"the offer and its 'If you do' / 'Otherwise' did not compile: {linked['unsupported_clauses']}")
    else:
        spell = copy.deepcopy(linked["passive"]["object_fields"])
        for entry in spell["printed_additional_costs"]:
            entry["cost_offer_id"] = "d"
        effects = copy.deepcopy(linked["program_effects"])
        for index, effect in enumerate(effects):
            effect.update({"player": "p1", "effect_id": f"e{index}"})
            effect["predicate"]["cost_offer_id"] = "d"
            effect["predicate"]["cost_id"] = "self_offer:d"
        for label, pay_it, wanted in (("paid", True, 2), ("declined", False, 1)):
            s = state(spell, kind="spell", printed=(1, None))
            s["players"]["p1"]["zones"]["main_deck"] = ["c3", "c4x"]
            s["objects"]["c4x"] = {**copy.deepcopy(s["objects"]["c3"])}
            s["players"]["p1"]["zones"]["trash"] = []
            played = play(s, kind="spell", printed=(1, None), with_decisions=decisions(s, intent("self_offer:d", pay_it)))
            if not played.get("committed"):
                errors.append(f"the {label} spell did not commit: {played.get('reason_code')} {played.get('reason')}")
                continue
            program = {"schema_version": pt.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                       "program_id": "linked", "controller": "p1", "source_object": "c1", "chain_item": "item-1",
                       "cost_receipt": played["cost_receipt"], "effects": effects}
            if validate_program(program):
                errors.append(f"the linked program was refused: {validate_program(program)}")
                continue
            before = len(played["next_effect_state"]["players"]["p1"]["zones"]["hand"])
            ran = apply_program(played["next_effect_state"], program)
            drawn = len(ran["next_state"]["players"]["p1"]["zones"]["hand"]) - before if ran.get("committed") else None
            if drawn != wanted:
                errors.append(f"'If you do' / 'Otherwise' after a {label} offer drew {drawn}, not {wanted}")
        borrowed = copy.deepcopy(effects)
        for effect in borrowed:
            effect["predicate"]["cost_offer_id"] = "another-offer"
        s = state(spell, kind="spell", printed=(1, None))
        played = play(s, kind="spell", printed=(1, None), with_decisions=decisions(s, intent("self_offer:d", True)))
        if played.get("committed") and not validate_program(
                {"schema_version": pt.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                 "program_id": "linked", "controller": "p1", "source_object": "c1", "chain_item": "item-1",
                 "cost_receipt": played["cost_receipt"], "effects": borrowed}):
            errors.append("a predicate naming another offer read this card's payment")

    # --- optional spend a buff, linked "ignore this spell's cost" -------------------------------------
    s = state(BUFF, kind="spell", energy=0, printed=(2, None), extra_units=[("e5", "p2", "base", {"buffed": True})])
    s["objects"]["u1"]["buffed"] = True
    spent = play(s, kind="spell", printed=(2, None), with_decisions=decisions(s, intent("self_offer:b", True)))
    if not spent.get("committed") or spent["next_effect_state"]["objects"]["u1"].get("buffed") \
            or not spent["next_effect_state"]["objects"]["e5"].get("buffed"):
        errors.append(f"spending the buff did not remove exactly the payer's buff and ignore the cost: "
                      f"{spent.get('reason_code')} {spent.get('reason')}")
    elif (spent["cost_receipt"]["total"]["energy"], spent["cost_receipt"]["after_base_modifications"]) != (0, {"energy": 0, "power": {}}):
        errors.append(f"'ignore this spell's cost' did not set the base cost to zero: {spent['cost_receipt']['after_base_modifications']}")
    if play(s, kind="spell", printed=(2, None), with_decisions=decisions(s, intent("self_offer:b", False))).get("committed"):
        errors.append("a declined buff offer still ignored the spell's cost (0 Energy paid a 2-Energy spell)")
    only_enemy = state(BUFF, kind="spell", energy=0, printed=(2, None), extra_units=[("e5", "p2", "base", {"buffed": True})])
    refused = play(only_enemy, kind="spell", printed=(2, None), with_decisions=decisions(only_enemy, intent("self_offer:b", True)))
    if refused.get("committed") or refused.get("reason_code") != "cost_unpayable":
        errors.append(f"an enemy's buff paid the spend-a-buff offer: {refused.get('reason_code')}")

    # --- any number of kills, a Power reduction per unit ----------------------------------------------
    s = state(MANY, energy=5, power={"order": 2}, printed=(5, {"order": 4}), extra_units=[("u5", "p1", "base", {})])
    two_killed = play(s, printed=(5, {"order": 4}),
                      with_decisions=decisions(s, intent("self_offer:m", True), pick(s, "self_offer:m", ["u1", "u5"])))
    if not two_killed.get("committed"):
        errors.append(f"two killed units did not pay the any-number offer: {two_killed.get('reason_code')} {two_killed.get('reason')}")
    else:
        after = two_killed["next_effect_state"]
        if (where(after, "u1"), where(after, "u5"), after["players"]["p1"]["resources"]["power"].get("order")) != ("p1:trash", "p1:trash", 0):
            errors.append("two kills did not reduce the Order cost by two")
        if component(two_killed, "self_offer:m#2") is None:
            errors.append("the second killed unit is not its own component of the offer")
    if play(s, printed=(5, {"order": 4}), with_decisions=decisions(s, intent("self_offer:m", True), pick(s, "self_offer:m", ["u1"]))).get("committed"):
        errors.append("one kill reduced the Order cost by more than one (2 Order paid 3)")
    rich = state(MANY, energy=5, power={"order": 4}, printed=(5, {"order": 4}), extra_units=[("u5", "p1", "base", {})])
    paid_none = play(rich, printed=(5, {"order": 4}),
                     with_decisions=decisions(rich, intent("self_offer:m", True), pick(rich, "self_offer:m", [])))
    if paid_none.get("committed") or paid_none.get("reason_code") != "cost_choice_illegal":
        errors.append(f"an any-number offer was paid with none: {paid_none.get('reason_code')}")
    many = state(MANY, energy=5, power={}, printed=(5, {"order": 1}), extra_units=[("u5", "p1", "base", {})])
    floored = play(many, printed=(5, {"order": 1}),
                   with_decisions=decisions(many, intent("self_offer:m", True), pick(many, "self_offer:m", ["u1", "u5"])))
    if not floored.get("committed") or floored["cost_receipt"]["total"]["power"].get("order") != 0:
        errors.append(f"a reduction larger than the Power cost did not stop at 0 (356.6): {floored.get('reason_code')}")

    # --- shapes ---------------------------------------------------------------------------------------
    for label, fields in (
        ("a mandatory 'any number'", {"printed_additional_costs": [{"cost_offer_id": "x", "mandatory": True, "payment": {"kind": "kill", "any_number": True}}]}),
        ("an unknown kind", {"printed_additional_costs": [{"cost_offer_id": "x", "mandatory": True, "payment": {"kind": "banish", "amount": 1}}]}),
        ("two units for one kill", {"printed_additional_costs": [{"cost_offer_id": "x", "mandatory": True, "payment": {"kind": "kill", "amount": 2}}]}),
        ("a link to a mandatory cost", {**KILL, "offer_linked_cost_modifications": [{"cost_offer_id": "k", "kind": "energy_reduction", "amount": 1}]}),
        ("a per-each link on one payment", {**DISCARD, "offer_linked_cost_modifications": [{"cost_offer_id": "d", "kind": "power_reduction_per_paid", "domain": "order", "amount": 1}]}),
        ("a fixed link on 'any number'", {**MANY, "offer_linked_cost_modifications": [{"cost_offer_id": "m", "kind": "energy_reduction", "amount": 1}]}),
        ("a link to no offer", {**DISCARD, "offer_linked_cost_modifications": [{"cost_offer_id": "nope", "kind": "energy_reduction", "amount": 2}]}),
        ("an offer id a resource offer uses", {**KILL, "optional_additional_costs": [{"cost_offer_id": "k", "payment": {"kind": "energy", "amount": 1}}]}),
    ):
        if not validate_state(state(fields)):
            errors.append(f"validate_state accepted {label}")
    for fields in (KILL, DISCARD, BUFF, MANY):
        if validate_state(state(fields)):
            errors.append(f"validate_state refused a well-formed printed cost: {validate_state(state(fields))}")

    # --- the enumerator reads the same costs ------------------------------------------------------------
    def offered(s):
        observation = la.build_observation(
            perspective="player1", source={"kind": "engine_state", "state_seq": 1},
            context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard", "card_data_version": "synthetic"},
            timing_state=fixture(), effect_state=s, facts={}, pending_decisions=[],
            completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"})
        enumerated = la.enumerate_actions(observation, "p1")
        return any(a["candidate_id"] == "play:c1" for a in enumerated["enumeration"]["actions"])
    if not offered(state(KILL, printed=(4, None))):
        errors.append("the enumerator did not offer a play whose mandatory cost a friendly unit can pay")
    if offered(none):
        errors.append("the enumerator offered a play whose mandatory cost nothing can pay")
    if not offered(state(DISCARD, energy=4)):
        errors.append("the enumerator did not offer a card affordable only with its own discount")
    if offered(state(DISCARD, energy=4, hand_extra=False)):
        errors.append("the enumerator offered a discount that no card in hand can pay")
    if offered(state(DISCARD, energy=3)):
        errors.append("the enumerator offered a card its pool cannot pay even with the discount")

    # --- the grammar ----------------------------------------------------------------------------------
    grammar = cg.load_grammar()
    one = cg.compile_clause("As an additional cost to play me, kill a friendly unit.", grammar)
    if one.get("unsupported") or one["passive"]["object_fields"]["printed_additional_costs"][0] != \
            {"cost_offer_id": "$clause_id", "mandatory": True, "payment": {"kind": "kill", "amount": 1}}:
        errors.append(f"the mandatory kill did not lower to its printed cost: {one}")
    pair = cg.compile_card([{"text": "As you play me, you may discard 1 as an additional cost."},
                            {"text": "If you do, reduce my cost by :rb_energy_2:."}], grammar)
    fields = pair["passive"]["object_fields"] if not pair["unsupported_clauses"] else {}
    if fields.get("offer_linked_cost_modifications") != [{"cost_offer_id": "$clause_id", "kind": "energy_reduction", "amount": 2}]:
        errors.append(f"'If you do, reduce my cost by [2]' did not link the offer: {pair['unsupported_clauses'] or fields}")
    per = cg.compile_card([{"text": "As you play me, you may spend any number of buffs as an additional cost."},
                           {"text": "Reduce my cost by :rb_rune_body: for each buff you spend."}], grammar)
    if per["unsupported_clauses"] or per["passive"]["object_fields"]["offer_linked_cost_modifications"][0]["domain"] != "body":
        errors.append(f"the per-buff Power reduction did not link the offer: {per['unsupported_clauses']}")
    for label, clauses in (
        ("'If you do' with no offer before it", [{"text": "Draw 1."}, {"text": "If you do, reduce my cost by :rb_energy_2:."}]),
        ("a per-kill discount after a buff offer", [{"text": "As you play me, you may spend any number of buffs as an additional cost."},
                                                    {"text": "Reduce my cost by :rb_rune_order: for each killed this way."}]),
        ("a fixed discount after an 'any number' offer", [{"text": "As you play me, you may kill any number of friendly units as an additional cost."},
                                                          {"text": "If you do, reduce my cost by :rb_energy_2:."}]),
    ):
        card = cg.compile_card(clauses, grammar)
        if not card["unsupported_clauses"]:
            errors.append(f"{label} compiled anyway")
    if not cg.compile_clause("If you do, reduce my cost by :rb_energy_2:.", grammar).get("unsupported"):
        errors.append("a linked cost modification with no clause before it compiled")

    if errors:
        print("FAILED: printed non-resource additional costs")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("printed additional cost checks passed: a mandatory kill is paid with a chosen friendly unit or stops the play, "
          "an optional discard / buff / any-number offer is an explicit choice whose payment switches on its linked "
          "reduction (floored at 0), 'If you do' / 'Otherwise' read that decision, and the enumerator and grammar agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
