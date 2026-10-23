#!/usr/bin/env python3
"""A keyword aura that only gives the keyword where it is absent (package 10, Spirit's Refuge).

The gear's static ability gives each friendly unit that has a buff the [Deflect] keyword, unless that unit already has
Deflect from anywhere else - then it keeps exactly its own (Deflect values are summed, so a second instance would change
what opponents pay). Read live while the source is on the board (Core 365.1, 479.3).

  A1 given         a buffed friendly unit with no Deflect: Deflect 1
  A2 not added     a buffed friendly unit with its own Deflect 2: still 2 (not 3)
  A4 not buffed    an unbuffed friendly unit: no Deflect
  A5 enemy         a buffed enemy unit: no Deflect
  A6 source gone   the gear in its owner's trash: nobody has it
  V  validation    only_if_absent is true when present, and never with a value
  G  grammar       the production and its near misses

    python skill/scripts/check_keyword_aura_if_absent.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import deflect_total, keyword_values, validate_state  # noqa: E402

TEXT = "Friendly buffed units have [Deflect] if they didn't already."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(aura):
    state = base_state()
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "static_auras": [copy.deepcopy(aura)]}
    state["players"]["p1"]["zones"]["base"].append("g1")
    for oid, owner, extra in (("b1", "p1", {"buffed": True}), ("b2", "p1", {"buffed": True, "keywords": ["deflect"],
                                                                            "deflect_value": 2}),
                              ("b3", "p1", {"buffed": True}), ("n1", "p1", {}), ("e1", "p2", {"buffed": True})):
        state["objects"][oid] = unit(owner, **extra)
        state["players"][owner]["zones"]["base"].append(oid)
    return state


def deflect(state, oid):
    """The Deflect Value opponents pay against (Core 809.2), 0 without Deflect."""
    return deflect_total(state, oid)


def main() -> int:
    grammar = cg.load_grammar()
    lowered = cg.compile_clause(TEXT, grammar)
    auras = ((lowered.get("passive") or {}).get("object_fields") or {}).get("static_auras") or []
    if lowered.get("production_id") != "friendly_buffed_units_have_keyword_if_they_didnt_already" or len(auras) != 1:
        print(f"FAILED: the static does not lower: {lowered.get('production_id')} {auras}")
        return 1
    aura = auras[0]
    s = board(aura)
    if validate_state(s):
        fail("V validation", f"the board is invalid: {validate_state(s)}")
    if deflect(s, "b1") != 1:
        fail("A1 given", deflect(s, "b1"))
    if deflect(s, "b2") != 2:
        fail("A2 not added", f"Deflect {deflect(s, 'b2')}, wanted its own 2")
    if deflect(s, "n1") or "deflect" in keyword_values(s, "n1"):
        fail("A4 not buffed", keyword_values(s, "n1"))
    if "deflect" in keyword_values(s, "e1"):
        fail("A5 enemy", keyword_values(s, "e1"))
    gone = copy.deepcopy(s)
    gone["players"]["p1"]["zones"]["base"].remove("g1")
    gone["players"]["p1"]["zones"]["trash"].append("g1")
    if "deflect" in keyword_values(gone, "b1"):
        fail("A6 source gone", keyword_values(gone, "b1"))
    for label, change in (("only_if_absent false", {"only_if_absent": False}), ("with a value", {"value": 2})):
        wrong = board({**aura, **change})
        if not validate_state(wrong):
            fail("V validation", f"{label} was accepted")
    for near in ("Friendly buffed units have [Deflect].", "Friendly units have [Deflect] if they didn't already.",
                 "Other friendly buffed units have [Deflect] if they didn't already."):
        if cg.compile_clause(near, grammar).get("production_id") == lowered.get("production_id"):
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: keyword aura if absent checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a keyword aura that gives the keyword only where it is absent - given, never summed onto one's own, not "
          "to the unbuffed or the enemy, gone with its source (A1, A2, A4-A6, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
