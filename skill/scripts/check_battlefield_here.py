#!/usr/bin/env python3
"""A Battlefield's own "here" (package 10, Navori Fighting Pit: "When you hold here, buff a unit here.").

"Here" names the Battlefield the ability's source is at (location_ref program_source_current_battlefield). When the
source IS a Battlefield - its own ability - "here" is that Battlefield, bound by its identity like any source.

  H1 here          the Battlefield's program buffs a chosen unit at it - of either side
  H2 elsewhere     a unit in a Base, or at another Battlefield, is no legal target
  H3 identity      the program bound to the Battlefield's earlier identity: refused by name, nothing buffed
  H4 no identity   a Battlefield program that declares none: refused by name

    python skill/scripts/check_battlefield_here.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, LOCATION_REF_ABSENT,  # noqa: E402
                       LOCATION_REF_IDENTITY_CHANGED, apply_program, battlefield_identity, hash_value, object_identity,
                       validate_state)

errors: list[str] = []
TARGET = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
          "location_ref": {"kind": "program_source_current_battlefield"}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board():
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["objects"]["u3"] = copy.deepcopy(state["objects"]["u1"])
    state["objects"]["u4"] = {**copy.deepcopy(state["objects"]["u1"]), "owner": "p2", "controller": "p2"}
    state["players"]["p1"]["zones"]["base"] = [o for o in state["players"]["p1"]["zones"]["base"] if o != "u1"]
    state["battlefields"]["bf1"].update({"controller": "p1", "objects": ["u1", "u4"]})
    state["battlefields"]["bf2"].update({"controller": "p1", "objects": ["u3"]})
    return settle_contested(state)


def buff(state, pick, *, identity="default"):
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "bf1-hold", "controller": "p1", "source_object": "bf1",
               "effects": [{"op": "buff", "effect_id": "b", "target": dict(TARGET)}]}
    if identity == "default":
        program["source_identity"] = battlefield_identity(state, "bf1")
    elif identity is not None:
        program["source_identity"] = identity
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "kind": "target_selection", "stage": "trigger_finalization", "controller": "p1",
         "value": [pick], "selection_identities": {pick: object_identity(state, pick)}}]}
    return apply_program(state, program, decisions=decisions)


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    for pick in ("u1", "u4"):
        got = buff(s, pick)
        if not got.get("committed") or not got["next_state"]["objects"][pick].get("buffed"):
            fail("H1 here", f"{pick}: {got.get('reason_code')} {got.get('reason') or got.get('errors')}")
    base = copy.deepcopy(s)
    base["battlefields"]["bf1"]["objects"].remove("u1")
    base["players"]["p1"]["zones"]["base"].append("u1")
    for label, state, pick in (("a unit in its Base", base, "u1"), ("a unit at another Battlefield", s, "u3")):
        got = buff(state, pick)
        if got.get("committed") and got["next_state"]["objects"][pick].get("buffed"):
            fail("H2 elsewhere", f"{label} was buffed")
    old = buff(s, "u1", identity="bf1@7")
    if (old.get("committed") and old["next_state"]["objects"]["u1"].get("buffed")) \
            or LOCATION_REF_IDENTITY_CHANGED not in str(old):
        fail("H3 identity", f"{old.get('reason_code')} {old.get('reason')}")
    none = buff(s, "u1", identity=None)
    if none.get("committed") and none["next_state"]["objects"]["u1"].get("buffed") or LOCATION_REF_ABSENT not in str(none):
        fail("H4 no identity", f"{none.get('reason_code')} {none.get('reason')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: battlefield here checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a Battlefield's own 'here' is that Battlefield - a unit of either side there is chosen; elsewhere is not; "
          "an earlier identity or none is refused by name (H1-H4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
