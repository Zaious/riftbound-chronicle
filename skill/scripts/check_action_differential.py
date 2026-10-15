#!/usr/bin/env python3
"""Gate: the enumerator's actions are exactly the declarations the engine accepts (package 13, C2; GPT ruling 3).

For each board and each covered family, D(s) - every syntactically valid declaration over the state's own sets - is
run through the engine's own procedure (V), and the enumerator's list must equal what V accepts, key for key
(action_space.differential). Families covered so far: standard_move, hide, pass_priority, pass_focus,
end_main_phase.

  D1 moves       a board with units at the Base and at two Battlefields, one exhausted, one with Ganking, an enemy at
                 the second Battlefield: every set of units to every destination, through combat.standard_move
  D2 restricted  the board whose Battlefield forbids a Move to a Base (check_move_restriction.board)
  D3 timing      the same units outside the Turn Player's Main Phase: the procedure takes none, the enumerator lists none
  D4 passes      pass_priority, pass_focus and end_main_phase on the timing kernel's canonical states, for each player
  D6 hides       cards with and without Hidden in the hand and the Champion Zone, a Battlefield each player controls,
                 Power of two Domains, a Legend's Energy instead of [A], and the same with 'ignoring costs' this turn:
                 every object from each source to each Battlefield for every cost shape, through hidden.hide_card
  D5 the method  a doctored enumeration - one action dropped, one added - is caught as missing and extra; a space over
                 the cap stops by name, never a partial answer

    python skill/scripts/check_action_differential.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_space as A  # noqa: E402
import legal_action as la  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_hide_cost_basis import granted, with_legend  # noqa: E402
from check_move_restriction import board as restricted_board  # noqa: E402
from check_rules_core import FIXTURES, fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
counts: dict[str, int] = {}


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, *, exhausted=False, keywords=None):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": exhausted, **({"keywords": keywords} if keywords else {})}


def moves_board():
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["objects"].update({"u3": unit("p1"), "u4": unit("p1"), "u5": unit("p1", exhausted=True),
                             "u6": unit("p1", keywords=["ganking"])})
    state["players"]["p1"]["zones"]["base"] += ["u3"]
    state["battlefields"]["bf1"]["objects"] += ["u4", "u5", "u6"]
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["objects"]["u2"]["exhausted"] = False
    state["battlefields"]["bf2"]["objects"].append("u2")
    return settle_contested(state)


def enumerate_for(timing, effect, actor):
    observation = la.build_observation(
        perspective={"p1": "player1", "p2": "player2"}[actor], source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard",
                 "card_data_version": "synthetic"},
        timing_state=timing, effect_state=effect, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"})
    return la.enumerate_actions(observation, actor)


def compare(label, family, timing, effect, actor, *, expect_some=None):
    result = enumerate_for(timing, effect, actor)
    got = A.differential(family, timing, effect, actor, result)
    if not got["complete"]:
        fail(label, f"{family} for {actor}: stopped {got.get('stopped')}, missing {got.get('missing')}, "
                    f"extra {got.get('extra')}")
        return got
    counts[family] = counts.get(family, 0) + got["accepted"]
    if expect_some is True and not got["accepted"]:
        fail(label, f"{family} for {actor}: nothing accepted, so the comparison proves nothing")
    if expect_some is False and got["accepted"]:
        fail(label, f"{family} for {actor}: {got['accepted']} accepted where none should be")
    return got


def main() -> int:
    # D1
    board = moves_board()
    if validate_state(board):
        fail("D1 moves", f"the board is not valid: {validate_state(board)[:2]}")
        return report()
    got = compare("D1 moves", "standard_move", fixture(), board, "p1", expect_some=True)
    if got.get("complete") and got["broad"] <= got["accepted"]:
        fail("D1 moves", "every broad declaration was accepted, so D(s) is not a superset worth the name")
    # D2
    compare("D2 restricted", "standard_move", fixture(), restricted_board(), "p1", expect_some=True)
    # D3
    beginning = copy.deepcopy(fixture())
    beginning["phase"] = "beginning"
    compare("D3 timing", "standard_move", beginning, board, "p1", expect_some=False)
    compare("D3 timing", "standard_move", fixture(), board, "p2", expect_some=False)
    # D4
    for name, timing in sorted(FIXTURES.items()):
        for family in ("pass_priority", "pass_focus", "end_main_phase"):
            for actor in ("p1", "p2"):
                compare(f"D4 passes ({name})", family, timing, base_state(), actor)
    # D6
    hides = with_legend(base_state(), energy=1)
    hides["battlefields"]["bf1"]["controller"] = "p1"
    hides["battlefields"]["bf2"] = {"controller": "p2", "objects": []}
    hides["objects"].update({
        "h1": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0,
               "exhausted": False, "hidden": True},
        "h2": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0,
               "exhausted": False},
        "h3": {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
               "exhausted": False, "hidden": True}})
    hides["players"]["p1"]["zones"]["hand"] += ["h1", "h2"]
    hides["players"]["p1"]["zones"].setdefault("champion_zone", []).append("h3")
    hides["players"]["p1"]["resources"] = {"energy": 1, "power": {"fury": 1, "calm": 1}}
    if validate_state(hides):
        fail("D6 hides", f"the board is not valid: {validate_state(hides)[:2]}")
    else:
        compare("D6 hides", "hide", fixture(), hides, "p1", expect_some=True)
        compare("D6 hides (ignoring costs)", "hide", fixture(), granted(hides), "p1", expect_some=True)
        compare("D6 hides (p2)", "hide", fixture(priority="p2"), hides, "p2", expect_some=False)

    # D5
    result = enumerate_for(fixture(), board, "p1")
    doctored = copy.deepcopy(result)
    actions = doctored["enumeration"]["actions"]
    moves = [a for a in actions if a["family"] == "standard_move"]
    actions.remove(moves[0])
    bogus = copy.deepcopy(moves[1])
    bogus["action"]["declaration"]["units"] = ["u5"]
    actions.append(bogus)
    caught = A.differential("standard_move", fixture(), board, "p1", doctored)
    if caught["complete"] or not caught["missing"] or not caught["extra"]:
        fail("D5 the method", f"a dropped and an added action were not both caught: {caught}")
    keep = A.BROAD_CAP
    A.BROAD_CAP = 3
    try:
        stopped = A.differential("standard_move", fixture(), board, "p1", result)
    finally:
        A.BROAD_CAP = keep
    if stopped["complete"] or not str(stopped.get("stopped") or "").startswith("over_cap"):
        fail("D5 the method", f"a space over the cap did not stop by name: {stopped}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: enumerator against the engine's own acceptance")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: on every board the enumerator lists exactly the declarations the engine accepts - accepted actions "
          f"compared {dict(sorted(counts.items()))}; a dropped or an added action is caught, a space over the cap "
          f"stops by name (D1-D6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
