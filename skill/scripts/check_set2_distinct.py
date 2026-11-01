#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "another" across a card's own two choices - "Give a unit +2 [M] this turn and
another unit -2 [M] this turn." (Defiant Dance), "Kill a friendly unit. If you do, give +[M] equal to its Might to another
friendly unit this turn." (Deathgrip). The second target is a targeting restriction on the first (Core 355.9.b): it is a
different object.

  P  play       two different units chosen - committed, and resolved each gets its own change (+2 on one, -2 on the
                other); the same unit chosen for both - refused at play (target_not_distinct), nothing on the Chain
  T  trigger    the same restriction on a triggered ability, checked as it is finalized (the same check, its own stage):
                the same unit twice - refused; two different - finalized
  V  shape      distinct_from that is not a list, names its own decision, or names no target of the program - refused

    python skill/scripts/check_set2_distinct.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_move_destination_at_choice import envelope, play, resolve, target, trig_program, trigger_board  # noqa: E402
from effect_ir import effective_might, validate_program  # noqa: E402
from resolution_bridge import finalize_trigger, program_hash  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def T(ref, **extra):
    return {"decision_ref": ref, "chosen_zone_class": "board", "kind": "unit", **extra}


DANCE = [{"op": "modify_might", "effect_id": "up", "amount": 2, "duration": "this_turn", "source": "$chain_item",
          "target": T("t")},
         {"op": "modify_might", "effect_id": "down", "amount": -2, "duration": "this_turn", "source": "$chain_item",
          "target": T("t-2", distinct_from=["t"])}]


def board() -> dict:
    state = base_state()
    p1 = state["players"]["p1"]["zones"]
    p1["main_deck"].remove("c1")
    p1["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return settle_contested(state)


def main() -> int:
    # P
    state = board()
    if problems := validate_program({"schema_version": "riftbound-effect-program.v1", "ruleset": {"core": "x"},
                                     "program_id": "p", "controller": "p1", "effects": copy.deepcopy(DANCE)}):
        if any("distinct_from" in p for p in problems):
            fail("P", f"the program is refused: {problems}")
    played = play(state, DANCE, [target(state, "play_declaration", "t", "u1"), target(state, "play_declaration", "t-2", "u2")])
    if not played.get("committed"):
        fail("P", f"two different units refused: {played.get('reason_code') or played.get('reason')}")
    else:
        done = resolve(played["next_effect_state"], DANCE)
        after = done.get("next_effect_state") if done.get("committed") else None
        if after is None or (effective_might(after, "u1"), effective_might(after, "u2")) != (5, 2):
            fail("P", f"resolved: {(effective_might(after, 'u1'), effective_might(after, 'u2')) if after else done.get('reason')}, "
                      f"not (5, 2)")
    same = play(state, DANCE, [target(state, "play_declaration", "t", "u1"), target(state, "play_declaration", "t-2", "u1")])
    if same.get("committed") or same.get("reason_code") != "target_not_distinct":
        fail("P", f"the same unit for both: {same.get('committed')} {same.get('reason_code')}, not refused target_not_distinct")
    # T
    for label, second, want in (("the same unit twice", "c1", False), ("two different", "u1", True)):
        program = trig_program([{**DANCE[0], "target": T("t")}, {**DANCE[1]}], "c1-dance")
        timing, effect_state = trigger_board(program, optional=False)
        entries = [target(effect_state, "trigger_finalization", "t", "c1"),
                   target(effect_state, "trigger_finalization", "t-2", second)]
        got = finalize_trigger(timing, effect_state, {program["program_id"]: program}, envelope(effect_state, entries))
        ok = bool(got.get("committed")) and not got.get("removed")
        if ok != want:
            fail("T", f"{label}: finalized {ok} ({got.get('reason_code') or got.get('reason')}), not {want}")
    # V
    for label, sel in (("not a list", T("t-2", distinct_from="t")), ("its own decision", T("t-2", distinct_from=["t-2"])),
                       ("no such target", T("t-2", distinct_from=["zz"]))):
        bad = copy.deepcopy(DANCE)
        bad[1]["target"] = sel
        problems = validate_program({"schema_version": "riftbound-effect-program.v1", "ruleset": {"core": "x"},
                                     "program_id": "p", "controller": "p1", "effects": bad})
        if not any("distinct_from" in p for p in problems):
            fail("V", f"{label}: validated ({problems[:2]})")
    if errors:
        print("FAILED: set 2 distinct targets")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'another' across a card's own choices is a different object (355.9.b) - two different units commit and each "
          "gets its own change, the same one is refused at play and at a trigger's finalization; malformed shapes refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
