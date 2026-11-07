#!/usr/bin/env python3
"""Regression gate: "While I'm at a battlefield, opponents can't gain points." (set 2 package A2: Tianna Crownguard). A
printed static (opponents_cant_gain_points: at_battlefield): while its source is at a Battlefield with its text active,
its controller's opponents gain no point (Core 054.1: can't beats can).

  P1  tianna (p1's) at bf1: p2 holds bf2 - the battlefield is scored (the ledger) but p2's points stay
  P2  the same with tianna in p1's Base: p2 gains the point
  P3  p1 itself is not stopped: p1 scores bf2 and gains the point
  P4  a gain_point instruction for p2 while tianna is at bf1: nothing gained (no_op, prohibited_by tianna)
  V   another value of the field does not validate
  G   the printed line lowers to exactly that field
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from battlefield_control import score_battlefield  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402

TEXT = "While I'm at a battlefield, opponents can't gain points."


def scene(at_battlefield=True):
    s = base_state()
    s["mode"] = {"victory_score": 8}
    s["objects"]["tianna"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "opponents_cant_gain_points": "at_battlefield"}
    if at_battlefield:
        s["battlefields"]["bf1"]["objects"].append("tianna")
        s["battlefields"]["bf1"]["controller"] = "p1"
    else:
        s["players"]["p1"]["zones"]["base"].append("tianna")
    s["battlefields"]["bf2"] = {"controller": None, "objects": []}
    return settle_contested(s)


def score(state, player):
    state = copy.deepcopy(state)
    state["battlefields"]["bf2"]["controller"] = player
    after, record, _ = score_battlefield(state, player, "bf2", "hold", state.get("turn_id", "turn-0"))
    return after, record


def main() -> int:
    errors: list[str] = []
    s = scene()
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    after, record = score(s, "p2")
    if after["players"]["p2"].get("points", 0) != 0 or record.get("gain") != "prohibited" \
            or "bf2" not in (after["players"]["p2"].get("scored_this_turn") or {}).get(s.get("turn_id", "turn-0"), []):
        errors.append(f"P1: p2 points {after['players']['p2'].get('points', 0)}, record {record}")
    after, record = score(scene(at_battlefield=False), "p2")
    if after["players"]["p2"].get("points", 0) != 1:
        errors.append(f"P2: tianna in the Base, p2 has {after['players']['p2'].get('points', 0)} point(s)")
    after, record = score(s, "p1")
    if after["players"]["p1"].get("points", 0) != 1:
        errors.append(f"P3: p1 has {after['players']['p1'].get('points', 0)} point(s)")
    done = IR.apply_program(s, {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
                                "program_id": "gp", "controller": "p2",
                                "effects": [{"op": "gain_point", "effect_id": "gp", "player": "p2", "amount": 1}]})
    trace = (done.get("trace") or [{}])[0]
    if not done.get("committed") or done["next_state"]["players"]["p2"].get("points", 0) != 0 \
            or trace.get("prohibited_by") != "tianna":
        errors.append(f"P4: {done.get('reason')} points {done.get('next_state', {}).get('players', {}).get('p2', {}).get('points')} {trace}")
    bad = copy.deepcopy(s)
    bad["objects"]["tianna"]["opponents_cant_gain_points"] = "always"
    if not any("opponents_cant_gain_points" in p for p in IR.validate_state(bad)):
        errors.append("V: another value validated")
    got = CG.compile_clause(TEXT, CG.load_grammar())
    if (got.get("passive") or {}).get("object_fields") != {"opponents_cant_gain_points": "at_battlefield"}:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    if errors:
        print("opponents-can't-gain-points checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("opponents-can't-gain-points checks passed: with the source at a Battlefield an opponent's Score gains no point "
          "(still scored) and its gain_point gains nothing; from the Base, or for its own controller, points are gained; "
          "validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
