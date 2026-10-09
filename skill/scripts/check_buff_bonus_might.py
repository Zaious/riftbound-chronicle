#!/usr/bin/env python3
"""Buffs give an additional +N Might this turn (package 10, Stand United).

The card buffs a friendly unit and, for the rest of the turn, makes each buff on its controller's units give one more
Might (Core 703: a buff gives +1). Read live off the turn effect - a unit buffed later this turn gets it too - and only on
the granting player's side; it expires with the turn (Core 317.2.c).

  S1 granted       a buffed friendly unit: Might base + 2 (one buff, +1 more)
  S2 later buff    a friendly unit buffed after the effect: + 2 as well
  S3 unbuffed      a friendly unit with no buff: unchanged
  S4 enemy         a buffed enemy unit: + 1 only
  S5 next turn     the turn moved on: + 1 again
  S6 two grants    two such effects: + 3 per buff
  V  validation    the value is a positive integer

    python skill/scripts/check_buff_bonus_might.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, effective_might, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
GRANT = {"op": "grant_turn_effect", "effect_id": "grant", "turn_effect_kind": "buff_bonus_might", "value": 1,
         "controller": "p1", "source": "c1"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board():
    state = base_state()
    for oid, owner, extra in (("f1", "p1", {"buffed": True}), ("f2", "p1", {}), ("f3", "p1", {}), ("e1", "p2", {"buffed": True})):
        state["objects"][oid] = unit(owner, **extra)
        state["players"][owner]["zones"]["base"].append(oid)
    return state


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "stand-united", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def main() -> int:
    granted = apply_program(board(), program(GRANT))
    if not granted.get("committed") or validate_state(granted["next_state"]):
        print(f"FAILED: the turn effect was not granted: {granted.get('errors') or validate_state(granted['next_state'])}")
        return 1
    s = granted["next_state"]
    if effective_might(s, "f1") != 5:
        fail("S1 granted", effective_might(s, "f1"))
    later = apply_program(s, program({"op": "buff", "effect_id": "b", "object_id": "f3"}))
    if not later.get("committed") or effective_might(later["next_state"], "f3") != 5:
        fail("S2 later buff", f"{later.get('reason')} {later.get('next_state') and effective_might(later['next_state'], 'f3')}")
    if effective_might(s, "f2") != 3:
        fail("S3 unbuffed", effective_might(s, "f2"))
    if effective_might(s, "e1") != 4:
        fail("S4 enemy", effective_might(s, "e1"))
    nxt = copy.deepcopy(s)
    nxt["turn_id"] = "turn-next"
    if effective_might(nxt, "f1") != 4:
        fail("S5 next turn", effective_might(nxt, "f1"))
    twice = apply_program(s, program({**GRANT, "effect_id": "grant2"}))
    if not twice.get("committed") or effective_might(twice["next_state"], "f1") != 6:
        fail("S6 two grants", twice.get("next_state") and effective_might(twice["next_state"], "f1"))
    for value in (0, True, "1"):
        bad = copy.deepcopy(s)
        bad["turn_effects"][-1]["value"] = value
        if not validate_state(bad):
            fail("V validation", f"value {value!r} was accepted")
    if errors:
        print("FAILED: buff bonus Might checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'buffs give an additional +1 [M] this turn' - each buff on the granting side gives +2 for the turn, a later "
          "buff too; not the unbuffed, not the enemy, not next turn (S1-S6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
