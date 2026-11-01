#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): two printed statics of a card about itself.

"I have [Assault] equal to the number of enemy units here." (Ancient Warmonger) - dynamic_keywords: a summed keyword
whose value is a count read as the board is now (Core 365.1, 807.2, 479.4.b).

  A1 two enemies here     the card at bf1 with two enemy Units there has Assault 2
  A2 none                 no enemy Unit there: no Assault; in its Base: none
  A3 friendly units       friendly Units there are not counted

"If you've spent at least [A][A] this turn, I have +2 [M] and [Ganking]." (Sivir - Mercenary) - a condition on the
controller's per-turn Power ledger, which every Power payment writes.

  S1 not yet              one Power spent this turn: base Might, no Ganking
  S2 two                  two spent: +2 Might and Ganking
  S3 another turn         two spent in an earlier turn: nothing
  S4 the ledger           a play paying two Power writes 2 for its player this turn, in a game with a card that reads
                          it (one in the trash will do); Energy writes nothing
  S5 no reader            the same play in a game no card of which reads the ledger writes nothing: the state is the
                          one it was before set 2
  V                       a malformed dynamic keyword, or a ledger entry of 0, does not validate

    python skill/scripts/check_set2_counted_keywords_and_power_spent.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (DEFAULT_TURN_ID, characteristics, effective_might, power_spent_this_turn,  # noqa: E402
                       record_power_spent, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
WARMONGER = [{"modifier_id": "own-text-assault", "keyword": "assault", "per": {"kind": "enemy_units_at_source_battlefield"}}]
SPENT = {"kind": "power_spent_this_turn_at_least", "count": 2}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might=2, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def warmonger_board(enemies=2, friends=0, where="bf1"):
    state = base_state()
    state["objects"]["wm"] = unit("p1", 3, dynamic_keywords=copy.deepcopy(WARMONGER))
    if where == "bf1":
        state["battlefields"]["bf1"]["objects"].append("wm")
    else:
        state["players"]["p1"]["zones"]["base"].append("wm")
    for i in range(enemies):
        state["objects"][f"e{i}"] = unit("p2")
        state["battlefields"]["bf1"]["objects"].append(f"e{i}")
    for i in range(friends):
        state["objects"][f"f{i}"] = unit("p1")
        state["battlefields"]["bf1"]["objects"].append(f"f{i}")
    settle_contested(state)
    return state


def sivir_board(spent=0, turn=None):
    state = base_state()
    state["objects"]["sv"] = unit("p1", 4, conditional_might=[{"modifier_id": "clause", "amount": 2, "condition": dict(SPENT)}],
                                  conditional_keywords=[{"modifier_id": "own-text-ganking", "keyword": "ganking",
                                                         "condition": dict(SPENT)}])
    state["players"]["p1"]["zones"]["base"].append("sv")
    if spent:
        state["players"]["p1"]["power_spent_this_turn"] = {turn or state.get("turn_id", DEFAULT_TURN_ID): spent}
    return state


def main() -> int:
    for label, state, want in (("A1", warmonger_board(2), 2), ("A2 none", warmonger_board(0), None),
                               ("A2 base", warmonger_board(2, where="base"), None), ("A3", warmonger_board(1, friends=2), 1)):
        problems = validate_state(state)
        if problems:
            fail(label, f"board invalid: {problems[:2]}")
            continue
        got = characteristics(state, "wm")["keywords"].get("assault")
        if got != want:
            fail(label, f"Assault {got}, expected {want}")
    for label, state, might, ganking in (("S1", sivir_board(1), 4, False), ("S2", sivir_board(2), 6, True),
                                         ("S3", sivir_board(2, turn="turn-earlier"), 4, False)):
        problems = validate_state(state)
        if problems:
            fail(label, f"board invalid: {problems[:2]}")
            continue
        keywords = characteristics(state, "sv")["keywords"]
        if effective_might(state, "sv") != might or ("ganking" in keywords) != ganking:
            fail(label, f"Might {effective_might(state, 'sv')}, keywords {keywords}")
    def paying_board(reader):
        board = base_state()
        board["players"]["p1"]["zones"]["main_deck"].remove("c1")
        board["players"]["p1"]["zones"]["hand"].append("c1")
        board["objects"]["c1"].update(kind="unit", base_might=2)
        board["players"]["p1"]["resources"] = {"energy": 1, "power": {"fury": 2}}
        if reader:
            board["objects"]["sv"] = sivir_board()["objects"]["sv"]
            board["players"]["p2"]["zones"]["trash"].append("sv")
        return board
    state = paying_board(True)
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {"fury": 2}}}, "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    played = play_card(fixture(), state, decl)
    if not played.get("committed") or power_spent_this_turn(played["next_effect_state"], "p1") != 2 \
            or power_spent_this_turn(played["next_effect_state"], "p2") != 0:
        fail("S4", f"{played.get('reason_code')} {played.get('reason')} "
                   f"{(played.get('next_effect_state') or {}).get('players', {}).get('p1', {}).get('power_spent_this_turn')}")
    quiet = play_card(fixture(), paying_board(False), decl)
    if not quiet.get("committed") or any("power_spent_this_turn" in p for p in quiet["next_effect_state"]["players"].values()):
        fail("S5", f"a game with no reader wrote the ledger: {quiet.get('reason_code')}")
    energy_only = base_state()
    record_power_spent(energy_only, "p1", 0)
    if "power_spent_this_turn" in energy_only["players"]["p1"]:
        fail("S4 zero", "a payment of no Power wrote the ledger")
    bad = warmonger_board(1)
    bad["objects"]["wm"]["dynamic_keywords"][0]["keyword"] = "ganking"
    if not validate_state(bad):
        fail("V keyword", "an unsummed dynamic keyword validated")
    zero = sivir_board(2)
    zero["players"]["p1"]["power_spent_this_turn"] = {DEFAULT_TURN_ID: 0}
    if not validate_state(zero):
        fail("V ledger", "a ledger entry of 0 validated")
    if errors:
        print("FAILED: set 2 counted keywords and Power spent this turn")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: Assault equal to the enemy Units here, read as the board is now (none in a Base, friends not counted); "
          "+2 Might and Ganking once two Power were spent this turn, off the ledger every Power payment writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
