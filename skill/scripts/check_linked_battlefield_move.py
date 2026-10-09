#!/usr/bin/env python3
"""A Move to the Battlefield of the object an earlier instruction acted on (package 10, Zenith Blade).

    "[Action] Stun an enemy unit at a battlefield. You may move a friendly unit to that enemy unit's battlefield."

"That enemy unit's battlefield" names the object the stun acted on (Core 359.3.e.14) and is read as the Move executes
(359.3.f.2): wherever that unit is then. Not at a Battlefield then (in a Base, off the board, a new object), the
destination reads null (359.3.e.12) and the Move is not carried out; the stun ignored, the Move is too (359.3.e.14.a).
"You may" is decided as the Move resolves (355.12).

  Z1 moved        e1 stunned at bf2; p1's u1 moved from its Base to bf2 (the stunned unit's Battlefield), contested
  Z2 read late    e1 moved to its Base between the stun and the Move: no destination, u1 stays (no_op)
  Z3 ignored      the stun ignored (its object already gone): the Move skipped_linked_dependency
  Z4 declined     the Move declined: nothing moved
  Z5 elsewhere    e1 at bf1 instead: u1 goes to bf1 (the destination is read, not fixed)
  V  validation   {kind, effect_id} only, naming an earlier instruction of the program

    python skill/scripts/check_linked_battlefield_move.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
STUN = {"op": "stun", "effect_id": "st", "object_id": "e1"}
MOVE = {"op": "move_board_object", "effect_id": "mv", "object_id": "u1", "optional": {"decision_ref": "may"},
        "destination": {"kind": "linked_object_battlefield", "effect_id": "st"}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(where="bf2"):
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": "p2", "objects": []}
    state["objects"]["e1"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["battlefields"][where]["objects"].append("e1")
    state["battlefields"][where]["controller"] = "p2"
    return state


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "zenith", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def may(state, value=True):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "may", "kind": "optional_choice", "stage": "resolution", "controller": "p1", "value": value}]}


def where(state, object_id):
    for bf, data in state["battlefields"].items():
        if object_id in data["objects"]:
            return f"battlefield:{bf}"
    for player, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if object_id in ids:
                return f"{player}:{zone}"
    return None


def event(result, effect_id):
    return next((t for t in result.get("trace") or [] if t.get("effect_id") == effect_id), {})


def main() -> int:
    # Z1
    s = board()
    done = apply_program(s, program(STUN, MOVE), decisions=may(s))
    if not done.get("committed") or where(done["next_state"], "u1") != "battlefield:bf2" \
            or not done["next_state"]["objects"]["e1"].get("stunned"):
        fail("Z1 moved", f"{done.get('reason') or done.get('errors')} u1 at {done.get('next_state') and where(done['next_state'], 'u1')}")
    elif not done["next_state"]["battlefields"]["bf2"].get("contested"):
        fail("Z1 moved", "u1 arrived at an enemy-held Battlefield and it is not contested")
    # Z2
    s = board()
    away = {"op": "move_board_object", "effect_id": "away", "object_id": "e1",
            "destination": {"kind": "base", "player_relation": "object_controller"}}
    done = apply_program(s, program(STUN, away, MOVE), decisions=may(s))
    if not done.get("committed") or where(done["next_state"], "u1") != "p1:base" \
            or event(done, "mv").get("reason") != "destination_ref_not_at_battlefield":
        fail("Z2 read late", f"{done.get('reason')} {event(done, 'mv')}")
    # Z3
    s = board()
    s["battlefields"]["bf2"]["objects"].remove("e1")
    s["players"]["p2"]["zones"]["trash"].append("e1")
    done = apply_program(s, program({**STUN, "target": {"object_id": "e1", "chosen_zone_class": "board", "kind": "unit",
                                                        "bound_identity": "e1@0"}}, MOVE), decisions=may(s))
    if not done.get("committed") or where(done["next_state"], "u1") != "p1:base" \
            or event(done, "mv").get("outcome") != "skipped_linked_dependency":
        fail("Z3 ignored", f"{done.get('reason') or done.get('errors')} {event(done, 'st').get('outcome')} {event(done, 'mv')}")
    # Z4
    s = board()
    done = apply_program(s, program(STUN, MOVE), decisions=may(s, False))
    if not done.get("committed") or where(done["next_state"], "u1") != "p1:base" or event(done, "mv").get("outcome") != "declined":
        fail("Z4 declined", f"{done.get('reason')} {event(done, 'mv')}")
    # Z5
    s = board("bf1")
    done = apply_program(s, program(STUN, MOVE), decisions=may(s))
    if not done.get("committed") or where(done["next_state"], "u1") != "battlefield:bf1":
        fail("Z5 elsewhere", f"{done.get('reason')} u1 at {done.get('next_state') and where(done['next_state'], 'u1')}")
    # V
    for label, destination, order in (("a later instruction", {"kind": "linked_object_battlefield", "effect_id": "st"}, "move_first"),
                                      ("an unknown instruction", {"kind": "linked_object_battlefield", "effect_id": "zz"}, None),
                                      ("an extra key", {"kind": "linked_object_battlefield", "effect_id": "st", "battlefield": "bf1"}, None)):
        move = {**MOVE, "destination": destination}
        effects = (move, STUN) if order == "move_first" else (STUN, move)
        if not validate_program(program(*effects)):
            fail("V validation", f"{label} was accepted")
    if validate_program(program(STUN, MOVE)):
        fail("V validation", f"the card's own program is invalid: {validate_program(program(STUN, MOVE))}")
    if errors:
        print("FAILED: linked-battlefield Move checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'to that enemy unit's battlefield' is read as the Move executes - moved there, nothing when the unit is no "
          "longer at a Battlefield, skipped when the stun was ignored, declined when declined (Z1-Z5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
