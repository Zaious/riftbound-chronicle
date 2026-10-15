#!/usr/bin/env python3
"""Gate: a catalogued object is played and activated exactly as its record says (package 13, C2).

The engine took a caller's word for a play's cost and for an activated ability's cost, timing, kind, program and
activation conditions - a card printed at 3 Energy was played for 0. For an object that carries card_ref (the closed
environment's catalogue key) the engine now checks the declaration against the record
(play_transaction.catalogued_declaration_problem); an object without card_ref is unchanged.

  P1 the price   a catalogued card printed at 3 Energy: declared at its printed cost, played; declared at 0, with a
                 declared discount, or with a declared additional cost, refused as declaration_not_as_catalogued
  P2 legacy      the same card without card_ref, declared at 0: still played (what the old path does - never reached
                 by a closed-environment state, whose receipt requires card_ref on every object)
  A1 the ability a catalogued unit with one row - 1 Energy, [Exhaust], a text cost, [Reaction], an [Add] ability,
                 its program and its own activation condition: declared as the row says, accepted at the payment
                 step; each single difference - Energy, no [Exhaust], no text cost, timing, kind, program, another
                 condition, an ability id the row does not have - refused by name
  A2 choices     a cost the row leaves to the payer (which friendly unit or gear to kill) is named by the declaration,
                 and the non-standard costs come in the order the payer declares them; no object named, another kind,
                 another object exhausted, or a cost twice, is refused
  A3 kill kinds  a kill cost that names its kinds is paid only with a friendly object of one of them: with "unit" alone,
                 a friendly Unit pays it and a friendly Gear does not
  A4 selections  a Discard or a Recycle cost is paid by the payer's card selection at play: declared as the row prints
                 it, accepted; naming an object in it, refused
  V1 validation  card_ref must be a non-empty string; a row with an unknown key or a bad timing does not validate

    python skill/scripts/check_catalogued_declarations.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from check_costs_and_activation import ability_declaration, declaration, hand_state  # noqa: E402
from check_effect_ir import program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from play_transaction import EXHAUST_SELF_COST_ID, catalogued_declaration_problem, play_card  # noqa: E402

errors: list[str] = []
CONDITION = {"kind": "source_at_battlefield"}


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def code(result):
    return result.get("reason_code")


def main() -> int:
    # P1 / P2
    state = hand_state("c1", energy=3)
    state["objects"]["c1"].update(printed_cost={"energy": 3, "power": {}}, card_ref="Test Card")
    printed = declaration(cost={"base": {"energy": 3, "power": {}}})
    if not play_card(fixture(), state, printed).get("committed"):
        fail("P1 the price", f"declared at its printed cost, refused: {code(play_card(fixture(), state, printed))}")
    for label, cost in (("0", {"base": {"energy": 0, "power": {}}}),
                        ("a discount", {"base": {"energy": 3, "power": {}},
                                        "discounts": [{"id": "d", "applies_to": "energy", "amount": 2}]}),
                        ("an additional cost", {"base": {"energy": 3, "power": {}},
                                                "additional": [{"cost_id": "x", "mandatory": True,
                                                                "payment": {"kind": "energy", "amount": 0}}]})):
        got = play_card(fixture(), state, declaration(cost=cost))
        if got.get("committed") or code(got) != "declaration_not_as_catalogued":
            fail("P1 the price", f"declared with {label}: {got.get('committed')} {code(got)}")
    legacy = copy.deepcopy(state)
    del legacy["objects"]["c1"]["card_ref"]
    if not play_card(fixture(), legacy, declaration(cost={"base": {"energy": 0, "power": {}}})).get("committed"):
        fail("P2 legacy", "an uncatalogued card's declared cost was refused - the old path changed")
    # A1
    ability_state = hand_state(energy=1)
    ability_state["players"]["p1"]["zones"]["base"].append("u1") if "u1" not in ability_state["players"]["p1"]["zones"]["base"] else None
    unit = ability_state["objects"]["u1"]
    unit.update(card_ref="Test Unit", exhausted=False, activated_abilities={"u1:a1": {
        "cost": {"energy": 1, "power": {}, "exhaust": True,
                 "additional": [{"cost_id": "text-cost", "mandatory": True, "payment": {"kind": "spend_buff", "object_id": "u1"}}]},
        "effect_program_id": "prog-a1", "timing": "reaction", "ability_kind": "add",
        "activation_conditions": [CONDITION]}})
    if validate_state(ability_state):
        fail("A1 the ability", f"the board does not validate: {validate_state(ability_state)[:2]}")
        return report()
    good = ability_declaration(
        chain_item={"id": "ability-1", "object_kind": "ability", "timing": "reaction", "ability_kind": "add"},
        cost={"base": {"energy": 1, "power": {}},
              "additional": [{"cost_id": EXHAUST_SELF_COST_ID, "mandatory": True, "payment": {"kind": "exhaust", "object_id": "u1"}},
                             {"cost_id": "text-cost", "mandatory": True, "payment": {"kind": "spend_buff", "object_id": "u1"}}]},
        effect_program_id="prog-a1", activation_conditions=[CONDITION])
    if catalogued_declaration_problem(ability_state, good) is not None:
        fail("A1 the ability", f"declared as its row says, refused: {catalogued_declaration_problem(ability_state, good)}")

    def variant(label, change):
        d = copy.deepcopy(good)
        change(d)
        if catalogued_declaration_problem(ability_state, d) is None:
            fail("A1 the ability", f"{label}: accepted")
        got = play_card(fixture(), ability_state, d)
        if got.get("committed") or code(got) != "declaration_not_as_catalogued":
            fail("A1 the ability", f"{label}: the play was not refused by name ({code(got)})")
    variant("0 Energy", lambda d: d["cost"]["base"].update(energy=0))
    variant("no [Exhaust]", lambda d: d["cost"]["additional"].pop(0))
    variant("no text cost", lambda d: d["cost"]["additional"].pop(1))
    variant("default timing", lambda d: d["chain_item"].update(timing="default"))
    variant("a standard ability", lambda d: d["chain_item"].update(ability_kind="standard"))
    variant("another program", lambda d: d.update(effect_program_id="prog-other"))
    variant("no activation condition", lambda d: d.update(activation_conditions=[]))
    variant("an ability the row does not have", lambda d: d["activation"].update(ability_id="u1:a9"))
    # A2: a cost the row leaves to the payer (whose friendly unit or gear to kill, Core 203.1) and the order the
    # payer declares the non-standard costs in (357.2) are the payer's; the row's own objects are not
    unit["activated_abilities"]["u1:a2"] = {
        "cost": {"energy": 0, "power": {}, "exhaust": True,
                 "additional": [{"cost_id": "text-cost", "mandatory": True,
                                 "payment": {"kind": "kill", "object_kinds": ["gear", "unit"]}}]},
        "effect_program_id": "prog-a2"}
    kill = ability_declaration(
        activation={"source_object": "u1", "ability_id": "u1:a2"}, effect_program_id="prog-a2",
        cost={"base": {"energy": 0, "power": {}},
              "additional": [{"cost_id": "text-cost", "mandatory": True,
                              "payment": {"kind": "kill", "object_kinds": ["gear", "unit"], "object_id": "u1"}},
                             {"cost_id": EXHAUST_SELF_COST_ID, "mandatory": True, "payment": {"kind": "exhaust", "object_id": "u1"}}]})
    if catalogued_declaration_problem(ability_state, kill) is not None:
        fail("A2 the payer's choices", f"a named kill target, costs in the payer's order: {catalogued_declaration_problem(ability_state, kill)}")
    for label, change in (
            ("no object named for the kill", lambda d: d["cost"]["additional"][0]["payment"].pop("object_id")),
            ("another kind of kill", lambda d: d["cost"]["additional"][0]["payment"].update(object_kinds=["unit"])),
            ("another object exhausted", lambda d: d["cost"]["additional"][1]["payment"].update(object_id="u2")),
            ("a cost twice", lambda d: d["cost"]["additional"].append(copy.deepcopy(d["cost"]["additional"][1])))):
        d = copy.deepcopy(kill)
        change(d)
        if catalogued_declaration_problem(ability_state, d) is None:
            fail("A2 the payer's choices", f"{label}: accepted")
    # A4: a Discard or a Recycle cost is the payer's card selection at play (CHOICE_COSTS), not a named object
    for kind, extra in (("discard", {"amount": 1}), ("recycle_trash", {"amount": 2})):
        unit["activated_abilities"]["u1:a3"] = {
            "cost": {"energy": 0, "power": {}, "exhaust": True,
                     "additional": [{"cost_id": "text-cost", "mandatory": True, "payment": {"kind": kind, **extra}}]},
            "effect_program_id": "prog-a3"}
        chosen = ability_declaration(
            activation={"source_object": "u1", "ability_id": "u1:a3"}, effect_program_id="prog-a3",
            cost={"base": {"energy": 0, "power": {}},
                  "additional": [{"cost_id": "text-cost", "mandatory": True, "payment": {"kind": kind, **extra}},
                                 {"cost_id": EXHAUST_SELF_COST_ID, "mandatory": True,
                                  "payment": {"kind": "exhaust", "object_id": "u1"}}]})
        if catalogued_declaration_problem(ability_state, chosen) is not None:
            fail("A4 selections", f"a {kind} cost as the row prints it: {catalogued_declaration_problem(ability_state, chosen)}")
        named = copy.deepcopy(chosen)
        named["cost"]["additional"][0]["payment"]["object_id"] = "c1"
        if catalogued_declaration_problem(ability_state, named) is None:
            fail("A4 selections", f"a {kind} cost naming an object: accepted")
    del unit["activated_abilities"]["u1:a3"]
    # A3: the kinds a kill cost names are the only objects that pay it - with "unit" alone, a friendly Unit does and a
    # friendly Gear does not (a Rune is never killed at all; with "unit or gear" both pay)
    board = copy.deepcopy(ability_state)
    board["objects"]["u1"]["activated_abilities"]["u1:a2"]["cost"]["additional"][0]["payment"]["object_kinds"] = ["unit"]
    board["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 1, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    board["players"]["p1"]["zones"]["base"].append("u3")
    board["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    board["players"]["p1"]["zones"]["base"].append("g1")
    board["players"]["p1"]["zones"]["rune_deck"].remove("r1")
    board["players"]["p1"]["zones"]["base"].append("r1")
    board["players"]["p1"]["resources"] = {"energy": 0, "power": {}}
    if validate_state(board):
        fail("A3 kill kinds", f"the board does not validate: {validate_state(board)[:2]}")
    else:
        drawing = program("prog-a2", {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1})
        drawing["source_object"] = "u1"
        for victim, want in (("u3", True), ("g1", False)):
            d = copy.deepcopy(kill)
            d["cost"]["additional"][0]["payment"].update(object_id=victim, object_kinds=["unit"])
            got = play_card(fixture(), board, d, effect_program=drawing)
            if bool(got.get("committed")) is not want:
                fail("A3 kill kinds", f"killing the friendly {board['objects'][victim]['kind']} to pay: "
                                      f"{got.get('committed')} {code(got)} {got.get('reason')}")

    # V1
    bad_ref = copy.deepcopy(state)
    bad_ref["objects"]["c1"]["card_ref"] = ""
    if not validate_state(bad_ref):
        fail("V1 validation", "an empty card_ref validated")
    for label, row in (("an unknown key", {"cost": {"energy": 0, "power": {}}, "effect_program_id": "p", "secret": 1}),
                       ("a bad timing", {"cost": {"energy": 0, "power": {}}, "effect_program_id": "p", "timing": "instant"})):
        bad_row = copy.deepcopy(ability_state)
        bad_row["objects"]["u1"]["activated_abilities"] = {"u1:a1": row}
        if not validate_state(bad_row):
            fail("V1 validation", f"a row with {label} validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: catalogued declarations")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a catalogued card is played only at its printed cost, and a catalogued ability only with its row's cost, "
          "[Exhaust], text costs, timing, kind, program and activation conditions - each difference refused by name; an "
          "uncatalogued object keeps the old path (P1-P2, A1-A4, V1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
