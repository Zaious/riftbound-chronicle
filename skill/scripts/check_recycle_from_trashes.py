#!/usr/bin/env python3
"""Recycle up to N cards from trashes (package 11, Forge of the Future: "Kill this: Recycle up to 4 cards from trashes.";
GPT 2026-10-12 PACKAGE11 ruling 7).

The cards are chosen by the ability's controller as the instruction executes, from every player's trash - not targets
(Core 417.6: "Recycle X from [Zone]" does not target) - zero to N of them (355.13); each goes to the bottom of its OWNER's
deck (417.1).

  R1 two owners    one card of p1's trash and one of p2's: each at the bottom of its owner's Main Deck
  R2 none          zero chosen: nothing moves (no_op)
  R3 over          five chosen for "up to 4": refused
  R4 chooser       the choice made by the opponent: refused
  R5 not a trash   a card of a hand: refused
  R6 at execution  a card put in a trash after the ability was made is a candidate (the zones are read as it executes)
  G  grammar       "Recycle up to 4 cards from trashes." lowers to it; its near misses do not

    python skill/scripts/check_recycle_from_trashes.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity  # noqa: E402

errors: list[str] = []
TEXT = "Recycle up to 4 cards from trashes."


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def card(owner):
    return {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board():
    """p1's trash: c3, t1, t2, t3; p2's trash: x1, x2; p1's hand: h1."""
    s = base_state()
    for oid in ("t1", "t2", "t3"):
        s["objects"][oid] = card("p1")
        s["players"]["p1"]["zones"]["trash"].append(oid)
    s["players"]["p2"]["zones"].setdefault("trash", [])
    for oid in ("x1", "x2"):
        s["objects"][oid] = card("p2")
        s["players"]["p2"]["zones"]["trash"].append(oid)
    s["objects"]["h1"] = card("p1")
    s["players"]["p1"]["zones"]["hand"].append("h1")
    return s


def run(state, picks, *, by="p1"):
    lowered = cg.compile_clause(TEXT, cg.load_grammar())
    effects = copy.deepcopy(lowered["program_effects"])
    for e in effects:
        e["player"] = "p1"
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "forge", "controller": "p1", "effects": effects}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "rc", "stage": "resolution", "kind": "card_selection", "controller": by, "value": list(picks),
         "selection_identities": {o: object_identity(state, o) for o in picks}}]}
    return apply_program(state, program, decisions=decisions)


def main() -> int:
    lowered = cg.compile_clause(TEXT, cg.load_grammar())
    if lowered.get("production_id") != "recycle_up_to_n_cards_from_trashes":
        print(f"FAILED: the sentence does not lower: {lowered.get('production_id')}")
        return 1
    s = board()
    got = run(s, ["t1", "x1"])
    after = got.get("next_state") or {}
    if not got.get("committed") or (after["players"]["p1"]["zones"]["main_deck"][-1:], after["players"]["p2"]["zones"]["main_deck"][-1:]) \
            != (["t1"], ["x1"]):
        fail("R1 two owners", f"{got.get('reason') or got.get('errors')} "
                              f"{[(after.get('players') or {}).get(p, {}).get('zones', {}).get('main_deck') for p in ('p1', 'p2')]}")
    none = run(s, [])
    if not none.get("committed") or none["next_state"]["players"]["p1"]["zones"]["trash"] != s["players"]["p1"]["zones"]["trash"]:
        fail("R2 none", f"{none.get('reason') or none.get('errors')}")
    over = run(s, ["t1", "t2", "t3", "x1", "x2"])
    if over.get("committed"):
        fail("R3 over", "five cards were recycled for 'up to 4'")
    theirs = run(s, ["t1"], by="p2")
    if theirs.get("committed"):
        fail("R4 chooser", "the opponent's choice was taken")
    hand = run(s, ["h1"])
    if hand.get("committed"):
        fail("R5 not a trash", "a card of a hand was recycled")
    later = copy.deepcopy(s)
    later["objects"]["late"] = card("p2")
    later["players"]["p2"]["zones"]["trash"].append("late")
    got = run(later, ["late"])
    if not got.get("committed") or got["next_state"]["players"]["p2"]["zones"]["main_deck"][-1:] != ["late"]:
        fail("R6 at execution", f"{got.get('reason') or got.get('errors')}")
    for near in ("Recycle up to 4 cards from your trash.", "Recycle 4 cards from trashes.", "Recycle up to 4 units from trashes."):
        if cg.compile_clause(near, cg.load_grammar()).get("production_id") == "recycle_up_to_n_cards_from_trashes":
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: recycle-from-trashes checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: up to N cards from any players' trashes, chosen by the controller as it executes, each to its owner's deck; "
          "zero allowed; more than N, the opponent's choice, or a card in a hand refused (R1-R6, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
