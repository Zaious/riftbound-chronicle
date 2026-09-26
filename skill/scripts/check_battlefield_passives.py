#!/usr/bin/env python3
"""
Regression gate for two printed Battlefield statements the clause grammar lowers
(package 5, 2026-09-27). Both are passives the engine already executes; this checks
that the grammar's lowering, bound onto a Battlefield, does what the sentence says.

  spells_and_abilities_deal_n_bonus_damage_to_units_here (Core 713-715)
    - p1's spell dealing 2 to a Unit at that Battlefield deals 3, whoever controls the
      Unit; so does p2's spell, and an ability (a program with a source object);
    - a Unit in a Base, or at another Battlefield, takes 2;
    - one Deal over every Unit at battlefields adds 1 to each Unit there and to no
      other (715.2: each target separately);
    - without the statement, every Deal is 2 (the lowering is what bites).
  you_may_hide_an_additional_card_here (Core 107.3.b, 107.3.b.1, 421.1)
    - at that Battlefield (p1 controls it) a first and a second hide commit and a
      third is refused facedown_zone_full;
    - at another Battlefield p1 controls, a second hide is refused;
    - without the statement, the second hide at that Battlefield is refused.
  Near misses ("your spells and abilities deal 1 bonus damage", "you may hide a card
  here") do not parse to either production.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, apply_program, object_identity, validate_state  # noqa: E402
from hidden import HIDE_DECLARATION_VERSION, hide_card  # noqa: E402

BONUS = "Spells and abilities deal 1 Bonus Damage to units here."
FACEDOWN = "You may hide an additional card here."


def bind(value, source, controller):
    """The lowering's symbols bound onto one Battlefield (as a card program pack binds them)."""
    text = json.dumps(value).replace('"$source_object"', json.dumps(source)).replace('"$controller"', json.dumps(controller))
    return json.loads(text.replace('"$clause_id"', json.dumps(f"{source}-statement")))


def unit(owner, might=9):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False}


def bonus_board(passive):
    """bf1 is the Battlefield with the statement, p1's, holding p1's f1 and p2's e1; bf2 is
    p2's with e2; b1 waits in p1's Base."""
    state = base_state()
    state["objects"].update({"f1": unit("p1"), "e1": unit("p2"), "e2": unit("p2"), "b1": unit("p1")})
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["f1", "e1"], "contested": True, "contested_by": "p2"}
    state["battlefields"]["bf2"] = {"controller": "p2", "objects": ["e2"]}
    state["players"]["p1"]["zones"]["base"].append("b1")
    for key, entries in (bind(passive, "bf1", "p1").get("state_lists") or {}).items():
        state.setdefault(key, []).extend(entries)
    return state


def dealt(state, controller, effect, source=None):
    prog = program("deal", dict(effect))
    prog["controller"] = controller
    if source:
        prog["source_object"] = source
        prog["source_identity"] = object_identity(state, source) or f"{source}@0"
    got = apply_program(state, prog)
    if not got.get("committed"):
        return {"refused": got.get("reason") or got.get("errors")}
    after = got["next_state"]
    return {o: after["objects"][o]["damage"] - state["objects"][o]["damage"] for o in ("f1", "e1", "e2", "b1")
            if after["objects"][o]["damage"] != state["objects"][o]["damage"]}


def bonus_readings(passive):
    state = bonus_board(passive)
    if validate_state(state):
        return {"invalid": validate_state(state)}
    one = lambda target: {"op": "deal_damage", "effect_id": "d", "object_id": target, "amount": 2}
    return {
        "p1_spell_enemy_here": dealt(state, "p1", one("e1")),
        "p1_spell_friendly_here": dealt(state, "p1", one("f1")),
        "p2_spell_here": dealt(state, "p2", one("f1")),
        "p1_ability_here": dealt(state, "p1", one("e1"), source="f1"),
        "p1_spell_in_base": dealt(state, "p1", one("b1")),
        "p1_spell_other_battlefield": dealt(state, "p1", one("e2")),
        "one_deal_over_battlefields": dealt(state, "p1", {"op": "deal_damage", "effect_id": "d", "amount": 2,
                                                         "affected": {"criteria": {"kind": "unit", "location": "any_battlefield"}}}),
    }


BONUS_EXPECTED = {"p1_spell_enemy_here": {"e1": 3}, "p1_spell_friendly_here": {"f1": 3}, "p2_spell_here": {"f1": 3},
                  "p1_ability_here": {"e1": 3}, "p1_spell_in_base": {"b1": 2}, "p1_spell_other_battlefield": {"e2": 2},
                  "one_deal_over_battlefields": {"f1": 3, "e1": 3, "e2": 2}}


def hide_board(passive):
    """bf1 (the statement's Battlefield) and bf2, both p1's and empty; p1 holds h1..h4, each
    with Hidden, and enough Power for four hides."""
    state = base_state()
    for k in range(1, 5):
        state["objects"][f"h{k}"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                     "might_modifiers": [], "damage": 0, "exhausted": False, "hidden": True}
        state["players"]["p1"]["zones"]["hand"].append(f"h{k}")
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": [], **bind(passive, "bf1", "p1").get("battlefield_fields", {})}
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
    state["players"]["p1"]["resources"] = {"energy": 0, "power": {"fury": 4}}
    return state


def hide(state, card, battlefield):
    declaration = {"schema_version": HIDE_DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "hide_id": f"hide-{card}", "actor": "p1", "card": card, "source": "hand", "battlefield": battlefield,
                   "cost": {"base": {"energy": 0, "power": {"fury": 1}}},
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    got = hide_card(fixture(), state, declaration)
    return (got["next_effect_state"], "committed") if got.get("committed") else (state, got.get("reason_code"))


def hide_readings(passive):
    state = hide_board(passive)
    if validate_state(state):
        return {"invalid": validate_state(state)}
    out = {}
    for label, card, battlefield in (("first_here", "h1", "bf1"), ("second_here", "h2", "bf1"), ("third_here", "h3", "bf1"),
                                     ("first_elsewhere", "h3", "bf2"), ("second_elsewhere", "h4", "bf2")):
        state, out[label] = hide(state, card, battlefield)
    return out


HIDE_EXPECTED = {"first_here": "committed", "second_here": "committed", "third_here": "facedown_zone_full",
                 "first_elsewhere": "committed", "second_elsewhere": "facedown_zone_full"}


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    bonus = CG.compile_clause(BONUS, grammar)
    facedown = CG.compile_clause(FACEDOWN, grammar)
    if bonus.get("production_id") != "spells_and_abilities_deal_n_bonus_damage_to_units_here" or bonus.get("unsupported"):
        errors.append(f"{BONUS!r} did not compile: {bonus.get('production_id')} {bonus.get('reason_code')}")
    if facedown.get("production_id") != "you_may_hide_an_additional_card_here" or facedown.get("unsupported"):
        errors.append(f"{FACEDOWN!r} did not compile: {facedown.get('production_id')} {facedown.get('reason_code')}")
    for near in ("Your spells and abilities deal 1 Bonus Damage.", "Spells and abilities deal 1 Bonus Damage to enemy units here.",
                 "You may hide a card here.", "You may hide two additional cards here."):
        got = CG.compile_clause(near, grammar)
        if got.get("production_id") in ("spells_and_abilities_deal_n_bonus_damage_to_units_here",
                                        "you_may_hide_an_additional_card_here"):
            errors.append(f"near miss {near!r} parsed as {got['production_id']}")
    if errors:
        print("FAILED\n  - " + "\n  - ".join(errors))
        return 1

    got = bonus_readings(bonus["passive"])
    if got != BONUS_EXPECTED:
        errors.append(f"Bonus Damage to units here: {got} != {BONUS_EXPECTED}")
    without = bonus_readings({})
    if without == BONUS_EXPECTED or any(v != 2 for r in without.values() for v in r.values()):
        errors.append(f"without the statement every Deal must be 2: {without}")
    # the lowering is the Battlefield's; the same entry scoped to p1's sources is not it
    mutant = copy.deepcopy(bonus["passive"])
    mutant["state_lists"]["damage_modifiers"][0]["scope"] = {"kind": "controller_sources"}
    if bonus_readings(mutant) == BONUS_EXPECTED:
        errors.append("counterexample: a controller-scoped Bonus Damage passed as 'to units here'")

    got = hide_readings(facedown["passive"])
    if got != HIDE_EXPECTED:
        errors.append(f"an additional facedown card here: {got} != {HIDE_EXPECTED}")
    without = hide_readings({})
    if without.get("second_here") != "facedown_zone_full":
        errors.append(f"without the statement a second hide at that Battlefield was not refused: {without}")
    three = {"battlefield_fields": {"facedown": {"capacity": 3, "cards": []}}}
    if hide_readings(three) == HIDE_EXPECTED:
        errors.append("counterexample: a capacity of three passed as 'an additional card'")

    if errors:
        print("FAILED\n  - " + "\n  - ".join(errors))
        return 1
    print("OK: 'Spells and abilities deal 1 Bonus Damage to units here.' adds 1 to every spell's or ability's Deal to a "
          "Unit at that Battlefield (either side, either player's spell) and to no other; 'You may hide an additional "
          "card here.' lets that Battlefield hold two facedown cards and no more, and no other Battlefield two; "
          "without either statement, or with a wrong scope or capacity, the readings differ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
