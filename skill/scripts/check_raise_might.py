#!/usr/bin/env python3
"""A Unit's Might raised, this turn, to another Unit's (package 9, Convergent Mutation).

"Choose a friendly unit. This turn, increase its Might to the Might of another friendly unit." GPT 2026-10-06
(PACKAGE9_INVENTORY section 7, ruling 7): two different targets chosen at play; both Mights read at resolution; an
increase only; it lasts this turn.

The engine's shape: raise_might_to_match {units [raised, reference], duration this_turn} - a composite op: both Units
revalidated, both Mights read once, and when the reference's is higher one ordinary modify_might of the difference
on the first (so replacements see it); nothing otherwise (370.1.a).

  R1 raised       Might 3 raised to 5: the first Unit now 5 this turn, the second unchanged, one modify_might
  R2 lower        the reference's Might 1: nothing changes (no_op), never a decrease
  R3 equal        equal Mights: no_op
  R4 read now     the reference's Might changed after the choice (+2 first): the raise reads the Might at resolution
  R5 same twice   one Unit in both slots is skipped at resolution (at play the pair's slots are refused as
                  target_slots_not_distinct by play_transaction for any `units` pair - check_target_counts.py)
  R6 illegal      the reference gone from the board: the whole instruction skipped (359.3.e.5)
  R7 this turn    the turn's Expiration Step ends the raise
  S  shapes       one unit, an amount, a lasting duration - each refused

    python skill/scripts/check_raise_might.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, effective_might, validate_program, validate_state  # noqa: E402
from resolution_bridge import run_expiration_step  # noqa: E402

errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner: str, might: int) -> dict:
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board() -> dict:
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["u1"]["damage"] = 0
    for oid, might in (("u5", 5), ("u6", 1), ("u7", 3)):
        state["objects"][oid] = unit("p1", might)
        state["players"]["p1"]["zones"]["base"].append(oid)
    assert not validate_state(state), validate_state(state)
    return state


def raise_(a: str, b: str) -> dict:
    return program("convergent", {"op": "raise_might_to_match", "effect_id": "raise", "duration": "this_turn",
                                  "source": "convergent", "units": [{"object_id": a, "chosen_zone_class": "board"}, {"object_id": b, "chosen_zone_class": "board"}]})


def outcome(result: dict) -> str | None:
    return (result.get("trace") or [{}])[0].get("outcome") if result.get("committed") else result.get("reason") or "refused"


def main() -> int:
    s = board()
    m = lambda st, o: effective_might(st, o)
    # R1
    r1 = apply_program(s, raise_("u1", "u5"))
    if outcome(r1) != "expanded" or m(r1["next_state"], "u1") != 5 or m(r1["next_state"], "u5") != 5:
        fail("R1 raised", f"{outcome(r1)} u1={r1.get('next_state') and m(r1['next_state'], 'u1')}")
    elif [e["op"] for e in r1["trace"]] != ["raise_might_to_match", "modify_might"] or r1["trace"][1].get("amount") != 2:
        fail("R1 one modify_might", [(e["op"], e.get("amount")) for e in r1["trace"]])
    # R2, R3
    for label, other in (("R2 lower", "u6"), ("R3 equal", "u7")):
        r = apply_program(s, raise_("u1", other))
        if outcome(r) != "no_op" or m(r["next_state"], "u1") != 3:
            fail(label, f"{outcome(r)} u1={r.get('next_state') and m(r['next_state'], 'u1')}")
    # R4: the reference's Might read at resolution
    bumped = apply_program(s, program("bump", {"op": "modify_might", "effect_id": "b", "object_id": "u7", "amount": 2,
                                               "duration": "this_turn", "source": "bump"}))["next_state"]
    r4 = apply_program(bumped, raise_("u1", "u7"))
    if m(r4["next_state"], "u1") != 5:
        fail("R4 read now", f"u1 is {m(r4['next_state'], 'u1')}, not the reference's current 5")
    # R5: same unit twice at resolution
    r5 = apply_program(s, raise_("u1", "u1"))
    if outcome(r5) != "ignored_illegal_target" or (r5["trace"][0].get("invalid_targets") or [{}])[0].get("reason") != "same_unit_twice":
        fail("R5 same twice", outcome(r5))
    # R6: the reference gone
    gone = copy.deepcopy(s)
    gone["players"]["p1"]["zones"]["base"].remove("u5")
    gone["players"]["p1"]["zones"]["trash"].append("u5")
    r6 = apply_program(gone, raise_("u1", "u5"))
    if outcome(r6) != "ignored_illegal_target" or m(r6["next_state"], "u1") != 3:
        fail("R6 illegal", outcome(r6))
    # R7: this turn
    if r1.get("committed"):
        timing = fixture()
        timing.update({"phase": "ending", "priority": None, "ending_step": {"status": "triggers_scheduled", "turn_id": "turn-3"}})
        expired = run_expiration_step(timing, r1["next_state"])
        after = (expired or {}).get("next_effect_state")
        if after is None or m(after, "u1") != 3:
            fail("R7 this turn", f"{expired and expired.get('reason')} u1={after and m(after, 'u1')}")
    # S
    good = raise_("u1", "u5")
    if validate_program(good):
        fail("S shapes", f"the shape is refused: {validate_program(good)}")
    e = good["effects"][0]
    for label, bad in (("one unit", {**e, "units": [{"object_id": "u1", "chosen_zone_class": "board"}]}), ("an amount", {**e, "amount": 2}),
                       ("lasting", {**e, "duration": "persistent"})):
        if not validate_program({**good, "effects": [bad]}):
            fail("S shapes", f"{label} was accepted")
    if errors:
        print("FAILED: raise Might checks")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("OK: a Unit's Might is raised this turn to another's, read once at resolution, never lowered (R1-R7, S)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
