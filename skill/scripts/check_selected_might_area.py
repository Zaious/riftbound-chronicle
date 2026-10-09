#!/usr/bin/env python3
"""A chosen unit's Might dealt to a targeted Battlefield's enemies, then that unit moved there (package 10, Stormbringer).

    "Choose a friendly unit in your base. Deal damage equal to its Might to all enemy units at a battlefield, then move
     your unit there."

"Its Might" is the chosen unit's current Might, read ONCE as the Deal executes (Core 359.3.f.2) and dealt to each enemy
unit at the targeted Battlefield (355.10.b: those units are not targets); "there" is the Battlefield the Deal targeted
(359.3.e.14), read off the Deal's own event; "your unit" is the chosen unit.

  S1 resolves      u1 (Might 3) chosen: u2 at bf1 takes 3, u1 moves to bf1 (contested)
  S2 read late     u1 given +2 between the choice and the Deal: u2 takes 5
  S3 unit gone     u1 killed between the choice and the Deal: nothing dealt (amount_ref_null); the Move does nothing
                   (subject_ref_object_unavailable: "your unit" is the chosen one, never chosen again)
  S4 empty there   no enemy unit at bf1: nothing dealt, u1 still moves there
  S5 none chosen   no friendly unit in p1's Base: the Deal and the Move are skipped as linked to it
  V  validation    the linked Might over any_battlefield refused; 'there' naming an instruction that targets no
                   battlefield refused

    python skill/scripts/check_selected_might_area.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
CHOOSE = {"op": "establish_selection", "effect_id": "ch", "selection_id": "ch", "decision_ref": "ch",
          "choice": {"selection_kind": "single", "from": "board", "count": {"one": True}, "visibility": "public",
                     "criteria": {"kind": "unit", "controller_relation": "friendly", "location": "base"}}}
DEAL = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "linked_object_current_might", "effect_id": "ch"},
        "target": {"object_id": "bf1", "chosen_zone_class": "board", "kind": "battlefield", "bound_identity": "bf1@0"},
        "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "target_battlefield"}}}
MOVE = {"op": "move_board_object", "effect_id": "mv", "subject_ref": {"kind": "linked_object", "effect_id": "ch"},
        "destination": {"kind": "linked_targeted_battlefield", "effect_id": "dmg"}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(enemy=True):
    state = base_state()
    state["objects"]["u1"]["damage"] = 0
    state["players"]["p2"]["zones"]["base"].remove("u2")
    if enemy:
        state["battlefields"]["bf1"] = {"controller": "p2", "objects": ["u2"]}
    else:
        state["players"]["p2"]["zones"]["base"].append("u2")
        state["battlefields"]["bf1"] = {"controller": "p2", "objects": []}
    return state


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "stormbringer", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def choose(state, value=("u1",)):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "ch", "kind": "target_selection", "stage": "resolution", "controller": "p1", "value": list(value),
         "selection_identities": {o: object_identity(state, o) for o in value}}]}


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
    might = board()["objects"]["u1"]["base_might"]
    # S1
    s = board()
    done = apply_program(s, program(CHOOSE, DEAL, MOVE), decisions=choose(s))
    if not done.get("committed") or done["next_state"]["objects"]["u2"]["damage"] != might \
            or where(done["next_state"], "u1") != "battlefield:bf1" or not done["next_state"]["battlefields"]["bf1"].get("contested"):
        fail("S1 resolves", f"{done.get('reason') or done.get('errors')} {done.get('next_state') and done['next_state']['battlefields']}")
    # S2
    s = board()
    pump = {"op": "modify_might", "effect_id": "pump", "object_id": "u1", "amount": 2, "duration": "this_turn", "source": "c1"}
    done = apply_program(s, program(CHOOSE, pump, DEAL, MOVE), decisions=choose(s))
    if not done.get("committed") or done["next_state"]["objects"]["u2"]["damage"] != might + 2:
        fail("S2 read late", f"{done.get('reason') or done.get('errors')} {event(done, 'dmg').get('amount_read')}")
    # S3
    s = board()
    kill = {"op": "kill", "effect_id": "k", "object_id": "u1"}
    done = apply_program(s, program(CHOOSE, kill, DEAL, MOVE), decisions=choose(s))
    if not done.get("committed") or done["next_state"]["objects"]["u2"]["damage"] != 0 \
            or event(done, "dmg").get("reason") != "amount_ref_null" or where(done["next_state"], "u1") != "p1:trash" \
            or event(done, "mv").get("reason") != "subject_ref_object_unavailable":
        fail("S3 unit gone", f"{done.get('reason') or done.get('errors')} {event(done, 'dmg')} {event(done, 'mv').get('outcome')}")
    # S4
    s = board(enemy=False)
    done = apply_program(s, program(CHOOSE, DEAL, MOVE), decisions=choose(s))
    if not done.get("committed") or where(done["next_state"], "u1") != "battlefield:bf1" or done["next_state"]["objects"]["u2"]["damage"]:
        fail("S4 empty there", f"{done.get('reason') or done.get('errors')} {event(done, 'dmg').get('outcome')}")
    # S5
    s = board()
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["players"]["p1"]["zones"]["trash"].append("u1")
    done = apply_program(s, program(CHOOSE, DEAL, MOVE), decisions=None)
    if not done.get("committed") or event(done, "dmg").get("outcome") != "skipped_linked_dependency" \
            or event(done, "mv").get("outcome") not in ("skipped_linked_dependency", "ignored_illegal_target"):
        fail("S5 none chosen", f"{done.get('reason') or done.get('errors')} {event(done, 'ch').get('outcome')} "
                               f"{event(done, 'dmg').get('outcome')} {event(done, 'mv').get('outcome')}")
    # V
    anywhere = {**DEAL, "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "any_battlefield"}}}
    anywhere.pop("target")
    if not validate_program(program(CHOOSE, anywhere, MOVE)):
        fail("V validation", "the linked Might over every battlefield was accepted")
    no_bf = {**MOVE, "destination": {"kind": "linked_targeted_battlefield", "effect_id": "ch"}}
    if not validate_program(program(CHOOSE, DEAL, no_bf)):
        fail("V validation", "'there' naming an instruction that targets no battlefield was accepted")
    for label, wrong in (("a subject_ref naming a later instruction", {**MOVE, "subject_ref": {"kind": "linked_object", "effect_id": "zz"}}),
                         ("a subject_ref beside a target", {**MOVE, "target": {"decision_ref": "t2", "chosen_zone_class": "board"}}),
                         ("a subject_ref on another op", {"op": "kill", "effect_id": "k", "subject_ref": {"kind": "linked_object", "effect_id": "ch"}})):
        if not validate_program(program(CHOOSE, DEAL, wrong)):
            fail("V validation", f"{label} was accepted")
    if validate_program(program(CHOOSE, DEAL, MOVE)):
        fail("V validation", f"the card's own program is invalid: {validate_program(program(CHOOSE, DEAL, MOVE))}")
    if errors:
        print("FAILED: chosen unit's Might over a targeted battlefield checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'its Might' is read once as the Deal executes and dealt to each enemy unit at the targeted Battlefield; "
          "'there' is that Battlefield; a unit gone reads null; nothing chosen skips both (S1-S5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
