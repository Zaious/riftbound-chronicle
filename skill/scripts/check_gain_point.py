#!/usr/bin/env python3
"""Regression gate: "you score 1 point" gains a Point and Scores no Battlefield.

Core 471.1 has a Score do two things: the player Gains up to one Point, and
Score abilities trigger at the Battlefield that Scored (471.2). The three cards
that say "you score 1 point" name no Battlefield -

    Ahri - Alluring          "When I hold, you score 1 point."
    Yasuo - Windrider        "The third time I move in a turn, you score 1 point."
    Tryndamere - Barbarian   "When I conquer after an attack, if you assigned 5 or
                              more excess damage to enemy units, you score 1 point."

- and in the first and third the Battlefield has already been Scored by the Hold
or the Conquer that triggered the ability. The point the card gives is an
ADDITIONAL one. So the op is the Gain alone, and it is named gain_point rather
than score so that nobody reads it as running 471.2.

471.1.a.1 settles the other half: "points Gained from sources that are not
Conquer are not beholden to these restrictions", so the Final Point conditions
of 471.1.b do not reach it, and 470's once-per-Battlefield limit has no
Battlefield to count.

What must hold:
  - the point lands on the named player and nobody else;
  - the trace says the source is not Conquer and no Battlefield was Scored,
    because those two facts are what keep 470, 471.1.b and 471.2 out;
  - naming a battlefield is refused - that would read as a Score;
  - a zero or negative amount is refused;
  - the op emits its own event kind, so it is never event_kind_unknown.

Deliberately NOT covered: whether the new total ends the game. That is the
victory procedure's business (Core 196), and an effect that decided a winner
from the inside would be the wrong shape.

    python3 skill/scripts/check_gain_point.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from check_effect_ir import base_state, program  # noqa: E402
import effect_ir as IR  # noqa: E402
import game_events  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def gain(state: dict, **extra) -> dict:
    effect = {"op": "gain_point", "effect_id": "gp", "player": "p1", "amount": 1, **extra}
    return IR.apply_program(state, program("g", effect))


def main() -> int:
    failures: list[str] = []

    result = gain(copy.deepcopy(base_state()))
    if not result.get("committed"):
        failures.append(f"a plain point gain did not commit: "
                        f"{result.get('errors') or result.get('reason')}")
    else:
        after = result["next_state"]["players"]
        if after["p1"].get("points") != 1:
            failures.append(f"p1 has {after['p1'].get('points')} point(s), expected 1")
        if after["p2"].get("points", 0) != 0:
            failures.append("the point reached a player the effect did not name")
        row = result["trace"][0]
        if row.get("source_is_conquer") is not False:
            failures.append("the trace does not record that the source is not Conquer; that is "
                            "the fact 471.1.a.1 turns on")
        if row.get("scored_a_battlefield") is not False:
            failures.append("the trace does not record that no Battlefield was Scored; that is "
                            "what keeps 470 and 471.2 out")
        if "Core 471.1.a.1" not in (row.get("rule_locators") or []):
            failures.append(f"the trace cites {row.get('rule_locators')}, without 471.1.a.1")

    # points accumulate rather than replace
    twice = gain(gain(copy.deepcopy(base_state()))["next_state"], amount=2)
    if twice.get("committed") and twice["next_state"]["players"]["p1"]["points"] != 3:
        failures.append(f"1 then 2 gave {twice['next_state']['players']['p1']['points']}, expected 3")

    # --- the shapes that must be refused ------------------------------------
    named = gain(copy.deepcopy(base_state()), battlefield="bf1")
    if named.get("valid") is not False:
        failures.append("naming a battlefield was accepted; that would read as a Battlefield "
                        "being Scored, which runs 471.2")
    for amount in (0, -1):
        bad = gain(copy.deepcopy(base_state()), amount=amount)
        if bad.get("valid") is not False:
            failures.append(f"an amount of {amount} was accepted")
    unknown = gain(copy.deepcopy(base_state()), player="p9")
    if unknown.get("valid") is not False and unknown.get("committed"):
        failures.append("an unknown player was accepted")

    # --- it has a semantic event of its own ---------------------------------
    if game_events.OP_PRIMARY.get("gain_point") != "point_gained":
        failures.append("gain_point has no primary event kind; it would be event_kind_unknown")
    if "point_gained" not in game_events.EVENT_KINDS:
        failures.append("point_gained is not in the event catalogue")

    print("gain_point (Core 471.1, 471.1.a.1, 471.2, 470)")
    print("  the Gain half of a Score, with no Battlefield: the trace records both facts")
    print("  a named battlefield, a zero amount and a negative amount are all refused")
    print("  NOT covered: whether the new total ends the game (Core 196, the victory procedure)")
    for failure in failures:
        print("\nFAILED: " + failure)
    if failures:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
