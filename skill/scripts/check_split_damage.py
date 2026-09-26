#!/usr/bin/env python3
"""Regression gate for split damage: "Deal 5 damage split among any number of enemy units here."
(Volibear - Furious's attack trigger; Core 355.14, 355.14.a-h, 359.3.f.2, 417).

The engine grammar's own IR - one target decision (min 0, capped by the amount: 355.14.c), each
Target an enemy Unit at the source's current Battlefield, and a division decided at resolution
(355.14.e) - is run on a board where the source v1 (p1's) stands at bf1 with p2's e1 (Might 3),
e2 and e3 (Might 6), p1's f1, and p2's e9 at bf2. Must hold:
  - targets e1, e2, e3 divided 1/2/2: exactly that damage is marked on them, nothing on anyone else;
  - with no division, the program stops at damage_division_required naming the legal Targets, the
    amount, and how many must be kept;
  - refused: a division summing to 4, one naming a Unit that is not a Target, one leaving out a
    legal Target (355.14.f: each Target receives damage), a zero share (the decision validator);
  - six Targets for 5 damage: refused at finalization (target_count_illegal, 355.14.c) and at
    resolution;
  - e2 moved away before resolution: it is no longer a Target; the division covers e1 and e3, and
    one still naming e2 is refused (359.3.e);
  - the source moved to its Base: every Target mistargets ("here" is read on execution,
    359.3.f.2), nothing is dealt;
  - no Target chosen (min 0): a no_op, no division asked for;
  - the validator refuses a split with a max of its own, on another op, without targets, or with
    an amount read off the board.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program  # noqa: E402
from engine_decisions import validate_engine_decisions  # noqa: E402

SENTENCE = "Deal 5 damage split among any number of enemy units here."


def unit(owner, might):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False}


def board():
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, owner, might, where in (("v1", "p1", 9, "bf1"), ("e1", "p2", 3, "bf1"), ("e2", "p2", 6, "bf1"),
                                     ("e3", "p2", 6, "bf1"), ("f1", "p1", 2, "bf1"), ("e9", "p2", 4, "bf2"),
                                     ("e4", "p2", 6, "bf1"), ("e5", "p2", 6, "bf1"), ("e6", "p2", 6, "bf1")):
        state["objects"][oid] = unit(owner, might)
        state["battlefields"][where]["objects"].append(oid)
    return settle_contested(state)


def split_program():
    effects = CG.compile_clause(SENTENCE, CG.load_grammar())["program_effects"]
    prog = program("volibear", *copy.deepcopy(effects))
    prog["source_object"] = "v1"
    prog["source_identity"] = "v1@0"      # 'here' reads a source whose identity the program declares
    return prog


def decisions(state, targets, division=None, *, identities=None):
    items = [{"decision_id": "t", "kind": "target_selection", "stage": "trigger_finalization", "controller": "p1",
              "value": list(targets), "selection_identities": {o: object_identity(state, o) for o in targets}}]
    if division is not None:
        items.append({"decision_id": "t-division", "kind": "damage_division", "stage": "resolution", "controller": "p1",
                      "value": dict(division),
                      "selection_identities": identities or {o: object_identity(state, o) for o in division}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": items}


def run(state, targets, division=None, chosen_on=None):
    return apply_program(state, split_program(), decisions=decisions(chosen_on or state, targets, division))


def dealt(before, result):
    after = result["next_state"]
    return {o: after["objects"][o]["damage"] - before["objects"][o]["damage"]
            for o in before["objects"] if before["objects"][o].get("kind") == "unit" and o in after["objects"]
            and after["objects"][o]["damage"] != before["objects"][o]["damage"]}


def main() -> int:
    errors: list[str] = []
    prog = split_program()
    if validate_program(prog):
        errors.append(f"the grammar's split program is invalid: {validate_program(prog)}")
    state = board()

    done = run(state, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2})
    if not done.get("committed") or dealt(state, done) != {"e1": 1, "e2": 2, "e3": 2}:
        errors.append(f"a 1/2/2 division was not dealt as divided: {done.get('reason') or done.get('errors')} "
                      f"{dealt(state, done) if done.get('committed') else ''}")

    asked = run(state, ["e1", "e2", "e3"])
    if asked.get("reason_code") != "damage_division_required" or asked.get("division_candidates") != ["e1", "e2", "e3"] \
            or asked.get("division_amount") != 5 or asked.get("division_keeps") != 3 or asked.get("committed"):
        errors.append(f"with no division the program did not ask for one: {asked.get('reason_code')} {asked.get('division_candidates')}")

    for label, division in (("summing to 4", {"e1": 1, "e2": 1, "e3": 2}),
                            ("naming a Unit that is not a Target", {"e1": 1, "e2": 2, "e9": 2}),
                            ("leaving out a legal Target", {"e1": 2, "e2": 3})):
        got = run(state, ["e1", "e2", "e3"], division)
        if got.get("committed") or got.get("valid") is not False:
            errors.append(f"a division {label} was accepted: {got.get('reason_code')}")
    zero = decisions(state, ["e1", "e2"], {"e1": 0, "e2": 5})
    if not validate_engine_decisions(zero):
        errors.append("a zero share in a damage division passed the decision validator (Core 355.14.g)")

    six = ["e1", "e2", "e3", "e4", "e5", "e6"]
    try:
        PT._check_play_targets(state, "p1", prog, decisions(state, six), stage="trigger_finalization")
        errors.append("six Targets for 5 damage were accepted at finalization (Core 355.14.c)")
    except PT.PlayError as refusal:
        if refusal.reason_code != "target_count_illegal":
            errors.append(f"six Targets were refused for the wrong reason: {refusal.reason_code}")
    five_ok = PT._check_play_targets(state, "p1", prog, decisions(state, six[:5]), stage="trigger_finalization")
    if sorted(five_ok) != sorted(six[:5]):
        errors.append(f"five Targets for 5 damage were not accepted at finalization: {five_ok}")
    over = run(state, six, {o: 1 for o in six[:5]})
    if over.get("committed"):
        errors.append("six Targets for 5 damage resolved")

    moved = copy.deepcopy(state)
    moved["battlefields"]["bf1"]["objects"].remove("e2")
    moved["battlefields"]["bf2"]["objects"].append("e2")
    moved = settle_contested(moved)
    kept = apply_program(moved, split_program(), decisions=decisions(moved, ["e1", "e2", "e3"], {"e1": 2, "e3": 3}))
    if not kept.get("committed") or dealt(moved, kept) != {"e1": 2, "e3": 3}:
        errors.append(f"a Target that left 'here' was not dropped from the split: {kept.get('reason') or kept.get('errors')}")
    stale = apply_program(moved, split_program(), decisions=decisions(moved, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2}))
    if stale.get("committed"):
        errors.append("a division still naming a Target that left 'here' was accepted")

    home = copy.deepcopy(state)
    home["battlefields"]["bf1"]["objects"].remove("v1")
    home["players"]["p1"]["zones"]["base"].append("v1")
    home = settle_contested(home)
    gone = apply_program(home, split_program(), decisions=decisions(home, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2}))
    if not gone.get("committed") or dealt(home, gone):
        errors.append(f"with its source gone to Base the split still dealt damage (359.3.f.2): {gone.get('reason_code')}")

    none = run(state, [])
    if not none.get("committed") or dealt(state, none):
        errors.append(f"no Target chosen was not a quiet no_op: {none.get('reason_code')} {none.get('errors')}")

    base_effect = copy.deepcopy(split_program()["effects"][0])
    for label, effect in (("a max of its own", {**base_effect, "targets": {**base_effect["targets"], "max": 5}}),
                          ("on a kill", {**{k: v for k, v in base_effect.items() if k != "amount"}, "op": "kill"}),
                          ("without targets", {k: v for k, v in base_effect.items() if k != "targets"}),
                          ("an amount read off the board", {**{k: v for k, v in base_effect.items() if k != "amount"},
                                                            "amount_ref": {"kind": "program_source_current_might"}})):
        if not validate_program(program("bad", effect)):
            errors.append(f"a split {label} was accepted by the validator")

    if errors:
        print("FAILED: split damage" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'deal 5 damage split among any number of enemy units here' - Targets chosen at finalization, no more "
          "than the damage; the division decided at resolution, all of it, at least 1 to each Target kept; a Target "
          "that left 'here' drops out, the source gone mistargets them all, no Target is a no_op; bad divisions and "
          "bad shapes are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
