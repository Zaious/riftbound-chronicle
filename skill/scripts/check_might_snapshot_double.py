#!/usr/bin/env python3
"""Doubling a unit's Might is a snapshot (package 10, Last Stand; GPT 2026-10-08 ruling 11).

The card doubles one friendly unit's Might for the turn and makes that unit Temporary. The ruling (Core 477.3.c): the
target's effective Might is read as the instruction executes and given to it as a FIXED this-turn modifier of +X -
not a running x2: a later change to its Might is not doubled again. A Might of 0 or less adds nothing (no event, Core
370.1.a). "It" is the same unit; [Temporary] is granted to it.

  L1 doubled       u1 at Might 3: +3 this turn, Might 6, one might_arithmetic entry of +3
  L2 snapshot      u1 at 3, doubled, then +2 by another effect: Might 8 (not 10)
  L3 read late     u1 given +1 before the doubling: Might 4 -> 8
  L4 not positive  u1 at Might 0 (a -3 modifier on 3): nothing given (no_op), still 0
  L5 temporary     the card's two instructions: doubled, and [Temporary] on the same unit
  V  validation    only a this-turn modify_might on one target, with no bounds, reads its own object's Might

    python skill/scripts/check_might_snapshot_double.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, effective_might, has_keyword, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(might=3):
    state = base_state()
    state["objects"]["u1"]["base_might"] = might
    return state


def double(state):
    return {"op": "modify_might", "effect_id": "dbl", "duration": "this_turn", "source": "c1",
            "amount_ref": {"kind": "object_current_might"},
            "target": {"object_id": "u1", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly",
                       "bound_identity": object_identity(state, "u1")}}


def pump(effect_id, amount):
    return {"op": "modify_might", "effect_id": effect_id, "object_id": "u1", "amount": amount, "duration": "this_turn",
            "source": "c2"}


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "last-stand", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def might_after(state, *effects):
    done = apply_program(state, program(*effects))
    return (effective_might(done["next_state"], "u1") if done.get("committed") else None), done


def main() -> int:
    s = board(3)
    got, done = might_after(s, double(s))
    if got != 6:
        fail("L1 doubled", f"{got} {done.get('reason') or done.get('errors')}")
    got, done = might_after(s, double(s), pump("p", 2))
    if got != 8:
        fail("L2 snapshot", f"Might {got}, wanted 8 (3 +3 fixed, +2 not doubled)")
    got, done = might_after(s, pump("p", 1), double(s))
    if got != 8:
        fail("L3 read late", f"Might {got}, wanted 8 (3 +1 read as 4, +4)")
    zero = board(3)
    got, done = might_after(zero, pump("p", -3), double(zero))
    event = next((t for t in done.get("trace") or [] if t.get("effect_id") == "dbl"), {})
    if got != 0 or event.get("outcome") != "no_op":
        fail("L4 not positive", f"Might {got}, event {event.get('outcome')} {event.get('reason')}")
    temp = {"op": "grant_keyword", "effect_id": "tmp", "keyword": "temporary", "duration": "permanent", "source": "c1",
            "object_id": "u1"}
    got, done = might_after(s, double(s), temp)
    if got != 6 or not done.get("committed") or not has_keyword(done["next_state"], "u1", "temporary"):
        fail("L5 temporary", f"{got} {done.get('reason') or done.get('errors')}")
    for label, wrong in (("on a deal", {**double(s), "op": "deal_damage"}),
                         ("persistent", {**double(s), "duration": "persistent"}),
                         ("with a floor", {**double(s), "minimum": 1})):
        if not validate_program(program(wrong)):
            fail("V validation", f"{label} was accepted")
    if validate_program(program(double(s))):
        fail("V validation", f"the card's own instruction is invalid: {validate_program(program(double(s)))}")
    if errors:
        print("FAILED: Might doubling snapshot checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'Double a unit's Might this turn' gives a fixed +X read as it executes - not doubled again later, nothing "
          "when not positive; [Temporary] on the same unit (L1-L5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
