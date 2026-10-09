#!/usr/bin/env python3
"""Targets that meet a requirement as a group (package 10, Facebreaker; the shape Fox-Fire's ruling names, GPT
2026-10-08 ruling 5).

Some cards name a group of targets with a requirement the group meets as a whole: "a friendly unit and an enemy unit
at the same battlefield", "any number of units at a battlefield with total Might 4 or less". As the targets are chosen,
the group must meet it (Core 355.11.a); a group that does not is refused at play by name. As the instruction resolves,
targets that became illegal on their own drop out as always (359.3.e); if those still legal no longer meet the group
requirement together, their controller keeps a subset of them that does (355.11.b) - chosen then, never adding a new
object - and the rest are unaffected.

  A1 one each      a friendly and an enemy unit at bf1: both Stunned
  A2 apart         the friendly at bf1 and the enemy at bf2: refused at play (target_group_requirement_failed)
  A3 two friendly  two friendly units at bf1: refused at play
  A4 moved apart   chosen together; the enemy moved to bf2 before resolution: the subset is asked for by name; the
                   friendly kept - it alone is Stunned; keeping both, or naming a unit never chosen, is refused
  A5 one gone      the enemy gone from the board: the friendly alone still meets the requirement - Stunned, nothing asked
  M1 total Might   "any number" of units at bf1 with total Might 4 or less (no max: the total bounds it): 2 + 1 killed;
                   none chosen is a legal play; 3 + 2 refused at play; +2 given to one before resolution (total 5): a
                   subset asked for, the one kept killed, the other not
  V  shape         a group with no subset_ref, one_per_relation unlike min and max, a negative min, a group with no
                   max and no total, or an "any number" group listed as selectors, does not validate
  G  grammar       Facebreaker's and Fox-Fire's lines lower to exactly these programs; near misses do not

    python skill/scripts/check_target_group.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_rules_core import fixture, item  # noqa: E402
from check_target_counts import RULESET, board, play, refused, spell_program  # noqa: E402
from effect_ir import hash_value, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

errors: list[str] = []
STUN_PAIR = {"op": "stun", "effect_id": "stun",
             "targets": {"min": 2, "max": 2, "decision_ref": "t", "subset_ref": "keep",
                         "restrictions": {"chosen_zone_class": "board", "kind": "unit", "location": "battlefield"},
                         "group": {"same_battlefield": True, "one_per_relation": ["friendly", "enemy"]}}}
KILL_TOTAL = {"op": "kill", "effect_id": "kill",
              "targets": {"min": 0, "decision_ref": "t", "subset_ref": "keep",
                          "restrictions": {"chosen_zone_class": "board", "kind": "unit", "location": "battlefield"},
                          "group": {"same_battlefield": True, "total_might_at_most": 4}}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def two_battlefields():
    state = board()
    state["battlefields"]["bf2"] = {"controller": "p2", "objects": []}
    return state


def resolve(effect_state, effect, keep=None):
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    decisions = None
    if keep is not None:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(effect_state), "decisions": [
            {"decision_id": "keep", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": list(keep),
             "selection_identities": {o: object_identity(effect_state, o) for o in keep}}]}
    return resolve_with_program(timing, "spell-1", effect_state, spell_program(effect), engine_decisions=decisions)


def move_to_bf2(state, unit):
    state = copy.deepcopy(state)
    state["battlefields"]["bf1"]["objects"].remove(unit)
    state["battlefields"]["bf2"]["objects"].append(unit)
    return state


def main() -> int:
    s = two_battlefields()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    # A1: u1 (p1) and u2 (p2) at bf1
    played = play(s, STUN_PAIR, t=["u1", "u2"])
    if not played.get("committed"):
        fail("A1 one each", f"{played.get('reason_code')} {played.get('reason')}")
        return report()
    done = resolve(played["next_effect_state"], STUN_PAIR)
    after = done.get("next_effect_state") or {}
    if not done.get("committed") or not all((after.get("objects") or {}).get(o, {}).get("stunned") for o in ("u1", "u2")):
        fail("A1 one each", f"{done.get('reason')} {[after.get('objects', {}).get(o, {}).get('stunned') for o in ('u1', 'u2')]}")
    # A2, A3: refused at play
    apart = move_to_bf2(s, "u2")
    if problem := refused(play(apart, STUN_PAIR, t=["u1", "u2"]), "target_group_requirement_failed"):
        fail("A2 apart", problem)
    if problem := refused(play(s, STUN_PAIR, t=["u1", "u3"]), "target_group_requirement_failed"):
        fail("A3 two friendly", problem)
    # A4: moved apart after play
    moved = move_to_bf2(played["next_effect_state"], "u2")
    asked = resolve(moved, STUN_PAIR)
    asked = {**asked, **(asked.get("effect_result") or {})}  # the bridge carries the engine's request inside its result
    if asked.get("committed") or asked.get("reason_code") != "target_group_subset_required" \
            or sorted(asked.get("subset_candidates") or []) != ["u1", "u2"]:
        fail("A4 moved apart", f"not asked for the subset: {asked.get('reason_code')} {asked.get('reason')}")
    kept = resolve(moved, STUN_PAIR, keep=["u1"])
    after = kept.get("next_effect_state") or {}
    if not kept.get("committed") or not after["objects"]["u1"].get("stunned") or after["objects"]["u2"].get("stunned"):
        fail("A4 moved apart", f"keeping u1: {kept.get('reason') or kept.get('errors')}")
    for label, keep in (("both kept", ["u1", "u2"]), ("a unit never chosen", ["u3"])):
        bad = resolve(moved, STUN_PAIR, keep=keep)
        if bad.get("committed"):
            fail("A4 moved apart", f"{label}: committed")
    # A5: the enemy gone
    gone = copy.deepcopy(played["next_effect_state"])
    gone["battlefields"]["bf1"]["objects"].remove("u2")
    gone["players"]["p2"]["zones"]["trash"].append("u2")
    gone["objects"]["u2"]["identity"] = "u2@1"
    alone = resolve(gone, STUN_PAIR)
    if not alone.get("committed") or not alone["next_effect_state"]["objects"]["u1"].get("stunned"):
        fail("A5 one gone", f"{alone.get('reason_code')} {alone.get('reason')}")
    # M1: total Might 4 or less (u3: 2, u4: 1, u1: 3)
    ok = play(s, KILL_TOTAL, t=["u3", "u4"])
    if not ok.get("committed"):
        fail("M1 total Might", f"2 + 1: {ok.get('reason_code')} {ok.get('reason')}")
    else:
        killed = resolve(ok["next_effect_state"], KILL_TOTAL)
        trash = sum([(killed.get("next_effect_state") or {"players": {}})["players"].get(p, {}).get("zones", {}).get("trash", [])
                    for p in ("p1", "p2")], []) if killed.get("committed") else []
        if not {"u3", "u4"} <= set(trash):
            fail("M1 total Might", f"2 + 1 not both killed: {killed.get('reason')}")
        grown = copy.deepcopy(ok["next_effect_state"])
        grown["objects"]["u4"]["might_modifiers"].append({"amount": 2, "duration": "this_turn", "source": "x",
                                                          "turn_id": grown.get("turn_id", "turn-0")})
        if validate_state(grown):
            fail("M1 total Might", f"the grown board: {validate_state(grown)[:1]}")
        else:
            if (resolve(grown, KILL_TOTAL).get("effect_result") or {}).get("reason_code") != "target_group_subset_required":
                fail("M1 total Might", "grown to 5: no subset asked for")
            kept = resolve(grown, KILL_TOTAL, keep=["u3"])
            trash = sum([(kept.get("next_effect_state") or {"players": {}})["players"].get(p, {}).get("zones", {}).get("trash", [])
                        for p in ("p1", "p2")], []) if kept.get("committed") else []
            if "u3" not in trash or "u4" in trash:
                fail("M1 total Might", f"grown to 5, u3 kept: {kept.get('reason') or kept.get('errors')}")
    if problem := refused(play(s, KILL_TOTAL, t=["u1", "u3"]), "target_group_requirement_failed"):
        fail("M1 total Might", f"3 + 2: {problem}")
    none = play(s, KILL_TOTAL, t=[])
    if not none.get("committed"):
        fail("M1 total Might", f"none chosen: {none.get('reason_code')} {none.get('reason')}")
    # V
    for label, change in (("no subset_ref", lambda t: {k: v for k, v in t.items() if k != "subset_ref"}),
                          ("relations unlike the count", lambda t: {**t, "min": 1, "max": 3}),
                          ("a negative min", lambda t: {**t, "min": -1}),
                          ("no max and no total", lambda t: {k: v for k, v in t.items() if k != "max"})):
        program = spell_program({**STUN_PAIR, "targets": change(copy.deepcopy(STUN_PAIR["targets"]))})
        if not validate_program(program):
            fail(f"V {label}", "validated")
    listed = {**KILL_TOTAL["targets"], "selectors": [{"object_id": "u3", "chosen_zone_class": "board"}]}
    listed.pop("decision_ref")
    if not validate_program(spell_program({**KILL_TOTAL, "targets": listed})):
        fail("V any number listed", "validated")
    if validate_program(spell_program(KILL_TOTAL)):
        fail("V any number", f"Fox-Fire's program does not validate: {validate_program(spell_program(KILL_TOTAL))}")
    # G
    import clause_grammar as cg
    grammar = cg.load_grammar()
    row = "stun_a_friendly_unit_and_an_enemy_unit_at_the_same_battlefield"
    got = cg.compile_clause("Stun a friendly unit and an enemy unit at the same battlefield.", grammar)
    if got.get("production_id") != row or got.get("program_effects") != [STUN_PAIR]:
        fail("G grammar", f"{got.get('production_id')} {got.get('program_effects')}")
    for near in ("Stun a friendly unit and an enemy unit.", "Stun two enemy units at the same battlefield."):
        if cg.compile_clause(near, grammar).get("production_id") == row:
            fail("G grammar", f"{near!r} lowered to the row")
    row = "kill_any_number_of_units_at_a_battlefield_with_total_might_n_or_less"
    got = cg.compile_clause("Kill any number of units at a battlefield with total Might 4 or less.", grammar)
    if got.get("production_id") != row or got.get("program_effects") != [KILL_TOTAL]:
        fail("G grammar", f"{got.get('production_id')} {got.get('program_effects')}")
    for near in ("Kill any number of units with total Might 4 or less.", "Kill any number of units at a battlefield."):
        if cg.compile_clause(near, grammar).get("production_id") == row:
            fail("G grammar", f"{near!r} lowered to the row")
    return report()


def report() -> int:
    if errors:
        print("FAILED: target group checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: targets meeting a requirement as a group - met as chosen or refused at play; as it resolves, a group "
          "that no longer meets it is cut to a subset its controller keeps (A1-A5, M1, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
