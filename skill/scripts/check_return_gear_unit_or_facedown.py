#!/usr/bin/env python3
"""Another friendly gear, unit or facedown card, to its owner's hand (package 10, Pack of Wonders).

One choice over three kinds of object its controller controls: a Gear or a Unit on the board, or a card in a Facedown
Zone - a public zone (so a target), whose card shows no kind to the chooser (so the alternative names none). "Another"
leaves the source out by identity. To the hand is a zone change: a new object; a facedown card leaves its Facedown Zone.

  R1 gear          p1's other Gear at its Base: to p1's hand, a new object
  R2 unit          p1's Unit at bf1: to p1's hand
  R3 facedown      p1's facedown card at bf1: to p1's hand; bf1's Facedown Zone is empty after
  R4 the source    the Pack itself: refused ("another")
  R5 enemy         p2's Unit, p2's facedown card: refused
  R6 other kind    p1's Rune: refused
  V  shape         a facedown alternative naming a kind, or claiming the board class, does not validate
  G  grammar       the printed line lowers to exactly this selector; near misses do not lower to the row

    python skill/scripts/check_return_gear_unit_or_facedown.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_costs_and_activation import hand_state  # noqa: E402
from effect_ir import (PROGRAM_VERSION, CORE_RULESET, FAQ_AS_OF, apply_program, evaluate_target, hash_value, object_identity,  # noqa: E402
                       validate_program, validate_state)

errors: list[str] = []
FACEDOWN = {"location": "facedown", "chosen_zone_class": "non_board", "controller_relation": "friendly"}
SELECTOR = {"decision_ref": "t", "chosen_zone_class": "board", "exclude_source_identity": "$source_identity",
            "any_of": [{"kind": "gear", "controller_relation": "friendly"}, {"kind": "unit", "controller_relation": "friendly"},
                       dict(FACEDOWN)]}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def thing(owner, kind, damage=0):
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": 2 if kind == "unit" else 0,
            "might_modifiers": [], "damage": damage, "exhausted": False}


def board():
    state = hand_state("c1")
    state["objects"].update({"pack": thing("p1", "gear"), "gear2": thing("p1", "gear"), "u-mine": thing("p1", "unit", 1),
                             "u-theirs": thing("p2", "unit"), "fd-mine": {**thing("p1", "spell"), "hidden": True},
                             "fd-theirs": {**thing("p2", "spell"), "hidden": True},
                             "rune1": {**thing("p1", "rune"), "domain": "calm"}})
    state["players"]["p1"]["zones"]["base"] += ["pack", "gear2", "rune1"]
    state["battlefields"]["bf1"].update({"controller": "p1", "contested": True, "contested_by": "p2"})
    state["battlefields"]["bf1"]["objects"] += ["u-mine", "u-theirs"]
    state["battlefields"]["bf1"]["facedown"] = {"capacity": 2, "cards": [
        {"object_id": "fd-mine", "controller": "p1", "hidden_on_turn": "turn-0"}]}
    state["battlefields"].setdefault("bf2", {"controller": "p2", "objects": []})
    state["battlefields"]["bf2"]["facedown"] = {"capacity": 1, "cards": [
        {"object_id": "fd-theirs", "controller": "p2", "hidden_on_turn": "turn-0"}]}
    return state


def put(state, pick, selector=SELECTOR):
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "pack", "controller": "p1", "source_object": "pack",
               "effects": [{"op": "return_to_hand", "effect_id": "ret", "target": copy.deepcopy(selector)}]}
    problems = validate_program(program)
    if problems:
        return {"invalid": problems}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "kind": "target_selection", "stage": "play_declaration", "controller": "p1", "value": [pick],
         "selection_identities": {pick: object_identity(state, pick)}}]}
    return apply_program(state, program, decisions=decisions)


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s))
        return report()
    for label, pick in (("R1 gear", "gear2"), ("R2 unit", "u-mine"), ("R3 facedown", "fd-mine")):
        got = put(s, pick)
        hand = ((got.get("next_state") or {}).get("players") or {}).get("p1", {}).get("zones", {}).get("hand", [])
        if not got.get("committed") or pick not in hand:
            fail(label, got.get("invalid") or got.get("reason") or [t.get("reason") for t in got.get("trace") or []])
            continue
        after = got["next_state"]
        if object_identity(after, pick) == object_identity(s, pick) or after["objects"][pick].get("damage"):
            fail(label, "not a new object (identity kept or damage kept)")
        if pick == "fd-mine" and after["battlefields"]["bf1"]["facedown"]["cards"]:
            fail(label, "bf1's Facedown Zone still holds a card")
    bound = {"chosen_zone_class": "board", "exclude_source_identity": object_identity(s, "pack")}
    for label, pick, alternative, why in (
            ("R4 the source", "pack", SELECTOR["any_of"][0], "target_excludes_source"),
            ("R5 enemy unit", "u-theirs", SELECTOR["any_of"][1], "target_controller_requirement_failed"),
            ("R5 enemy facedown", "fd-theirs", FACEDOWN, "target_controller_requirement_failed"),
            ("R6 other kind", "rune1", SELECTOR["any_of"][0], "target_kind_requirement_failed")):
        # the alternative it would come under names the requirement that failed (any_of reports only that one did)
        ok, reason = evaluate_target(s, {**bound, **alternative, "object_id": pick}, "p1")
        if ok or reason != why:
            fail(label, f"its alternative gives {reason}, not {why}")
        got = put(s, pick)
        if "invalid" in got:
            fail(label, got["invalid"])
            continue
        if got.get("committed") and pick in got["next_state"]["players"]["p1"]["zones"]["hand"]:
            fail(label, "put into p1's hand")
        if [t.get("outcome") for t in got.get("trace") or []] != ["ignored_illegal_target"] and got.get("committed"):
            fail(label, f"not refused as an illegal target: {[t.get('outcome') for t in got.get('trace') or []]}")
    for label, wrong in (("V facedown with a kind", {**FACEDOWN, "kind": "spell"}),
                         ("V facedown on the board", {**FACEDOWN, "chosen_zone_class": "board"})):
        got = put(s, "fd-mine", {**SELECTOR, "any_of": SELECTOR["any_of"][:2] + [wrong]})
        if "invalid" not in got:
            fail(label, "the selector validated")
    import clause_grammar as cg
    grammar = cg.load_grammar()
    row = "return_another_friendly_gear_unit_or_facedown_card_to_its_owners_hand"
    got = cg.compile_clause("Return another friendly gear, unit, or facedown card to its owner's hand.", grammar)
    if got.get("production_id") != row or (got.get("program_effects") or [{}])[0].get("target") != SELECTOR:
        fail("G grammar", f"{got.get('production_id')} {(got.get('program_effects') or [{}])[0].get('target')}")
    for near in ("Return another friendly gear or unit to its owner's hand.",
                 "Return a friendly gear, unit, or facedown card to its owner's hand."):
        if cg.compile_clause(near, grammar).get("production_id") == row:
            fail("G grammar", f"{near!r} lowered to the row")
    return report()


def report() -> int:
    if errors:
        print("FAILED: return gear, unit or facedown card checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: another friendly gear, unit or facedown card to its owner's hand - a new object, the Facedown Zone left; "
          "the source, an enemy's, a Rune: refused; the selector's shape held; the grammar row (R1-R6, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
