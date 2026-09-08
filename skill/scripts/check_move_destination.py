#!/usr/bin/env python3
"""Regression gate for a Move whose destination is chosen (Charm; Core 428).

"Move an enemy unit." names the object and not the destination. The
destination is the effect controller's choice, made while the effect resolves,
and Codex's contract for it is one sentence:

    the candidates must be generated from the board's existing legal move
    destinations.

That word "generated" is the whole gate. A destination list supplied by the
caller would let a program move a unit somewhere the board does not have, or
somewhere it already is - and a Move to where you already are is not a Move
(355.4.a: from one Location to *another*). So:

  - with no choice made, the program does not run. It answers
    location_selection_required and carries the candidates with it, so a
    caller never has to reconstruct what was legal;
  - the candidates are every Battlefield and every Base *except* the one the
    object occupies, computed from the state;
  - a choice outside that list is refused by name - including the object's
    current location, which is the one a careless implementation would allow;
  - the choice belongs to the effect's controller, not to whoever supplies the
    envelope.

Every fixture here is synthetic.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, hash_value, legal_move_destinations  # noqa: E402


def board_state():
    """u2 (p2's unit) sits at bf1; there is a second Battlefield and two Bases."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["players"]["p2"]["zones"]["base"] = []
    state["battlefields"]["bf1"]["objects"] = ["u2"]
    return state


def move_program():
    prog = program("charm", {"op": "move_board_object", "effect_id": "mv", "object_id": "u2",
                             "destination": {"decision_ref": "dest"}})
    prog["source_object"] = "u1"
    return prog


def decisions(state, value, controller="p1"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": "dest", "kind": "location_selection", "stage": "resolution",
                           "controller": controller, "value": value}]}


def main() -> int:
    errors: list[str] = []
    state = board_state()

    # --- the candidates are generated, and exclude where the object already is ---------------------
    candidates = legal_move_destinations(state, "u2")
    expected = ["battlefield:bf2", "base:p1", "base:p2"]
    if sorted(candidates) != sorted(expected):
        errors.append(f"the legal destinations are not the board's other Locations: {candidates}")
    if "battlefield:bf1" in candidates:
        errors.append("the object's own Location was offered as a Move destination; "
                      "a Move goes to another Location (355.4.a)")
    off_board = legal_move_destinations(state, "c1")     # in a deck, not on the board
    if off_board:
        errors.append(f"an object that is not on the board was offered Move destinations: {off_board}")

    # --- no choice, no Move -------------------------------------------------------------------------
    undecided = apply_program(state, move_program())
    if undecided.get("committed"):
        errors.append("a Move resolved without anyone choosing where to")
    if undecided.get("reason_code") != "location_selection_required":
        errors.append(f"the missing destination was not reported as a required decision: "
                      f"{undecided.get('reason_code')}")
    if sorted(undecided.get("location_candidates") or []) != sorted(expected):
        errors.append(f"the refusal did not carry the legal destinations: "
                      f"{undecided.get('location_candidates')}")
    if undecided.get("decision_ids") != ["dest"] or undecided.get("decision_controller") != "p1":
        errors.append(f"the required decision was not named and attributed: {undecided.get('decision_ids')} "
                      f"{undecided.get('decision_controller')}")

    # --- a legal choice moves it, and only it -------------------------------------------------------
    moved = apply_program(state, move_program(), decisions=decisions(state, "battlefield:bf2"))
    if not moved.get("committed"):
        errors.append(f"a legal Move did not commit: {moved.get('reason') or moved.get('errors')}")
    else:
        after = moved["next_state"]
        if after["battlefields"]["bf2"]["objects"] != ["u2"] or after["battlefields"]["bf1"]["objects"]:
            errors.append(f"the unit did not move: bf1={after['battlefields']['bf1']['objects']} "
                          f"bf2={after['battlefields']['bf2']['objects']}")
    to_base = apply_program(state, move_program(), decisions=decisions(state, "base:p2"))
    if not to_base.get("committed") or "u2" not in to_base["next_state"]["players"]["p2"]["zones"]["base"]:
        errors.append("a Move to a Base was refused or did not land there")

    # --- an illegal choice is refused by name -------------------------------------------------------
    for value, why in (("battlefield:bf1", "the Location the object already occupies"),
                       ("battlefield:bf9", "a Battlefield this board does not have"),
                       ("base:p9", "a player who is not in this game"),
                       ("bf2", "a bare id, which is the procedure-stage form")):
        refused = apply_program(state, move_program(), decisions=decisions(state, value))
        if refused.get("committed"):
            errors.append(f"a Move to {why} was allowed: {value!r}")
        if refused.get("committed") is False and "next_state" in refused:
            errors.append(f"an uncommitted Move to {value!r} still produced a next state")

    # --- and the choice belongs to the controller ---------------------------------------------------
    wrong_player = apply_program(state, move_program(), decisions=decisions(state, "battlefield:bf2", controller="p2"))
    if wrong_player.get("committed") or wrong_player.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"the opponent chose where a Move went: {wrong_player.get('reason_code')}")

    # --- the clause compiles to exactly this --------------------------------------------------------
    compiled = cg.compile_clause("Move an enemy unit.", cg.load_grammar())
    if compiled.get("unsupported") or compiled.get("production_id") != "move_selector":
        errors.append(f"Charm's clause did not compile: {compiled}")
    else:
        effect = compiled["program_effects"][0]
        if effect.get("destination") != {"decision_ref": "dest"}:
            errors.append(f"the clause named a destination instead of deferring to a choice: {effect}")
        if effect.get("target", {}).get("controller_relation") != "enemy":
            errors.append(f"'an enemy unit' lost its controller restriction: {effect}")

    if errors:
        print("FAILED: move destination checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("move destination checks passed: candidates are generated from the board and exclude the "
          "object's own Location, an unchosen destination refuses and carries them, an off-board or "
          "occupied Location is refused by name, and the choice is the controller's")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
