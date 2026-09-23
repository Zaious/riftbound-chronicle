#!/usr/bin/env python3
"""A triggered ability's program runs with the identity its source had when it triggered.

The relational "here" (`location_ref`, GPT 2026-09-23) refuses to resolve unless the
program declares its source's identity - mandatory, so a reference never lands on a
different object standing at the same id. A triggered ability's program is a
registered TEMPLATE: it cannot know which generation of its source will trigger it.
combat.open_combat already records that identity on every Attack/Defend descriptor,
but schedule_triggered_items dropped it, so "When I attack, deal 3 to all enemy
units here." could never resolve in play - only in hand-built probes that declared
the identity themselves.

Now the chain item keeps the descriptor's identity and the resolution bridge hands
it to the program at finalization and at resolution. Held here, through the real
schedule -> finalize_trigger -> priority -> resolve_with_program path:

  kept             the scheduled chain item carries the descriptor's identity; an
                   empty one is refused as a descriptor error
  positive         source still at bf1: exactly the enemy there is hit, not e3 at bf2
  moved            source moved to bf2 before resolution: "here" is read fresh (e3)
  base             source moved to Base before resolution (Core 359.3.f.2's own
                   example): named refusal, nothing hit
  new object       source replaced by a new generation at the same id: named
                   refusal, never the new object standing in
  forged           a template declaring some other identity: refused at dispatch,
                   not silently overridden
  no record        a descriptor that recorded no identity: the program is unchanged,
                   so "here" is refused by name - never guessed

    python skill/scripts/check_trigger_source_identity.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import object_identity  # noqa: E402
from resolution_bridge import finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority, schedule_triggered_items  # noqa: E402

TRIGGER, PROGRAM_ID = "u1-on-attack", "u1-on-attack-effects"
HERE = {"kind": "program_source_current_battlefield"}


def program() -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": PROGRAM_ID, "controller": "p1", "source_object": "u1",
            "effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": 3,
                         "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy",
                                                   "location_ref": dict(HERE)}}}]}


def board() -> dict:
    """u1 (p1, the source) and u2 (p2) at bf1; e3 (p2) at bf2."""
    state = base_state()
    state["turn_id"] = "T1"
    state["players"]["p1"]["zones"]["base"] = []
    state["players"]["p2"]["zones"]["base"] = []
    state["objects"]["e3"] = {"owner": "p2", "controller": "p2", "kind": "unit",
                              "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
    state["battlefields"] = {"bf1": {"controller": None, "objects": ["u1", "u2"]},
                             "bf2": {"controller": None, "objects": ["e3"]}}
    settle_contested(state)
    return state


def descriptor(state: dict, *, identity: str | None = "own") -> dict:
    entry = {"trigger_id": TRIGGER, "controller": "p1", "source_object": "u1", "controller_order": 0,
             "effect_program_id": PROGRAM_ID, "effect_program_hash": program_hash(program()),
             "optional_at_finalize": False}
    if identity == "own":
        entry["source_identity"] = object_identity(state, "u1")
    elif identity is not None:
        entry["source_identity"] = identity
    return entry


def run(state: dict, *, registry: dict | None = None, identity: str | None = "own", before_resolution=None) -> dict:
    scheduled = schedule_triggered_items(fixture(), [descriptor(state, identity=identity)])
    if scheduled.get("applied") is not True:
        return {"stage": "schedule", "result": scheduled}
    timing = scheduled["next_state"]
    finalized = finalize_trigger(timing, state, registry or {PROGRAM_ID: program()}, None)
    if not finalized.get("committed"):
        return {"stage": "finalize", "result": finalized, "timing": timing}
    timing = finalized["next_timing_state"]
    for actor in ("p1", "p2"):
        timing = pass_priority(timing, actor).get("next_state") or timing
    effect_state = copy.deepcopy(state)
    if before_resolution is not None:
        before_resolution(effect_state)
    done = resolve_with_program(timing, TRIGGER, effect_state, program())
    return {"stage": "resolve", "result": done, "timing": timing}


def hit(done: dict) -> list[str] | None:
    if not done["result"].get("committed"):
        return None
    event = next((e for e in (done["result"].get("trace") or {}).get("effect") or []
                  if e.get("op") == "deal_damage"), None) if isinstance(done["result"].get("trace"), dict) else None
    if event is None:
        after = done["result"]["next_effect_state"]["objects"]
        return sorted(o for o in ("u1", "u2", "e3") if after[o].get("damage"))
    return sorted(event.get("affected_objects") or [])


def refusal_code(done: dict) -> str | None:
    result = done["result"]
    return ((result.get("effect_result") or {}).get("reason_code") or result.get("reason_code")
            or result.get("reason"))


def main() -> int:
    errors: list[str] = []
    state = board()
    if found := effect_ir.validate_state(state):
        print(f"FAILED: fixture invalid: {found}")
        return 1

    # kept
    scheduled = schedule_triggered_items(fixture(), [descriptor(state)])
    item = (scheduled.get("next_state") or {}).get("chain", {}).get("items", [{}])[0]
    if item.get("source_identity") != object_identity(state, "u1"):
        errors.append(f"kept: the chain item carries {item.get('source_identity')!r}, not the descriptor's identity")
    empty = schedule_triggered_items(fixture(), [descriptor(state, identity="")])
    if empty.get("applied") is not False:
        errors.append("kept: a descriptor with an empty source_identity was scheduled")

    # positive
    done = run(state)
    if done["stage"] != "resolve" or hit(done) != ["u2"]:
        errors.append(f"positive: expected exactly ['u2'] hit at bf1, got stage {done['stage']} "
                      f"{hit(done) if done['stage'] == 'resolve' else refusal_code(done)}")

    # moved to bf2 before resolution
    def to_bf2(s):
        s["battlefields"]["bf1"]["objects"].remove("u1")
        s["battlefields"]["bf2"]["objects"].append("u1")
    done = run(state, before_resolution=to_bf2)
    if done["stage"] != "resolve" or hit(done) != ["e3"]:
        errors.append(f"moved: expected exactly ['e3'] (read fresh at bf2), got "
                      f"{hit(done) if done['stage'] == 'resolve' else refusal_code(done)}")

    # moved to Base before resolution (Core 359.3.f.2)
    def to_base(s):
        s["battlefields"]["bf1"]["objects"].remove("u1")
        s["players"]["p1"]["zones"]["base"].append("u1")
    done = run(state, before_resolution=to_base)
    if done["result"].get("committed") or refusal_code(done) != effect_ir.LOCATION_REF_NOT_AT_BATTLEFIELD:
        errors.append(f"base: expected {effect_ir.LOCATION_REF_NOT_AT_BATTLEFIELD}, got "
                      f"committed={done['result'].get('committed')} {refusal_code(done)}")

    # a new object at the same id before resolution
    def new_generation(s):
        s["objects"]["u1"]["identity"] = "u1@9"
    done = run(state, before_resolution=new_generation)
    if done["result"].get("committed") or refusal_code(done) != effect_ir.LOCATION_REF_IDENTITY_CHANGED:
        errors.append(f"new object: expected {effect_ir.LOCATION_REF_IDENTITY_CHANGED}, got "
                      f"committed={done['result'].get('committed')} {refusal_code(done)}")

    # a template forging another identity
    forged = {**program(), "source_identity": "u1@7"}
    done = run(state, registry={PROGRAM_ID: forged})
    if done["stage"] != "finalize" or done["result"].get("reason") != "effect_program_source_identity_mismatch":
        errors.append(f"forged: expected a refusal at dispatch, got stage {done['stage']} {refusal_code(done)}")

    # no identity recorded on the descriptor
    done = run(state, identity=None)
    if done["result"].get("committed") or refusal_code(done) != effect_ir.LOCATION_REF_ABSENT:
        errors.append(f"no record: expected {effect_ir.LOCATION_REF_ABSENT}, got "
                      f"committed={done['result'].get('committed')} {refusal_code(done)}")

    if errors:
        print("FAILED: trigger source identity")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("trigger source identity: the chain item keeps the descriptor's identity and the program runs with it - "
          "'here' resolves at bf1, re-reads bf2 after a move, and refuses by name after a move to Base, a new "
          "object at the same id, a forged template identity, and a descriptor that recorded none.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
