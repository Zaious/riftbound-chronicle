#!/usr/bin/env python3
"""A death trigger's "my battlefield" (package 11, Kog'Maw - Caustic: "[Deathknell] - Deal 4 to all units at my
battlefield.").

The Battlefield the source was at as its abilities were noted, before it moved to the trash (Core 808.1.d.3): the kill
records it on each death trigger (noted_location), the chain item carries it, resolution hands it to the program, and
the location reference {kind: program_source_noted_battlefield} reads it. A source that died in its Base has no
battlefield: "my battlefield" reads null and the instruction is ignored - no battlefield is chosen instead.

  N1 noted         the unit dies at bf1: its trigger notes bf1; resolved, every unit at bf1 - of either side - takes 4;
                   units at another battlefield and in the bases do not
  N2 base          the unit dies in its Base: the trigger notes its Base; resolved, ignored as source-unavailable,
                   nothing dealt
  N3 not noted     a program with that reference and no noted location: refused by name, nothing dealt
  N4 carried       the chain item carries the note from the trigger; a program bringing its own note is refused at
                   binding (only the engine binds it); a malformed note on a descriptor is refused when scheduled

    python skill/scripts/check_noted_battlefield.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (PROGRAM_VERSION, SOURCE_UNAVAILABLE_OUTCOME, apply_program, validate_program,  # noqa: E402
                       validate_state)
from resolution_bridge import bind_trigger_event  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, schedule_triggered_items  # noqa: E402

errors: list[str] = []
MY_BATTLEFIELD = {"kind": "program_source_noted_battlefield"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(where="bf1"):
    """kog (p1, Deathknell) at `where`; at bf1 also a1 (p1) and e1 (p2); at bf2 e2 (p2); u1, u2 in the bases."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["objects"]["kog"] = unit("p1", keywords=["deathknell"], death_triggers=[
        {"trigger_id": "kog-dk", "controller": "p1", "source_object": "kog", "controller_order": 0,
         "effect_program_id": "kog-dk-fx", "optional_at_finalize": False}])
    for oid, owner in (("a1", "p1"), ("e1", "p2"), ("e2", "p2")):
        state["objects"][oid] = unit(owner)
    state["battlefields"]["bf1"]["objects"] = ["a1", "e1"]
    state["battlefields"]["bf2"]["objects"] = ["e2"]
    if where == "base":
        state["players"]["p1"]["zones"]["base"].append("kog")
    else:
        state["battlefields"][where]["objects"].append("kog")
    return settle_contested(state)


def program(pid, effects, controller="p1", **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": controller, "effects": effects, **extra}


DEAL = {"op": "deal_damage", "effect_id": "d", "amount": 4,
        "affected": {"criteria": {"kind": "unit", "location_ref": dict(MY_BATTLEFIELD)}}}


def dies(state):
    done = apply_program(state, program("kill", [{"op": "kill", "effect_id": "k", "object_id": "kog"}], controller="p2"))
    if not done.get("committed"):
        return None, None
    return done["next_state"], (done.get("pending_triggers") or [None])[0]


def resolve(state, trigger):
    chain_item = {"id": trigger["trigger_id"], "noted_location": trigger.get("noted_location")}
    bound, refusal = bind_trigger_event(program("kog-dk-fx", [dict(DEAL)], source_object="kog"), chain_item)
    if refusal is not None:
        return {"refused_at_binding": refusal}
    return apply_program(state, bound)


def damage(state, *oids):
    return [state["objects"][o]["damage"] for o in oids]


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    after, trigger = dies(s)
    if trigger is None or trigger.get("noted_location") != {"kind": "battlefield", "battlefield": "bf1"}:
        fail("N1 noted", f"the trigger did not note bf1: {trigger}")
    else:
        got = resolve(after, trigger)
        if not got.get("committed") or damage(got["next_state"], "a1", "e1") != [4, 4] \
                or damage(got["next_state"], "e2", "u1", "u2") != damage(after, "e2", "u1", "u2"):
            fail("N1 noted", f"{got.get('reason') or got.get('errors')} {damage((got.get('next_state') or after), 'a1', 'e1', 'e2')}")
    after, trigger = dies(board("base"))
    if trigger is None or trigger.get("noted_location") != {"kind": "base", "player": "p1"}:
        fail("N2 base", f"the trigger did not note p1's Base: {trigger}")
    else:
        got = resolve(after, trigger)
        step = next((e for e in got.get("trace") or [] if e.get("effect_id") == "d"), {})
        if not got.get("committed") or step.get("outcome") != SOURCE_UNAVAILABLE_OUTCOME \
                or damage(got["next_state"], "a1", "e1", "e2") != [0, 0, 0]:
            fail("N2 base", f"{step.get('outcome')} {got.get('reason')}")
    after, _ = dies(s)
    none = apply_program(after, program("kog-dk-fx", [dict(DEAL)], source_object="kog"))
    if none.get("committed") and any(none["next_state"]["objects"][o]["damage"] for o in ("a1", "e1")):
        fail("N3 not noted", "dealt with no noted location")
    if none.get("committed") or "location_ref" not in str(none.get("reason_code") or "") + str(none.get("reason") or ""):
        fail("N3 not noted", f"not refused by name: {none.get('committed')} {none.get('reason_code')} {none.get('reason')}")
    _, trigger = dies(s)
    forged = program("kog-dk-fx", [dict(DEAL)], source_object="kog", noted_location={"kind": "battlefield", "battlefield": "bf2"})
    _, refusal = bind_trigger_event(forged, {"id": "kog-dk", "noted_location": trigger["noted_location"]})
    if refusal is None or refusal.get("reason") != "effect_program_noted_location_mismatch":
        fail("N4 carried", f"a program's own note was accepted: {refusal}")
    from check_rules_core import fixture as timing_fixture  # noqa: E402
    descriptor = {**trigger, "controller_order": 0}
    scheduled = schedule_triggered_items(timing_fixture(), [descriptor])
    item = next((i for i in (scheduled.get("next_state") or {}).get("chain", {}).get("items", []) if i["id"] == "kog-dk"), {})
    if item.get("noted_location") != trigger["noted_location"]:
        fail("N4 carried", f"the chain item did not carry the note: {item.get('noted_location')} {scheduled.get('reason_code')}")
    bad = schedule_triggered_items(timing_fixture(), [{**descriptor, "noted_location": {"kind": "battlefield"}}])
    if bad.get("applied"):
        fail("N4 carried", "a malformed note was scheduled")
    if not validate_program(program("x", [dict(DEAL)], noted_location={"kind": "hand", "player": "p1"})):
        fail("N4 carried", "a program with a malformed note validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: noted battlefield checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a death trigger's 'my battlefield' is where its source was as it died - every unit there, of either side, "
          "nothing elsewhere; died in a Base it reads null and the instruction is ignored; with no note it is refused; "
          "the note is the engine's, carried from the trigger to the chain item to the program (N1-N4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
