#!/usr/bin/env python3
"""The cost a Hide is taken for (package 10, Teemo - Swift Scout and Guerilla Warfare; GPT 2026-10-08 ruling 1).

A Legend's static can let its controller take a Hide for N Energy instead of the usual one Power of any Domain - one Hide,
one cost, never both (ruling 1). A spell can let its controller hide cards ignoring costs for the rest of the turn. A
declaration that names its basis is checked against it; one that names none is taken as before. A card in the trash with
the Hidden keyword can be chosen as such (with_hidden), for "return cards with [Hidden] from your trash".

  H1 alternative   the Legend with the static: a Hide for [1] Energy (cost_basis alternative_energy) commits, the Energy
                   paid, no Power
  H2 not both      the same basis declared with [1] and a Power: refused (hide_cost_mismatch)
  H3 no Legend     the basis with no such Legend: refused (hide_cost_basis_unavailable)
  H4 ignoring      after the turn effect: a Hide for nothing (cost_basis ignoring_costs) commits with an empty pool
  H5 not granted   ignoring_costs with no such effect: refused; next turn's: refused
  H6 as before     a declaration with no basis is taken exactly as before
  T1 with_hidden   return_to_hand of up to two cards from p1's trash, each with [Hidden]: the two Hidden cards return; a
                   card without Hidden named: refused as a target
  G  grammar       both productions lower; near misses do not

    python skill/scripts/check_hide_cost_basis.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_hidden import hide_declaration, hideable  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, CORE_RULESET, FAQ_AS_OF, hash_value, object_identity, validate_program  # noqa: E402
from hidden import hide_card  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def with_legend(state, energy=1):
    state["objects"]["leg"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                               "damage": 0, "exhausted": False, "hide_alternative_energy": energy}
    state["players"]["p1"]["zones"].setdefault("legend_zone", []).append("leg")
    return state


def granted(state, turn=None):
    state = copy.deepcopy(state)
    state.setdefault("turn_effects", []).append({"effect_id": "hide-free", "kind": "hide_ignoring_costs", "controller": "p1",
                                                 "value": "all", "turn_id": turn or state.get("turn_id", "turn-0"), "source": "gw"})
    return state


def main() -> int:
    s = with_legend(hideable(energy=1, power={}))
    alt = hide_card(fixture(), s, hide_declaration(cost={"base": {"energy": 1, "power": {}}}, cost_basis="alternative_energy"))
    if not alt.get("committed") or alt["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
        fail("H1 alternative", f"{alt.get('reason_code')} {alt.get('reason')}")
    both = hide_card(fixture(), with_legend(hideable(energy=1, power={"fury": 1})),
                     hide_declaration(cost={"base": {"energy": 1, "power": {"fury": 1}}}, cost_basis="alternative_energy"))
    if both.get("committed") or both.get("reason_code") != "hide_cost_mismatch":
        fail("H2 not both", both.get("reason_code"))
    none = hide_card(fixture(), hideable(energy=1, power={}),
                     hide_declaration(cost={"base": {"energy": 1, "power": {}}}, cost_basis="alternative_energy"))
    if none.get("committed") or none.get("reason_code") != "hide_cost_basis_unavailable":
        fail("H3 no Legend", none.get("reason_code"))
    free = hide_card(fixture(), granted(hideable(energy=0, power={})),
                     hide_declaration(cost={"base": {"energy": 0, "power": {}}}, cost_basis="ignoring_costs"))
    if not free.get("committed"):
        fail("H4 ignoring", f"{free.get('reason_code')} {free.get('reason')}")
    for label, state in (("no effect", hideable(energy=0, power={})), ("next turn's", granted(hideable(energy=0, power={}), "turn-later"))):
        refused = hide_card(fixture(), state, hide_declaration(cost={"base": {"energy": 0, "power": {}}}, cost_basis="ignoring_costs"))
        if refused.get("committed") or refused.get("reason_code") != "hide_cost_basis_unavailable":
            fail("H5 not granted", f"{label}: {refused.get('reason_code')}")
    plain = hide_card(fixture(), hideable(), hide_declaration())
    if not plain.get("committed"):
        fail("H6 as before", f"{plain.get('reason_code')} {plain.get('reason')}")
    # T1: cards with [Hidden] chosen from the trash
    t = hideable()
    for oid, hidden in (("th1", True), ("th2", True), ("tn", False)):
        t["objects"][oid] = {**copy.deepcopy(t["objects"]["c2"]), **({"hidden": True} if hidden else {})}
        t["objects"][oid].pop("hidden", None) if not hidden else None
        t["players"]["p1"]["zones"]["trash"].append(oid)

    def returned(picks):
        effect = {"op": "return_to_hand", "effect_id": "rt",
                  "targets": {"min": 0, "max": 2, "decision_ref": "t", "restrictions": {"location": "trash", "with_hidden": True,
                                                                                     "zone_owner_relation": "own"}}}
        program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "program_id": "gw", "controller": "p1", "effects": [effect]}
        if validate_program(program):
            return f"invalid: {validate_program(program)}"
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(t), "decisions": [
            {"decision_id": "t", "kind": "target_selection", "stage": "play_declaration", "controller": "p1", "value": picks,
             "selection_identities": {o: object_identity(t, o) for o in picks}}]}
        return apply_program(t, program, decisions=decisions)
    ok = returned(["th1", "th2"])
    if not isinstance(ok, dict) or not ok.get("committed") or not {"th1", "th2"} <= set(ok["next_state"]["players"]["p1"]["zones"]["hand"]):
        fail("T1 with_hidden", ok if not isinstance(ok, dict) else (ok.get("reason") or ok.get("errors")))
    bad = returned(["tn"])
    if isinstance(bad, dict) and bad.get("committed") and "tn" in bad["next_state"]["players"]["p1"]["zones"]["hand"]:
        fail("T1 with_hidden", "a card without Hidden was returned")
    grammar = cg.load_grammar()
    for text, pid in (("You may pay :rb_energy_1: to hide a card with [Hidden] instead of :rb_rune_rainbow:.",
                       "you_may_pay_energy_to_hide_a_card_with_hidden_instead_of_power_any"),
                      ("You can hide cards ignoring costs this turn.", "you_can_hide_cards_ignoring_costs_this_turn")):
        if cg.compile_clause(text, grammar).get("production_id") != pid:
            fail("G grammar", f"{text!r} does not lower to {pid}")
    for near in ("You may pay :rb_energy_1: to hide a card.", "You can play cards ignoring costs this turn."):
        if cg.compile_clause(near, grammar).get("production_id") in ("you_may_pay_energy_to_hide_a_card_with_hidden_instead_of_power_any",
                                                                     "you_can_hide_cards_ignoring_costs_this_turn"):
            fail("G grammar", f"{near!r} lowered to a row")
    if errors:
        print("FAILED: hide cost basis checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a Hide's cost basis - the Legend's Energy instead of [A] (never both), nothing while 'ignoring costs' this "
          "turn, as before with no basis; cards with [Hidden] chosen from the trash (H1-H6, T1, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
