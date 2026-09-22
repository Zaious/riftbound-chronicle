#!/usr/bin/env python3
"""Regression gate for Legend activation (Core 174.8; GPT ruling 2026-09-22, option B).

The Legend Zone stays non-board and is no Location (107.4.b, ADR-0012, check_legends).
Exactly two narrow paths are added: a Legend is an activation source from its
controller's Legend Zone, and that Legend can pay its own exhaust cost there.

Must hold:
  - a ready Legend activates its ability from its Legend Zone: the play commits, the
    Legend is exhausted, the Energy is spent, the ability is on the Chain;
  - negatives: an already exhausted Legend cannot pay (414.1); a non-Legend is not
    activated from anywhere but the board (a Unit in hand); an opponent's Legend is not
    the actor's to activate; a card PLAY whose cost names the Legend is not an activation
    and cannot exhaust it;
  - the board selector universe is untouched: an effect exhausting the Legend through a
    board selector is refused, and so is readying it;
  - mutation: without the Legend-source path the same activation is refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def legend_board(*, exhausted=False, owner="p1"):
    state = base_state()
    state["objects"]["l1"] = {"owner": owner, "controller": owner, "kind": "legend", "base_might": 0,
                              "might_modifiers": [], "damage": 0, "exhausted": exhausted}
    state["players"][owner]["zones"].setdefault("legend_zone", []).append("l1")
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    return state


BUFF = program("l1-ability", {"op": "buff", "effect_id": "bf", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}})


def activation(card="l1", *, kind="ability"):
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "act-1", "actor": "p1", "card": card,
            "chain_item": {"id": "ability-1", "object_kind": kind, "timing": "default", "ability_kind": "standard"},
            "activation": {"source_object": card, "ability_id": f"{card}:a1"},
            "cost": {"base": {"energy": 1, "power": {}},
                     "additional": [{"cost_id": "tap", "mandatory": True, "payment": {"kind": "exhaust", "object_id": card}}]},
            "effect_program_id": "l1-ability", "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def target(state):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"],
         "selection_identities": {"u1": object_identity(state, "u1") or "u1@0"}}]}


def main() -> int:
    errors: list[str] = []
    state = legend_board()
    if validate_state(state):
        errors.append(f"the Legend board is invalid: {validate_state(state)}")
    ok = PT.play_card(fixture(), state, activation(), engine_decisions=target(state), effect_program=BUFF)
    if not ok.get("committed"):
        errors.append(f"a ready Legend did not activate from its Legend Zone: {ok.get('reason_code')} {ok.get('reason')}")
    else:
        after = ok["next_effect_state"]
        if not after["objects"]["l1"]["exhausted"] or after["players"]["p1"]["resources"]["energy"] != 0:
            errors.append("the Legend's costs were not paid (exhausted, 1 Energy)")
        if [i["id"] for i in ok["next_timing_state"]["chain"]["items"]] != ["ability-1"]:
            errors.append("the Legend's ability is not on the Chain")
        if validate_state(after):
            errors.append(f"the state after a Legend activation is invalid: {validate_state(after)}")

    # negatives -------------------------------------------------------------------------------
    tired = legend_board(exhausted=True)
    got = PT.play_card(fixture(), tired, activation(), engine_decisions=target(tired), effect_program=BUFF)
    if got.get("committed") or got.get("reason_code") != "cost_unpayable":
        errors.append(f"an exhausted Legend paid its exhaust cost: {got.get('reason_code')}")
    in_hand = legend_board()
    in_hand["players"]["p1"]["zones"]["main_deck"].remove("c1")
    in_hand["players"]["p1"]["zones"]["hand"].append("c1")
    in_hand["objects"]["c1"]["kind"] = "unit"
    got = PT.play_card(fixture(), in_hand, activation("c1"), engine_decisions=target(in_hand), effect_program=BUFF)
    if got.get("committed") or got.get("reason_code") != "activation_source_not_on_board":
        errors.append(f"a non-Legend was activated from off the board: {got.get('reason_code')}")
    theirs = legend_board(owner="p2")
    theirs["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    got = PT.play_card(fixture(), theirs, activation(), engine_decisions=target(theirs), effect_program=BUFF)
    if got.get("committed"):
        errors.append("p1 activated p2's Legend")
    play = legend_board()
    play["players"]["p1"]["zones"]["main_deck"].remove("c1")
    play["players"]["p1"]["zones"]["hand"].append("c1")
    spell = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
             "play_id": "play-1", "actor": "p1", "card": "c1",
             "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
             "cost": {"base": {"energy": 1, "power": {}},
                      "additional": [{"cost_id": "tap", "mandatory": True, "payment": {"kind": "exhaust", "object_id": "l1"}}]},
             "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    got = PT.play_card(fixture(), play, spell)
    if got.get("committed"):
        errors.append("a card play exhausted a Legend as its cost; only the Legend's own activation may")

    # the board selector universe is untouched ------------------------------------------------
    for op in ("exhaust", "ready"):
        via_board = apply_program(legend_board(exhausted=(op == "ready")), program("fx", {"op": op, "effect_id": "x", "object_id": "l1",
                                                                                        "target": {"object_id": "l1", "chosen_zone_class": "board"}}))
        if via_board.get("committed") and (via_board.get("trace") or [{}])[0].get("outcome") == "applied":
            errors.append(f"an effect {op}ed the Legend through a board selector")

    # mutation: no Legend-source path, no activation --------------------------------------------
    saved = PT.legend_activation_source
    try:
        PT.legend_activation_source = lambda *_a, **_k: False
        again = PT.play_card(fixture(), state, activation(), engine_decisions=target(state), effect_program=BUFF)
    finally:
        PT.legend_activation_source = saved
    if again.get("committed"):
        errors.append("mutation not caught: without the Legend-source path the Legend still activated")

    if errors:
        print("FAILED: Legend activation checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a ready Legend activates from its Legend Zone and pays its own exhaust cost (Core 174.8, 414.1); an "
          "exhausted Legend, a non-Legend off the board, an opponent's Legend and a card play naming the Legend are "
          "refused; board selectors still cannot exhaust or ready it; removing the path is caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
