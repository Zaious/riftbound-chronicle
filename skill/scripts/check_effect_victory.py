#!/usr/bin/env python3
"""
Gate (package 9, The Grand Plaza): "When you hold here, if you have 7+ units here, you win the game."

GPT 2026-10-06 ruling 10. "if you have 7+ units here" right after the Condition is part of the Trigger Condition
(Core 383.2.a.1): it is read as the Hold is processed, and decides whether the ability goes on the Chain at all. The
ability resolving makes its controller win (Core 195) and the game ends right then (196), without waiting for a
Cleanup's victory check (194.2).

Must hold:
  T1  seven units p1 controls at the held Battlefield: the hold trigger is scheduled; resolved, the timing state is
      terminal - reason effect_victory, winner p1, immediate - though p1 has far fewer points than the Victory Score
  T2  six units there: the trigger is not scheduled at all (not "scheduled and doing nothing")
  T3  scheduled with seven, then units leave before it resolves: it still resolves and p1 still wins (the condition
      is the trigger's, not the effect's)
  T4  scheduled, then countered (removed from the Chain, Core 425.1): no terminal state, nothing happens
  T5  units of p2 there do not count toward p1's seven
  T6  after the win the snapshot is frozen: a further procedure is refused as game_over (Core 196)
  S   shapes: a condition on a non-hold trigger, a condition of another kind, a win_game with no player - refused
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from battlefield_control import SCORING_TASK, run_scoring_step  # noqa: E402
from check_combat_damage_assignment import add_unit  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, validate_program, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, is_terminal, next_procedure, pass_priority, remove_chain_item  # noqa: E402

errors: list[str] = []
PLAZA_TRIGGER = {"trigger_id": "plaza-hold", "controller_order": 0, "effect_program_id": "plaza-hold-effects",
                 "optional_at_finalize": False, "condition": {"kind": "controls_units", "count": 7, "location": "here"}}
WIN = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
       "program_id": "plaza-hold-effects", "controller": "p1", "source_object": "bf1",
       "effects": [{"op": "win_game", "effect_id": "win", "player": "p1"},
                   {"op": "draw", "effect_id": "after", "player": "p1", "count": 1}]}


def fail(label, why):
    errors.append(f"{label}: {why}")


def plaza(units: int, *, enemy: int = 0) -> dict:
    """p1 controls bf1 (The Grand Plaza, its hold trigger) with `units` of p1's units there and `enemy` of p2's."""
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["players"]["p1"]["points"] = 2
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": [], "hold_triggers": [copy.deepcopy(PLAZA_TRIGGER)]}
    for i in range(units):
        add_unit(state, f"pu{i}", "p1", "bf1", might=1)
    for i in range(enemy):
        add_unit(state, f"eu{i}", "p2", "bf1", might=1)
    if enemy:
        state["battlefields"]["bf1"]["contested"] = True
        state["battlefields"]["bf1"]["contested_by"] = "p2"
    return state


def beginning():
    return {**fixture(tasks=[SCORING_TASK]), "phase": "beginning", "priority": None}


def hold(units, **kw):
    e = plaza(units, **kw)
    if validate_state(e):
        fail(f"board {units}", validate_state(e))
    return run_scoring_step(beginning(), e)


def to_resolution(t):
    for _ in range(10):
        step = next_procedure(t)
        if step.get("procedure") == "resolve_newest_finalized":
            return t
        if step.get("procedure") == "finalize_oldest_pending":
            got = finalize_oldest_pending(t)
            t = got["next_state"]
            continue
        holder = t.get("priority")
        t = pass_priority(t, holder)["next_state"]
    return t


def plaza_items(timing):
    return [i for i in timing["chain"]["items"] if "plaza-hold" in str(i.get("id"))]


def main() -> int:
    # T1
    held = hold(7)
    if not held.get("committed") or len(plaza_items(held["next_timing_state"])) != 1:
        fail("T1 scheduled", f"seven units: the hold trigger was not scheduled once ({held.get('reason')})")
    else:
        t = to_resolution(held["next_timing_state"])
        item = plaza_items(t)[0]["id"]
        done = resolve_with_program(t, item, held["next_effect_state"], WIN)
        term = (done.get("next_timing_state") or {}).get("terminal") or {}
        if not done.get("committed") or term.get("reason") != "effect_victory" or term.get("winner") != "p1" \
                or not term.get("immediate") or not is_terminal(done["next_timing_state"]):
            fail("T1 win", f"resolving did not end the game for p1 at once: {done.get('reason')} {term}")
        trace = (done.get("trace") or {}).get("effect") or []
        if [e.get("outcome") for e in trace] != ["applied", "skipped_after_terminal"]:
            fail("T1 after", f"the instruction after the win was not skipped: {[e.get('outcome') for e in trace]}")
        if done.get("next_effect_state", {}).get("players", {}).get("p1", {}).get("points") \
                != held["next_effect_state"]["players"]["p1"]["points"]:
            fail("T1 points", "the win changed p1's points or waited for the Victory Score")
        # T6
        again = pass_priority(done["next_timing_state"], done["next_timing_state"].get("priority") or "p1")
        if again.get("applied") or again.get("reason_code") != "game_over":
            fail("T6 frozen", f"a procedure after the win was not refused as game_over: {again.get('reason_code')}")
        # T3: units leave after scheduling
        e = copy.deepcopy(held["next_effect_state"])
        for oid in [o for o in e["battlefields"]["bf1"]["objects"]][:5]:
            e["battlefields"]["bf1"]["objects"].remove(oid)
            e["players"]["p1"]["zones"]["trash"].append(oid)
        late = resolve_with_program(t, item, e, WIN)
        if ((late.get("next_timing_state") or {}).get("terminal") or {}).get("winner") != "p1":
            fail("T3 count changed", f"with two units left when it resolved, p1 did not still win: {late.get('reason')}")
        # T4: countered
        countered = remove_chain_item(t, item, reason="countered")
        if not countered.get("applied") or is_terminal(countered["next_state"]) or plaza_items(countered["next_state"]):
            fail("T4 countered", "a countered trigger left the game ended or the item on the Chain")
    # T2
    six = hold(6)
    if not six.get("committed") or plaza_items(six["next_timing_state"]):
        fail("T2 six", f"six units: the trigger was scheduled or the Hold failed ({six.get('reason')})")
    # T5: the condition counts only units p1 controls there (read on a board where p2's units are there too)
    from effect_ir import evaluate_condition
    cond = PLAZA_TRIGGER["condition"]
    six_and_three = evaluate_condition(plaza(6, enemy=3), cond, controller="p1", object_id="bf1")
    seven_and_three = evaluate_condition(plaza(7, enemy=3), cond, controller="p1", object_id="bf1")
    if six_and_three or not seven_and_three:
        fail("T5 enemy units", "p2's units counted toward p1's seven, or p1's seven were not counted beside them")
    # S
    bad = plaza(7)
    bad["battlefields"]["bf1"]["conquer_triggers"] = [copy.deepcopy(PLAZA_TRIGGER)]
    if not validate_state(bad):
        fail("S", "a condition on a conquer trigger validated")
    other = plaza(7)
    other["battlefields"]["bf1"]["hold_triggers"][0]["condition"] = {"kind": "runes_at_least", "count": 7}
    if not validate_state(other):
        fail("S", "a condition of another kind validated")
    noplayer = copy.deepcopy(WIN)
    noplayer["effects"][0].pop("player")
    if not validate_program(noplayer):
        fail("S", "a win_game with no player validated")
    if errors:
        print("FAILED: effect victory checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: The Grand Plaza - seven units of p1's at the held Battlefield schedule the hold trigger and resolving it "
          "ends the game for p1 at once (effect_victory, Core 195-196), the instruction after it skipped; six do not "
          "schedule it, p2's units do not count, units leaving after scheduling do not stop the win, a countered trigger "
          "does nothing, and the frozen snapshot refuses every procedure; three shapes refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
