#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): three trigger conditions on events the engine already emits.

  M1 from a battlefield  "When I move from a battlefield": a Move from bf1 to the Base raises it, and from bf1 to bf2;
                         a Move from the Base to bf1 does not; the condition on a play trigger is refused
  B1 buff me             "When you buff me": p1's spell buffs the watcher itself - one trigger; another of p1's units -
                         none; p2's spell buffs it - none; already buffed - none
  D1 friendly dies       "When a friendly unit dies": p1's unit killed - one trigger; two killed - two; p2's unit - none
  G  grammar             each sentence lowers to exactly its descriptor
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_move_count_and_legend_triggers import descriptor, resolve  # noqa: E402
from effect_ir import apply_program, validate_state  # noqa: E402

errors: list[str] = []
BUFF_ME = {"kinds": ["buffed"], "scope": "self", "filter": {"actor_is_controller": True}}
FRIENDLY_DIES = {"kinds": ["died"], "scope": "any", "filter": {"object_kind": "unit", "object_controller_relation": "friendly"},
                 "grouping": "each"}


def fail(label, why):
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def raised(result, prefix):
    timing = result.get("next_timing_state") or {}
    return [i for i in (timing.get("chain") or {}).get("items", []) if str(i.get("id", "")).startswith(prefix)]


def move_case(origin, destination):
    state = base_state()
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
    state["objects"]["hs"] = unit("p1", move_triggers=[descriptor("hs-move", "hs", condition={"kind": "moved_from_battlefield"})])
    if origin == "base":
        state["players"]["p1"]["zones"]["base"].append("hs")
    else:
        state["battlefields"][origin]["objects"].append("hs")
    dest = {"kind": "base", "player": "p1"} if destination == "base" else {"kind": "battlefield", "battlefield": destination}
    done = apply_program(state, program("mv", {"op": "move_board_object", "effect_id": "mv", "object_id": "hs",
                                               "destination": dest}))
    if not done.get("committed"):
        return f"refused: {done.get('reason') or done.get('errors')}"
    return [t["trigger_id"] for t in done.get("pending_triggers") or []]


def watch_board(watch):
    state = base_state()
    state["turn_id"] = "turn-6"
    state["objects"]["w1"] = unit("p1", event_triggers=[descriptor("w-watch", "w1", "p1", watch=copy.deepcopy(watch))])
    state["players"]["p1"]["zones"]["base"].append("w1")
    for oid, owner, extra in (("a1", "p1", {}), ("a2", "p1", {}), ("e1", "p2", {})):
        state["objects"][oid] = unit(owner, **extra)
        state["players"][owner]["zones"]["base"].append(oid)
    assert not validate_state(state), validate_state(state)
    return state


def main() -> int:
    for label, origin, destination, want in (("bf1 to the Base", "bf1", "base", ["hs-move"]),
                                              ("bf1 to bf2", "bf1", "bf2", ["hs-move"]),
                                              ("the Base to bf1", "base", "bf1", [])):
        if (got := move_case(origin, destination)) != want:
            fail("M1", f"{label}: raised {got}, not {want}")
    misfiled = base_state()
    misfiled["objects"]["u1"]["play_triggers"] = [descriptor("u1-play", "u1", condition={"kind": "moved_from_battlefield"})]
    if not validate_state(misfiled):
        fail("M1", "'moved_from_battlefield' was accepted on a play trigger")
    buff = lambda state, obj, controller="p1": resolve(state, [{"op": "buff", "effect_id": "bf", "object_id": obj}],
                                                       controller=controller)
    for label, obj, controller, pre, want in (("p1 buffs it", "w1", "p1", {}, 1), ("p1 buffs another unit", "a1", "p1", {}, 0),
                                              ("p2 buffs it", "w1", "p2", {}, 0),
                                              ("already buffed", "w1", "p1", {"buffed": True}, 0)):
        state = watch_board(BUFF_ME)
        state["objects"]["w1"].update(pre)
        got = buff(state, obj, controller)
        if not got.get("committed") or len(raised(got, "w-watch@")) != want:
            fail("B1", f"{label}: {got.get('reason')} {len(raised(got, 'w-watch@'))} trigger(s), not {want}")
    kill = lambda state, objs: resolve(state, [{"op": "kill", "effect_id": f"k{i}", "object_id": o} for i, o in enumerate(objs)])
    for label, objs, want in (("p1's unit", ["a1"], 1), ("two of p1's", ["a1", "a2"], 2), ("p2's unit", ["e1"], 0)):
        got = kill(watch_board(FRIENDLY_DIES), objs)
        found = raised(got, "w-watch@") if got.get("reason_code") != "trigger_order_required" else \
            [t for t in got.get("trigger_ids") or [] if str(t).startswith("w-watch@")]
        if len(found) != want:
            fail("D1", f"{label}: {got.get('reason_code')} {got.get('reason')} {len(found)} trigger(s), not {want}")
    g = CG.load_grammar()
    for sentence, field, expected in (
            ("When I move from a battlefield, draw 1.", "move_triggers", {"condition": {"kind": "moved_from_battlefield"}}),
            ("When you buff me, draw 1.", "event_triggers", {"watch": BUFF_ME}),
            ("When a friendly unit dies, draw 1.", "event_triggers", {"watch": FRIENDLY_DIES})):
        got = ((CG.compile_clause(sentence, g).get("passive") or {}).get("object_fields") or {}).get(field) or [{}]
        if any(got[0].get(k) != v for k, v in expected.items()):
            fail("G", f"{sentence!r} lowered to {got}")
    if errors:
        print("FAILED: set 2 trigger conditions")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'When I move from a battlefield' (a Move out of a Battlefield only), 'When you buff me' (its controller's "
          "Buff of the card), 'When a friendly unit dies' (each friendly death) trigger exactly on their events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
