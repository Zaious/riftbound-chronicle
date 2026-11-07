#!/usr/bin/env python3
"""ADR-0017 §4: Quick-Draw (Core 819) - Reaction, and a play trigger that attaches the card to one of your units.

Through the real play transaction, play completion, trigger finalization and resolution:

  Q1 reaction    a Gear with Quick-Draw (printed play timing reaction, 819.1.b) may be declared at Reaction timing;
                 the same Gear without it, printed at default timing, may not
  Q2 trigger     its play completion schedules one Quick-Draw trigger bound to the engine's attach program by content
                 hash; a program with that id but other content is refused by dispatch
  Q3 attach      finalized with a friendly unit as its target and resolved, the Gear is attached to that unit, which
                 has the Might Bonus
  Q4 enemy       finalized with an enemy unit, the target is refused
  Q5 none        the same Gear without Quick-Draw schedules no trigger
  V1 shape       a card with Quick-Draw whose printed play timing is not reaction is not a valid state
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import effect_ir as IR  # noqa: E402
import engine_decisions as ed  # noqa: E402
import play_transaction as PT  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import effective_might, hash_value, object_identity, validate_state  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

FAILS: list[str] = []
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + str(detail)) if detail != '' and not ok else ''}")
    if not ok:
        FAILS.append(name)


def board(*, quick_draw=True):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "gear", "base_might": 0, "might_bonus": 2, "tags": ["Equipment"]})
    if quick_draw:
        state["objects"]["c1"].update({"keywords": ["quick_draw"], "play_timing": "reaction"})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return state


def declaration(timing):
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "gear-1", "object_kind": "gear", "timing": timing},
            "cost": {"base": {"energy": 2, "power": {}}}, "payment_context": dict(CLOSED)}


def completed(state, timing="reaction"):
    played = PT.play_card(fixture(), state, declaration(timing))
    if not played.get("committed"):
        return played
    after = fixture(priority="p2", items=[item("gear-1", "p1", "gear", timing, "finalized")], passes=["p1", "p2"])
    return resolve_with_program(after, "gear-1", played["next_effect_state"], None)


def host(state, unit):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [
        {"decision_id": IR.QUICK_DRAW_HOST, "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [unit], "selection_identities": {unit: object_identity(state, unit) or f"{unit}@0"}}]}


def main() -> int:
    state = board()
    check("the board is valid", not validate_state(state), validate_state(state))
    plain = PT.play_card(fixture(), board(quick_draw=False), declaration("reaction"))
    check("Q1 without Quick-Draw the Gear may not be declared at Reaction timing",
          not plain.get("committed") and plain.get("reason_code") == "timing_not_printed", plain.get("reason_code"))
    done = completed(state)
    items = done.get("next_timing_state", {}).get("chain", {}).get("items", [])
    check("Q1 with Quick-Draw it is declared at Reaction timing and completes", done.get("committed"), done.get("reason"))
    check("Q2 its play completion schedules one Quick-Draw trigger", [i.get("id") for i in items] == ["c1:quick_draw"],
          [i.get("id") for i in items])
    if not items:
        print(f"check_quick_draw: FAILED {', '.join(FAILS)}")
        return 1
    after, trig = done["next_effect_state"], items[0]
    program = IR.quick_draw_program(after, "c1", "p1")
    check("Q2 dispatch takes the engine's own program", dispatch_program({program["program_id"]: program}, trig)[0] is not None)
    forged = copy.deepcopy(program)
    forged["effects"][0]["target"]["controller_relation"] = "enemy"
    check("Q2 and refuses other content under its id", dispatch_program({program["program_id"]: forged}, trig)[0] is None)

    registry = {program["program_id"]: program}
    enemy = finalize_trigger(done["next_timing_state"], after, registry, host(after, "u2"))
    check("Q4 an enemy unit is refused as the target", not enemy.get("committed"), enemy.get("reason"))
    finalized = finalize_trigger(done["next_timing_state"], after, registry, host(after, "u1"))
    check("Q3 the trigger finalizes with a friendly unit", finalized.get("committed"), finalized.get("reason"))
    if finalized.get("committed"):
        timing = finalized["next_timing_state"]
        for _ in range(4):
            if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
                break
            timing = RC.pass_priority(timing, timing["priority"])["next_state"]
        resolved = resolve_with_program(timing, "c1:quick_draw", after, program, engine_decisions=host(after, "u1"))
        end = resolved.get("next_effect_state") or {}
        check("Q3 resolved, the Gear is attached to the unit", resolved.get("committed")
              and (end.get("objects") or {}).get("c1", {}).get("attached_to") == "u1", resolved.get("reason"))
        if end:
            check("Q3 the unit has the Might Bonus", effective_might(end, "u1") == effective_might(after, "u1") + 2)

    none = completed(board(quick_draw=False), timing="default")
    none_items = none.get("next_timing_state", {}).get("chain", {}).get("items", [])
    check("Q5 without Quick-Draw no trigger is scheduled", none.get("committed") and none_items == [], none_items)
    bad = board()
    bad["objects"]["c1"]["play_timing"] = "default"
    check("V1 Quick-Draw with a default play timing is not a valid state", any("Quick-Draw" in e for e in validate_state(bad)))
    print(f"check_quick_draw: {'FAILED ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
