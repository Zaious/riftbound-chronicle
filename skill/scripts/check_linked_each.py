#!/usr/bin/env python3
"""An instruction applied to each object an earlier instruction acted on (package 10, Overt Operation).

The card lets its controller spend the buff of any number of friendly units, readying each unit whose buff was spent,
then buffs every friendly unit. "Ready it" is applied to exactly the units the spend acted on (Core 359.3.e.14) - each one
its own Ready; none spent, nothing readied; the spend ignored, the readying is too (359.3.e.14.a).

  E1 two spent     u1 and u3 (buffed, exhausted) chosen: both lose the buff and are readied; u4 (buffed, exhausted, not
                   chosen) is untouched
  E2 none spent    nothing chosen: nothing readied (no_op)
  E3 then buff     the card's three instructions: spent ones readied, then every friendly unit buffed
  E4 enemy         an enemy unit named for the spend: refused (Core 702.2.b.2)
  V  validation    linked_each only on ready, naming an earlier spend_buffs; no target / object_id beside it

    python skill/scripts/check_linked_each.py
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
SPEND = {"op": "spend_buffs", "effect_id": "sb", "player": "p1", "decision_ref": "sb"}
READY = {"op": "ready", "effect_id": "rd", "linked_each": "sb"}
BUFF_ALL = {"op": "buff", "effect_id": "bf", "affected": {"criteria": {"kind": "unit", "controller_relation": "friendly", "location": "board"}}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": True, "buffed": True, **extra}


def board():
    state = base_state()
    state["objects"]["u1"].update({"buffed": True, "exhausted": True})
    for oid, owner in (("u3", "p1"), ("u4", "p1"), ("e3", "p2")):
        state["objects"][oid] = unit(owner)
        state["players"][owner]["zones"]["base"].append(oid)
    return state


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "overt", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def spend(state, chosen):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "sb", "kind": "target_selection", "stage": "resolution", "controller": "p1", "value": list(chosen),
         "selection_identities": {o: object_identity(state, o) for o in chosen}}]}


def flags(state, *oids):
    return {o: (bool(state["objects"][o].get("buffed")), bool(state["objects"][o]["exhausted"])) for o in oids}


def main() -> int:
    s = board()
    two = apply_program(s, program(SPEND, READY), decisions=spend(s, ["u1", "u3"]))
    if not two.get("committed") or flags(two["next_state"], "u1", "u3", "u4") != {"u1": (False, False), "u3": (False, False),
                                                                                    "u4": (True, True)}:
        fail("E1 two spent", f"{two.get('reason') or two.get('errors')} {two.get('next_state') and flags(two['next_state'], 'u1', 'u3', 'u4')}")
    none = apply_program(s, program(SPEND, READY), decisions=spend(s, []))
    event = next((t for t in none.get("trace") or [] if t.get("effect_id") == "rd"), {})
    if not none.get("committed") or event.get("outcome") not in ("no_op", "skipped_linked_dependency") \
            or flags(none["next_state"], "u1", "u3") != {"u1": (True, True), "u3": (True, True)}:
        fail("E2 none spent", f"{none.get('reason')} {event.get('outcome')}")
    whole = apply_program(s, program(SPEND, READY, BUFF_ALL), decisions=spend(s, ["u3"]))
    if not whole.get("committed") or flags(whole["next_state"], "u1", "u3", "u4") != {"u1": (True, True), "u3": (True, False),
                                                                                        "u4": (True, True)}:
        fail("E3 then buff", f"{whole.get('reason') or whole.get('errors')} {whole.get('next_state') and flags(whole['next_state'], 'u1', 'u3', 'u4')}")
    enemy = apply_program(s, program(SPEND, READY), decisions=spend(s, ["e3"]))
    if enemy.get("committed"):
        fail("E4 enemy", "an enemy unit's buff was spent")
    for label, effects in (("on a kill", [SPEND, {**READY, "op": "kill"}]),
                           ("naming a buff", [BUFF_ALL, {**READY, "linked_each": "bf"}]),
                           ("beside an object", [SPEND, {**READY, "object_id": "u1"}])):
        if not validate_program(program(*effects)):
            fail("V validation", f"{label} was accepted")
    if errors:
        print("FAILED: linked-each checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'spend its buff to ready it' readies exactly the units whose buff was spent - each its own Ready; none "
          "spent, none readied; an enemy's buff refused (E1-E4, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
