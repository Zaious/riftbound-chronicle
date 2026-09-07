#!/usr/bin/env python3
"""Regression gate for C-58 (ADR-0015 §2): Cleanup step 5 on the P3
attachment and facedown topology.

The rule, in its own words: "Recall all Unattached non-Unit Gear and non-Unit
Runes at Battlefields, and all Permanents and Runes in Bases other than their
controller's. Remove all Hidden cards from all Battlefields that are not
controlled by the same player and place them in their owner's Trash."

Must hold:
  - an unattached non-Unit Gear or Rune at a Battlefield is Recalled to its
    controller's Base, keeping its identity because a Battlefield and a Base
    are both board Locations (429, 124), and an **attached** one
    is not — its location is its Top-Most card's (434.4). The negative
    mutation attaches the same Gear and it stays;
  - a Permanent or Rune sitting in a Base that is not its controller's is
    Recalled to its own controller's Base, and one already in its controller's
    Base is left alone;
  - a Hidden card at a Battlefield its controller does not control goes to its
    **owner's** Trash, and one at a Battlefield its controller does control
    stays facedown — and that card's identity never appears in the public
    trace, which knows only how many remain;
  - all of it runs on the working state the rest of the Cleanup acts on, so a
    step-5 failure commits nothing;
  - `gear_rune_recall_cleanup` is no longer an unsupported exit, and the
    engine-check scope says so.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from battlefield_control import run_board_cleanup  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import find_location, object_identity, validate_state  # noqa: E402
from engine_check import KIND_CONFIG  # noqa: E402
from turn_cycle import run_cleanup  # noqa: E402


def permanent(owner, kind="gear", **extra):
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": 0,
            "might_modifiers": [], "damage": 0, "exhausted": False, **extra}


def board():
    """One Battlefield p1 controls, with everything step 5 has to sort out."""
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["turn_id"] = "turn-4"
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["battlefields"]["bf1"]["objects"].append("u1")
    state["players"]["p1"]["zones"]["base"].remove("u1")
    # unattached Gear and Rune at the Battlefield: both Recalled
    for object_id, kind in (("g_loose", "gear"), ("r_loose", "rune")):
        state["objects"][object_id] = permanent("p1", kind)
        state["battlefields"]["bf1"]["objects"].append(object_id)
    # an attached Gear: its location is its host's, so step 5 passes it by
    state["objects"]["g_worn"] = permanent("p1", "gear", attached_to="u1")
    state["battlefields"]["bf1"]["objects"].append("g_worn")
    # a Permanent sitting in the wrong player's Base
    state["objects"]["g_visitor"] = permanent("p1", "gear")
    state["players"]["p2"]["zones"]["base"].append("g_visitor")
    # and one already at home
    state["objects"]["g_home"] = permanent("p1", "gear")
    state["players"]["p1"]["zones"]["base"].append("g_home")
    # two Hidden cards: p2's at p1's Battlefield goes, p1's own stays
    state["objects"]["h_intruder"] = permanent("p2", "spell", hidden=True)
    state["objects"]["h_owner"] = permanent("p1", "spell", hidden=True)
    state["battlefields"]["bf1"]["facedown"] = {"capacity": 4, "cards": [
        {"object_id": "h_intruder", "controller": "p2", "hidden_on_turn": "turn-3"},
        {"object_id": "h_owner", "controller": "p1", "hidden_on_turn": "turn-3"},
    ]}
    return state


def step_five(state):
    return run_board_cleanup(fixture(), state, steps=("recall_remove",), within_cleanup=True)


def main() -> int:
    errors: list[str] = []
    state = board()
    if found := validate_state(state):
        errors.append(f"the step 5 fixture is invalid: {found}")
    before = {object_id: object_identity(state, object_id) for object_id in state["objects"]}
    result = step_five(state)
    if not result.get("committed"):
        print("FAILED: Cleanup step 5 checks")
        print(f"  - step 5 did not commit: {result.get('reason_code')} {result.get('reason')}")
        return 1
    after = result["next_effect_state"]
    five = result["trace"]["step_five"]

    # --- the Recalls ------------------------------------------------------------------------
    recalled = sorted(item["object_id"] for item in five["recalled"])
    if recalled != ["g_loose", "g_visitor", "r_loose"]:
        errors.append(f"step 5 did not Recall exactly the unattached non-Units and the visitor: {recalled}")
    for object_id in ("g_loose", "r_loose", "g_visitor"):
        if find_location(after, object_id) != ("player", "p1", "base"):
            errors.append(f"{object_id} was not Recalled to its controller's Base: {find_location(after, object_id)}")
        if object_identity(after, object_id) != before[object_id]:
            errors.append(f"{object_id} changed identity on a board-to-board Recall (Core 124 changes it only "
                          f"across a non-board zone): {before[object_id]} -> {object_identity(after, object_id)}")
    if find_location(after, "g_worn") != ("battlefield", "bf1", None):
        errors.append("an attached Gear was Recalled; its location is its Top-Most card's (434.4)")
    if object_identity(after, "g_home") != before["g_home"] or find_location(after, "g_home") != ("player", "p1", "base"):
        errors.append("a Permanent already in its controller's Base was disturbed")

    # negative mutation: the same Gear, attached, is left where it is
    attached = copy.deepcopy(board())
    attached["objects"]["g_loose"]["attached_to"] = "u1"
    attached_result = step_five(attached)
    if not attached_result.get("committed"):
        errors.append(f"the attached fixture did not commit: {attached_result.get('reason')}")
    elif "g_loose" in [item["object_id"] for item in attached_result["trace"]["step_five"]["recalled"]]:
        errors.append("negative mutation failed: attaching the Gear did not stop step 5 Recalling it")

    # --- the Hidden removal -----------------------------------------------------------------
    removed = [item["object_id"] for item in five["removed_hidden"]]
    if removed != ["h_intruder"]:
        errors.append(f"step 5 removed the wrong Hidden cards: {removed}")
    if "h_intruder" not in after["players"]["p2"]["zones"]["trash"]:
        errors.append("the removed Hidden card did not go to its owner's Trash")
    remaining = [entry["object_id"] for entry in after["battlefields"]["bf1"]["facedown"]["cards"]]
    if remaining != ["h_owner"]:
        errors.append(f"the Hidden card at its own controller's Battlefield did not stay: {remaining}")
    if five["still_hidden"] != 1:
        errors.append(f"the trace does not count the cards that stay hidden: {five['still_hidden']}")
    dumped = json.dumps(result["trace"])
    if '"h_owner"' in dumped:
        errors.append("the public trace named a card that is still Hidden")
    if '"h_intruder"' not in dumped:
        errors.append("the trace does not record the Hidden card that left for the Trash")

    # the Battlefield losing its controller makes every Hidden card there leave
    uncontrolled = copy.deepcopy(board())
    uncontrolled["battlefields"]["bf1"]["controller"] = None
    both_gone = step_five(uncontrolled)
    if sorted(item["object_id"] for item in both_gone["trace"]["step_five"]["removed_hidden"]) != ["h_intruder", "h_owner"]:
        errors.append("an Uncontrolled Battlefield did not remove every Hidden card on it")

    # --- one transaction ---------------------------------------------------------------------
    for transition in five["transitions"]:
        if transition["outcome"] not in {"applied", "no_op"} or not transition["rule_locators"]:
            errors.append(f"a step 5 transition carries no outcome or locator: {transition}")
        if transition["op"] == "remove_hidden" and transition["identity_after"] is None:
            errors.append(f"a Hidden card left a hidden zone without a new identity (Core 124): {transition}")
        if transition["op"] == "recall" and transition["to"] is None:
            errors.append(f"a Recall transition does not say where it went: {transition}")
    whole = run_cleanup({**fixture(), "outstanding_tasks": ["cleanup"]}, board())
    if not whole.get("committed"):
        errors.append(f"the whole Cleanup did not commit with step 5 in it: {whole.get('reason_code')} {whole.get('reason')}")
    else:
        recorded = next(s for s in whole["trace"]["iterations"][0]["steps"] if s["step"] == 5)
        if sorted(recorded["recalled"]) != ["g_loose", "g_visitor", "r_loose"] or recorded["removed_hidden"] != ["h_intruder"]:
            errors.append(f"the Cleanup's own step 5 record disagrees with the procedure: {recorded}")
        if find_location(whole["next_effect_state"], "g_loose") != ("player", "p1", "base"):
            errors.append("the Cleanup committed without step 5's Recall")

    # --- the unsupported exit is gone ----------------------------------------------------------
    if "gear_rune_recall_cleanup" in KIND_CONFIG["turn_step"]["unsupported"]:
        errors.append("gear_rune_recall_cleanup is still declared unsupported")
    if step_five(board()) != result:
        errors.append("step 5 is not deterministic")
    empty = base_state()
    empty["mode"] = {"victory_score": 8}
    quiet = step_five(empty)
    if not quiet.get("committed") or quiet["trace"]["step_five"]["transitions"]:
        errors.append("step 5 changed something on a board with nothing to do")

    if errors:
        print("FAILED: Cleanup step 5 checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Cleanup step 5 checks passed: Recall of the unattached and the misplaced, Hidden removal to the owner's "
          "Trash, and the cards that stay hidden stay unnamed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
