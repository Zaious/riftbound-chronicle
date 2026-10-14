#!/usr/bin/env python3
"""An ability whose mode must be one not chosen this turn (package 12, Udyr - Wildman: "Spend my buff: Choose one you've
not chosen this turn - Deal 2 to a unit at a battlefield. / Stun a unit at a battlefield. / Ready me. / Give me [Ganking]
this turn.").

The reading, by GPT's 2026-10-08 ruling 9 the site's own (no published source): the record belongs to the object - two
of them on the board keep two records, and one that leaves the board and comes back is a new object with none (Core
124); "you" is the player choosing - after a change of control, what the earlier controller chose with it does not bind
the new one (the site's reading of the open case, named as such); a new turn starts every record afresh. The engine's
shape: modal.not_chosen_this_turn on the program; the play transaction refuses a mode already in the source's record
(mode_chosen_this_turn) and records the chosen one on the source - {identity, turn_id, by: {player: [modes]}}, read only
while that identity and turn are current.

  U1 first        p1 activates u1 choosing "ready": made; u1's record holds it for p1
  U2 again        "ready" again this turn: refused (mode_chosen_this_turn); "ganking": made
  U3 next turn    the turn changes: "ready" is made again
  U4 new object   u1 leaves the board and comes back (a new identity): "ready" is made again
  U5 two copies   u1 chose "ready"; another such unit u3 chooses "ready": made
  U6 new control  u1 (p1 chose "ready") changes control to p2: p2 choosing "ready" is made; p1's record is untouched
  V  validation   not_chosen_this_turn only as true; the record only in its shape

    python skill/scripts/check_modes_not_chosen.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from check_costs_and_activation import ability_declaration  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, hash_value, validate_program, validate_state  # noqa: E402
from play_transaction import modes_chosen_this_turn, play_card  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
COUNTER = [0]


def program(source="w1"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": f"{source}:a1", "controller": "p1", "source_object": source,
            "modal": {"choose": 1, "timing": "play_declaration", "decision_ref": "mode", "not_chosen_this_turn": True,
                      "options": [
                          {"option_id": "ready", "effects": [{"op": "ready", "effect_id": "rd",
                                                              "object_id": {"object_ref": "program_source"}}]},
                          {"option_id": "ganking", "effects": [{"op": "grant_keyword", "effect_id": "kw",
                                                                "keyword": "ganking", "duration": "this_turn",
                                                                "source": "$chain_item",
                                                                "object_id": {"object_ref": "program_source"}}]}]},
            "effects": []}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board():
    state = base_state()
    for oid in ("w1", "w3"):
        state["objects"][oid] = unit("p1")
        state["battlefields"]["bf1"]["objects"].append(oid)
    state["turn_id"] = "turn-1"
    return settle_contested(state)


def activate(state, mode, *, source="w1", actor="p1"):
    decisions = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [
        {"decision_id": "mode", "stage": "play_declaration", "kind": "mode_selection", "controller": actor, "value": mode}]}
    COUNTER[0] += 1
    declared = ability_declaration(card=source, actor=actor, activation={"source_object": source, "ability_id": f"{source}:a1"},
                                   effect_program_id=f"{source}:a1", play_id=f"play-{COUNTER[0]}",
                                   chain_item={"id": f"ability-{COUNTER[0]}", "object_kind": "ability", "timing": "default"})
    prog = program(source)
    prog["controller"] = actor
    timing = fixture(priority=actor)
    timing["turn_player"] = actor   # an activation on its controller's own turn (Core 381)
    return play_card(timing, state, declared, engine_decisions=decisions, effect_program=prog)


def after(result, state):
    return result["next_effect_state"] if result.get("committed") else state


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    first = activate(s, "ready")
    if not first.get("committed") or modes_chosen_this_turn(first["next_effect_state"], "w1", "p1") != ["ready"]:
        fail("U1 first", f"{first.get('reason_code')} {first.get('reason')}")
        return report()
    s1 = first["next_effect_state"]
    again = activate(s1, "ready")
    if again.get("committed") or again.get("reason_code") != "mode_chosen_this_turn":
        fail("U2 again", f"{again.get('committed')} {again.get('reason_code')}")
    other = activate(s1, "ganking")
    if not other.get("committed"):
        fail("U2 again", f"the other mode was refused: {other.get('reason_code')} {other.get('reason')}")
    turned = copy.deepcopy(s1)
    turned["turn_id"] = "turn-2"
    if not activate(turned, "ready").get("committed"):
        fail("U3 next turn", "the mode chosen last turn was still refused")
    renewed = copy.deepcopy(s1)
    renewed["objects"]["w1"]["identity"] = "w1@5"
    if not activate(renewed, "ready").get("committed"):
        fail("U4 new object", "a new object inherited the old one's record (Core 124)")
    twin = activate(s1, "ready", source="w3")
    if not twin.get("committed"):
        fail("U5 two copies", f"another unit's record bound this one: {twin.get('reason_code')}")
    taken = copy.deepcopy(s1)
    taken["objects"]["w1"]["controller"] = "p2"
    taken = settle_contested(taken)
    new_owner = activate(taken, "ready", actor="p2")
    if not new_owner.get("committed"):
        fail("U6 new control", f"the new controller was refused: {new_owner.get('reason_code')} {new_owner.get('reason')}")
    elif modes_chosen_this_turn(new_owner["next_effect_state"], "w1", "p1") != ["ready"] or \
            modes_chosen_this_turn(new_owner["next_effect_state"], "w1", "p2") != ["ready"]:
        fail("U6 new control", "p1's record changed when p2 chose")
    bad = program()
    bad["modal"]["not_chosen_this_turn"] = False
    if not validate_program(bad):
        fail("V validation", "not_chosen_this_turn: false was accepted")
    broken = copy.deepcopy(s1)
    broken["objects"]["w1"]["modes_chosen"] = {"turn_id": "turn-1", "by": {}}
    if not validate_state(broken):
        fail("V validation", "a record without its identity was accepted")
    return report()


def report() -> int:
    if errors:
        print("FAILED: modes not chosen this turn")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a mode chosen this turn with this object is refused to the player who chose it; another mode, the next "
          "turn, a new object, another copy and a new controller each choose afresh (U1-U6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
