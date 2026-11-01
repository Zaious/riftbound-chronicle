#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "put the top N cards of your Main Deck into your trash" (Minefield) - op trash_top.

  T1 the top 2 of a 3-card Main Deck go to the player's trash, in order; the third stays; the hand is untouched; each card
     is a new object (Core 124); one put_into_trash event per card, naming the player
  T2 a deck of 1 asked for 2: the one card goes, then the player Burns Out (Core 432.1.b) - the trash recycled in the
     order of a randomization receipt (none supplied: external input required, nothing changed), then the rest follows
  T3 another player's deck is not touched; an unknown player or a count below 1 is refused

    python skill/scripts/check_set2_trash_top.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, object_identity  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "mill", "controller": "p1", "effects": effects}


def card(owner):
    return {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(deck):
    state = base_state()
    zones = state["players"]["p1"]["zones"]
    for c in list(zones["main_deck"]):
        zones["main_deck"].remove(c)
        zones["hand"].append(c)
    for c in deck:
        state["objects"][c] = card("p1")
        zones["main_deck"].append(c)
    return state


MILL2 = [{"op": "trash_top", "effect_id": "tt", "player": "p1", "count": 2}]


def main() -> int:
    # T1
    state = board(["d1", "d2", "d3"])
    hand, trash = list(state["players"]["p1"]["zones"]["hand"]), list(state["players"]["p1"]["zones"]["trash"])
    ids = {c: object_identity(state, c) for c in ("d1", "d2")}
    done = apply_program(state, program(MILL2))
    if not done.get("committed"):
        fail("T1", f"refused: {done.get('errors') or done.get('reason')}")
    else:
        z = done["next_state"]["players"]["p1"]["zones"]
        if z["main_deck"] != ["d3"] or z["trash"] != trash + ["d1", "d2"] or z["hand"] != hand:
            fail("T1", f"deck {z['main_deck']}, trash {z['trash']}, hand {z['hand']}")
        if any(object_identity(done["next_state"], c) == ids[c] for c in ids):
            fail("T1", "a card put into the trash kept its identity (Core 124)")
        events = [e for e in done.get("events") or [] if e.get("kind") == "put_into_trash"]
        if sorted(e.get("object") for e in events) != ["d1", "d2"] or any(e.get("player") != "p1" for e in events):
            fail("T1", f"events {[(e.get('kind'), e.get('object'), e.get('player')) for e in done.get('events') or []]}")
    # T2
    short = board(["d1"])
    done = apply_program(short, program(MILL2))
    if done.get("committed") or done.get("reason_code") != "randomization_receipt_required":
        fail("T2", f"a short deck with cards in the trash: {done.get('committed')} {done.get('reason_code')}, not refused "
                   f"for its randomization receipt (Core 432.2.b)")
    # T3
    state = board(["d1", "d2", "d3"])
    state["objects"]["o1"] = card("p2")
    state["players"]["p2"]["zones"]["main_deck"].insert(0, "o1")
    done = apply_program(state, program(MILL2))
    if done.get("committed") and done["next_state"]["players"]["p2"]["zones"]["main_deck"][0] != "o1":
        fail("T3", "another player's deck was touched")
    for label, bad in (("unknown player", {**MILL2[0], "player": "p9"}), ("count 0", {**MILL2[0], "count": 0})):
        if apply_program(board(["d1", "d2"]), program([bad])).get("committed"):
            fail("T3", f"{label} committed")
    if errors:
        print("FAILED: set 2 trash_top")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: the top N cards of a player's Main Deck go to their trash in order, each a new object with its own event "
          "(124); a short deck Burns Out by the draw's own sequence (432.1.b), never without its randomization receipt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
