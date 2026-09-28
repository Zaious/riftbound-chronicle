#!/usr/bin/env python3
"""A Beginning Phase trigger whose conditional statement is part of its trigger condition
(Core 383.2.a.1): "At the start of your Beginning Phase, if you control a facedown card at a
battlefield, draw 1." (Mushroom Pouch).

The engine grammar puts the condition on the trigger's descriptor (controls_facedown_card_at_
battlefield), not on the draw; turn_cycle reads it as the Beginning Step schedules (315.2.a).

Must hold, through a real turn (begin_turn, the Awaken step, enter_beginning_phase, finalize,
resolve):
  - p1 controls a facedown card at a Battlefield p1 controls: scheduled once, p1 draws 1;
  - no facedown card: nothing is scheduled (the reason is recorded);
  - only p2 controls a facedown card (at p2's Battlefield): nothing is scheduled for p1;
  - the facedown card is gone after scheduling and before resolution: it still resolves and
    draws (383.2.a.1's own Sona example - the condition is not read again);
  - the plain wrapper without the condition schedules with no facedown card (the condition is
    what refuses, not the board);
  - validator: the condition on a play trigger, or with extra fields, is refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import rules_core as RC  # noqa: E402
from check_turn_cycle import duel_board, handled, setup_timing  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, validate_state  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from turn_cycle import begin_turn, enter_beginning_phase, run_awaken_step  # noqa: E402

TEXT = "At the start of your Beginning Phase, if you control a facedown card at a battlefield, draw 1."
PLAIN = "At the start of your Beginning Phase, draw 1."
GEAR = "pouch"
PROGRAM_ID = "pouch-beginning"


def board(lowered, *, facedown_for=None):
    """p1's gear with the trigger in its Base; bf2 controlled by p1 and bf3 by p2, each with a
    Facedown Zone; `facedown_for` puts one facedown card under that player's Battlefield."""
    e = duel_board()
    descriptor = copy.deepcopy(lowered["passive"]["object_fields"]["beginning_phase_triggers"][0])
    descriptor.update({"trigger_id": "pouch-on-beginning", "controller": "p1", "source_object": GEAR,
                       "effect_program_id": PROGRAM_ID})
    e["objects"][GEAR] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "beginning_phase_triggers": [descriptor]}
    e["players"]["p1"]["zones"]["base"].append(GEAR)
    e["battlefields"]["bf2"] = {"controller": "p1", "objects": [], "facedown": {"capacity": 1, "cards": []}}
    e["battlefields"]["bf3"] = {"controller": "p2", "objects": [], "facedown": {"capacity": 1, "cards": []}}
    for n in range(3):
        e["objects"][f"deck-{n}"] = copy.deepcopy(e["objects"]["c1"])
        e["players"]["p1"]["zones"]["main_deck"].append(f"deck-{n}")
    if facedown_for is not None:
        e["objects"]["fd"] = {"owner": facedown_for, "controller": facedown_for, "kind": "spell", "base_might": 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
        e["battlefields"]["bf2" if facedown_for == "p1" else "bf3"]["facedown"]["cards"].append(
            {"object_id": "fd", "controller": facedown_for, "hidden_on_turn": "turn-0"})
    return e


def program(lowered):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": PROGRAM_ID, "controller": "p1", "source_object": GEAR,
            "effects": [dict(e, player="p1") for e in lowered["program_effects"]]}


def turn(lowered, e, *, before_resolution=None):
    """(scheduled trigger ids, cards drawn at resolution, evaluated records) on a real turn."""
    began = begin_turn(setup_timing(), e)
    assert began.get("committed"), began.get("reason") or began.get("errors")
    awake = run_awaken_step(handled(began["next_timing_state"]), began["next_effect_state"])
    assert awake.get("committed"), awake.get("reason")
    entered = enter_beginning_phase(handled(awake["next_timing_state"]), awake["next_effect_state"])
    assert entered.get("committed"), entered.get("reason") or entered.get("errors")
    t, state = handled(entered["next_timing_state"]), entered["next_effect_state"]
    evaluated = (entered.get("trace") or {}).get("beginning_triggers") or []
    scheduled = [i["id"] for i in t["chain"]["items"] if i.get("trigger_kind") == "triggered"]
    if not scheduled:
        return scheduled, 0, evaluated
    prog = program(lowered)
    finalized = finalize_trigger(t, state, {PROGRAM_ID: prog})
    assert finalized.get("committed"), finalized.get("reason")
    timing = finalized["next_timing_state"]
    for actor in ("p1", "p2"):
        timing = (RC.pass_priority(timing, actor) or {}).get("next_state") or timing
    current = copy.deepcopy(finalized.get("next_effect_state") or state)
    if before_resolution is not None:
        before_resolution(current)
    hand = len(current["players"]["p1"]["zones"]["hand"])
    done = resolve_with_program(timing, scheduled[0], current, prog)
    assert done.get("committed"), done.get("reason") or done.get("errors")
    return scheduled, len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"]) - hand, evaluated


def main() -> int:
    errors: list[str] = []
    lowered = CG.compile_clause(TEXT, CG.load_grammar())
    descriptor = ((lowered.get("passive") or {}).get("object_fields") or {}).get("beginning_phase_triggers") or [{}]
    if lowered.get("unsupported") or descriptor[0].get("condition") != {"kind": "controls_facedown_card_at_battlefield"} \
            or any("predicate" in e for e in lowered.get("program_effects") or []):
        print(f"FAILED: the grammar did not put the condition on the trigger: {lowered}")
        return 1
    with_card = board(lowered, facedown_for="p1")
    if validate_state(with_card):
        print(f"FAILED: the board is invalid: {validate_state(with_card)}")
        return 1
    scheduled, drew, _ = turn(lowered, with_card)
    if len(scheduled) != 1 or drew != 1:
        errors.append(f"p1 controls a facedown card: scheduled {scheduled}, drew {drew} (want 1 and 1)")
    scheduled, drew, evaluated = turn(lowered, board(lowered))
    if scheduled or not any("controls_facedown_card_at_battlefield" in str(r.get("reason")) for r in evaluated):
        errors.append(f"no facedown card: scheduled {scheduled}, evaluated {evaluated}")
    scheduled, _, _ = turn(lowered, board(lowered, facedown_for="p2"))
    if scheduled:
        errors.append("only p2's facedown card: p1's trigger was scheduled")

    def gone(state):
        state["battlefields"]["bf2"]["facedown"]["cards"] = []
        state["players"]["p1"]["zones"]["trash"].append("fd")
    scheduled, drew, _ = turn(lowered, board(lowered, facedown_for="p1"), before_resolution=gone)
    if len(scheduled) != 1 or drew != 1:
        errors.append(f"the facedown card gone before resolution: it still resolves (383.2.a.1) - scheduled {scheduled}, drew {drew}")
    plain = CG.compile_clause(PLAIN, CG.load_grammar())
    scheduled, drew, _ = turn(plain, board(plain))
    if len(scheduled) != 1 or drew != 1:
        errors.append("the plain Beginning Phase draw did not schedule on the same board (the board, not the condition, refused)")

    misplaced = board(lowered, facedown_for="p1")
    misplaced["objects"][GEAR]["play_triggers"] = misplaced["objects"][GEAR].pop("beginning_phase_triggers")
    if not validate_state(misplaced):
        errors.append("the facedown condition on a play trigger validated")
    extra = board(lowered, facedown_for="p1")
    extra["objects"][GEAR]["beginning_phase_triggers"][0]["condition"]["battlefield"] = "bf2"
    if not validate_state(extra):
        errors.append("the facedown condition with an extra field validated")

    if errors:
        print("FAILED: Beginning Phase trigger condition" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'if you control a facedown card at a battlefield' is the trigger's condition (383.2.a.1): scheduled only "
          "while p1 controls a facedown card at a Battlefield, not for p2's, not read again at resolution; the plain "
          "wrapper schedules on the same board; misplaced or widened conditions are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
