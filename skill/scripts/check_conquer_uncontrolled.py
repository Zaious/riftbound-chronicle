#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Yone - Blademaster, "When I conquer a battlefield that was uncontrolled, deal damage
equal to my Might to an enemy unit in a base."): the unit's own conquer trigger, met only when the Battlefield had no
controller before this conquer (Core 190.2.b, 471.1, 383.2.a.1).

  G1 grammar        the wrapper lowers to a conquer_triggers descriptor, scope unit_here, condition battlefield_was_uncontrolled
  U1 uncontrolled   the unit at bf1 conquers it from no controller: the trigger is scheduled
  U2 from an enemy  the same conquer of a Battlefield p2 controlled: nothing
  U3 not known      a caller that does not say what it replaced (the default): nothing - never assumed uncontrolled
  U4 hold           a Hold of bf1 with the unit there: nothing (a hold is not a conquer)
  U5 control path   resolve_battlefield_control's conquer passes the controller it replaces: from none, scheduled; from p2,
                    not
  V  validation     the condition on a hold trigger, or with a field, does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battlefield_control as BC  # noqa: E402
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

TEXT = "When I conquer a battlefield that was uncontrolled, draw 1."


def descriptor():
    got = CG.compile_clause(TEXT, CG.load_grammar())
    return got.get("production_id"), ((got.get("passive") or {}).get("object_fields") or {}).get("conquer_triggers")


def board(controller=None):
    s = base_state()
    s["mode"] = {"victory_score": 8}
    _pid, triggers = descriptor()
    s["objects"]["yo"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4, "might_modifiers": [],
                          "damage": 0, "exhausted": False,
                          "conquer_triggers": [{**copy.deepcopy(triggers[0]), "controller": "p1", "source_object": "yo",
                                                "effect_program_id": "yo-on-conquer"}]}
    for oid in list(s["battlefields"]["bf1"]["objects"]):
        s["battlefields"]["bf1"]["objects"].remove(oid)
        s["players"][s["objects"][oid]["controller"]]["zones"]["base"].append(oid)
    # p1's unit arrived: contested by p1 (Core 190.3.a), whoever controlled it
    s["battlefields"]["bf1"] = {"controller": controller, "objects": ["yo"], "contested": True, "contested_by": "p1"}
    return s


def sources(triggers):
    return sorted(t.get("source_object") for t in triggers)


def main() -> int:
    errors: list[str] = []
    pid, triggers = descriptor()
    if pid != "when_i_conquer_a_battlefield_that_was_uncontrolled" or not triggers \
            or triggers[0].get("scope") != "unit_here" or triggers[0].get("condition") != {"kind": "battlefield_was_uncontrolled"}:
        errors.append(f"G1 grammar: {pid} {triggers}")
        print("\n".join(errors))
        return 1
    s = board()
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    turn = s.get("turn_id", "turn-0")
    if sources(BC._score_triggers(s, "p1", "bf1", "conquer", turn, previous_controller=None)) != ["yo"]:
        errors.append("U1 uncontrolled: not scheduled")
    if sources(BC._score_triggers(s, "p1", "bf1", "conquer", turn, previous_controller="p2")):
        errors.append("U2 from an enemy: scheduled")
    if sources(BC._score_triggers(s, "p1", "bf1", "conquer", turn)):
        errors.append("U3 not known: scheduled")
    if sources(BC._score_triggers(s, "p1", "bf1", "hold", turn, previous_controller=None)):
        errors.append("U4 hold: scheduled")
    for label, controller, want in (("from none", None, ["yo"]), ("from p2", "p2", [])):
        state = board(controller)
        _next, _record, found = BC.score_battlefield(state, "p1", "bf1", "conquer", turn,
                                                     previous_controller=state["battlefields"]["bf1"]["controller"])
        if sources(found) != want:
            errors.append(f"U5 control path {label}: {sources(found)}")
    bad = board()
    bad["objects"]["yo"]["hold_triggers"] = bad["objects"]["yo"].pop("conquer_triggers")
    if not IR.validate_state(bad):
        errors.append("V: the condition on a hold trigger validated")
    bad = board()
    bad["objects"]["yo"]["conquer_triggers"][0]["condition"]["extra"] = 1
    if not IR.validate_state(bad):
        errors.append("V: the condition with a field validated")
    if errors:
        print("conquer-uncontrolled checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("conquer-uncontrolled checks passed: the unit's conquer trigger fires only on a Battlefield that had no "
          "controller before it (not from an enemy, not when the caller does not say, not on a hold); validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
