#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): a death trigger whose own condition opens its effect - "[Deathknell] - If I died
alone, draw 1." (Lonely Poro) and "[Deathknell] - If I was [Mighty], draw 2." (Unsung Hero). The condition is part of
the trigger condition (Core 383.2.a.1), read off the permanent as its abilities are noted, before it leaves the board
(808.1.d.2): alone (740.2.a, no other friendly unit at its location) or Mighty (708, 5+ Might) then.

  A  alone     dies in its Base with no other friendly unit there - noted; with u1 beside it - not noted; at a Battlefield
               beside an enemy unit only - noted (an enemy unit does not keep it from being alone)
  B  batch     it and a friendly unit beside it die in one simultaneous batch, in both orders - not noted either time (the
               deaths are simultaneous, Core 370.1.a.2: the other is still there as its abilities are noted); the same
               batch with no friendly unit beside it - noted
  M  Mighty    printed 5 - noted; printed 4 - not noted; printed 4 with +1 this turn - noted (its Might as it dies)
  G  grammar   the closed table: "if i died alone" and "if i was [mighty]" only, each the condition above
  V  shape     the condition on a play trigger, or with another field, is refused; a program bringing its own
               noted_at_death is refused (only a kill batch notes it)

    python skill/scripts/check_set2_deathknell.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, apply_simultaneous_kill_batch, validate_program,  # noqa: E402
                       validate_state)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def descriptor(condition):
    return {"trigger_id": "dk", "controller": "p1", "source_object": "dk-unit", "controller_order": 0,
            "effect_program_id": "dk-fx", "optional_at_finalize": False, "condition": {"kind": condition}}


def unit(owner, might=2, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(condition, *, where="base", might=2, beside=None):
    """dk-unit (p1, Deathknell, the condition) at `where` ('base' or 'bf1'); u1 stays in p1's Base only when beside is
    'friendly' - else it goes to p1's trash; 'enemy' puts p2's e1 beside it at bf1."""
    state = base_state()
    state["objects"]["dk-unit"] = unit("p1", might, keywords=["deathknell"], death_triggers=[descriptor(condition)])
    if beside != "friendly":
        state["players"]["p1"]["zones"]["base"].remove("u1")
        state["players"]["p1"]["zones"]["trash"].append("u1")
    if where == "base":
        state["players"]["p1"]["zones"]["base"].append("dk-unit")
    else:
        state["battlefields"]["bf1"]["objects"] = ["dk-unit"]
        if beside == "enemy":
            state["objects"]["e1"] = unit("p2")
            state["battlefields"]["bf1"]["objects"].append("e1")
    return settle_contested(state)


def program(pid, effects, controller="p1"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": controller, "effects": effects}


def noted(state):
    if problems := validate_state(state):
        return f"invalid board: {problems[:2]}"
    done = apply_program(state, program("kill", [{"op": "kill", "effect_id": "k", "object_id": "dk-unit"}], controller="p2"))
    if not done.get("committed"):
        return f"refused: {done.get('errors') or done.get('reason')}"
    return [t["trigger_id"] for t in done.get("pending_triggers") or [] if t.get("source_object") == "dk-unit"]


def noted_in_batch(state, order):
    done = apply_simultaneous_kill_batch(state, order)
    if not done.get("committed"):
        return f"refused: {done.get('errors') or done.get('reason')}"
    return [t["trigger_id"] for t in done.get("pending_triggers") or [] if t.get("source_object") == "dk-unit"]


def main() -> int:
    # A
    for label, state, want in (("alone in its Base", board("died_alone"), ["dk"]),
                               ("u1 beside it in its Base", board("died_alone", beside="friendly"), []),
                               ("at bf1 beside an enemy unit only", board("died_alone", where="bf1", beside="enemy"), ["dk"])):
        if (got := noted(state)) != want:
            fail("A", f"{label}: noted {got}, not {want} (Core 383.2.a.1, 740.2.a)")
    # B
    for order in (["dk-unit", "u1"], ["u1", "dk-unit"]):
        if (got := noted_in_batch(board("died_alone", beside="friendly"), order)) != []:
            fail("B", f"dying with u1 in one batch {order}: noted {got}, not [] (Core 370.1.a.2)")
    if (got := noted_in_batch(board("died_alone"), ["dk-unit"])) != ["dk"]:
        fail("B", f"a batch of one, alone: noted {got}, not ['dk']")
    # M
    for label, might, pump, want in (("printed 5", 5, 0, ["dk"]), ("printed 4", 4, 0, []), ("4, +1 this turn", 4, 1, ["dk"])):
        state = board("was_mighty", might=might)
        if pump:
            done = apply_program(state, program("pump", [{"op": "modify_might", "effect_id": "mm", "object_id": "dk-unit",
                                                          "amount": pump, "duration": "this_turn", "source": "pump"}]))
            if not done.get("committed"):
                fail("M", f"{label}: the +1 was refused: {done.get('errors') or done.get('reason')}")
                continue
            state = done["next_state"]
        if (got := noted(state)) != want:
            fail("M", f"{label}: noted {got}, not {want} (Core 708)")
    # G
    if CG.DEATHKNELL_CONDITIONS != {"if i died alone": {"kind": "died_alone"}, "if i was [mighty]": {"kind": "was_mighty"}}:
        fail("G", f"the table is {CG.DEATHKNELL_CONDITIONS}")
    # V
    misfiled = board("died_alone")
    misfiled["objects"]["u1"] = unit("p1", play_triggers=[{**descriptor("died_alone"), "trigger_id": "pl", "source_object": "u1"}])
    misfiled["players"]["p1"]["zones"]["base"].append("u1")
    misfiled["players"]["p1"]["zones"]["trash"].remove("u1")
    if not any("death trigger" in e for e in validate_state(misfiled)):
        fail("V", "'died_alone' was accepted on a play trigger")
    wide = board("was_mighty")
    wide["objects"]["dk-unit"]["death_triggers"][0]["condition"]["at_least"] = 5
    if not any("death trigger" in e for e in validate_state(wide)):
        fail("V", "a death condition with another field was accepted")
    forged = program("forged", [{"op": "kill", "effect_id": "k", "object_id": "dk-unit",
                                 "noted_at_death": {"alone": True, "mighty": True}}])
    if not any("noted_at_death" in e for e in validate_program(forged)):
        fail("V", "a program bringing its own noted_at_death validated")
    if errors:
        print("FAILED: set 2 Deathknell conditions")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a death trigger's 'if I died alone' / 'if I was [Mighty]' is read off the permanent as its abilities are "
          "noted (383.2.a.1, 808.1.d.2), a simultaneous batch from one snapshot (370.1.a.2); only a death trigger carries it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
