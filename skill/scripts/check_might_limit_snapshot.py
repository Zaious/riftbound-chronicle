#!/usr/bin/env python3
"""Regression gate: a limited Might change is remembered, not recomputed.

Core 477.3.b: "When an arithmetic effect from a source that is not a passive
ability has a limitation that applies, it is limited at the time of its
application, and is 'remembered' at that limited level for the duration of its
effect. This process is called 'snapshotting'." Its own example: an effect
giving a Unit "-4 [M] to a min of 1 this turn", choosing a Unit with 2 [M],
generates -1 [M] this turn.

The engine applied the bound afresh on every evaluation of the layers. That
agrees with the rule whenever the board does not move, which is why it read as
correct, and disagrees the moment it does:

    a 2 Might Unit carrying a +3 buff is at 5
    "-4 [M] to a minimum of 1" applies: 5 - 4 = 1, the floor does not bite, so
    the effect is limited to -4 and remembered at -4
    the buff is then removed

    remembered   2 - 4 = -2, referenced as 0 (Core 143.2.b)
    recomputed   the floor bites now, the effect gives -1, the Unit sits at 1

A Unit at 0 Might and a Unit at 1 Might are not the same Unit, and "what is my
Might now" is a question new players ask constantly.

The passive half is the other side of the same rule: a limitation from a
passive ability is NOT snapshotted, and 479.1's worked example depends on two
such effects each changing what the other applies.

What must hold:
  - Riot's own example reproduces: -4 to a min of 1 on a 2 Might Unit gives -1;
  - that -1 survives a later +3, landing the Unit on 4;
  - a -4 taken at 5 Might stays -4 when the buff falls away, landing on 0;
  - a passive limited effect has no snapshot and is recomputed;
  - a change the floor eats entirely leaves no event and no entry (370.1.a);
  - the state schema refuses a passive entry carrying a snapshot, and a
    snapshot with no limitation to snapshot.

    python3 skill/scripts/check_might_limit_snapshot.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from check_effect_ir import base_state, program  # noqa: E402
import effect_ir as IR  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def unit_at(might: int) -> dict:
    state = copy.deepcopy(base_state())
    state["objects"]["u1"].update({"base_might": might, "damage": 0})
    return state


def apply(state: dict, effect: dict) -> dict:
    result = IR.apply_program(state, program("p", effect))
    if not result.get("committed"):
        raise AssertionError(f"{effect['effect_id']} did not commit: "
                             f"{result.get('errors') or result.get('reason')}")
    return result


def floor_effect(effect_id: str, amount: int, minimum: int) -> dict:
    return {"op": "modify_might", "effect_id": effect_id, "object_id": "u1", "amount": amount,
            "minimum": minimum, "duration": "this_turn", "source": effect_id}


def buff_effect(effect_id: str, amount: int) -> dict:
    return {"op": "modify_might", "effect_id": effect_id, "object_id": "u1", "amount": amount,
            "duration": "this_turn", "source": effect_id}


def entry_named(state: dict, name: str) -> dict | None:
    return next((e for e in state.get("continuous_effects") or []
                 if e.get("source", {}).get("name") == name), None)


def main() -> int:
    failures: list[str] = []

    # --- Riot's own example, verbatim ---------------------------------------
    result = apply(unit_at(2), floor_effect("stupefy", -4, 1))
    state = result["next_state"]
    recorded = result["trace"][0].get("amount")
    if recorded != -1:
        failures.append(f"'-4 to a min of 1' on a 2 Might Unit generated {recorded}, "
                        f"and 477.3.b's own example says -1")
    if IR.effective_might(state, "u1") != 1:
        failures.append(f"the Unit is at {IR.effective_might(state, 'u1')}, expected 1")

    # --- the -1 is remembered through a later increase ----------------------
    after = apply(state, buff_effect("buff", 3))["next_state"]
    if IR.effective_might(after, "u1") != 4:
        failures.append(f"after a later +3 the Unit is at {IR.effective_might(after, 'u1')}; the "
                        f"remembered -1 gives 2 + 3 - 1 = 4, recomputing gives 1 (477.3.b)")

    # --- a -4 taken at 5 stays -4 when the buff falls away -------------------
    state = apply(unit_at(2), buff_effect("buff", 3))["next_state"]
    if IR.effective_might(state, "u1") != 5:
        failures.append("the fixture did not reach 5 Might; the rest of this case means nothing")
    state = apply(state, floor_effect("stupefy", -4, 1))["next_state"]
    entry = entry_named(state, "stupefy")
    if not entry or entry["value"].get("snapshot_amount") != -4:
        failures.append(f"the effect was not snapshotted at -4: {entry and entry['value']}")
    state["continuous_effects"] = [e for e in state["continuous_effects"]
                                   if e["source"]["name"] != "buff"]
    got = IR.effective_might(state, "u1")
    if got != 0:
        failures.append(f"with the buff gone the Unit is at {got}; the remembered -4 gives 2 - 4 = "
                        f"-2, read as 0 (143.2.b, 477.3.b). Recomputing the bound gives 1")

    # --- a passive limitation is NOT snapshotted ----------------------------
    passive = unit_at(2)
    passive["continuous_effects"] = [{
        "effect_id": "passive-floor", "kind": "might_arithmetic",
        "source": {"object": "u1", "identity": None, "name": "passive"},
        "affects": {"scope": "object", "object": "u1", "identity": "u1@0"},
        "layer": "arithmetic", "sublayer": "decrease", "timestamp": 0,
        "value": {"amount": -4, "mode": "delta", "minimum": 1},
        "duration": {"kind": "permanent"}, "passive": True,
    }]
    if IR.validate_state(passive):
        failures.append(f"the passive fixture is not a valid state: {IR.validate_state(passive)[:1]}")
    if IR.effective_might(passive, "u1") != 1:
        failures.append(f"a passive '-4 to a min of 1' on a 2 Might Unit gave "
                        f"{IR.effective_might(passive, 'u1')}, expected 1")
    lifted = copy.deepcopy(passive)
    lifted["objects"]["u1"]["base_might"] = 9
    if IR.effective_might(lifted, "u1") != 5:
        failures.append(f"a passive limitation was not recomputed on a 9 Might Unit: got "
                        f"{IR.effective_might(lifted, 'u1')}, expected 5 (477.3.b: a passive "
                        f"ability does not snapshot)")

    # --- 370.1.a still holds: eaten entirely, so no event and no entry ------
    result = apply(unit_at(3), floor_effect("stupefy", -9, 3))
    if result["trace"][0].get("outcome") != "no_op":
        failures.append("a change the floor eats entirely still produced an event (370.1.a)")
    if result["next_state"].get("continuous_effects"):
        failures.append("a change the floor eats entirely still left a continuous effect")

    # --- the schema refuses the two incoherent shapes ------------------------
    bad_passive = copy.deepcopy(passive)
    bad_passive["continuous_effects"][0]["value"]["snapshot_amount"] = -1
    if not any("snapshot" in e for e in IR.validate_state(bad_passive)):
        failures.append("a passive entry carrying a snapshot_amount was accepted (477.3.b)")
    bare = copy.deepcopy(passive)
    bare["continuous_effects"][0]["passive"] = False
    bare["continuous_effects"][0]["value"] = {"amount": -1, "mode": "delta", "snapshot_amount": -1}
    if not any("snapshot" in e for e in IR.validate_state(bare)):
        failures.append("a snapshot_amount with no limitation to snapshot was accepted")

    print("might limit snapshotting (Core 477.3.b, 477.3.e.2.b, 143.2.b, 370.1.a)")
    print("  Riot's example reproduces: -4 to a min of 1 on a 2 Might Unit generates -1")
    print("  the limited amount is remembered: a later +3 gives 4, a buff falling away gives 0")
    print("  a passive limitation is recomputed instead, and carries no snapshot")
    for failure in failures:
        print("\nFAILED: " + failure)
    if failures:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
