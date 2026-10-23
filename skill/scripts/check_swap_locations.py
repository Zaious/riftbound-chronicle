#!/usr/bin/env python3
"""Two Moves that swap two units' places (package 11, Tideturner: "When you play me, you may choose a unit you control at
another location. Move me to its location and it to my original location.").

GPT 2026-10-08 (package 10 ruling 4), affirmed 2026-10-12: two Moves in the card's order (Core 303.2), not one
simultaneous swap; the target and both original locations are bound as the ability is finalized - the second Move uses
the source's ORIGINAL location; a unit in its Base is a candidate too; each Move raises its own move triggers once. The
program: Move {object_ref: program_source} to destination {decision_ref, restriction: location_of_target, target_ref: t},
then Move target t to destination {decision_ref, restriction: source_location}. Each restriction narrows the choice to one
place as it is made (bind_move_here); as the Moves execute, the recorded places only have to be legal destinations.

  S1 base <-> bf1     the source in p1's Base, f1 at bf1: the source goes to bf1, f1 to p1's Base, in that order
  S2 not the places   a destination other than f1's place, or other than the source's, is refused at finalization
  S3 same place       a unit where the source already is: refused - it is not 'at another location'; with only such units
                      the trigger leaves the Chain (Core 403.4)
  S4 source gone      finalized, then the source killed: its Move is ignored; f1 still goes to the source's original place
  S5 target moved     finalized, then f1 moved to bf2: the source still goes to bf1 (f1's place when chosen); f1, now at
                      bf2, goes to p1's Base
  S6 bf1 <-> bf2      the source at bf1, f1 at bf2: swapped
  S7 move triggers    each unit's own 'When I move' is raised once
  V  validation       location_of_target names a target decision of the program; bound_location is the engine's

    python skill/scripts/check_swap_locations.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, find_location, hash_value, object_identity,  # noqa: E402
                       validate_program, validate_state)
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority, schedule_triggered_items  # noqa: E402

errors: list[str] = []
SWAP = [{"op": "move_board_object", "effect_id": "mv1", "object_id": {"object_ref": "program_source"},
         "destination": {"decision_ref": "d1", "restriction": "location_of_target", "target_ref": "t"}},
        {"op": "move_board_object", "effect_id": "mv2",
         "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"},
         "destination": {"decision_ref": "d2", "restriction": "source_location"}}]


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "effects": effects, **extra}


PROGRAM = program("tt-fx", copy.deepcopy(SWAP), source_object="tt")
REGISTRY = {"tt-fx": PROGRAM}


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(tt="base", f1="bf1", *, f3_with_tt=False, triggers=False):
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid in ("tt", "f1", "f3"):
        state["objects"][oid] = unit("p1")
        if triggers and oid != "f3":
            state["objects"][oid]["move_triggers"] = [{"trigger_id": f"{oid}-moved", "controller": "p1", "source_object": oid,
                                                       "controller_order": 0, "effect_program_id": f"{oid}-moved-fx",
                                                       "optional_at_finalize": False}]
    for oid, where in (("tt", tt), ("f1", f1), ("f3", tt if f3_with_tt else "bf2")):
        if where == "base":
            state["players"]["p1"]["zones"]["base"].append(oid)
        else:
            state["battlefields"][where]["objects"].append(oid)
    return settle_contested(state)


def pending(state):
    descriptor = {"trigger_id": "tt-play", "controller": "p1", "source_object": "tt", "controller_order": 0,
                  "effect_program_id": "tt-fx", "optional_at_finalize": True, "trigger_kind": "triggered",
                  "batch_sequence": 0, "batch_id": "play:unit-1", "source_identity": object_identity(state, "tt")}
    return schedule_triggered_items(fixture(), [descriptor])["next_state"]


def choose(state, target, d1, d2):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [target], "selection_identities": {target: object_identity(state, target)}},
        {"decision_id": "d1", "stage": "trigger_finalization", "kind": "location_selection", "controller": "p1", "value": d1},
        {"decision_id": "d2", "stage": "trigger_finalization", "kind": "location_selection", "controller": "p1", "value": d2}]}


def finalize(state, target=None, d1=None, d2=None):
    return finalize_trigger(pending(state), state, REGISTRY, choose(state, target, d1, d2) if target else None,
                            perform_optional_trigger=True)


def resolve(finalized, between=None):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    if between is not None:
        effect = between(effect)
    return resolve_with_program(timing, "tt-play", effect, PROGRAM)


def at(state, oid):
    loc = find_location(state, oid)
    return None if loc is None else (f"battlefield:{loc[1]}" if loc[0] == "battlefield" else f"{loc[1]}:{loc[2]}")


def relocate(state, oid, where):
    s = copy.deepcopy(state)
    loc = find_location(s, oid)
    (s["battlefields"][loc[1]]["objects"] if loc[0] == "battlefield" else s["players"][loc[1]]["zones"][loc[2]]).remove(oid)
    s["battlefields"][where]["objects"].append(oid)
    return settle_contested(s)


def kill(state, oid):
    done = apply_program(state, {**program("k", [{"op": "kill", "effect_id": "k", "object_id": oid}]), "controller": "p2"})
    return done["next_state"]


def steps(got):
    trace = (got.get("trace") or {}).get("effect", []) if isinstance(got.get("trace"), dict) else []
    return [(e.get("effect_id"), e.get("outcome")) for e in trace if e.get("effect_id") in ("mv1", "mv2")]


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    ok = finalize(s, "f1", "battlefield:bf1", "base:p1")
    if not ok.get("committed") or ok.get("removed"):
        fail("S1 base <-> bf1", f"not finalized: {ok.get('reason')} {ok.get('message')}")
        return report()
    got = resolve(ok)
    e = got.get("next_effect_state") or s
    if not got.get("committed") or (at(e, "tt"), at(e, "f1")) != ("battlefield:bf1", "p1:base") \
            or [x[0] for x in steps(got)] != ["mv1", "mv2"]:
        fail("S1 base <-> bf1", f"{got.get('reason') or got.get('reason_code')} tt {at(e, 'tt')} f1 {at(e, 'f1')} {steps(got)}")
    for label, d1, d2 in (("S2 not the places", "battlefield:bf2", "base:p1"), ("S2 not the places", "battlefield:bf1", "battlefield:bf2")):
        refused = finalize(s, "f1", d1, d2)
        if refused.get("committed") or refused.get("reason") != "move_destination_illegal":
            fail(label, f"{d1}/{d2}: {refused.get('committed')} {refused.get('reason')}")
    same = board(f3_with_tt=True)
    refused = finalize(same, "f3", "base:p1", "base:p1")
    if refused.get("committed") or refused.get("reason") != "move_destination_illegal":
        fail("S3 same place", f"f3 with the source: {refused.get('committed')} {refused.get('reason')}")
    alone = board(f1="base", f3_with_tt=True)
    left = finalize(alone)
    if not left.get("removed") or (left.get("transition") or {}).get("type") != "no_legal_choices":
        fail("S3 same place", f"only units where the source is - the trigger did not leave: {left.get('reason')} {left.get('transition')}")
    gone = resolve(ok, lambda st: kill(st, "tt"))
    e = gone.get("next_effect_state") or s
    if not gone.get("committed") or at(e, "f1") != "p1:base" or dict(steps(gone)).get("mv1") != "ignored_source_unavailable":
        fail("S4 source gone", f"{gone.get('reason') or gone.get('reason_code')} f1 {at(e, 'f1')} {steps(gone)}")
    moved = resolve(ok, lambda st: relocate(st, "f1", "bf2"))
    e = moved.get("next_effect_state") or s
    if not moved.get("committed") or (at(e, "tt"), at(e, "f1")) != ("battlefield:bf1", "p1:base"):
        fail("S5 target moved", f"{moved.get('reason') or moved.get('reason_code')} tt {at(e, 'tt')} f1 {at(e, 'f1')}")
    two = board(tt="bf1", f1="bf2")
    ok2 = finalize(two, "f1", "battlefield:bf2", "battlefield:bf1")
    got2 = resolve(ok2) if ok2.get("committed") and not ok2.get("removed") else {}
    e = got2.get("next_effect_state") or two
    if not got2.get("committed") or (at(e, "tt"), at(e, "f1")) != ("battlefield:bf2", "battlefield:bf1"):
        fail("S6 bf1 <-> bf2", f"{ok2.get('reason')} {got2.get('reason') or got2.get('reason_code')} tt {at(e, 'tt')} f1 {at(e, 'f1')}")
    trig = board(triggers=True)
    ok3 = finalize(trig, "f1", "battlefield:bf1", "base:p1")
    got3 = resolve(ok3) if ok3.get("committed") and not ok3.get("removed") else {}
    raised = sorted(i["id"] for i in (got3.get("next_timing_state") or {}).get("chain", {}).get("items", [])
                    if i.get("id", "").endswith("-moved"))
    if raised != ["f1-moved", "tt-moved"]:
        fail("S7 move triggers", f"{ok3.get('reason')} {got3.get('reason')} raised {raised}")
    bad = copy.deepcopy(PROGRAM)
    bad["effects"][0]["destination"]["target_ref"] = "nope"
    if not validate_program(bad):
        fail("V validation", "a target_ref naming no target decision validated")
    bad = copy.deepcopy(PROGRAM)
    bad["effects"][1]["destination"]["bound_location"] = "base:p1"
    if not validate_program(bad):
        fail("V validation", "a program carrying its own bound_location validated")
    if validate_program(PROGRAM):
        fail("V validation", f"the swap program did not validate: {validate_program(PROGRAM)}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: two Moves that swap places")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the source to the chosen unit's place, then the unit to the source's original place, in that order; both "
          "places bound at finalization (others refused; a unit already with the source refused, none left - the trigger "
          "leaves); the source gone - only its Move ignored; the unit moved meanwhile - the bound places stand; Base or "
          "Battlefield alike; each unit's move trigger once (S1-S7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
