#!/usr/bin/env python3
"""Regression gate for a card's own Energy reduction read off the board as its cost is
determined (Core 356.4, 356.4.b, 356.4.e, 356.6; 428.1).

Sky Splitter, "This spell's Energy cost is reduced by the highest Might among units you
control." (Core 356.4.e and 206 use this very card; 8 Energy):
  - through the real play transaction: p1's Units at Might 4, 4, 2 take 4 off - paid with 4,
    and 3 Energy cannot pay; no Unit takes nothing off;
  - the Might is the Unit's Might as the layers compute it (a +3 modifier on a 4 makes 7), a
    Unit in its Base counts (355.9.a.1: a unit is on the board, Base or Battlefield), and a
    9-Might Unit brings the cost to 0, not below (356.6);
  - an opponent's Units do not count; a Unit card in the trash does not count;
  - 356.4.e's own example: a declared reduction of 1 to a minimum of 1 applied first, then a
    7-Might Unit - the cost is 0;
  - mutations: without the per-each the reduction is 1; the per-each shape is closed.

Spoils of War, "If an enemy unit has died this turn, this costs [2] less." (4 Energy):
  - the Kill action counts a Unit's death for its controller as it died, per turn (428.1):
    an enemy Unit killed this turn makes the cost 2; a token killed counts (it died, then
    ceased to exist, 186.1); a Unit killed by lethal damage in a Cleanup counts (428.4);
  - no death, only a friendly death, a death last turn, a Unit returned to its owner's hand,
    and a Gear killed are not "an enemy unit has died this turn" - the cost stays 4;
  - the leaf needs a controller_relation and a controller to ask for.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (ConditionUnsupported, apply_program, evaluate_condition, perform_lethal_cleanup,  # noqa: E402
                       validate_condition, validate_state)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SKY = "This spell's Energy cost is reduced by the highest Might among units you control."
SPOILS = "If an enemy unit has died this turn, this costs :rb_energy_2: less."


def lowered(text):
    got = CG.compile_clause(text, CG.load_grammar())
    return (got.get("passive") or {}).get("object_fields") or {}, got.get("production_id")


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False, **extra}


def board(fields, energy, *, units=(), their_units=(), trash_units=(), gear=()):
    """p1 holds the card c1 (a spell) in hand. `units` / `their_units`: (id, Might, where) with
    where 'base' or 'bf1'."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update(copy.deepcopy(fields))
    for owner in ("p1", "p2"):          # the fixture's own units leave; each case places its own
        state["players"][owner]["zones"]["base"] = []
    del state["objects"]["u1"], state["objects"]["u2"]
    for owner, rows in (("p1", units), ("p2", their_units)):
        for oid, might, where in rows:
            state["objects"][oid] = unit(owner, might)
            if where == "base":
                state["players"][owner]["zones"]["base"].append(oid)
            else:
                state["battlefields"]["bf1"]["objects"].append(oid)
    for oid, might in trash_units:
        state["objects"][oid] = unit("p1", might)
        state["players"]["p1"]["zones"]["trash"].append(oid)
    for oid, owner in gear:
        state["objects"][oid] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": False}
        state["players"][owner]["zones"]["base"].append(oid)
    bf = state["battlefields"]["bf1"]
    sides = {state["objects"][o]["controller"] for o in bf["objects"]}
    if sides:
        bf["controller"] = "p1" if "p1" in sides else "p2"
        if len(sides) > 1:
            bf["contested"], bf["contested_by"] = True, "p2"
    state["players"]["p1"]["resources"] = {"energy": energy, "power": {}}
    return state


def play(state, energy_cost, *, discounts=None):
    cost = {"base": {"energy": energy_cost, "power": {}}}
    if discounts:
        cost["discounts"] = discounts
    return PT.play_card(fixture(), state, {
        "schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": "play-1", "actor": "p1", "card": "c1",
        "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
        "cost": cost, "payment_context": {"add_window_closed": True, "confirmed_by": "human"}})


def left(result):
    return result["next_effect_state"]["players"]["p1"]["resources"]["energy"] if result.get("committed") else None


def run(state, *effects):
    got = apply_program(state, program("setup", *effects))
    if not got.get("committed"):
        raise AssertionError(f"setup program did not commit: {got.get('reason') or got.get('errors')}")
    return got["next_state"]


def main() -> int:
    errors: list[str] = []
    sky, sky_pid = lowered(SKY)
    spoils, spoils_pid = lowered(SPOILS)
    if sky_pid != "self_cost_reduction_highest_might" or spoils_pid != "self_cost_reduction_unit_died":
        errors.append(f"the engine grammar did not lower the two sentences: {sky_pid}, {spoils_pid}")

    # --- Sky Splitter ---------------------------------------------------------------------------
    base_units = (("a", 4, "bf1"), ("b", 4, "bf1"), ("c", 2, "base"))
    for label, state, paid_with, want_left in (
            ("4, 4, 2", board(sky, 8, units=base_units), 8, 4),
            ("no Unit", board(sky, 8), 8, 0),
            ("a 9 in Base (356.6)", board(sky, 8, units=(("a", 9, "base"),)), 8, 8),
            ("an opponent's 9", board(sky, 8, units=(("a", 2, "bf1"),), their_units=(("z", 9, "bf1"),)), 8, 2),
            ("a 9 in the trash", board(sky, 8, units=(("a", 3, "base"),), trash_units=(("t", 9),)), 8, 3)):
        if validate_state(state):
            errors.append(f"Sky Splitter board '{label}' is invalid: {validate_state(state)[:2]}")
            continue
        got = play(state, 8)
        if left(got) != want_left:
            errors.append(f"Sky Splitter, {label}: paid with {paid_with}, {left(got)} left, wanted {want_left} "
                          f"({got.get('reason_code')} {got.get('reason')})")
    short = play(board(sky, 3, units=base_units), 8)
    if short.get("committed") or short.get("reason_code") != "cost_unpayable":
        errors.append(f"Sky Splitter: 3 Energy paid a cost of 4: {short.get('reason_code')}")
    modified = board(sky, 8, units=(("a", 4, "bf1"),))
    modified = run(modified, {"op": "modify_might", "effect_id": "m", "object_id": "a", "amount": 3,
                              "duration": "this_turn", "source": "a"})
    if left(play(modified, 8)) != 7:
        errors.append(f"Sky Splitter: a 4-Might Unit given +3 did not take 7 off (the layered Might): {left(play(modified, 8))}")
    # 356.4.e: "reduced by 1, to a minimum of 1" first (declared), then the 7-Might Unit: 0
    eager = board(sky, 8, units=(("a", 7, "bf1"),))
    got = play(eager, 8, discounts=[{"id": "eager", "applies_to": "energy", "amount": 1, "minimum": 1}])
    if left(got) != 8:
        errors.append(f"Sky Splitter, 356.4.e: a 1-to-minimum-1 reduction then a 7-Might Unit did not make the cost 0: "
                      f"{left(got)} left ({got.get('reason_code')})")
    flat = board({"printed_cost_modifications": [{"modification_id": "own-text", "kind": "energy_reduction", "amount": 1}]},
                 8, units=base_units)
    if left(play(flat, 8)) == 4:
        errors.append("mutation not caught: a flat reduction of 1 took as much off as the highest Might")
    widened = board(sky, 8, units=base_units)
    widened["objects"]["c1"]["printed_cost_modifications"][0]["per_each"]["player"] = "p2"
    if not validate_state(widened):
        errors.append("a highest-Might per-each naming another player was accepted; the shape is closed")

    # --- Spoils of War --------------------------------------------------------------------------
    def spoils_board():
        state = board(spoils, 4, units=(("f", 3, "bf1"),), their_units=(("e", 3, "bf1"),),
                      gear=(("g2", "p2"),))
        state["turn_id"] = "turn-7"
        return state

    enemy_token = spoils_board()
    enemy_token["objects"]["e"]["is_token"] = True
    lethal = spoils_board()
    lethal["objects"]["e"]["damage"] = 3
    lethal_done = perform_lethal_cleanup(lethal)
    last_turn = run(spoils_board(), {"op": "kill", "effect_id": "k", "object_id": "e"})
    last_turn["turn_id"] = "turn-8"
    cases = [
        ("no death", spoils_board(), 4),
        ("an enemy Unit killed this turn", run(spoils_board(), {"op": "kill", "effect_id": "k", "object_id": "e"}), 2),
        ("an enemy token killed this turn", run(enemy_token, {"op": "kill", "effect_id": "k", "object_id": "e"}), 2),
        ("an enemy Unit dead of lethal damage in a Cleanup", lethal_done.get("next_state"), 2),
        ("only a friendly Unit killed", run(spoils_board(), {"op": "kill", "effect_id": "k", "object_id": "f"}), 4),
        ("an enemy Unit killed last turn", last_turn, 4),
        ("an enemy Unit returned to hand", run(spoils_board(), {"op": "return_to_hand", "effect_id": "r", "object_id": "e"}), 4),
        ("an enemy Gear killed", run(spoils_board(), {"op": "kill", "effect_id": "k", "object_id": "g2"}), 4),
    ]
    for label, state, want_cost in cases:
        if state is None or validate_state(state):
            errors.append(f"Spoils of War '{label}': the board is invalid: {state and validate_state(state)[:2]}")
            continue
        got = play(state, 4)
        if left(got) != 4 - want_cost:
            errors.append(f"Spoils of War, {label}: cost {4 - (left(got) or 0) if got.get('committed') else '?'}, wanted {want_cost} "
                          f"({got.get('reason_code')} {got.get('reason')})")
    friendly = copy.deepcopy(spoils)
    friendly["printed_cost_modifications"][0]["condition"]["controller_relation"] = "friendly"
    only_friend = run(spoils_board(), {"op": "kill", "effect_id": "k", "object_id": "f"})
    only_friend["objects"]["c1"].update(copy.deepcopy(friendly))
    if left(play(only_friend, 4)) != 2:
        errors.append("the leaf's friendly side did not read a friendly Unit's death")
    if validate_condition({"kind": "unit_died_this_turn"}) == []:
        errors.append("unit_died_this_turn without a controller_relation was accepted")
    try:
        evaluate_condition(spoils_board(), {"kind": "unit_died_this_turn", "controller_relation": "enemy"})
        errors.append("unit_died_this_turn was answered with no controller to ask for")
    except ConditionUnsupported:
        pass
    forged = spoils_board()
    forged["players"]["p2"]["units_died_this_turn"] = {"turn-7": 0}
    if not validate_state(forged):
        errors.append("a zero death count was accepted; the ledger holds positive counts only")

    if errors:
        print("FAILED: cost read off the board" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Sky Splitter's Energy cost falls by the highest layered Might among its player's Units on the board "
          "(Base or Battlefield), never below 0 (356.6), after a declared minimum-1 reduction as in 356.4.e; an "
          "opponent's Units and a Unit card in the trash do not count. Spoils of War costs 2 less once an enemy Unit "
          "died this turn - by a kill, as a token, or in a Cleanup - and not for a friendly death, last turn's death, a "
          "return to hand or a Gear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
