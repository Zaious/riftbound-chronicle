#!/usr/bin/env python3
"""Regression gate: a triggered ability's base cost "return a unit you control here to its owner's hand" (set 2 package A2:
Emperor's Dais; Core 383.3.b.1, 448.2).

  T1  the source and p1's unit rt at bf1: the controller is asked which; chosen rt, it is in p1's hand (a new object) and
      the ability is finalized and resolves; p1's unit in its Base and p2's unit at bf1 are not candidates
  T2  a Battlefield source: its own units are the candidates ("here" is that Battlefield)
  T3  nothing of p1's there: no candidate, so the cost cannot be paid (Core 203.3); a payment naming another place, or
      another kind, is refused by the validator
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import trigger_cost as TC  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_trigger_cost import cost, pending, program  # noqa: E402
from resolution_bridge import finalize_trigger  # noqa: E402

PAYMENT = {"add_window_closed": True, "confirmed_by": "harness"}
PROG = program("dais-effects", "dais", [cost({"kind": "energy", "amount": 1},
                                             {"kind": "return_to_hand", "object_kind": "unit", "location": "here"}),
                                        {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])


def unit(owner):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(*, mine_there=True):
    state = base_state()
    bf1 = state["battlefields"]["bf1"]
    for held in list(bf1["objects"]):
        bf1["objects"].remove(held)
        state["players"][state["objects"][held]["controller"]]["zones"]["base"].append(held)
    state["objects"]["dais"] = unit("p1")
    state["objects"]["rt"] = unit("p1")
    state["objects"]["home"] = unit("p1")
    state["objects"]["foe"] = unit("p2")
    bf1["objects"] += ["dais", "foe"] + (["rt"] if mine_there else [])
    state["players"]["p1"]["zones"]["base"].append("home")
    if not mine_there:
        state["players"]["p1"]["zones"]["base"].append("rt")
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    return settle_contested(state)


def finalize(state, decisions=None):
    reg = {PROG["program_id"]: PROG}
    item = pending(state, "dais", PROG)
    envelope = None
    if decisions:
        envelope = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(state), "decisions": decisions}
    return finalize_trigger(item, state, reg, envelope, perform_optional_trigger=True, pay_trigger_cost=True,
                            payment_context=PAYMENT), item


def main() -> int:
    errors: list[str] = []
    problems = IR.validate_program(PROG)
    if problems:
        errors.append(f"T3: the program is refused: {problems[:2]}")
    state = board()
    asked, item = finalize(state)
    if asked.get("committed") or asked.get("reason") != "cost_selection_required" \
            or sorted(asked.get("candidates") or []) != ["dais", "rt"]:
        errors.append(f"T1: not asked between the source and rt: {asked.get('reason')} {asked.get('candidates')}")
    item_id = next(i["id"] for i in item["chain"]["items"] if i.get("source_object") == "dais")
    chose, _ = finalize(state, [{"decision_id": TC.return_decision_id(item_id), "kind": "card_selection",
                                 "stage": "trigger_finalization", "controller": "p1", "value": ["rt"],
                                 "selection_identities": {"rt": IR.object_identity(state, "rt")}}])
    if not chose.get("committed"):
        errors.append(f"T1: the chosen return did not finalize: {chose.get('reason')} {chose.get('message')}")
    else:
        after = chose["next_effect_state"]
        if IR.find_location(after, "rt") != ("player", "p1", "hand") or IR.object_identity(after, "rt") == IR.object_identity(state, "rt"):
            errors.append(f"T1: rt is at {IR.find_location(after, 'rt')}")
        if after["players"]["p1"]["resources"]["energy"] != 0:
            errors.append("T1: the Energy was not paid")
    bf_item = {"id": "x", "controller": "p1", "source_object": "bf1"}
    if TC.return_candidates(state, bf_item, {"object_kind": "unit"}) != ["dais", "rt"]:
        errors.append(f"T2: a Battlefield source's candidates are {TC.return_candidates(state, bf_item, {'object_kind': 'unit'})}")
    empty = board(mine_there=False)
    for oid in ("dais",):
        empty["battlefields"]["bf1"]["objects"].remove(oid)
        empty["players"]["p1"]["zones"]["base"].append(oid)
    settle_contested(empty)
    nothing = TC.return_candidates(empty, bf_item, {"object_kind": "unit"})
    if nothing:
        errors.append(f"T3: with nothing of p1's at bf1 the candidates are {nothing}")
    for label, part in (("another place", {"kind": "return_to_hand", "object_kind": "unit", "location": "base"}),
                        ("another kind", {"kind": "return_to_hand", "object_kind": "spell", "location": "here"})):
        bad = copy.deepcopy(PROG)
        bad["effects"][0]["payment"][1] = part
        if not IR.validate_program(bad):
            errors.append(f"T3: a payment naming {label} was accepted")
    if errors:
        print("trigger return-to-hand cost checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("trigger return-to-hand cost checks passed: the controller chooses among its units here, the chosen one returned "
          "to hand and the ability finalized; a Battlefield source's own units; nothing there, no candidates; shape validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
