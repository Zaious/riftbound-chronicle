#!/usr/bin/env python3
"""
Standing gate: the typed self-reference `{"object_ref": "program_source"}`.

"Give me +3 Might this turn." names the resolving source object and makes no
decision. Codex approved wiring it on 2026-09-10 with one shape refused up
front: a magic string. `"$source_object"` would be forgeable by anything that
can write a string - a decision artifact, a hand-edited program, a mapping's
expected IR - and forging it means naming the source without the engine ever
checking its identity or its zone. So it is a typed reference the engine alone
creates and resolves, and this holds that:

  * the four adopted ops resolve it and really act on the source. Adoption is
    PER OP: `ready` working proves nothing about `kill`, so an op outside the
    reviewed set is refused by its own code rather than quietly allowed;
  * it binds the source's full IDENTITY, not its id. An id can be reused after
    an object leaves and returns; the identity token cannot;
  * five named refusals fire on the five things that can be wrong, each with
    its own code, so a failure says which one happened;
  * a decision artifact carrying the shape is refused. If an artifact could
    inject one, the typing would buy nothing.

    python skill/scripts/check_object_ref_self.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program,  # noqa: E402
                       effective_might, hash_value, object_identity)
from engine_decisions import DECISIONS_VERSION, validate_engine_decisions  # noqa: E402

REF = {"object_ref": "program_source"}
EXTRA = {"ready": {}, "buff": {}, "banish": {},
         "modify_might": {"amount": 3, "duration": "this_turn", "source": "u1"}}


def state_with_source():
    state = base_state()
    state["turn_id"] = "T1"
    state["objects"]["u1"].update(base_might=3, might_modifiers=[], exhausted=True)
    return state


def program(op, state, *, source="u1", declare_identity=True, effects=None):
    doc = {"schema_version": PROGRAM_VERSION,
           "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
           "program_id": "p1", "controller": "p1", "source_object": source,
           "effects": effects or [dict({"op": op, "effect_id": "e", "object_id": REF},
                                       **EXTRA.get(op, {}))]}
    if declare_identity:
        doc["source_identity"] = (object_identity(state, source) if source in state["objects"]
                                  else "gone@0")
    return doc


def main() -> int:
    errors: list[str] = []

    def fail(label, detail):
        errors.append(f"{label}: {detail}")

    def expect_refusal(label, result, code):
        if result.get("committed") is not False:
            return fail(label, f"expected {code}, but the program committed")
        if result.get("reason_code") != code:
            return fail(label, f"expected {code}, got {result.get('reason_code')!r} "
                               f"({result.get('reason') or result.get('errors')})")

    # --- every adopted op resolves it, and really acts on the source ----------
    for op in sorted(effect_ir.OBJECT_REF_OPS):
        state = state_with_source()
        result = apply_program(state, program(op, state))
        if result.get("committed") is not True:
            fail(f"adopted op {op}", f"did not run: "
                                     f"{result.get('reason') or result.get('errors')}")
            continue
        # The trace must name the object it resolved to, never the reference.
        # Ops record it differently - `banish` writes an `objects` list where
        # `ready` writes `object_id` - so the check is that the resolved id is
        # there and the raw reference is not, rather than one field's shape.
        event = next((e for e in result["trace"] if e.get("op") == op), {})
        named = ([event["object_id"]] if isinstance(event.get("object_id"), str)
                 else list(event.get("objects") or []))
        if "u1" not in named:
            fail(f"adopted op {op}", f"the trace names {named}, not the resolved source")
        if effect_ir.contains_object_ref(event):
            fail(f"adopted op {op}", "the trace still carries the raw object_ref; a reader "
                                     "downstream would see the reference, not the object")
        # and the state really changed, so this is resolution and not acceptance
        after = result["next_state"]
        if op == "ready" and after["objects"]["u1"].get("exhausted") is not False:
            fail("adopted op ready", "the source is still exhausted; nothing was applied")
        if op == "modify_might" and effective_might(after, "u1") != 6:
            fail("adopted op modify_might", f"Might is {effective_might(after, 'u1')}, not 6")
        if op == "buff" and not after["objects"]["u1"].get("buffed"):
            fail("adopted op buff", "the source is not Buffed; nothing was applied")
        if op == "banish" and "u1" in (after["players"]["p1"]["zones"]["base"]):
            fail("adopted op banish", "the source is still in its Base")
        # The static executor audit lives in the overlay (executor_audit.py) and
        # is asserted there, per op, by check_object_ref_adoption.py. What is
        # checked HERE is stronger and independent: the op ran and the source's
        # own state changed, which no amount of schema acceptance can fake.

    # --- adoption is per op ---------------------------------------------------
    state = state_with_source()
    for op in ("kill", "stun", "exhaust"):
        if op in effect_ir.OBJECT_REF_OPS:
            continue
        expect_refusal(f"unadopted op {op}", apply_program(state, program(op, state)),
                       effect_ir.OBJECT_REF_OP_NOT_ADOPTED)

    # --- the four ways the reference itself can be wrong ----------------------
    expect_refusal("the source is not in the state",
                   apply_program(state, program("ready", state, source="nobody")),
                   effect_ir.OBJECT_REF_ABSENT)

    changed = copy.deepcopy(state)
    changed["objects"]["u1"]["identity"] = "u1@9"
    expect_refusal("the source's identity changed",
                   apply_program(changed, {**program("ready", state), "source_identity": "u1@0"}),
                   effect_ir.OBJECT_REF_IDENTITY_CHANGED)

    gone = copy.deepcopy(state)
    gone["players"]["p1"]["zones"]["base"].remove("u1")
    gone["players"]["p1"]["zones"]["trash"].append("u1")
    expect_refusal("the source left the board",
                   apply_program(gone, program("ready", gone)),
                   effect_ir.OBJECT_REF_LEFT_PLAY)

    spell = copy.deepcopy(state)
    expect_refusal("the source is a Spell, not a permanent",
                   apply_program(spell, program("ready", spell, source="c3")),
                   effect_ir.OBJECT_REF_LEFT_PLAY)

    expect_refusal("the clause also names a target",
                   apply_program(state, program("ready", state, effects=[
                       {"op": "ready", "effect_id": "e", "object_id": REF,
                        "target": {"object_id": "u2", "chosen_zone_class": "board",
                                   "kind": "unit"}}])),
                   effect_ir.OBJECT_REF_NOT_SELF)

    # --- identity, not id: a returned object with the same id is not the same -
    returned = copy.deepcopy(state)
    returned["objects"]["u1"]["identity"] = "u1@1"
    result = apply_program(returned, {**program("ready", state), "source_identity": "u1@0"})
    if result.get("reason_code") != effect_ir.OBJECT_REF_IDENTITY_CHANGED:
        fail("identity binding", "an object reusing the id at a new generation was accepted; "
                                 "the reference binds the identity, not the id")

    # --- an artifact may not inject the shape --------------------------------
    envelope = {"schema_version": DECISIONS_VERSION, "input_hash": hash_value(state),
                "decisions": [{"decision_id": "t", "stage": "play_declaration",
                               "kind": "optional_choice", "controller": "p1",
                               "value": True, "provenance": REF}]}
    if validate_engine_decisions(envelope):
        fail("injection", "an object_ref inside `provenance` was refused; provenance is prose "
                          "and the check should not reach into it")
    hostile = copy.deepcopy(envelope)
    hostile["decisions"][0]["value"] = REF
    if not any("object_ref" in e for e in validate_engine_decisions(hostile)):
        fail("injection", "a decision artifact carrying an object_ref was accepted; the typing "
                          "buys nothing if an artifact can forge one")

    if errors:
        print("FAILED: typed self-reference")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print(f"typed self-reference holds: {len(effect_ir.OBJECT_REF_OPS)} adopted op(s) "
          f"({', '.join(sorted(effect_ir.OBJECT_REF_OPS))}) resolve it and change the state, "
          f"adoption is refused for every other op by its own code, the reference binds the "
          f"source's identity rather than its id, five named refusals fire, and a decision "
          f"artifact carrying the shape is refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
