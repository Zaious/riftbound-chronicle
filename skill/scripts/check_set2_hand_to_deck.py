#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "put a card from your hand on the top or bottom of your Main Deck" (Altar of
Memories) - choose_option top/bottom, then hand_to_deck under only_if_chose.

  H1 top     the player picks top and a card of their hand: it is the Main Deck's first card, a new object (Core 124), the
             rest of the hand and deck in order; one put_on_deck event naming the player and the position
  H2 bottom  the same with bottom: it is the deck's last card
  H3 private no card decision: the instruction stops for the player's own card_selection (private, Core 355.10.a);
             a decision naming a card outside the hand is refused
  H4 empty   an empty hand: nothing moves, the program still commits
  V          a position other than top or bottom, or an unknown player, is refused

    python skill/scripts/check_set2_hand_to_deck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "altar", "controller": "p1", "effects": effects}


ALTAR = [{"op": "choose_option", "effect_id": "pick", "by": "controller", "options": ["top", "bottom"], "record": "pos",
          "decision_ref": "pos"},
         {"op": "hand_to_deck", "effect_id": "top", "player": "p1", "position": "top", "decision_ref": "c-top",
          "only_if_chose": {"record": "pos", "option": "top"}},
         {"op": "hand_to_deck", "effect_id": "bottom", "player": "p1", "position": "bottom", "decision_ref": "c-bottom",
          "only_if_chose": {"record": "pos", "option": "bottom"}}]


def board(hand=("h1", "h2")):
    state = base_state()
    zones = state["players"]["p1"]["zones"]
    zones["hand"] = []
    for c in hand:
        state["objects"][c] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
        zones["hand"].append(c)
    return state


def decide(state, position, card):
    entries = [{"decision_id": "pos", "stage": "resolution", "kind": "option_selection", "controller": "p1", "value": position}]
    if card is not None:
        entries.append({"decision_id": f"c-{position}", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                        "value": [card], "selection_identities": {card: object_identity(state, card) or f"{card}@0"}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": entries}


def main() -> int:
    for label, position in (("H1", "top"), ("H2", "bottom")):
        state = board()
        deck = list(state["players"]["p1"]["zones"]["main_deck"])
        before = object_identity(state, "h2")
        done = apply_program(state, program(ALTAR), decisions=decide(state, position, "h2"))
        if not done.get("committed"):
            fail(label, f"refused: {done.get('reason_code') or done.get('errors') or done.get('reason')}")
            continue
        z = done["next_state"]["players"]["p1"]["zones"]
        want = ["h2"] + deck if position == "top" else deck + ["h2"]
        if z["main_deck"] != want or z["hand"] != ["h1"]:
            fail(label, f"deck {z['main_deck']} (want {want}), hand {z['hand']}")
        if object_identity(done["next_state"], "h2") == before:
            fail(label, "the card kept its identity (Core 124)")
        events = [e for e in done.get("events") or [] if e.get("kind") == "put_on_deck"]
        if len(events) != 1 or events[0].get("object") != "h2" or events[0].get("position") != position:
            fail(label, f"events {[(e.get('kind'), e.get('object'), e.get('position')) for e in done.get('events') or []]}")
    state = board()
    done = apply_program(state, program(ALTAR), decisions=decide(state, "top", None))
    if done.get("committed") or not done.get("choice_required"):
        fail("H3", f"no card decision: {done.get('committed')} {done.get('reason_code')}")
    stray = decide(state, "top", "h2")
    stray["decisions"][1]["value"] = ["c1"]
    stray["decisions"][1]["selection_identities"] = {"c1": object_identity(state, "c1")}
    if apply_program(state, program(ALTAR), decisions=stray).get("committed"):
        fail("H3", "a card outside the hand was accepted")
    empty = board(hand=())
    done = apply_program(empty, program(ALTAR), decisions=decide(empty, "bottom", None))
    if not done.get("committed") or done["next_state"]["players"]["p1"]["zones"]["main_deck"] != empty["players"]["p1"]["zones"]["main_deck"]:
        fail("H4", f"an empty hand: {done.get('committed')} {done.get('reason_code')}")
    for label, bad in (("position middle", {**ALTAR[1], "position": "middle"}), ("unknown player", {**ALTAR[1], "player": "p9"})):
        state = board()
        if apply_program(state, program([ALTAR[0], bad]), decisions=decide(state, "top", "h2")).get("committed"):
            fail("V", f"{label} committed")
    if errors:
        print("FAILED: set 2 hand_to_deck")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a card of the player's own hand, chosen privately as it resolves, goes on the top or bottom of their Main "
          "Deck as they picked - a new object with its own event; nothing chosen stops for the choice; an empty hand moves nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
