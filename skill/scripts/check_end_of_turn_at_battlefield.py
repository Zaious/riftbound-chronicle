#!/usr/bin/env python3
"""An end-of-turn trigger whose Trigger Condition is "if I'm at a battlefield" (package 10, Sona - Harmonious).

"At the end of your turn, if I'm at a battlefield, ready up to 4 friendly runes." The conditional statement right after
the trigger condition is part of it (Core 383.2.a.1): read as the Ending Step schedules the turn player's end-of-turn
triggers (Core 317.1) - the card at a Battlefield then, or it does not trigger.

The engine's shape: the clause grammar row at_the_end_of_your_turn_if_im_at_a_battlefield puts {kind at_battlefield}
on the end_of_turn_triggers descriptor; resolution_bridge.begin_ending_step reads it.

  E1 there         p1's unit at bf1 carrying it: the Ending Step schedules it, the condition gone from what it scheduled
  E2 base          the same unit in p1's Base: nothing scheduled
  E3 theirs        the unit at bf1 on p2's turn: nothing scheduled (the turn player's)
  G  grammar       the sentence lowers to exactly that descriptor; "at the end of your turn, draw 1" carries no condition

    python skill/scripts/check_end_of_turn_at_battlefield.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from resolution_bridge import begin_ending_step  # noqa: E402

SENTENCE = "At the end of your turn, if I'm at a battlefield, draw 1."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(where: str):
    state = base_state()
    state["objects"]["so"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False,
                              "end_of_turn_triggers": [{"trigger_id": "eot", "controller": "p1", "source_object": "so",
                                                        "controller_order": 0, "effect_program_id": "eot-effects",
                                                        "optional_at_finalize": False, "condition": {"kind": "at_battlefield"}}]}
    if where == "bf1":
        state["battlefields"]["bf1"]["objects"].append("so")
        state["battlefields"]["bf1"]["controller"] = "p1"
        for o in [o for o in state["battlefields"]["bf1"]["objects"] if state["objects"][o].get("controller") == "p2"]:
            state["battlefields"]["bf1"]["objects"].remove(o)
            state["players"]["p2"]["zones"]["base"].append(o)
        state["battlefields"]["bf1"].update({"contested": False, "contested_by": None})
    else:
        state["players"]["p1"]["zones"]["base"].append("so")
    problems = validate_state(state)
    if problems:
        raise AssertionError(problems[:2])
    return state


def scheduled(state, turn_player="p1"):
    timing = fixture()
    timing["phase"] = "main"
    if turn_player != "p1":
        timing.update({"turn_player": turn_player, "priority": turn_player})
    began = begin_ending_step(timing, state)
    if not began.get("committed"):
        return f"refused: {began.get('reason_code')} {began.get('reason')}"
    return [i for i in began["next_timing_state"]["chain"]["items"] if str(i.get("id", "")).startswith("eot")]


def main() -> int:
    got = scheduled(board("bf1"))
    if not isinstance(got, list) or len(got) != 1 or "condition" in got[0]:
        fail("E1 there", got)
    got = scheduled(board("base"))
    if got != []:
        fail("E2 base", got)
    got = scheduled(board("bf1"), turn_player="p2")
    if got != []:
        fail("E3 theirs", got)
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    rows = ((lowered.get("passive") or {}).get("object_fields") or {}).get("end_of_turn_triggers") or []
    if lowered.get("production_id") != "at_the_end_of_your_turn_if_im_at_a_battlefield" or len(rows) != 1 \
            or rows[0].get("condition") != {"kind": "at_battlefield"}:
        fail("G grammar", f"{lowered.get('production_id')} {rows}")
    plain = CG.compile_clause("At the end of your turn, draw 1.", CG.load_grammar())
    plain_rows = ((plain.get("passive") or {}).get("object_fields") or {}).get("end_of_turn_triggers") or []
    if plain.get("production_id") != "at_the_end_of_your_turn" or any("condition" in r for r in plain_rows):
        fail("G grammar", f"the plain row: {plain.get('production_id')} {plain_rows}")
    if errors:
        print("FAILED: end-of-turn at-battlefield checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'At the end of your turn, if I'm at a battlefield' triggers only with the card at a Battlefield as the "
          "turn player's Ending Step schedules it (E1-E3, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
