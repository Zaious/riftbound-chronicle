#!/usr/bin/env python3
"""Regression gate: "Your Equipment each give [Assault]." (set 2 package A2: Lucian - Purifier; Core 807.2, 435).

  E1  with the source on the board, a unit of p1's carrying two of p1's Equipment has Assault 2, one carrying one has
      Assault 1, an unequipped one none
  E2  p2's Equipment attached to p1's unit gives nothing; an untagged gear attached gives nothing
  E3  the source in the trash: none of it
  E4  the printed form lowers to the field; another keyword is refused by the validator
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import assault_total, has_keyword, validate_state  # noqa: E402


def board(source_zone="base"):
    state = base_state()
    state["objects"]["src"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                               "damage": 0, "exhausted": False, "equipment_each_give": ["assault"]}
    state["players"]["p1"]["zones"][source_zone].append("src")
    for oid in ("two", "one", "none"):
        state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                                 "damage": 0, "exhausted": False}
        state["players"]["p1"]["zones"]["base"].append(oid)
    for gid, owner, host, tags in (("eq1", "p1", "two", ["Equipment"]), ("eq2", "p1", "two", ["Equipment"]),
                                   ("eq3", "p1", "one", ["Equipment"]), ("eq4", "p2", "none", ["Equipment"]),
                                   ("g5", "p1", "none", [])):
        state["objects"][gid] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False, "attached_to": host, "tags": tags}
        state["players"]["p1"]["zones"]["base"].append(gid)
    return state


def main() -> int:
    errors: list[str] = []
    s = board()
    problems = validate_state(s)
    if problems:
        errors.append(f"fixture invalid: {problems[:2]}")
    got = {o: assault_total(s, o) for o in ("two", "one", "none")}
    if got != {"two": 2, "one": 1, "none": 0}:
        errors.append(f"E1/E2: Assault {got}")
    legend = board()
    legend["players"]["p1"]["zones"]["base"].remove("src")
    legend["objects"]["src"]["kind"] = "legend"
    legend["players"]["p1"]["zones"].setdefault("legend_zone", []).append("src")
    if assault_total(legend, "two") != 2:
        errors.append("E1: a Legend in its Legend Zone did not give it")
    gone = board("trash")
    if any(has_keyword(gone, o, "assault") for o in ("two", "one")):
        errors.append("E3: the source in the trash still gave Assault")
    lowered = CG.compile_clause("Your Equipment each give [Assault].", CG.load_grammar())
    if ((lowered.get("passive") or {}).get("object_fields") or {}) != {"equipment_each_give": ["assault"]}:
        errors.append(f"E4: lowered to {lowered.get('production_id')} {lowered.get('passive')}")
    bad = board()
    bad["objects"]["src"]["equipment_each_give"] = ["shield"]
    if not any("equipment_each_give" in e for e in validate_state(bad)):
        errors.append("E4: another keyword was accepted")
    if errors:
        print("equipment-each-give checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("equipment-each-give checks passed: one Assault per Equipment of the controller's attached to the unit, summed; "
          "an opponent's or an untagged gear gives none; nothing from the trash; lowered; one keyword")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
