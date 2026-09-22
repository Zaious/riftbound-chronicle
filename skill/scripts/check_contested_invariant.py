#!/usr/bin/env python3
"""State-validator invariant: an opposing Unit at a controlled Battlefield means Contested.

Core 190.3.a: a Battlefield becomes Contested when a Unit whose controller does not
control it arrives there, and stays so until the Showdown or Combat there resolves.
A board that has p2's Unit standing at p1's Battlefield with no Contested mark is not
a position the game can reach, and a scoring test run over it measures nothing: the
Scoring Step would Hold a Battlefield that is actually being fought over.

This holds that:

  - the validator refuses that board, naming Core 190.3.a
  - the Scoring Step refuses it as input rather than Holding bf1 over an enemy Unit
  - the same board marked Contested by p2 is valid
  - an UNCONTROLLED Battlefield with any Unit at it and no Contested mark is refused too
    (GPT, capability 006 ruling): one player's Unit, or both players'
  - an allied Unit (same team_id) at a controlled Battlefield, or an opponent's Gear, do
    not trip it
  - a real Standard Move of p2's Unit into p1's Battlefield yields a state that passes,
    so the engine's own transitions keep the invariant
  - a Move to an uncontrolled Battlefield applies Contested too, and an arrival at one
    already Contested leaves the first applier recorded (190.3.a.1)
  - in a team state an arrival, and control resolution, are unsupported
    (team_contest_unsupported) - never silently continued
  - the state builder derives the applier only when exactly one player can be it, and
    refuses by name (contested_applier_undetermined) when more than one can

and removes the invariant from a copy of the validator once, to prove the refusal
comes from it.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
import types
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from battlefield_control import SCORING_TASK, run_scoring_step  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from check_standard_move import declare  # noqa: E402
from combat import standard_move  # noqa: E402
from battlefield_control import resolve_battlefield_control  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from state_builder import build_state_assumption  # noqa: E402

MARK = "Core 190.3.a"


def controlled_with_enemy() -> dict:
    """p1 controls bf1 with u1 there; p2's u2 stands there too; nothing is Contested."""
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1", "u2"]}
    return state


def invariant_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if MARK in e and "not contested" in e]


def main() -> int:
    problems: list[str] = []

    bad = controlled_with_enemy()
    if not invariant_errors(validate_state(bad)):
        problems.append(f"an enemy Unit at a controlled, uncontested Battlefield was accepted: {validate_state(bad)}")
    scored = run_scoring_step({**fixture(tasks=[SCORING_TASK]), "phase": "beginning", "priority": None}, bad)
    if scored.get("committed"):
        problems.append(f"the Scoring Step took the invalid board as input and Held {scored['trace'].get('held')}")

    contested = copy.deepcopy(bad)
    contested["battlefields"]["bf1"].update({"contested": True, "contested_by": "p2"})
    if found := validate_state(contested):
        problems.append(f"the same board marked Contested by p2 was refused: {found}")

    allied = copy.deepcopy(bad)
    allied["players"]["p1"]["team_id"] = allied["players"]["p2"]["team_id"] = "t1"
    if invariant_errors(validate_state(allied)):
        problems.append("an allied Unit (same team_id) at a controlled Battlefield tripped the invariant")

    open_bf = copy.deepcopy(bad)
    open_bf["battlefields"]["bf1"]["controller"] = None
    if not invariant_errors(validate_state(open_bf)):
        problems.append("an uncontrolled Battlefield with both players' Units and no Contested mark was accepted")
    lone = copy.deepcopy(open_bf)
    lone["battlefields"]["bf1"]["objects"].remove("u2")
    lone["players"]["p2"]["zones"]["base"].append("u2")
    if not invariant_errors(validate_state(lone)):
        problems.append("an uncontrolled Battlefield with one player's Unit and no Contested mark was accepted")
    lone["battlefields"]["bf1"].update({"contested": True, "contested_by": "p1"})
    if found := validate_state(lone):
        problems.append(f"an uncontrolled Battlefield marked Contested by its lone Unit's controller was refused: {found}")

    gear = controlled_with_enemy()
    gear["battlefields"]["bf1"]["objects"].remove("u2")
    gear["players"]["p2"]["zones"]["base"].append("u2")
    gear["objects"]["g2"] = {"owner": "p2", "controller": "p2", "kind": "gear", "base_might": 0,
                             "might_modifiers": [], "damage": 0, "exhausted": False}
    gear["battlefields"]["bf1"]["objects"].append("g2")
    if invariant_errors(validate_state(gear)):
        problems.append("an opposing Gear, not a Unit, tripped the invariant")

    # the engine's own transition: p2 moves u2 from Base into p1's bf1
    before = base_state()
    before["players"]["p1"]["zones"]["base"].remove("u1")
    before["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"]}
    before["objects"]["u2"]["exhausted"] = False
    timing = {**fixture(), "turn_player": "p2", "priority": "p2"}
    moved = standard_move(timing, before, declare(["u2"], {"kind": "battlefield", "battlefield": "bf1"}, actor="p2"))
    if not moved.get("committed"):
        problems.append(f"the real Standard Move into an enemy Battlefield did not commit: "
                        f"{moved.get('reason_code')} {moved.get('reason') or moved.get('errors')}")
    else:
        after = moved["next_effect_state"]
        if found := validate_state(after):
            problems.append(f"the engine's own Move left a state the validator refuses: {found}")
        if not after["battlefields"]["bf1"].get("contested"):
            problems.append("the engine's own Move into an enemy Battlefield did not mark it Contested")

    # 190.3.a.1: an uncontrolled Battlefield is one the mover does not control either
    empty = base_state()
    empty["objects"]["u1"]["exhausted"] = False
    to_open = standard_move(fixture(), empty, declare(["u1"], {"kind": "battlefield", "battlefield": "bf1"}))
    if not to_open.get("committed"):
        problems.append(f"a Move to an uncontrolled Battlefield did not commit: {to_open.get('reason_code')}")
    elif to_open["next_effect_state"]["battlefields"]["bf1"].get("contested_by") != "p1":
        problems.append("a Move to an uncontrolled Battlefield did not apply Contested (190.3.a.1)")

    # 190.3.a.1: "if that battlefield is not already Contested" - the first applier stays
    already = copy.deepcopy(before)
    already["battlefields"]["bf1"].update({"contested": True, "contested_by": "p1"})
    already["battlefields"]["bf1"]["objects"].append("u3")
    already["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 1,
                                "might_modifiers": [], "damage": 0, "exhausted": False}
    already["battlefields"]["bf1"]["controller"] = None
    second = standard_move(timing, already, declare(["u2"], {"kind": "battlefield", "battlefield": "bf1"}, actor="p2"))
    if second.get("committed") and second["next_effect_state"]["battlefields"]["bf1"].get("contested_by") != "p1":
        problems.append("a second arrival overwrote who applied Contested; 190.3.a.1 applies it only if not already Contested")
    elif not second.get("committed"):
        problems.append(f"a Move to an already Contested Battlefield did not commit: {second.get('reason_code')} {second.get('reason')}")

    # team state: the arrival is not decided on a guess
    teamed = copy.deepcopy(before)
    teamed["players"]["p1"]["team_id"], teamed["players"]["p2"]["team_id"] = "t1", "t2"
    team_move = standard_move(timing, teamed, declare(["u2"], {"kind": "battlefield", "battlefield": "bf1"}, actor="p2"))
    if team_move.get("committed") or "team_contest_unsupported" not in str(team_move.get("reason") or team_move.get("errors")):
        problems.append(f"an arrival in a team state was not refused as team_contest_unsupported: "
                        f"committed={team_move.get('committed')} {team_move.get('reason') or team_move.get('errors')}")
    mode_teams = copy.deepcopy(before)
    mode_teams["mode"] = {"victory_score": 11, "teams": [["p1"], ["p2"]]}
    moded = standard_move(timing, mode_teams, declare(["u2"], {"kind": "battlefield", "battlefield": "bf1"}, actor="p2"))
    if moded.get("committed"):
        problems.append("an arrival in a state whose Mode of Play names teams went through")
    if to_open.get("committed"):
        closing = {**fixture(), "showdown": {"active": True, "kind": "non_combat", "focus": "p1", "battlefield": "bf1",
                                             "focus_passes": [], "closing": True}}
        team_board = copy.deepcopy(to_open["next_effect_state"])
        team_board["players"]["p1"]["team_id"], team_board["players"]["p2"]["team_id"] = "t1", "t2"
        resolved = resolve_battlefield_control(closing, team_board)
        if resolved.get("committed") or resolved.get("reason_code") != "team_contest_unsupported":
            problems.append(f"control resolution in a team state was not unsupported: {resolved.get('reason_code')}")

    # the state builder: derive only a determined applier, refuse the rest by name
    def draft(units, controller=None):
        return {"players": ["p1", "p2"], "mode": {"id": "duel", "victory_score": 8, "teams": False},
                "points": {"p1": 0, "p2": 0}, "battlefields": [{"battlefield_id": "bf1", "controller": controller}],
                "units": [{"object_id": u, "controller": c, "might": 1, "location": "bf1"} for u, c in units]}
    one = build_state_assumption(question="q", question_kind="scored_board", draft=draft([("u1", "p1")]))
    if not one.get("buildable") or one["state"]["battlefields"]["bf1"].get("contested_by") != "p1":
        problems.append(f"the builder did not derive the lone applier at an uncontrolled Battlefield: {one.get('downgrade')}")
    elif not any(a["slot"] == "battlefield_contested" for a in one["assumptions"]):
        problems.append("the builder derived Contested without listing it as a derived assumption")
    two = build_state_assumption(question="q", question_kind="scored_board", draft=draft([("u1", "p1"), ("u2", "p2")]))
    if two.get("buildable") or (two.get("downgrade") or {}).get("reason") != "contested_applier_undetermined":
        problems.append(f"the builder guessed an applier between two players: {two.get('downgrade')}")

    # mutation: the validator without the invariant must accept the bad board
    source = (SCRIPT_DIR / "effect_ir.py").read_text(encoding="utf-8")
    anchor = "        if enemies:\n"
    if source.count(anchor) != 1:
        problems.append("the invariant's anchor is gone from effect_ir.py; the mutation cannot be placed")
    else:
        spec = importlib.util.spec_from_loader("effect_ir_mutated", loader=None)
        mutated = types.ModuleType(spec.name)
        mutated.__file__ = str(SCRIPT_DIR / "effect_ir.py")
        exec(compile(source.replace(anchor, "        if False and enemies:\n"), mutated.__file__, "exec"), mutated.__dict__)
        if invariant_errors(mutated.validate_state(controlled_with_enemy())):
            problems.append("mutation not caught: the validator without the invariant still refused the board")

    if problems:
        print("FAILED: contested invariant" + chr(10) + "  - " + (chr(10) + "  - ").join(problems))
        return 1
    print("OK: an enemy Unit at a controlled, uncontested Battlefield is refused by the validator (Core 190.3.a) "
          "and by the Scoring Step as input; Contested, allied and Gear boards pass; the engine's "
          "own Move keeps the invariant and applies Contested at an uncontrolled Battlefield without overwriting "
          "a first applier (190.3.a.1); uncontrolled Battlefields with Units are held to it too; team-state "
          "arrivals and control resolution are unsupported; the builder derives only a determined applier and "
          "refuses the rest by name; removing the invariant is caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
