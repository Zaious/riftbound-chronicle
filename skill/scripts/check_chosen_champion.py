#!/usr/bin/env python3
"""
Regression gate (GPT 2026-09-27 ruling 15, Hallowed Tomb): a Chosen Champion returns from the trash to
an EMPTY Champion Zone.

"you may return your Chosen Champion from your trash to your Champion Zone if it is empty." Must hold,
through apply_program:
  - Core 103.2.a.3: the chosen card and any Champion Unit with its name are the Chosen Champion; a unit
    of that name that is not a Champion Unit, a Champion Unit of another name, and a card in the
    opponent's trash are not legal targets;
  - with two copies in the trash the program stops for its controller's choice (a target, the trash is
    public, 355.10.a) - it never picks one;
  - the chosen copy goes to its owner's Champion Zone as a new object (124);
  - Core 108.3.c.1 / "if it is empty", read as the instruction executes: an occupied Champion Zone makes
    it a no_op (champion_zone_occupied) and the card stays in the trash;
  - an unknown chosen_champion value on a selector and a non-boolean champion_unit are refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402

NAME = "Jinx, Rebel"


def card(owner, name, champion):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 4, "might_modifiers": [], "damage": 0,
            "exhausted": False, "name": name, "champion_unit": champion}


def board(*, occupied=False):
    state = base_state()
    state["players"]["p1"]["chosen_champion"] = NAME
    state["players"]["p1"]["zones"]["champion_zone"] = []
    for oid, owner, name, champion in (("j1", "p1", NAME, True), ("j2", "p1", NAME, True), ("x1", "p1", NAME, False),
                                        ("y1", "p1", "Jinx, Demolitionist", True), ("o1", "p2", NAME, True)):
        state["objects"][oid] = card(owner, name, champion)
        state["players"][owner]["zones"]["trash"].append(oid)
    if occupied:
        state["objects"]["j0"] = card("p1", NAME, True)
        state["players"]["p1"]["zones"]["champion_zone"].append("j0")
    return state


RETURN = {"op": "return_to_champion_zone", "effect_id": "rt",
          "target": {"decision_ref": "t", "chosen_zone_class": "non_board", "kind": "unit", "location": "trash",
                     "zone_owner_relation": "own", "chosen_champion": True}}


def run(state, chosen=None):
    decisions = None
    if chosen is not None:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
            {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1", "value": [chosen],
             "selection_identities": {chosen: object_identity(state, chosen) or f"{chosen}@0"}}]}
    return apply_program(state, program("tomb", copy.deepcopy(RETURN)), decisions=decisions)


def main() -> int:
    errors: list[str] = []
    start = board()
    if validate_state(start) or validate_program(program("tomb", copy.deepcopy(RETURN))):
        print(f"FAILED: fixture invalid: {validate_state(start)[:2]} {validate_program(program('tomb', copy.deepcopy(RETURN)))[:2]}")
        return 1
    asked = run(start)
    if asked.get("committed") or asked.get("reason_code") != "target_selection_required":
        errors.append(f"two copies in the trash did not stop for p1's choice: {asked.get('reason_code')} {asked.get('reason')}")
    done = run(start, "j2")
    zones = (done.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
    if not done.get("committed") or zones.get("champion_zone") != ["j2"] or "j2" in zones.get("trash", []) \
            or object_identity(done["next_state"], "j2") == object_identity(start, "j2"):
        errors.append(f"the chosen copy did not go to the Champion Zone as a new object: {done.get('reason') or done.get('errors')} {zones}")
    for wrong, why in (("x1", "a unit of that name that is not a Champion Unit"), ("y1", "a Champion Unit of another name"),
                       ("o1", "a card in the opponent's trash")):
        got = run(start, wrong)
        moved = got.get("committed") and wrong in ((got.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("champion_zone") or [])
        if moved:
            errors.append(f"{why} ({wrong}) was returned as the Chosen Champion")
    full = board(occupied=True)
    occupied = run(full, "j1")
    event = next((t for t in occupied.get("trace") or [] if t.get("op") == "return_to_champion_zone"), {})
    fz = (occupied.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
    if not occupied.get("committed") or event.get("reason") != "champion_zone_occupied" or fz.get("champion_zone") != ["j0"] \
            or "j1" not in fz.get("trash", []):
        errors.append(f"an occupied Champion Zone did not make it a no_op (108.3.c.1): {occupied.get('reason')} {event} {fz}")
    bad = copy.deepcopy(RETURN)
    bad["target"]["chosen_champion"] = "yes"
    if not validate_program(program("bad", bad)):
        errors.append("a non-true chosen_champion on a selector was accepted")
    odd = board()
    odd["objects"]["j1"]["champion_unit"] = "yes"
    if not validate_state(odd):
        errors.append("a non-boolean champion_unit was accepted")
    if errors:
        print("FAILED: chosen champion")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: the Chosen Champion (the name, a Champion Unit, the owner's trash) is chosen by its controller, returns to an "
          "empty Champion Zone as a new object, and an occupied zone is a no_op (108.3.c.1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
