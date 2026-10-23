#!/usr/bin/env python3
"""A discard the caster chooses from a revealed hand (package 10, Mindsplitter).

    "Choose an opponent. They reveal their hand. Choose a card from it, and they discard that card."

"It" is what the second clause revealed (Core 425.2.b), named by that reveal's effect_id (reveal_ref); "they" is the
player whose hand it revealed - the opponent the first clause chose - read off that reveal, never named again. The
caster - the program's controller - chooses the card, among the reveal's own marks in that player's hand (so nothing
still private is choosable, 128.4), and that player discards it (423.1): it goes to its owner's trash. The three-player board
of check_player_ref_and_reveal.py (Sabotage), so "they" has something to get wrong.

  D1 resolves      p1 chooses p2's revealed spell: it is in p2's trash, the rest of p2's hand and p3's hand untouched
  D2 unrevealed    the discard with no hand reveal before it (or naming a deck reveal): refused as a program
  D3 not revealed  p3's card (never revealed) named: refused
  D4 wrong chooser the card chosen by p2 (the discarding player) instead of the caster: refused
  D5 empty hand    p2 reveals an empty hand: nothing to choose, nothing discarded
  D6 order         the clauses out of order do not compile (player_ref_not_declared / reveal_not_declared)
  V  validation    the choice shape is closed; the player is a decision_ref; no count / objects
  G  grammar       the production and its near misses

    python skill/scripts/check_discard_from_reveal.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_player_ref_and_reveal import decisions, pick_player, table  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

CLAUSES = [{"text": "Choose an opponent."}, {"text": "They reveal their hand."},
           {"text": "Choose a card from it, and they discard that card."}]
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects):
    bound = copy.deepcopy(effects)
    for e in bound:
        if e.get("player") == "$controller":
            e["player"] = "p1"
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "mindsplitter", "controller": "p1", "source_object": "d1", "effects": bound}


def pick(object_id, controller="p1"):
    return {"decision_id": "revealed-card", "kind": "card_selection", "stage": "resolution", "controller": controller,
            "value": [object_id], "selection_identities": {object_id: f"{object_id}@0"}}


def main() -> int:
    grammar = cg.load_grammar()
    compiled = cg.compile_card(CLAUSES, grammar)
    if compiled["unsupported_clauses"]:
        print(f"FAILED: Mindsplitter does not compile: {compiled['unsupported_clauses']}")
        return 1
    effects = compiled["program_effects"]
    if [e["op"] for e in effects] != ["choose_player", "reveal", "discard"]:
        fail("G grammar", [e["op"] for e in effects])
    if validate_program(program(effects)):
        fail("V validation", validate_program(program(effects)))
    state = table()
    # D1
    done = apply_program(state, program(effects), decisions=decisions(state, pick_player("p2"), pick("h_spell")))
    if not done.get("committed"):
        fail("D1 resolves", done.get("reason") or done.get("errors"))
    else:
        after = done["next_state"]
        if after["players"]["p2"]["zones"]["trash"] != ["h_spell"] or sorted(after["players"]["p2"]["zones"]["hand"]) != ["h_gear", "h_unit"] \
                or after["players"]["p3"]["zones"]["hand"] != ["h_other"] or after["players"]["p1"]["zones"]["trash"]:
            fail("D1 resolves", {p: after["players"][p]["zones"]["hand"] + after["players"][p]["zones"]["trash"] for p in after["players"]})
        trace = next((t for t in done["trace"] if t.get("op") == "discard"), {})
        if trace.get("player") != "p2" or trace.get("selection", {}).get("chosen_by") != "p1":
            fail("D1 resolves", f"the discard is not p2's, chosen by p1: {trace.get('player')} {trace.get('selection')}")
    # D2
    if not validate_program(program([effects[0], effects[2]])):
        fail("D2 unrevealed", "a discard from a reveal with no reveal before it was accepted")
    deck_reveal = copy.deepcopy(effects)
    deck_reveal[1] = {"op": "reveal", "effect_id": "rv", "from": "main_deck_top", "count": 1, "player": "p2"}
    if not validate_program(program(deck_reveal)):
        fail("D2 unrevealed", "a discard naming a Main Deck reveal was accepted")
    # D3
    other = apply_program(state, program(effects), decisions=decisions(state, pick_player("p2"), pick("h_other")))
    if other.get("committed"):
        fail("D3 not revealed", "a card of an unrevealed hand was discarded")
    # D4
    theirs = apply_program(state, program(effects), decisions=decisions(state, pick_player("p2"), pick("h_spell", "p2")))
    if theirs.get("committed"):
        fail("D4 wrong chooser", "the discarding player chose the card")
    # D5
    empty = table()
    for o in empty["players"]["p2"]["zones"]["hand"]:
        empty["players"]["p2"]["zones"]["trash"].append(o)
    empty["players"]["p2"]["zones"]["hand"] = []
    none = apply_program(empty, program(effects), decisions=decisions(empty, pick_player("p2")))
    trace = next((t for t in none.get("trace", []) if t.get("op") == "discard"), {})
    if not none.get("committed") or trace.get("outcome") != "no_op":
        fail("D5 empty hand", f"{none.get('reason_code')} {none.get('reason')} {trace}")
    # D6
    for order, expected in (([1, 0, 2], "player_ref_not_declared"), ([0, 2, 1], "reveal_not_declared")):
        shuffled = cg.compile_card([CLAUSES[i] for i in order], grammar)
        if expected not in [c.get("reason_code") for c in shuffled["clauses"] if c.get("unsupported")]:
            fail("D6 order", f"{order} compiled anyway")
    # V
    for label, change in (("an open choice", lambda e: e["choice"].update({"by": "opponent"})),
                          ("a count", lambda e: e.update({"count": 1})),
                          ("a named player", lambda e: e.update({"player": "p2"})),
                          ("a reveal_ref naming no reveal", lambda e: e.update({"reveal_ref": "opp"})),
                          ("no decision_ref", lambda e: e.pop("decision_ref"))):
        wrong = copy.deepcopy(effects)
        change(wrong[2])
        if not validate_program(program(wrong)):
            fail("V validation", f"{label} was accepted")
    # G
    for near in ("Choose a card from it, and recycle that card.", "They discard a card.",
                 "Choose a card from their hand, and they discard that card."):
        if cg.compile_clause(near, grammar).get("production_id") == "choose_a_card_from_it_and_they_discard_that_card":
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: discard from a reveal checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'Choose a card from it, and they discard that card' - the caster chooses among the reveal's own marks in "
          "the chosen player's hand, and that player discards it (D1-D6, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
