#!/usr/bin/env python3
"""Regression gate: "Units can't be played here." printed on a Battlefield (set 2 package A2: Rockfall Path; Core 355.2).

  P1  a Unit played to the restricted Battlefield its player controls is refused (entry_location_units_not_here); the
      same Unit to its Base commits; the same play to a Battlefield with no restriction commits
  P2  battlefield_entry_paths - the predicate the enumerator reads too - names no path to it for a Unit
  P3  the printed form lowers to the Battlefield field; a value other than true is refused
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def state_with(restricted=True):
    state = base_state()
    bf = state["battlefields"]["bf1"]
    for held in list(bf.get("objects", [])):
        if state["objects"][held]["controller"] != "p1":
            bf["objects"].remove(held)
            state["players"][state["objects"][held]["controller"]]["zones"]["base"].append(held)
    bf["controller"] = "p1"
    if restricted:
        bf["units_cannot_be_played_here"] = True
    settle_contested(state)
    state["objects"]["nu"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "printed_cost": {"energy": 0, "power": {}}}
    state["players"]["p1"]["zones"]["hand"].append("nu")
    return state


def play(state, entry):
    decl = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-nu", "actor": "p1", "card": "nu",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}}, "entry_location": entry,
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return pt.play_card(fixture(), state, decl)


def main() -> int:
    errors: list[str] = []
    here = {"kind": "battlefield", "battlefield": "bf1"}
    got = play(state_with(), here)
    if got.get("committed") or got.get("reason_code") != "entry_location_units_not_here":
        errors.append(f"P1: a unit played to the restricted battlefield: {got.get('committed')} {got.get('reason_code')}")
    if not play(state_with(), {"kind": "base"}).get("committed"):
        errors.append("P1: the same unit to its base was refused")
    free = play(state_with(restricted=False), here)
    if not free.get("committed"):
        errors.append(f"P1: the unit to an unrestricted battlefield was refused: {free.get('reason_code')}")
    if any(pt.battlefield_entry_paths(state_with(), "nu", "p1", "bf1").values()):
        errors.append("P2: the entry paths named a way onto the restricted battlefield")
    lowered = CG.compile_clause("Units can't be played here.", CG.load_grammar())
    if ((lowered.get("passive") or {}).get("battlefield_fields") or {}) != {"units_cannot_be_played_here": True}:
        errors.append(f"P3: lowered to {lowered.get('production_id')} {lowered.get('passive')}")
    bad = state_with()
    bad["battlefields"]["bf1"]["units_cannot_be_played_here"] = 1
    if not any("units_cannot_be_played_here" in e for e in validate_state(bad)):
        errors.append("P3: a value other than true was accepted")
    if errors:
        print("units-not-played-here checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("units-not-played-here checks passed: a Unit's play to the restricted Battlefield refused, to its Base and to "
          "another Battlefield committed; no entry path names it; lowered; a bad value refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
