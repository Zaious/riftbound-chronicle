#!/usr/bin/env python3
"""
Regression gate: three more conditions on a card's own entry, and a keyword aura over every friendly Unit (2026-10-29).

"I enter ready if you control another Dragon.", "I enter ready if you have two or more other units in your base." and
"If you have two or fewer cards in your hand, I enter ready." are conditional passives (Core 364.3.a) and entry
replacements with a condition (369.3), read as the unit enters; without the condition holding it enters exhausted
(143.4). The conditions are controls_units with `other` (the card itself not counted) and a `tag` or a `location`, and
the negation of zone_count_at_least over the controller's own hand. "Friendly units have [Deflect]." is a printed
keyword aura (365.1, 479.3) over every friendly Unit, the source included when it is one.

Must hold, through the real play transaction and entry:
  - another Dragon: p1 controls a Dragon - ready; only an opponent does - exhausted; p1 controls a Unit that is not a
    Dragon - exhausted; no other Unit - exhausted (the card's own tag is not "another");
  - other units in base: two in p1's Base - ready; three - ready; one - exhausted; two at a Battlefield - exhausted;
  - cards in hand: two left after the play - ready; none - ready; three - exhausted;
  - the aura: a friendly Unit in a Base and one at a Battlefield have Deflect while the source is on the board, an enemy
    Unit does not; the source, a Unit, has it too; gone from the board, nobody has it;
  - invalid: `other` that is not true;
  - mutation caught: controls_units ignoring `other` enters ready with no other Dragon.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_conditional_entry import enter  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import validate_state  # noqa: E402

DRAGON = "I enter ready if you control another Dragon."
BASE = "I enter ready if you have two or more other units in your base."
HAND = "If you have two or fewer cards in your hand, I enter ready."
AURA = "Friendly units have [Deflect]."


def fields_of(text):
    return (CG.compile_clause(text, CG.load_grammar()).get("passive") or {}).get("object_fields") or {}


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(fields, *, tags=None, units=(), hand=0):
    """p1's c1, a Unit with `fields` (and `tags`), in hand; `units` = [(id, owner, where, tags)]; `hand` other cards in
    p1's hand besides c1."""
    state = base_state()
    # the base state's u1 stands in p1's Base; the cases place every other Unit themselves
    state["players"]["p1"]["zones"]["base"].remove("u1")
    del state["objects"]["u1"]
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, **copy.deepcopy(fields),
                                   **({"tags": list(tags)} if tags is not None else {})})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    for oid, owner, where, utags in units:
        state["objects"][oid] = unit(owner, **({"tags": list(utags)} if utags is not None else {}))
        if where == "base":
            state["players"][owner]["zones"]["base"].append(oid)
        else:
            bf = state["battlefields"].setdefault(where, {"controller": owner, "objects": []})
            bf["objects"].append(oid)
            bf["controller"] = owner
    for n in range(hand):
        state["objects"][f"hc{n}"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                      "might_modifiers": [], "damage": 0, "exhausted": False}
        state["players"]["p1"]["zones"]["hand"].append(f"hc{n}")
    return state


def main() -> int:
    errors: list[str] = []
    dragon, base, hand, aura = fields_of(DRAGON), fields_of(BASE), fields_of(HAND), fields_of(AURA)
    expected = {
        "dragon": (dragon, {"kind": "controls_units", "count": 1, "tag": "Dragon", "other": True}),
        # set 2 package A2 (Breakneck Mech): the same sentence over the Mech tag
        "mech": (fields_of("I enter ready if you control another Mech."),
                 {"kind": "controls_units", "count": 1, "tag": "Mech", "other": True}),
        "base": (base, {"kind": "controls_units", "count": 2, "location": "base", "other": True}),
        "hand": (hand, {"kind": "not", "of": {"kind": "zone_count_at_least", "zone": "hand", "count": 3}}),
    }
    for label, (got, condition) in expected.items():
        if got != {"entry_replacements": [{"replacement_id": "own-text", "mode": "entry_state", "value": "ready",
                                            "condition": condition}]}:
            errors.append(f"the {label} sentence lowered to {got}")
    if aura != {"static_auras": [{"aura_id": "all-deflect", "keyword": "deflect",
                                  "criteria": {"kind": "unit", "controller_relation": "friendly"}}]}:
        errors.append(f"the aura sentence lowered to {aura}")
    D = ["Dragon"]
    cases = {
        "you_control_a_dragon": (board(dragon, tags=D, units=[("d1", "p1", "base", D)]), "ready"),
        "only_an_opponent_controls_a_dragon": (board(dragon, tags=D, units=[("d1", "p2", "base", D)]), "exhausted"),
        "you_control_a_unit_not_a_dragon": (board(dragon, tags=D, units=[("u9", "p1", "base", ["Poro"])]), "exhausted"),
        "no_other_unit": (board(dragon, tags=D), "exhausted"),
        "two_other_units_in_base": (board(base, units=[("b1", "p1", "base", None), ("b2", "p1", "base", None)]), "ready"),
        "three_other_units_in_base": (board(base, units=[("b1", "p1", "base", None), ("b2", "p1", "base", None),
                                                        ("b3", "p1", "base", None)]), "ready"),
        "one_other_unit_in_base": (board(base, units=[("b1", "p1", "base", None)]), "exhausted"),
        "two_at_a_battlefield": (board(base, units=[("b1", "p1", "bf1", None), ("b2", "p1", "bf1", None)]), "exhausted"),
        "two_cards_left_in_hand": (board(hand, hand=2), "ready"),
        "no_card_left_in_hand": (board(hand, hand=0), "ready"),
        "three_cards_left_in_hand": (board(hand, hand=3), "exhausted"),
    }
    for label, (state, want) in cases.items():
        if found := validate_state(state):
            errors.append(f"the {label} board is invalid: {found}")
            continue
        if (got := enter(state)) != want:
            errors.append(f"{label}: entered {got}, not {want} (Core 364.3.a, 369.3, 143.4)")
    # the aura: on the board, every friendly Unit has Deflect - the source too; an enemy Unit does not
    state = base_state()
    state["objects"]["src"] = unit("p1", **copy.deepcopy(aura))
    state["players"]["p1"]["zones"]["base"].append("src")
    state["objects"]["fb"] = unit("p1")
    state["players"]["p1"]["zones"]["base"].append("fb")
    state["objects"]["fx"] = unit("p1")
    state["objects"]["ex"] = unit("p2")
    state["battlefields"]["bf1"] = {"controller": None, "objects": ["fx", "ex"], "contested": True, "contested_by": "p1"}
    if found := validate_state(state):
        errors.append(f"the aura board is invalid: {found}")
    else:
        seen = {o: IR.has_keyword(state, o, "deflect") for o in ("src", "fb", "fx", "ex")}
        if seen != {"src": True, "fb": True, "fx": True, "ex": False}:
            errors.append(f"with the aura on the board, Deflect is {seen} (Core 365.1, 479.3)")
        gone = copy.deepcopy(state)
        gone["players"]["p1"]["zones"]["base"].remove("src")
        gone["players"]["p1"]["zones"]["trash"].append("src")
        if any(IR.has_keyword(gone, o, "deflect") for o in ("fb", "fx")):
            errors.append("the aura still grants Deflect with its source off the board")
    broken = board({"entry_replacements": [{"mode": "entry_state", "value": "ready",
                                            "condition": {"kind": "controls_units", "count": 1, "other": False}}]})
    if not validate_state(broken):
        errors.append("an entry condition with other: false validated")
    # `other` itself: with the card on the board (as the entry is read the card is not yet there, so the cases above
    # cannot tell), the card is not "another Dragon" and not one of the "other units"; without `other` it is counted
    on_board = board(dragon, tags=D)
    on_board["players"]["p1"]["zones"]["hand"].remove("c1")
    on_board["players"]["p1"]["zones"]["base"].append("c1")
    own = {"kind": "controls_units", "count": 1, "tag": "Dragon", "other": True}
    bare = {k: v for k, v in own.items() if k != "other"}
    seen = (IR.evaluate_condition(on_board, own, controller="p1", object_id="c1"),
            IR.evaluate_condition(on_board, bare, controller="p1", object_id="c1"))
    if seen != (False, True):
        errors.append(f"with only the card itself on the board, 'another Dragon' / 'a Dragon' read {seen}, not (False, True)")
    # mutation: the condition ignored - every exhausted case would enter ready
    saved = IR.evaluate_condition
    try:
        IR.evaluate_condition = lambda *a, **k: True
        wrong = [label for label, (state, want) in cases.items() if enter(copy.deepcopy(state)) != want]
    finally:
        IR.evaluate_condition = saved
    if sorted(wrong) != sorted(label for label, (_s, want) in cases.items() if want == "exhausted"):
        errors.append(f"mutation not caught as expected: an entry ignoring its condition was seen on {wrong}")
    if errors:
        print("FAILED: set 2 conditional entries and friendly keyword aura")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"OK: another Dragon / two or more other units in your base / two or fewer cards in hand enter ready exactly "
          f"where the condition holds as the unit enters (364.3.a, 369.3), exhausted otherwise (143.4); 'Friendly units "
          f"have [Deflect]' covers every friendly Unit and the source while it is on the board; mutation caught on "
          f"{sorted(wrong)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
