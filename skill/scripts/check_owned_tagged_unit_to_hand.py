#!/usr/bin/env python3
"""A unit of one tag that its controller owns, put into their hand from their Champion Zone or the board (package 10,
Teemo - Swift Scout).

"A Teemo unit you own" chooses a unit carrying the tag (Core 133.8) whose owner is the ability's controller - owner, not
controller. "From your Champion Zone or the board" is one choice over two places: the board, or the controller's own
Champion Zone, which is public (so the unit is a target either way). Putting it into the hand is a zone change, as a
return to hand is: a new object, nothing kept.

  B1 board         the Teemo unit p1 owns at a battlefield: into p1's hand, a new object, its damage gone
  B2 champion zone the Teemo unit in p1's Champion Zone: into p1's hand; the zone is empty after
  B3 not owned     a Teemo unit p2 owns, under p1's control: refused as a target (owner, not controller)
  B4 other tag     p1's unit tagged otherwise: refused
  B5 no tags seen  a unit whose tags were never observed: refused (not guessed)
  B6 other zone    a Teemo unit in p1's trash, or in p2's Champion Zone: refused
  V  shape         the Champion Zone alternative must be the controller's own and non-board; a board alternative
                   cannot claim a non-board class
  G  grammar       the printed line lowers to exactly this selector; near misses do not lower to the row

    python skill/scripts/check_owned_tagged_unit_to_hand.py
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
SELECTOR = {"decision_ref": "t", "chosen_zone_class": "board", "with_tag": "Teemo", "owner_relation": "own",
            "any_of": [{"kind": "unit", "location": "board"},
                       {"kind": "unit", "location": "champion_zone", "chosen_zone_class": "non_board",
                        "zone_owner_relation": "own"}]}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, controller=None, tags=("Teemo",), damage=0):
    o = {"owner": owner, "controller": controller or owner, "kind": "unit", "base_might": 2, "might_modifiers": [],
         "damage": damage, "exhausted": False}
    if tags is not None:
        o["tags"] = list(tags)
    return o


def board():
    state = hand_state("c1")
    state["objects"].update({"tm-bf": unit("p1", damage=1), "tm-cz": unit("p1"), "tm-stolen": unit("p2", "p1"),
                             "other": unit("p1", tags=("Yordle",)), "unseen": unit("p1", tags=None), "tm-trash": unit("p1"),
                             "tm-p2cz": unit("p2")})
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["battlefields"]["bf1"]["objects"] += ["tm-bf", "tm-stolen", "other", "unseen"]
    state["players"]["p1"]["zones"].setdefault("champion_zone", []).append("tm-cz")
    state["players"]["p1"]["zones"]["trash"].append("tm-trash")
    state["players"]["p2"]["zones"].setdefault("champion_zone", []).append("tm-p2cz")
    return state


def put(state, pick, selector=SELECTOR):
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "teemo-put", "controller": "p1",
               "effects": [{"op": "return_to_hand", "effect_id": "put", "target": copy.deepcopy(selector)}]}
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
    for label, pick, zone in (("B1 board", "tm-bf", None), ("B2 champion zone", "tm-cz", "champion_zone")):
        got = put(s, pick)
        hand = ((got.get("next_state") or {}).get("players") or {}).get("p1", {}).get("zones", {}).get("hand", [])
        if not got.get("committed") or pick not in hand:
            fail(label, got.get("invalid") or got.get("reason") or got.get("errors"))
            continue
        after = got["next_state"]
        if object_identity(after, pick) == object_identity(s, pick) or after["objects"][pick].get("damage"):
            fail(label, "not a new object (identity kept or damage kept)")
        if zone and after["players"]["p1"]["zones"][zone]:
            fail(label, f"p1's {zone} is not empty after")
    board_alternative = {k: v for k, v in SELECTOR.items() if k not in ("any_of", "decision_ref")} | SELECTOR["any_of"][0]
    for label, pick, why in (("B3 not owned", "tm-stolen", "target_owner_requirement_failed"),
                             ("B4 other tag", "other", "target_tag_requirement_failed"),
                             ("B5 no tags seen", "unseen", "target_tags_not_observed"),
                             ("B6 other zone (trash)", "tm-trash", None), ("B6 other zone (p2's Champion Zone)", "tm-p2cz", None)):
        got = put(s, pick)
        if got.get("committed") and pick in got["next_state"]["players"]["p1"]["zones"]["hand"]:
            fail(label, "put into p1's hand")
        if [t.get("outcome") for t in got.get("trace") or []] != ["ignored_illegal_target"]:
            fail(label, f"not refused as an illegal target: {[t.get('outcome') for t in got.get('trace') or []]}")
        if why is not None:
            # the board alternative alone names the requirement that failed (any_of reports only that one did)
            ok, reason = evaluate_target(s, {**board_alternative, "object_id": pick}, "p1")
            if ok or reason != why:
                fail(label, f"the board alternative gives {reason}, not {why}")
    for label, alternatives in (
            ("V opponent's Champion Zone", [{"kind": "unit", "location": "board"},
                                            {"kind": "unit", "location": "champion_zone", "chosen_zone_class": "non_board",
                                             "zone_owner_relation": "opponent"}]),
            ("V board alternative claims non_board", [{"kind": "unit", "location": "board", "chosen_zone_class": "non_board"},
                                                      {"kind": "unit", "location": "champion_zone",
                                                       "chosen_zone_class": "non_board", "zone_owner_relation": "own"}]),
            ("V trash alternative", [{"kind": "unit", "location": "board"},
                                     {"kind": "unit", "location": "trash", "chosen_zone_class": "non_board",
                                      "zone_owner_relation": "own"}])):
        got = put(s, "tm-cz", {**SELECTOR, "any_of": alternatives})
        if "invalid" not in got:
            fail(label, "the selector validated")
    import clause_grammar as cg
    grammar = cg.load_grammar()
    row = "put_a_tag_unit_you_own_into_your_hand_from_your_champion_zone_or_the_board"
    got = cg.compile_clause("Put a Teemo unit you own into your hand from your Champion Zone or the board.", grammar)
    if got.get("production_id") != row or (got.get("program_effects") or [{}])[0].get("target") != SELECTOR:
        fail("G grammar", f"{got.get('production_id')} {(got.get('program_effects') or [{}])[0].get('target')}")
    for near in ("Put a Teemo unit you control into your hand from your Champion Zone or the board.",
                 "Put a Teemo unit you own into your hand from the board."):
        if cg.compile_clause(near, grammar).get("production_id") == row:
            fail("G grammar", f"{near!r} lowered to the row")
    return report()


def report() -> int:
    if errors:
        print("FAILED: owned tagged unit to hand checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a unit of a tag its controller owns, into their hand from their Champion Zone or the board - a new object; "
          "not owned, another tag, tags unseen, another zone: refused; the selector's shape held; the grammar row (B1-B6, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
