#!/usr/bin/env python3
"""Regression gate: a card's own Energy reduction read off a count, with a printed minimum (set 2 package A2).

Two counts beside the trash count and the highest Might (check_self_cost_reduction, check_cost_from_board):

  C1  per card its player has Finalized this turn (Core 420.4.b): none played, the printed cost; two, two less; the
      card being played is not among them (it is Finalized after its cost is paid)
  C2  "to a minimum of N" (Core 356.4.e): the reduction stops at N however many cards were played
  C3  per Mighty Unit its player controls on the board (Core 708: Might 5 or more): a 4-Might Unit and an opponent's
      Mighty Unit are not counted
  C4  the payment path and the enumeration agree on the reduced cost (the enumeration evaluates a per-each count as the
      payment does - before, one with no condition was counted once)
  V1  a minimum that is not a non-negative number, and a per-each over any other count, are refused by the validator
  V2  the clause grammar lowers both printed forms to exactly these fields

The fixture cards are synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import legal_action as la  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

PLAYED = {"kind": "cards_finalized_this_turn"}
MIGHTY = {"kind": "units_you_control", "mighty": True}


def state_with(modification, *, energy=5, pool=5, played=(), units=()):
    """A synthetic spell in hand whose own text reduces its Energy cost; `played` the cards p1 Finalized this turn,
    `units` (controller, Might) on p1's Base."""
    state = base_state()
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": pool, "power": {}}
    for oid in played:
        if oid not in state["objects"]:
            state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                     "might_modifiers": [], "damage": 0, "exhausted": False}
            state["players"]["p1"]["zones"]["trash"].append(oid)
    state["players"]["p1"]["cards_finalized_this_turn"] = {"turn-3": list(played)}
    for i, (controller, might) in enumerate(units):
        oid = f"m{i}"
        state["objects"][oid] = {"owner": controller, "controller": controller, "kind": "unit", "base_might": might,
                                 "might_modifiers": [], "damage": 0, "exhausted": False}
        state["players"][controller]["zones"]["base"].append(oid)
    state["objects"]["c1"].update({"kind": "spell", "printed_cost": {"energy": energy, "power": {}},
                                   "printed_cost_modifications": [copy.deepcopy(modification)], "play_timing": "action"})
    return state


def declaration(energy=5):
    return {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "action"},
            "cost": {"base": {"energy": energy, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def paid(state):
    played = pt.play_card(fixture(), state, declaration(state["objects"]["c1"]["printed_cost"]["energy"]))
    if not played.get("committed"):
        return f"refused: {played.get('reason_code')}"
    return next((c["final"] for c in played["cost_receipt"]["components"] if c["cost_id"] == "base:energy"), None)


def enumerated(state):
    obj = state["objects"]["c1"]
    return la._cost_total({"base": obj["printed_cost"]}, effect_state=state, card_id="c1", actor="p1")


def main() -> int:
    errors: list[str] = []
    per_card = {"modification_id": "own-text", "kind": "energy_reduction", "amount": 1, "per_each": PLAYED}
    floored = {**per_card, "minimum": 1}
    per_mighty = {"modification_id": "own-text", "kind": "energy_reduction", "amount": 2, "per_each": MIGHTY}

    # C1
    for played, want in (((), 5), (("x1", "x2"), 3)):
        got = paid(state_with(per_card, played=played))
        if got != want:
            errors.append(f"C1: {len(played)} card(s) played this turn, paid {got}, not {want}")
    # C2
    for played, want in ((("x1", "x2"), 3), (tuple(f"x{i}" for i in range(7)), 1)):
        got = paid(state_with(floored, played=played))
        if got != want:
            errors.append(f"C2: minimum 1 with {len(played)} played, paid {got}, not {want}")
    # C3
    got = paid(state_with(per_mighty, energy=6, pool=6, units=(("p1", 5), ("p1", 4), ("p2", 7))))
    if got != 4:
        errors.append(f"C3: one Mighty unit of p1's (a 4-Might one and p2's Mighty one not counted), paid {got}, not 4")
    # C4
    for label, state in (("per card", state_with(floored, played=("x1", "x2", "x3"))),
                         ("per mighty", state_with(per_mighty, energy=6, pool=6, units=(("p1", 6), ("p1", 5))))):
        total, payment = enumerated(state), paid(state)
        energy = (total[0] if isinstance(total, tuple) else total).get("energy")
        if energy != payment:
            errors.append(f"C4 {label}: enumeration {energy} and payment {payment} disagree")
    # V1
    for label, change in (("a negative minimum", {**floored, "minimum": -1}), ("a minimum not a number", {**floored, "minimum": "1"}),
                          ("a per-each over spells played", {**per_card, "per_each": {"kind": "spells_finalized_this_turn"}}),
                          ("a Mighty count of the opponent's", {**per_mighty, "per_each": {"kind": "units_you_control", "mighty": True,
                                                                                           "controller_relation": "enemy"}})):
        if not any("printed_cost_modifications" in e for e in validate_state(state_with(change))):
            errors.append(f"V1: {label} was not refused")
    for label, mod in (("per card", floored), ("per mighty", per_mighty)):
        problems = [e for e in validate_state(state_with(mod)) if "printed_cost_modifications" in e]
        if problems:
            errors.append(f"V1: the {label} reduction was refused: {problems[:1]}")
    # V2
    grammar = CG.load_grammar()
    for text, want in (("I cost :rb_energy_1: less for each card you've played this turn, to a minimum of :rb_energy_1:.",
                        floored),
                       ("I cost :rb_energy_2: less for each of your [Mighty] units.", per_mighty)):
        fields = ((CG.compile_clause(text, grammar).get("passive") or {}).get("object_fields") or {}).get(
            "printed_cost_modifications")
        if fields != [want]:
            errors.append(f"V2: {text!r} lowered to {fields}, not {[want]}")

    if errors:
        print("self cost count checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("self cost count checks passed: per card played this turn (the card itself not among them), floored at the "
          "printed minimum, per Mighty unit of its player's; payment and enumeration agree; other counts refused; the "
          "grammar lowers both printed forms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
