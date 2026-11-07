#!/usr/bin/env python3
"""Regression gate: "cost [1] or [A] less" (set 2 package A2, GPT A2 ruling 16; Core 356.4.c, 356.4.c.2).

The payer chooses ONE component the discount reduces - its Energy, or the Power of a Domain the cost actually has - never
both, never below 0; the choice is declared in cost.discount_choices. A cost with a single such component takes it; with
two or more and none declared, the play waits (discount_choice_required) naming each choice and its options.

  Irelia - Graceful "Your spells that choose me cost [1] or [A] less." (scope card, spells choosing the source)
    I1 asked      a spell costing [2][Calm] chooses Irelia: it waits for the choice, options energy and power:calm
    I2 energy     declared energy: 1 Energy and 1 Calm paid
    I3 power      declared power:calm: 2 Energy paid, no Calm (the Calm component at 0, not below)
    I4 one        a spell costing [2] only: the Energy is reduced without asking (1 paid)
    I5 not me     the spell chooses another unit: no discount (2 Energy and 1 Calm paid)
    I6 not theirs Irelia is p2's: no discount
    I7 bad        a declared option the cost does not have (power:fury) is refused as invalid
  Ezreal - Prodigy "Optional additional costs you pay cost [1] or [A] less." (scope optional_additional)
    E1 asked      a card whose optional additional cost is [1][Order], paid: waits, one choice for that cost
    E2 energy     declared energy: the offer's Energy is 0, its Order Power still paid; the base cost unchanged
    E3 power      declared power:order: the offer's Energy paid, its Order Power not
    E4 declined   the offer not paid: nothing asked, nothing reduced
  S  space        the legal-action enumerator (play_space) tries the declaration with each option declared
  V  validation   an energy_or_power discount of 2, or a scope on an Energy discount, does not validate
  G  grammar      each printed line lowers to exactly its granted discount
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

IRELIA = "Your spells that choose me cost :rb_energy_1: or :rb_rune_rainbow: less."
EZREAL = "Optional additional costs you pay cost :rb_energy_1: or :rb_rune_rainbow: less."
GRAMMAR = CG.load_grammar()


def granted(text):
    return copy.deepcopy(CG.compile_clause(text, GRAMMAR)["passive"]["object_fields"]["granted_cost_discounts"])


def discounts(text, discount_id):
    return [{**g, "discount_id": discount_id} for g in granted(text)]


def board(*, holder="ir", owner="p1", power=None, energy_cost=2, offer=False):
    s = base_state()
    s["objects"][holder] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [],
                            "damage": 0, "exhausted": False,
                            "granted_cost_discounts": discounts(IRELIA if holder == "ir" else EZREAL, f"{holder}-d")}
    s["players"][owner]["zones"]["base"].append(holder)
    s["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s["players"]["p1"]["zones"]["hand"].append("c1")
    s["objects"]["c1"]["printed_cost"] = {"energy": energy_cost, "power": dict(power or {})}
    if offer:
        s["objects"]["c1"]["optional_additional_costs"] = [
            {"cost_offer_id": "ex", "payment": {"kind": "power", "domain": "order", "amount": 1}, "energy": 1}]
    s["players"]["p1"]["resources"] = {"energy": 4, "power": {"calm": 2, "order": 2}}
    return s


def program(target):
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": "c1-effects", "controller": "p1",
            "effects": ([{"op": "ready", "effect_id": "r", "target": {"decision_ref": "t", "chosen_zone_class": "board",
                                                                       "kind": "unit"}}] if target
                        else [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])}


def play(s, *, target=None, choices=None, paid=None, energy_cost=2, power=None):
    cost = {"base": {"energy": energy_cost, "power": dict(power or {})}}
    if choices is not None:
        cost["discount_choices"] = choices
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": cost, "effect_program_id": "c1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    picks = []
    if target:
        picks.append({"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
                      "value": [target], "selection_identities": {target: IR.object_identity(s, target)}})
    if paid is not None:
        picks.append({"decision_id": "self_offer:ex", "kind": "optional_choice", "stage": "play_declaration",
                      "controller": "p1", "value": paid})
    env = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s), "decisions": picks}
    return play_card(fixture(), s, decl, engine_decisions=env, effect_program=program(target))


def pool(played):
    r = played["next_effect_state"]["players"]["p1"]["resources"]
    return r["energy"], r["power"].get("calm", 0), r["power"].get("order", 0)


def main() -> int:
    errors: list[str] = []

    def expect(label, got, energy, calm, order):
        if not got.get("committed"):
            errors.append(f"{label}: refused {got.get('reason_code')} {got.get('reason')}")
        elif pool(got) != (energy, calm, order):
            errors.append(f"{label}: pool after {pool(got)}, expected {(energy, calm, order)}")

    calm = {"calm": 1}
    s = board(power=calm)
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    asked = play(s, target="ir", power=calm)
    key = "granted:ir:ir-d"
    if asked.get("committed") or asked.get("reason_code") != "discount_choice_required" \
            or asked.get("discount_choice_options") != {key: ["energy", "power:calm"]} \
            or asked.get("decision_controller") != "p1":
        errors.append(f"I1 asked: {asked.get('reason_code')} {asked.get('discount_choice_options')}")
    expect("I2 energy", play(s, target="ir", power=calm, choices={key: "energy"}), 3, 1, 2)
    expect("I3 power", play(s, target="ir", power=calm, choices={key: "power:calm"}), 2, 2, 2)
    expect("I4 one", play(board(), target="ir"), 3, 2, 2)
    expect("I5 not me", play(s, target="u1", power=calm), 2, 1, 2)
    expect("I6 not theirs", play(board(owner="p2", power=calm), target="ir", power=calm), 2, 1, 2)
    bad = play(s, target="ir", power=calm, choices={key: "power:fury"})
    if bad.get("committed") or bad.get("reason_code") != "invalid_input":
        errors.append(f"I7 bad: {bad.get('committed')} {bad.get('reason_code')}")

    e = board(holder="ez", offer=True)
    if IR.validate_state(e):
        errors.append(f"ezreal board: {IR.validate_state(e)[:2]}")
    asked = play(e, paid=True)
    ekey = "granted:ez:ez-d@self_offer:ex"
    if asked.get("committed") or asked.get("reason_code") != "discount_choice_required" \
            or asked.get("discount_choice_options") != {ekey: ["energy", "power:order"]}:
        errors.append(f"E1 asked: {asked.get('reason_code')} {asked.get('reason')} {asked.get('discount_choice_options')}")
    expect("E2 energy", play(e, paid=True, choices={ekey: "energy"}), 2, 2, 1)
    expect("E3 power", play(e, paid=True, choices={ekey: "power:order"}), 1, 2, 2)
    expect("E4 declined", play(e, paid=False), 2, 2, 2)

    # S: the legal-action enumerator answers the wait by trying each option declared - both plays are found
    import play_space as PS
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": dict(calm)}}, "effect_program_id": "c1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    orders: set = set()
    PS.discover(fixture(), s, decl, program("ir"), "p1", [0], orders)
    tried = PS._discount_orders(decl, orders)
    found = sorted(d["cost"].get("discount_choices", {}).get(key, "") for d in tried)
    if found != ["energy", "power:calm"]:
        errors.append(f"S space: the enumerator tried {found}")

    for label, entry in (("an amount of 2", {**granted(IRELIA)[0], "discount_id": "x", "amount": 2}),
                         ("a scope on an Energy discount", {"discount_id": "x", "applies_to": "energy", "amount": 1,
                                                            "card_kind": "spell", "scope": "card"})):
        v = board()
        v["objects"]["ir"]["granted_cost_discounts"] = [entry]
        if not any("granted_cost_discounts" in p for p in IR.validate_state(v)):
            errors.append(f"V: {label} validated")
    if granted(IRELIA) != [{"discount_id": "$clause_id", "applies_to": "energy_or_power", "amount": 1, "scope": "card",
                            "card_kind": "spell", "chooses_source": True}] \
            or granted(EZREAL) != [{"discount_id": "$clause_id", "applies_to": "energy_or_power", "amount": 1,
                                    "scope": "optional_additional"}]:
        errors.append(f"G: {granted(IRELIA)} {granted(EZREAL)}")
    if errors:
        print("either cost discount checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("either cost discount checks passed: '[1] or [A] less' reduces the ONE component the payer declares (Energy or "
          "a Domain's Power the cost has), never below 0; one component, no question; two and none declared, the play "
          "waits; Irelia's only for spells that choose it and its controller's; Ezreal's per optional additional cost "
          "paid; validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
