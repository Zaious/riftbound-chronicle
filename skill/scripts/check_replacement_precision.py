#!/usr/bin/env python3
"""Regression gate: a Replacement Effect sees the event the rules describe.

Two ways the engine used to offer a replacement an event the rules do not have.

Core 355.6 - being CHOSEN. A replacement worded "if a spell or ability that
chooses me would stun me…" only applies when the incoming effect chose that
object. An effect that reaches it by back-reference - "move an enemy unit, then
Stun it" - never chose it, and the replacement must not fire. The engine matched
on the event's op alone, so it fired.

Core 370.1.a - an event is a moment that RESULTS from an action. An action that
changes nothing leaves no event, so there is nothing to replace: "-1 Might, to a
minimum of 1" on a 1 Might Unit moves nothing, and a Stun on an already Stunned
Unit is the no_op of 423.2. The engine offered both.

What must hold:
  - a replacement with `requires_chosen` applies when the effect says it chose
    the object, and does not when the effect is silent or says otherwise;
  - a replacement without `requires_chosen` is unaffected - every existing one
    keeps working;
  - a Might change floored to zero offers no replacement, while the same
    replacement still applies to a change that moves something;
  - a replacement that answers to "-Might" sees a decrease and not an increase,
    and the sign that counts is the one left after the card's own floor;
  - a Stun on an already Stunned Unit offers no replacement;
  - an "[Empowered][>] …" replacement is off while its source is not Empowered,
    and comes back when it is Empowered again (Core 828.1.c).

    python3 skill/scripts/check_replacement_precision.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from check_effect_ir import base_state  # noqa: E402
import effect_ir as IR  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def stun_replacement(requires_chosen: bool | None) -> dict:
    """Gangplank's shape: if a spell or ability that chooses me would stun me,
    give me +3 Might this turn instead."""
    spec = {
        "replacement_id": "gp-stun", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "stun", "optional": False, "uses_remaining": None,
        "target_object_id": "u1",
        "replacement_effects": [{"op": "modify_might", "effect_id": "gp-plus", "object_id": "$affected",
                                 "amount": 3, "duration": "this_turn", "source": "u1"}],
    }
    if requires_chosen is not None:
        spec[IR.REQUIRES_CHOSEN_FIELD] = requires_chosen
    return spec


def might_replacement() -> dict:
    return {
        "replacement_id": "gp-might", "controller": "p1", "source_object": "u1",
        "mode": "replace_with", "event_op": "modify_might", "optional": False, "uses_remaining": None,
        "target_object_id": "u1",
        "replacement_effects": [{"op": "modify_might", "effect_id": "gp-plus", "object_id": "$affected",
                                 "amount": 3, "duration": "this_turn", "source": "u1"}],
    }


def main() -> int:
    failures: list[str] = []
    base = base_state()

    # --- Core 355.6: chosen, or reached by back-reference -------------------
    state = copy.deepcopy(base)
    state["replacement_effects"] = [stun_replacement(True)]
    chose = {"op": "stun", "effect_id": "s", "object_id": "u1", IR.CHOSEN_FIELD: True}
    did_not = {"op": "stun", "effect_id": "s", "object_id": "u1"}
    if not IR._applicable_replacements(state, chose):
        failures.append("a replacement requiring a choice did not apply when the effect chose the object (355.6)")
    if IR._applicable_replacements(state, did_not):
        failures.append("a replacement requiring a choice applied to an effect that never chose the object (355.6)")
    if IR._applicable_replacements(state, {**did_not, IR.CHOSEN_FIELD: False}):
        failures.append("an effect that says it did not choose still matched a replacement requiring a choice")

    # A replacement that does not ask about choosing is untouched.
    plain = copy.deepcopy(base)
    plain["replacement_effects"] = [stun_replacement(None)]
    if not IR._applicable_replacements(plain, did_not):
        failures.append("an existing replacement stopped applying; requires_chosen must be opt-in")

    # --- Core 370.1.a: nothing changes, so there is no event ----------------
    floored = copy.deepcopy(base)
    floored["replacement_effects"] = [might_replacement()]
    floored["objects"]["u1"]["base_might"] = 1
    minus_one_floored = {"op": "modify_might", "effect_id": "m", "object_id": "u1",
                         "amount": -1, "minimum": 1, "duration": "this_turn", "source": "stupefy"}
    if IR._applicable_replacements(floored, minus_one_floored):
        failures.append("a Might change floored to zero still offered a replacement (370.1.a)")
    moves = {"op": "modify_might", "effect_id": "m", "object_id": "u1",
             "amount": -1, "duration": "this_turn", "source": "stupefy"}
    if not IR._applicable_replacements(floored, moves):
        failures.append("a Might change that does move something no longer offers its replacement")

    bigger = copy.deepcopy(floored)
    bigger["objects"]["u1"]["base_might"] = 5
    if not IR._applicable_replacements(bigger, minus_one_floored):
        failures.append("the same floored wording on a 5 Might Unit does move it, and must offer the replacement")

    # --- Core 477: "-Might" is a decrease, not every Might change -----------
    signed = copy.deepcopy(base)
    signed["objects"]["u1"]["base_might"] = 5
    signed["replacement_effects"] = [{**might_replacement(), IR.MIGHT_DIRECTION_FIELD: "decrease"}]
    down = {"op": "modify_might", "effect_id": "m", "object_id": "u1",
            "amount": -1, "duration": "this_turn", "source": "stupefy"}
    up = {**down, "amount": 1}
    if not IR._applicable_replacements(signed, down):
        failures.append("a replacement worded '-Might' did not see a decrease (477)")
    if IR._applicable_replacements(signed, up):
        failures.append("a replacement worded '-Might' fired on a buff (477)")
    # A decrease the card's own floor turns into an increase is an increase.
    if IR._applicable_replacements(signed, {**down, "amount": -9, "minimum": 7}):
        failures.append("the direction was read before the floor, not after (477, 370.1.a)")

    stunned = copy.deepcopy(base)
    stunned["replacement_effects"] = [stun_replacement(None)]
    stunned["objects"]["u1"]["stunned"] = True
    if IR._applicable_replacements(stunned, did_not):
        failures.append("a Stun on an already Stunned Unit still offered a replacement (423.2, 370.1.a)")

    # --- Core 828.1.c: an Empowered Ability lasts as long as the status ------
    dependent = copy.deepcopy(base)
    dependent["replacement_effects"] = [{**stun_replacement(None), IR.DEPENDENT_ON_EMPOWERED_FIELD: True}]
    if IR._applicable_replacements(dependent, did_not):
        failures.append("an Empowered Ability applied while its source was not Empowered (828.1.c)")
    dependent["objects"]["u1"]["empowered"] = True
    if not IR._applicable_replacements(dependent, did_not):
        failures.append("an Empowered Ability did not apply while its source was Empowered (828.1.c)")
    # Switched off is not gone: pruning must leave it in place.
    off = copy.deepcopy(dependent)
    off["objects"]["u1"]["empowered"] = False
    IR._prune_inactive_replacements(off)
    if not off["replacement_effects"]:
        failures.append("a Disempowered source's Empowered Ability was pruned away; re-Empowering could never restore it")

    print("replacement precision (Core 355.6, 370.1.a, 423.2)")
    print(f"  fields: {IR.CHOSEN_FIELD} on the effect, {IR.REQUIRES_CHOSEN_FIELD} on the replacement")
    print("  chosen/not-chosen split=ok; floored Might offers nothing; already-Stunned offers nothing")
    print(f"  {IR.MIGHT_DIRECTION_FIELD}: a '-Might' replacement sees the decrease only, after the floor")
    print(f"  {IR.DEPENDENT_ON_EMPOWERED_FIELD}: an Empowered Ability is off without the status, and not pruned")
    for failure in failures:
        print("\nFAILED: " + failure)
    if failures:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
