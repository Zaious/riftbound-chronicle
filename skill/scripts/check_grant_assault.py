#!/usr/bin/env python3
"""Regression gate for a GRANTED Assault (Core 807, 801.3.a).

"Give a unit [Assault 3] this turn." (Cleave). Must hold:

  - the engine grammar reads it as one grant_keyword instruction: keyword assault, value 3,
    duration this_turn, one chosen unit; "[Assault]" with no number grants Assault 1
    (807.1.b.3) - the value is left off and the grant counts it as 1;
  - Core 807.2's own example: a Unit that has Assault and is granted Assault 3 has Assault 4;
    through the real Combat opening it is +4 Might as the Attacker (807.1.c), and a granted
    Assault on the Defender adds nothing;
  - the grant is this turn's (801.3.a.2): the next turn it is gone;
  - counter-examples: Assault granted to a Gear, or to a unit in a hand, is refused; a
    value of 0 is refused; the same attacker with a grant of Assault 1 is 2 Might short of
    the Assault 3 board (the value is carried, not only the keyword).
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
from effect_ir import (apply_program, assault_total, effective_might, has_keyword,  # noqa: E402
                       validate_program, validate_state)


def opened(effect_state):
    staged = stage_combat(fixture(), effect_state)
    assert staged.get("committed"), staged.get("reason") or staged.get("errors")
    result = open_combat(staged["next_timing_state"], effect_state)
    assert result.get("committed"), result.get("reason") or result.get("errors")
    return result["next_timing_state"], result["next_effect_state"]


def lowered(text):
    got = CG.compile_clause(text, CG.load_grammar())
    return got, (got.get("program_effects") or [None])[0]


def grant(state, effect, object_id):
    """The grammar's instruction, pointed at one object (the chosen target, bound)."""
    single = {k: v for k, v in copy.deepcopy(effect).items() if k != "target"}
    single.update({"object_id": object_id, "source": "cleave"})
    return apply_program(state, program("cleave", single))


def main() -> int:
    errors: list[str] = []
    got, cleave = lowered("Give a unit [Assault 3] this turn.")
    want = {"op": "grant_keyword", "effect_id": "kw", "keyword": "assault", "value": 3, "duration": "this_turn",
            "source": "$chain_item", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}
    if got.get("production_id") != "grant_keyword_for_duration" or cleave != want:
        errors.append(f"'Give a unit [Assault 3] this turn.' did not lower to one Assault 3 grant: {got}")
        cleave = want
    _, bare = lowered("Give a unit [Assault] this turn.")
    if not bare or "value" in bare or bare.get("keyword") != "assault":
        errors.append(f"'[Assault]' with no number should grant Assault with the value left off: {bare}")

    # Core 807.2's example: a unit that has Assault, granted Assault 3, has Assault 4
    board = contested_board()
    board["objects"]["u1"].update({"keywords": ["assault"], "damage": 0})
    if validate_state(board):
        errors.append(f"the board is invalid: {validate_state(board)}")
    done = grant(board, cleave, "u1")
    if not done.get("committed"):
        errors.append(f"the Assault 3 grant did not commit: {done.get('reason') or done.get('errors')}")
        print("FAILED: granted Assault" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    after = done["next_state"]
    if assault_total(after, "u1") != 4 or not has_keyword(after, "u1", "assault"):
        errors.append(f"Assault 1 + a granted Assault 3 is not Assault 4 (807.2): {assault_total(after, 'u1')}")
    base_u1 = board["objects"]["u1"]["base_might"]
    if effective_might(after, "u1") != base_u1:
        errors.append("a granted Assault added Might before the Unit was an Attacker")
    # the defender granted Assault 3 as well: nothing while it defends
    both = grant(after, cleave, "u2")
    if not both.get("committed"):
        errors.append(f"the grant to u2 did not commit: {both.get('reason') or both.get('errors')}")
    else:
        _, combat = opened(both["next_state"])
        if effective_might(combat, "u1") != base_u1 + 4:
            errors.append(f"the Attacker with Assault 4 is not +4 (807.1.c): {effective_might(combat, 'u1')} vs {base_u1}")
        if effective_might(combat, "u2") != board["objects"]["u2"]["base_might"]:
            errors.append("a granted Assault added Might to a Defender")

    # the value is carried: a grant of Assault 1 is 2 short of the Assault 3 board
    one = grant(board, {**cleave, "value": 1}, "u1")
    _, combat_one = opened(one["next_state"])
    if effective_might(combat_one, "u1") != base_u1 + 2:
        errors.append(f"Assault 1 + a granted Assault 1 as Attacker is not +2: {effective_might(combat_one, 'u1')}")

    # this turn only (801.3.a.2)
    later = copy.deepcopy(after)
    later["turn_id"] = "turn-next"
    if assault_total(later, "u1") != 1:
        errors.append(f"the granted Assault outlived its turn: {assault_total(later, 'u1')}")

    # counter-examples
    gear_board = contested_board()
    gear_board["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0,
                                   "might_modifiers": [], "damage": 0, "exhausted": False}
    gear_board["players"]["p1"]["zones"]["base"].append("g1")
    if grant(gear_board, cleave, "g1").get("committed"):
        errors.append("Assault was granted to a Gear")
    hand_board = contested_board()
    hand_board["objects"]["h1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2,
                                   "might_modifiers": [], "damage": 0, "exhausted": False}
    hand_board["players"]["p1"]["zones"]["hand"].append("h1")
    if grant(hand_board, cleave, "h1").get("committed"):
        errors.append("Assault was granted to a unit in a hand")
    zero = copy.deepcopy(cleave)
    zero.update({"value": 0, "object_id": "u1", "source": "cleave"})
    zero.pop("target")
    if not validate_program(program("cleave", zero)):
        errors.append("a grant of Assault 0 validated")

    if errors:
        print("FAILED: granted Assault" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'Give a unit [Assault 3] this turn.' is one Assault 3 grant; Assault 1 + Assault 3 is Assault 4 (807.2), "
          "+4 only as the Attacker, nothing on a Defender, gone the next turn; a Gear, a unit in hand and Assault 0 are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
