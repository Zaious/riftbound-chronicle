#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "When I conquer after an attack, if you assigned 5 or more excess damage to enemy
units, you may deal that much to an enemy unit." (Sivir - Ambitious) - "that much" is the excess the trigger's condition
read (package 12's battlefield_control.assigned_excess), noted on the chain item and bound into the program.

  X1 six over    u1 (9) attacks d1 (3): the conquer trigger goes on the Chain noting 6; bound and resolved, a Deal of
                 amount_ref noted_excess deals 6 to an enemy unit
  X2 exactly 5   u1 (8) against d1 (3): noted 5
  X3 not bound   the same Deal in a program with no noted excess is refused by name (only the engine binds it); a program
                 bringing its own noted excess is refused at binding; a chain item with a malformed note is refused
                 when scheduled
  X4 you may     the same Deal carrying optional {decision_ref} (MAYPERFORM, decided as it resolves): performed, 6 dealt;
                 declined, nothing dealt and the program commits

    python skill/scripts/check_set2_excess.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import battlefield_control as BC  # noqa: E402
from check_assigned_excess import decided  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program  # noqa: E402
from resolution_bridge import bind_trigger_event  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, schedule_triggered_items  # noqa: E402
from check_rules_core import fixture as timing_fixture  # noqa: E402

errors: list[str] = []
DEAL = {"op": "deal_damage", "effect_id": "d", "amount_ref": {"kind": "noted_excess"}, "object_id": "foe"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(**extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "tr-conquer-effects", "controller": "p1", "effects": [dict(DEAL)], **extra}


def noted(attacker, defender):
    t, e, problem = decided(attacker, defender)
    if problem:
        return problem
    resolved = BC.resolve_battlefield_control(t, e)
    if not resolved.get("committed"):
        return f"control: {resolved.get('reason_code')}"
    items = [i for i in resolved["next_timing_state"]["chain"]["items"] if "tr-conquer" in str(i.get("id"))]
    return items[0].get("noted_excess") if len(items) == 1 else f"items {items}"


def foe_board():
    state = base_state()
    state["objects"]["foe"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 9, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
    state["players"]["p2"]["zones"]["base"].append("foe")
    return state


def main() -> int:
    for label, args, want in (("X1", (9, 3), 6), ("X2", (8, 3), 5)):
        if (got := noted(*args)) != want:
            fail(label, f"the chain item noted {got!r}, not {want}")
    bound, refusal = bind_trigger_event(program(), {"id": "tr-conquer", "noted_excess": 6})
    if refusal is not None:
        fail("X1", f"binding refused: {refusal}")
    else:
        done = apply_program(foe_board(), bound)
        if not done.get("committed") or done["next_state"]["objects"]["foe"]["damage"] != 6:
            fail("X1", f"the Deal of 'that much': {done.get('reason') or done.get('errors') or done['next_state']['objects']['foe']['damage']}")
    done = apply_program(foe_board(), program())
    if done.get("committed"):
        fail("X3", "a Deal of 'that much' with nothing noted committed")
    from effect_ir import hash_value
    may, refusal = bind_trigger_event(program(effects=[{**DEAL, "optional": {"decision_ref": "may"}}]),
                                      {"id": "tr-conquer", "noted_excess": 6})
    for answer, want in ((True, 6), (False, 0)):
        board = foe_board()
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(board), "decisions": [
            {"decision_id": "may", "stage": "resolution", "kind": "optional_choice", "controller": "p1", "value": answer}]}
        done = apply_program(board, may, decisions=decisions) if refusal is None else {}
        if not done.get("committed") or done["next_state"]["objects"]["foe"]["damage"] != want:
            fail("X4", f"answered {answer}: {refusal or done.get('reason') or done.get('errors') or done['next_state']['objects']['foe']['damage']}")
    _, refusal = bind_trigger_event(program(noted_excess=9), {"id": "tr-conquer", "noted_excess": 6})
    if refusal is None or refusal.get("reason") != "effect_program_noted_excess_mismatch":
        fail("X3", f"a program bringing its own excess was bound: {refusal}")
    descriptor = {"trigger_id": "x", "controller": "p1", "source_object": "u1", "controller_order": 0,
                  "effect_program_id": "x-fx", "optional_at_finalize": False, "noted_excess": -1}
    if schedule_triggered_items(timing_fixture(), [descriptor]).get("applied"):
        fail("X3", "a negative noted excess was scheduled")
    if errors:
        print("FAILED: set 2 noted excess")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'that much' after an excess-damage conquer is the excess its condition read (6, 5), noted on the chain item "
          "and bound only by the engine; with none bound, the Deal is refused by name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
