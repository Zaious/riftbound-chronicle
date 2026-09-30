#!/usr/bin/env python3
"""Regression gate for "Spend any number of buffs." as an instruction, and a count read off it
(package 6, 2026-09-27).

"When you play me, spend any number of buffs. For each buff spent, channel 1 rune exhausted." The
first instruction is no cost: its player chooses, as it resolves, any number of the Units they
control that have a buff (Core 702.2.b, 702.2.b.1, 702.2.b.2); buffs are counters, not targets
(Core 704.1), so the choice is made on resolution (355.17). Each chosen Unit loses its buff. How many
it spent is its receipt; "for each buff spent" is a linked later instruction that reads it (Core
359.3.e.14) - count_per {kind: linked_applied_count, effect_id}.

Must hold (each has a failing case below):
  choose     with Units to spend from, the player is asked (any number, zero included); with none,
             nothing is asked and nothing is spent
  spend      exactly the chosen Units lose their buff; an enemy's buffed Unit, a Unit with no buff,
             and a decision by the wrong player or at the wrong stage are refused
  count      the linked Channel (or Draw) runs its printed count times the number spent; none spent,
             it does nothing
  shapes     the count reads only an earlier spend_buffs, only for channel_rune / draw; spend_buffs
             carries only its player and its decision
  events     one buff_spent per Unit, and the Channel's own events; coverage complete
Every fixture is synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402


def unit(owner, *, buffed=False):
    obj = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
           "exhausted": False}
    if buffed:
        obj["buffed"] = True
    return obj


def state(*, p1_buffed=("u1", "u5"), p2_buffed=("u2",)):
    s = base_state()
    s["objects"]["u5"] = unit("p1")
    s["objects"]["u6"] = unit("p1")
    s["players"]["p1"]["zones"]["base"] += ["u5"]
    s["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u6"]}
    for object_id in p1_buffed + p2_buffed:
        s["objects"][object_id]["buffed"] = True
    s["players"]["p1"]["zones"]["rune_deck"] = ["r1", "r2", "r3"]
    for rune in ("r2", "r3"):
        s["objects"][rune] = {"owner": "p1", "controller": "p1", "kind": "rune", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    return s


def program(*, reader="channel_rune", count=1, per="sb", extra=None):
    second = ({"op": "channel_rune", "effect_id": "ch", "player": "p1", "count": count, "entry_state": "exhausted"}
              if reader == "channel_rune" else {"op": "draw", "effect_id": "dr", "player": "p1", "count": count})
    if per is not None:
        second["count_per"] = {"kind": "linked_applied_count", "effect_id": per}
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": "spend-then-count", "controller": "p1",
            "effects": [{"op": "spend_buffs", "effect_id": "sb", "player": "p1", "decision_ref": "sb", **(extra or {})}, second]}


def chosen(s, objects, *, controller="p1", stage="resolution"):
    return {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s), "decisions": [
        {"decision_id": "sb", "stage": stage, "kind": "target_selection", "controller": controller, "value": list(objects),
         "selection_identities": {o: IR.object_identity(s, o) for o in objects}}]}


def main() -> int:
    errors: list[str] = []

    # --- the choice ------------------------------------------------------------------------------------
    s = state()
    asked = IR.apply_program(s, program())
    if asked.get("committed") or asked.get("decision_ids") != ["sb"]:
        errors.append(f"with buffed Units the player was not asked what to spend: {asked.get('reason_code')}")
    elif sorted(o["object_id"] for o in (asked.get("choice") or {}).get("options") or []) != ["u1", "u5"]:
        errors.append(f"the candidates are not exactly the player's own buffed Units: {asked.get('choice')}")
    bare = state(p1_buffed=())
    ran = IR.apply_program(bare, program())
    if not ran.get("committed") or [e.get("outcome") for e in ran["trace"]] != ["no_op", "no_op"]:
        errors.append(f"with nothing to spend, the instruction asked or did something: {ran.get('reason_code')} {ran.get('trace')}")

    # --- spending and the count --------------------------------------------------------------------------
    for picked, runes in ((["u1", "u5"], 2), (["u5"], 1), ([], 0)):
        ran = IR.apply_program(s, program(), decisions=chosen(s, picked))
        if not ran.get("committed"):
            errors.append(f"spending {picked} did not commit: {ran.get('reason') or ran.get('errors')}")
            continue
        after = ran["next_state"]
        buffed = sorted(o for o in ("u1", "u2", "u5") if after["objects"][o].get("buffed"))
        if buffed != sorted({"u1", "u5", "u2"} - set(picked)):
            errors.append(f"spending {picked} left buffs on {buffed}")
        channeled = [r for r in ("r1", "r2", "r3") if r in after["players"]["p1"]["zones"]["base"]]
        if len(channeled) != runes or any(not after["objects"][r]["exhausted"] for r in channeled):
            errors.append(f"spending {picked} channeled {channeled}, not {runes} exhausted")
        if ran.get("event_coverage") != "complete" or \
                sum(e["kind"] == "buff_spent" for e in ran.get("events") or []) != len(picked):
            errors.append(f"spending {picked}: events {[e['kind'] for e in ran.get('events') or []]} / {ran.get('event_coverage')}")
    drew = IR.apply_program(s, program(reader="draw", count=1), decisions=chosen(s, ["u1", "u5"]))
    s_hand = len(s["players"]["p1"]["zones"]["hand"])
    if not drew.get("committed") or len(drew["next_state"]["players"]["p1"]["zones"]["hand"]) != s_hand + 2:
        errors.append("a Draw 1 for each buff spent did not draw 2 for two spent")
    twice = IR.apply_program(s, program(count=2), decisions=chosen(s, ["u5"]))
    if not twice.get("committed") or sum(r in twice["next_state"]["players"]["p1"]["zones"]["base"] for r in ("r1", "r2", "r3")) != 2:
        errors.append("a printed count of 2 was not multiplied by the one buff spent")

    # --- refusals ------------------------------------------------------------------------------------------
    for label, decisions in (("an enemy's buffed Unit", chosen(s, ["u2"])), ("a Unit with no buff", chosen(s, ["u6"])),
                             ("the opponent's choice", chosen(s, ["u1"], controller="p2")),
                             ("a play-stage choice", chosen(s, ["u1"], stage="play_declaration"))):
        if IR.apply_program(s, program(), decisions=decisions).get("committed"):
            errors.append(f"spend_buffs accepted {label}")
    stale = chosen(s, ["u1"])
    stale["decisions"][0]["selection_identities"]["u1"] = "u1@7"
    if IR.apply_program(s, program(), decisions=stale).get("committed"):
        errors.append("spend_buffs accepted a stale identity")

    # --- shapes ----------------------------------------------------------------------------------------------
    for label, bad in (("a count read off a later instruction", program(per="ch")),
                       ("a count read off an instruction that is not a spend", program(per="nope")),
                       ("spend_buffs with a target", program(extra={"target": {"decision_ref": "t", "kind": "unit"}})),
                       ("spend_buffs with a count", program(extra={"count": 2}))):
        if not IR.validate_program(bad):
            errors.append(f"validate_program accepted {label}")
    after_draw = program()
    after_draw["effects"].insert(0, {"op": "draw", "effect_id": "d0", "player": "p1", "count": 1})
    after_draw["effects"][2]["count_per"]["effect_id"] = "d0"
    if not IR.validate_program(after_draw):
        errors.append("validate_program accepted a count read off an earlier Draw (only a spend's receipt is a count)")
    other = program()
    other["effects"][1] = {"op": "deal_damage", "effect_id": "dd", "amount": 1, "target": {"decision_ref": "t", "kind": "unit"},
                           "count_per": {"kind": "linked_applied_count", "effect_id": "sb"}}
    if not IR.validate_program(other):
        errors.append("validate_program accepted a linked count on a Deal")
    if IR.validate_program(program()) or IR.validate_program(program(reader="draw")):
        errors.append(f"validate_program refused the well-formed program: {IR.validate_program(program())}")

    # --- through the resolution bridge: a trigger's finalized target, and the spend chosen as it resolves
    from check_trigger_finalization import PROGRAM_ID, TRIGGER, board, choose, enter, to_resolution, program as target_program
    from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program
    combo = target_program()
    combo["effects"] += [{"op": "spend_buffs", "effect_id": "sb", "player": "p1", "decision_ref": "sb"},
                         {"op": "channel_rune", "effect_id": "ch", "player": "p1", "count": 1, "entry_state": "exhausted",
                          "count_per": {"kind": "linked_applied_count", "effect_id": "sb"}}]
    registry = {PROGRAM_ID: combo}
    s = board(with_hash=False)
    s["objects"]["c1"]["play_triggers"][0]["effect_program_hash"] = program_hash(combo)
    s["objects"]["u1"]["buffed"] = True
    timing, s = enter(s)
    finalized = finalize_trigger(timing, s, registry, choose(s, "u2"))
    if not finalized.get("committed"):
        errors.append(f"bridge: the trigger did not finalize: {finalized.get('reason')}")
    else:
        ready = to_resolution(finalized["next_timing_state"])
        dispatched, _ = dispatch_program(registry, ready["chain"]["items"][0])
        done = resolve_with_program(ready, TRIGGER, s, dispatched, engine_decisions=chosen(s, ["u1"]))
        after = done.get("next_effect_state") or {}
        if not done.get("committed") or after["objects"]["u1"].get("buffed") \
                or "r1" not in after["players"]["p1"]["zones"]["base"]:
            errors.append(f"bridge: the resolution-stage spend beside a finalized target was not honoured: "
                          f"{done.get('stage')} {done.get('reason')}")
        again = resolve_with_program(ready, TRIGGER, s, dispatched, engine_decisions=choose(s, "u9", stage="resolution"))
        if again.get("committed") or again.get("reason") != "target_changed_after_finalization":
            errors.append(f"bridge: a target re-chosen at resolution was not refused: {again.get('reason')}")

    if errors:
        print("FAILED: spend any number of buffs")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("spend-buffs checks passed: the player chooses on resolution among the Units they control with a buff, exactly "
          "those lose it, and a linked Channel / Draw counts how many were spent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
