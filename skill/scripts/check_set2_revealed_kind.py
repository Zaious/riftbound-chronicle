#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "reveal the top card of your Main Deck. If it's a gear, draw it. Otherwise, recycle
it." (Apprentice Smith) and "... If it's a spell, put it in your hand. Otherwise, recycle it." (Ravenbloom Conservatory) -
predicate revealed_is_kind on the taking instruction, predicate_not_met on the recycle.

  K1 gear drawn       the top card a gear: it is drawn (to the hand, a draw event); nothing recycled
  K2 not a gear       the top card a spell: it goes under the rest of the deck (a recycle); nothing drawn
  K3 spell to hand    Ravenbloom's shape with a spell on top: put in the hand (not a draw); with a unit: recycled
  V                   revealed_is_kind naming an instruction that is not a reveal, or another card kind, is refused

    python skill/scripts/check_set2_revealed_kind.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def body(take_op, kind):
    return [{"op": "reveal", "effect_id": "rv", "from": "main_deck_top", "count": 1, "player": "p1"},
            {"op": take_op, "effect_id": "take", "player": "p1",
             "predicate": {"kind": "revealed_is_kind", "effect_id": "rv", "card_kind": kind}},
            {"op": "recycle", "effect_id": "rc", "player": "p1", "revealed_by": "rv",
             "predicate": {"kind": "predicate_not_met", "effect_id": "take"}}]


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "reveal-kind", "controller": "p1", "effects": effects}


def run(top_kind, take_op, wanted):
    state = base_state()
    state["objects"]["top"] = {"owner": "p1", "controller": "p1", "kind": top_kind, "base_might": 0, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["main_deck"].insert(0, "top")
    done = apply_program(state, program(body(take_op, wanted)))
    if not done.get("committed"):
        return f"refused: {done.get('reason') or done.get('errors')}"
    z = done["next_state"]["players"]["p1"]["zones"]
    drawn = any(e.get("kind") == "drawn" and e.get("object") == "top" for e in done.get("events") or [])
    return {"in hand": "top" in z["hand"], "at the bottom": z["main_deck"][-1:] == ["top"], "drawn": drawn}


def main() -> int:
    for label, args, want in (("K1 gear drawn", ("gear", "draw_it", "gear"), {"in hand": True, "at the bottom": False, "drawn": True}),
                              ("K2 not a gear", ("spell", "draw_it", "gear"), {"in hand": False, "at the bottom": True, "drawn": False}),
                              ("K3 spell to hand", ("spell", "put_in_hand", "spell"), {"in hand": True, "at the bottom": False, "drawn": False}),
                              ("K3 unit recycled", ("unit", "put_in_hand", "spell"), {"in hand": False, "at the bottom": True, "drawn": False})):
        if (got := run(*args)) != want:
            fail(label, f"{got}, not {want}")
    bad = body("draw_it", "gear")
    bad[1]["predicate"]["effect_id"] = "rc"
    if not validate_program(program(bad)):
        fail("V", "revealed_is_kind naming a later recycle validated")
    odd = body("draw_it", "rune")
    if not validate_program(program(odd)):
        fail("V", "revealed_is_kind of a rune validated")
    if errors:
        print("FAILED: set 2 revealed card kind")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'if it's a gear, draw it. Otherwise, recycle it' - the one revealed card of that kind is drawn (or put in the "
          "hand), any other goes under the rest of the deck; only an earlier reveal is read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
