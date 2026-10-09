#!/usr/bin/env python3
"""A player-level Conquer whose Trigger Condition counts units at that battlefield (package 10, Garen - Might of Demacia
(Starter)).

"When you conquer, if you have 4+ units at that battlefield, draw 2." The conditional statement right after the trigger
condition is part of it (Core 383.2.a.1): read as the Conquer is processed, about the Battlefield conquered, and not met
the ability does not trigger. A player-level Conquer Effect fires from any source the player controls where its
abilities work - a Legend in its Legend Zone included (Core 383.4.c.2.b).

The engine's shape: the clause grammar row when_you_conquer_if_you_have_n_units_at_that_battlefield puts
{kind controls_units, count N, location here} on the conquer_triggers descriptor (scope controller);
battlefield_control._score_triggers evaluates it with the scored Battlefield as its object (here) and drops it from the
descriptor it schedules.

  C1 four          p1 conquers bf1 with four of its units there: one descriptor, no condition left on it
  C2 three         three units there: none
  C3 elsewhere     four of p1's units at bf2, three at bf1, bf1 conquered: none (that battlefield, not any)
  C4 theirs        p2's units do not count: two of p1's and three of p2's at bf1: none
  C5 hold          the same board's Hold of bf1: none (a conquer trigger)
  S  shapes        the condition on a unit's own "When I conquer" (scope unit_here), or another location, refused
  G  grammar       the sentence lowers to exactly that descriptor; near misses do not

    python skill/scripts/check_conquer_unit_count.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import battlefield_control as BC  # noqa: E402
import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import validate_state  # noqa: E402

SENTENCE = "When you conquer, if you have 4+ units at that battlefield, draw 2."
CONDITION = {"kind": "controls_units", "count": 4, "location": "here"}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def descriptor(**extra):
    return {"trigger_id": "g-conquer", "controller": "p1", "source_object": "lg", "controller_order": 0,
            "effect_program_id": "g-conquer-effects", "optional_at_finalize": False, "scope": "controller",
            "condition": dict(CONDITION), **extra}


def board(p1_bf1: int, *, p1_bf2: int = 0, p2_bf1: int = 0, desc=None):
    """p1's Legend lg in its Legend Zone with the conquer trigger; bf1 p1's with `p1_bf1` of p1's units and `p2_bf1` of
    p2's; bf2 p1's with `p1_bf2` of p1's units."""
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": []}
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
    for player in ("p1", "p2"):
        # only the units this board counts are on it
        for o in [o for o in state["players"][player]["zones"]["base"] if state["objects"][o].get("kind") == "unit"]:
            state["players"][player]["zones"]["base"].remove(o)
            del state["objects"][o]
    for bf in list(state["battlefields"]):
        for o in [o for o in state["battlefields"][bf].get("objects", []) if state["objects"].get(o, {}).get("kind") == "unit"]:
            state["battlefields"][bf]["objects"].remove(o)
            del state["objects"][o]
    state["objects"]["lg"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "conquer_triggers": [desc or descriptor()]}
    state["players"]["p1"]["zones"].setdefault("legend_zone", []).append("lg")
    n = 0
    for owner, where, count in (("p1", "bf1", p1_bf1), ("p1", "bf2", p1_bf2), ("p2", "bf1", p2_bf1)):
        for _ in range(count):
            n += 1
            oid = f"x{n}"
            state["objects"][oid] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2,
                                     "might_modifiers": [], "damage": 0, "exhausted": False}
            state["battlefields"][where]["objects"].append(oid)
    if p2_bf1:
        state["battlefields"]["bf1"]["contested"] = True
    return state


def scheduled(state, how="conquer"):
    return [d for d in BC._score_triggers(state, "p1", "bf1", how, "turn-1") if d.get("trigger_id") == "g-conquer"]


def main() -> int:
    got = scheduled(board(4))
    if len(got) != 1 or "condition" in got[0]:
        fail("C1 four", got)
    if scheduled(board(3)):
        fail("C2 three", scheduled(board(3)))
    if scheduled(board(3, p1_bf2=4)):
        fail("C3 elsewhere", "counted another battlefield's units")
    if scheduled(board(2, p2_bf1=3)):
        fail("C4 theirs", "counted p2's units")
    if scheduled(board(4), how="hold"):
        fail("C5 hold", "a Hold scheduled the conquer trigger")
    for label, desc in (("unit_here", descriptor(scope="unit_here")),
                        ("location", descriptor(condition={**CONDITION, "location": "battlefield"}))):
        problems = validate_state(board(4, desc=desc))
        if not any("conquer" in p.lower() or "condition" in p.lower() for p in problems):
            fail("S shapes", f"{label} accepted: {problems[:2]}")
    good = validate_state(board(4))
    if good:
        fail("S shapes", f"the valid shape refused: {good[:2]}")
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    rows = ((lowered.get("passive") or {}).get("object_fields") or {}).get("conquer_triggers") or []
    if lowered.get("production_id") != "when_you_conquer_if_you_have_n_units_at_that_battlefield" or len(rows) != 1 \
            or rows[0].get("condition") != CONDITION or rows[0].get("scope") != "controller":
        fail("G grammar", f"{lowered.get('production_id')} {rows}")
    for near in ("When you conquer here, if you have 4+ units here, draw 2.",
                 "When you hold, if you have 4+ units at that battlefield, draw 2."):
        other = CG.compile_clause(near, CG.load_grammar())
        if other.get("production_id") == "when_you_conquer_if_you_have_n_units_at_that_battlefield":
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: conquer unit-count checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'When you conquer, if you have N+ units at that battlefield' triggers only when the conquered Battlefield "
          "holds N of the player's units, read as the Conquer is processed (C1-C5, S, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
