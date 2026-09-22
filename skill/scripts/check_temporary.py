#!/usr/bin/env python3
"""Regression gate for Temporary (Core 816; 315.2).

    816.1.b  short for "At the start of this permanent's controller's Beginning Phase,
             before scoring, kill this."
    816.1.c  the trigger condition is the controller's Beginning Phase starting
    816.2.a  however many instances, it triggers once
    816.3    Temporary is a characteristic

Must hold, through the real turn cycle (begin_turn, run_awaken_step,
enter_beginning_phase), trigger finalization and resolution:
  - entering p1's Beginning Phase schedules one Temporary trigger for p1's Temporary
    Unit, with the Scoring Step still outstanding behind it (before scoring);
  - resolving it with the engine's program kills that Unit (it goes to its owner's trash);
  - negatives: p2's Temporary Unit does not trigger in p1's Beginning Phase; a Unit
    without Temporary does not trigger; a program with the Temporary id but other
    content is refused by dispatch;
  - "[Temporary]" lowered by the engine grammar is the keyword;
  - mutation: without the Temporary production nothing is scheduled.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from check_turn_cycle import duel_board, handled, setup_timing  # noqa: E402
from effect_ir import find_location, has_keyword  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, resolve_with_program  # noqa: E402
from turn_cycle import begin_turn, enter_beginning_phase, run_awaken_step  # noqa: E402


def beginning(board):
    began = begin_turn(setup_timing(), board)
    assert began.get("committed"), began.get("reason")
    awake = run_awaken_step(handled(began["next_timing_state"]), began["next_effect_state"])
    assert awake.get("committed"), awake.get("reason")
    return enter_beginning_phase(awake["next_timing_state"], awake["next_effect_state"])


def main() -> int:
    errors: list[str] = []
    board = duel_board()
    board["objects"]["u1"]["keywords"] = ["temporary"]
    board["objects"]["u2"]["keywords"] = ["temporary"]
    entered = beginning(board)
    if not entered.get("committed"):
        print(f"FAILED: Temporary checks\n  - the Beginning Phase was not entered: {entered.get('reason_code')} {entered.get('reason')}")
        return 1
    timing, state = entered["next_timing_state"], entered["next_effect_state"]
    ids = [i["id"] for i in timing["chain"]["items"]]
    if ids != ["u1:temporary"]:
        errors.append(f"p1's Beginning Phase did not schedule exactly p1's Temporary trigger: {ids}")
    if "scoring_step" not in timing["outstanding_tasks"]:
        errors.append("the Scoring Step is not still outstanding behind the Temporary trigger (before scoring)")

    program = IR.temporary_program(state, "u1", "p1")
    registry = {program["program_id"]: program}
    forged = copy.deepcopy(program); forged["effects"][0]["object_id"] = "u2"
    item = next((i for i in timing["chain"]["items"] if i["id"] == "u1:temporary"), None)
    if item is not None and dispatch_program({program["program_id"]: forged}, item)[0] is not None:
        errors.append("dispatch accepted a program under the Temporary id with other content")

    finalized = finalize_trigger(handled(timing), state, registry, None)
    if not finalized.get("committed"):
        errors.append(f"the Temporary trigger did not finalize: {finalized.get('reason')}")
    else:
        t = finalized["next_timing_state"]
        for _ in range(4):
            if RC.next_procedure(t).get("procedure") == "resolve_newest_finalized":
                break
            t = RC.pass_priority(t, t["priority"])["next_state"]
        chain_item = next(i for i in t["chain"]["items"] if i["status"] == "finalized")
        dispatched, refusal = dispatch_program(registry, chain_item)
        done = resolve_with_program(t, chain_item["id"], state, dispatched) if refusal is None else {"reason": refusal}
        if not done.get("committed") or find_location(done["next_effect_state"], "u1") != ("player", "p1", "trash"):
            errors.append(f"resolving Temporary did not kill the Unit: {done.get('reason_code')} {done.get('reason')}")
        elif find_location(done["next_effect_state"], "u2") == ("player", "p2", "trash"):
            errors.append("p2's Temporary Unit died in p1's Beginning Phase")

    plain = duel_board()
    quiet = beginning(plain)
    if not quiet.get("committed") or quiet["next_timing_state"]["chain"]["items"]:
        errors.append("a Beginning Phase with no Temporary permanent scheduled a trigger")

    fields = (CG.compile_clause("[Temporary]", CG.load_grammar()).get("passive") or {}).get("object_fields") or {}
    if fields.get("keywords") != ["temporary"]:
        errors.append(f"[Temporary] did not lower to the keyword: {fields}")
    if not has_keyword(state, "u1", "temporary"):
        errors.append("Temporary is not a characteristic other effects can read (816.3)")

    saved = IR.temporary_triggers
    try:
        IR.temporary_triggers = lambda *_a, **_k: []
        mutated = beginning(board)
    finally:
        IR.temporary_triggers = saved
    if mutated.get("committed") and mutated["next_timing_state"]["chain"]["items"]:
        errors.append("mutation not caught: with no Temporary production the trigger was still scheduled")

    if errors:
        print("FAILED: Temporary checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: entering its controller's Beginning Phase schedules one Temporary trigger per Temporary permanent, before "
          "the Scoring Step (816.1.b-c, 816.2.a, 315.2); resolving it with the engine's program kills that permanent; an "
          "opponent's Temporary, a board without one, a forged program and a missing production are all caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
