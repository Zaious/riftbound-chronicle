#!/usr/bin/env python3
"""Regression gate for Assault (Core 807).

    807.1.b  formatted "Assault [X]"; X omitted is 1
    807.1.c  short for "While I am an attacker, I have +X [M]."
    807.1.d.1  in effect as long as the Unit keeps the Attacker designation
    807.2    Assault values from several sources are summed
    807.3    Assault is a characteristic other effects can check

Must hold, through the real Combat procedures (stage_combat, open_combat), not a
hand-set designation:
  - a printed Assault adds nothing before the Combat opens, adds X to the attacker once
    it is the Attacker, and adds nothing to a defender that has it;
  - an omitted X is 1; "[Assault 2]" lowered by the engine grammar is 2;
  - granting Assault (grant_keyword) is refused - a later item, not half-supported;
  - effective_might and combat_might_contributions agree;
  - negative mutation: the same attacker without the keyword is its printed Might.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_combat_staging import contested_board  # noqa: E402
from check_effect_ir import program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from combat import open_combat, stage_combat  # noqa: E402
from effect_ir import (apply_program, assault_total, combat_might_contributions, effective_might,  # noqa: E402
                       has_keyword, validate_state)


def opened(effect_state):
    staged = stage_combat(fixture(), effect_state)
    assert staged.get("committed"), staged.get("reason") or staged.get("errors")
    result = open_combat(staged["next_timing_state"], effect_state)
    assert result.get("committed"), result.get("reason") or result.get("errors")
    return result["next_timing_state"], result["next_effect_state"]


def main() -> int:
    errors: list[str] = []
    # contested_board: u1 (p1, the applier -> Attacker), u2 (p2 -> Defender) at bf1
    board = contested_board()
    board["objects"]["u1"].update({"keywords": ["assault"], "damage": 0})
    board["objects"]["u2"].update({"keywords": ["assault"], "assault_value": 2})
    if validate_state(board):
        errors.append(f"the Assault board is invalid: {validate_state(board)}")
    printed_u1, printed_u2 = board["objects"]["u1"]["base_might"], board["objects"]["u2"]["base_might"]
    if effective_might(board, "u1") != printed_u1 or effective_might(board, "u2") != printed_u2:
        errors.append("Assault added Might before any Attacker designation")
    timing, state = opened(board)
    if effective_might(state, "u1") != printed_u1 + 1:
        errors.append(f"a bare Assault on the Attacker did not add 1 (807.1.b.3, 807.1.c): {effective_might(state, 'u1')}")
    if effective_might(state, "u2") != printed_u2:
        errors.append("Assault added Might to a Defender")
    parts = combat_might_contributions(state, "u1")
    if [p["amount"] for p in parts if p["kind"] == "assault"] != [1]:
        errors.append(f"combat_might_contributions disagrees with effective_might: {parts}")
    if not has_keyword(state, "u1", "assault") or assault_total(state, "u1") != 1:
        errors.append("Assault is not a characteristic other effects can read (807.3)")

    # the value, lowered by the engine's own grammar
    fields = (CG.compile_clause("[Assault 2]", CG.load_grammar()).get("passive") or {}).get("object_fields") or {}
    if fields.get("keywords") != ["assault"] or fields.get("assault_value") != 2:
        errors.append(f"[Assault 2] did not lower to assault_value 2: {fields}")

    # granting Assault is not part of this capability: the grammar's grant production
    # names the grantable keywords, and "Give a unit [Assault 3] this turn." is its own
    # later item. Until then a grant is refused, not half-supported.
    combat_id = timing["combat"]["combat_id"]
    granted = apply_program(state, program("rally", {"op": "grant_keyword", "object_id": "u1", "keyword": "assault", "value": 2,
                                                     "duration": "this_combat", "source": "rally", "effect_id": "g"}),
                            context={"combat": {"combat_id": combat_id, "battlefield": "bf1"}})
    if granted.get("committed"):
        errors.append("a grant of Assault went through, though granting it is not supported yet")

    # negative mutation: no keyword, no bonus
    bare = copy.deepcopy(contested_board())
    bare["objects"]["u1"]["damage"] = 0
    _, bare_state = opened(bare)
    if effective_might(bare_state, "u1") != bare["objects"]["u1"]["base_might"]:
        errors.append("an Attacker without Assault gained Might")

    if errors:
        print("FAILED: Assault checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Assault adds its summed value to Might only while the Unit is the Attacker (807.1.c, 807.2), "
          "through the real Combat opening; omitted X is 1; [Assault 2] lowers to 2; a Defender with it and an "
          "Attacker without it gain nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
