#!/usr/bin/env python3
"""Regression gate: "Play me only to a battlefield you conquered this turn." (set 2 package A2: Perched Grimwyrm).

  Q1  with bf1 in p1's conquered-this-turn ledger, the card played to bf1 commits; to its Base, and to bf2 (p1's, not
      conquered), it is refused; with no conquest this turn bf1 is refused too
  Q2  battlefield_entry_paths names the conquered path only
  Q3  the printed form lowers to the field; the ledger and the field are validated
"""
from __future__ import annotations

import copy
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


def state_with(conquered=("bf1",)):
    state = base_state()
    state["turn_id"] = "turn-5"
    for bf_id in ("bf1", "bf2"):
        bf = state["battlefields"].setdefault(bf_id, {"controller": None, "objects": []})
        for held in list(bf.get("objects", [])):
            if state["objects"][held]["controller"] != "p1":
                bf["objects"].remove(held)
                state["players"][state["objects"][held]["controller"]]["zones"]["base"].append(held)
        bf["controller"] = "p1"
    settle_contested(state)
    state["players"]["p1"]["conquered_this_turn"] = {"turn-5": list(conquered)}
    state["objects"]["gw"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "printed_cost": {"energy": 0, "power": {}},
                              "play_only_to_conquered_this_turn": True}
    state["players"]["p1"]["zones"]["hand"].append("gw")
    return state


def play(state, entry):
    decl = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-gw", "actor": "p1", "card": "gw",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}}, "entry_location": entry,
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return pt.play_card(fixture(), state, decl)


def main() -> int:
    errors: list[str] = []
    bf1, bf2 = {"kind": "battlefield", "battlefield": "bf1"}, {"kind": "battlefield", "battlefield": "bf2"}
    problems = validate_state(state_with())
    if problems:
        errors.append(f"fixture invalid: {problems[:2]}")
    for label, state, entry, want in (("bf1, conquered", state_with(), bf1, True),
                                      ("its Base", state_with(), {"kind": "base"}, False),
                                      ("bf2, not conquered", state_with(), bf2, False),
                                      ("bf1 with no conquest", state_with(()), bf1, False)):
        got = play(state, entry)
        if bool(got.get("committed")) != want:
            errors.append(f"Q1 {label}: committed {got.get('committed')} ({got.get('reason_code')})")
    paths = pt.battlefield_entry_paths(state_with(), "gw", "p1", "bf1")
    if [k for k, v in paths.items() if v] != ["conquered_this_turn"]:
        errors.append(f"Q2: paths {paths}")
    got = CG.compile_clause("Play me only to a battlefield you conquered this turn.", CG.load_grammar())
    if ((got.get("passive") or {}).get("object_fields") or {}) != {"play_only_to_conquered_this_turn": True}:
        errors.append(f"Q3: lowered to {got.get('production_id')} {got.get('passive')}")
    bad = state_with()
    bad["players"]["p1"]["conquered_this_turn"] = {"turn-5": ["nowhere"]}
    if not any("conquered_this_turn" in e for e in validate_state(bad)):
        errors.append("Q3: a ledger naming no battlefield was accepted")
    if errors:
        print("conquered-only checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("conquered-only checks passed: played to a battlefield conquered this turn, refused anywhere else; the one path; "
          "lowered; the ledger validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
