#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "When I attack, you may move any number of your token units to this battlefield."
(Azir - Sovereign) - targets {any_number, restrictions token} and the destination source_current_battlefield.

  Z1 two tokens  the source at bf1, two of p1's tokens in its Base: both chosen - both at bf1
  Z2 none        none chosen (any number includes none): nothing moves, the program commits
  Z3 not token   a unit that is not a token named: an illegal target (target_token_requirement_failed)
  Z4 elsewhere   the source in its Base as it executes: the Move is not carried out (a no_op), the tokens stay
  V              any_number beside a group, or not true, is refused

    python skill/scripts/check_set2_tokens_here.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, evaluate_target, find_location, hash_value,  # noqa: E402
                       object_identity, validate_program)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
MOVE = {"op": "move_board_object", "effect_id": "mv",
        "targets": {"min": 0, "any_number": True, "decision_ref": "t",
                    "restrictions": {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly", "token": True}},
        "destination": {"kind": "source_current_battlefield"}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(source_at="bf1"):
    state = base_state()
    state["objects"]["azir"] = unit("p1")
    if source_at == "bf1":
        state["battlefields"]["bf1"]["objects"] = ["azir"]
    else:
        state["players"]["p1"]["zones"]["base"].append("azir")
    for t in ("tk1", "tk2"):
        state["objects"][t] = unit("p1", is_token=True)
        state["players"]["p1"]["zones"]["base"].append(t)
    return settle_contested(state)


def run(state, chosen):
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "azir", "controller": "p1", "source_object": "azir",
               "source_identity": object_identity(state, "azir"), "effects": [copy.deepcopy(MOVE)]}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1", "value": chosen,
         "selection_identities": {c: object_identity(state, c) for c in chosen}}]}
    return apply_program(state, program, decisions=decisions)


def where(state, oid):
    loc = find_location(state, oid)
    return loc[:2] if loc else None


def main() -> int:
    done = run(board(), ["tk1", "tk2"])
    if not done.get("committed") or [where(done["next_state"], t) for t in ("tk1", "tk2")] != [("battlefield", "bf1")] * 2:
        fail("Z1", f"{done.get('reason') or [where(done['next_state'], t) for t in ('tk1', 'tk2')]}")
    done = run(board(), [])
    if not done.get("committed") or [where(done["next_state"], t) for t in ("tk1", "tk2")] != [("player", "p1")] * 2:
        fail("Z2", f"none chosen: {done.get('reason') or done.get('errors')}")
    state = board()
    state["objects"]["plain"] = unit("p1")
    state["players"]["p1"]["zones"]["base"].append("plain")
    ok, why = evaluate_target(state, {**MOVE["targets"]["restrictions"], "object_id": "plain",
                                      "bound_identity": object_identity(state, "plain")}, "p1")
    if ok or why != "target_token_requirement_failed":
        fail("Z3", f"a unit that is not a token: {ok} {why}")
    done = run(board(source_at="base"), ["tk1"])
    if not done.get("committed") or where(done["next_state"], "tk1") != ("player", "p1"):
        fail("Z4", f"the source in its Base: {done.get('reason') or where(done['next_state'], 'tk1')}")
    for label, bad in (("beside a group", {**MOVE["targets"], "group": {"same_battlefield": True}, "subset_ref": "k"}),
                       ("not true", {**MOVE["targets"], "any_number": 1})):
        program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "program_id": "bad", "controller": "p1", "effects": [{**MOVE, "targets": bad}]}
        if not any("any_number" in p for p in validate_program(program)):
            fail("V", f"any_number {label} validated")
    if errors:
        print("FAILED: set 2 tokens to this battlefield")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'any number of your token units' chooses tokens only, none included; 'to this battlefield' is the source's "
          "Battlefield as the Move executes (359.3.f.2), and with the source at none nothing moves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
