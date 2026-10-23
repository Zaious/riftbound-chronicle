#!/usr/bin/env python3
"""A Ready or a Buff the player performs on a friendly Unit (package 10, Pirate's Haven and Mistfall).

"When you ready a friendly unit, give it +1 :rb_might: this turn." / "When you buff a friendly unit, you may pay
:rb_rune_body: and exhaust this to ready it." "You" is the player who performs it (the event's actor, Core 412.4): an
instruction's controller, or the Turn Player in the Awaken step, who readies every object they control that can be
readied (Core 315.1.b, 416.3.a). A Unit already Ready is not readied again (416.1.b, 416.1.c) and one that already has a
buff is not buffed again: neither wakes anything. Each unit readied or buffed is its own trigger, the unit its "it".

The engine's shape: watches over `readied` / `buffed` events, scope actor, filters object_kind unit and
object_controller_relation friendly, grouping each; the Awaken step emits one `readied` event per object it readied
(game_events.awaken_ready_event) and wakes watchers with them.

  R1 effect        p1's spell readies p1's exhausted unit: one trigger, its object that unit
  R2 already       the same spell on a ready unit: none
  R3 enemy         p1's spell readies p2's exhausted unit: none (not friendly)
  R4 opponent      p2's spell readies p2's exhausted unit: none (not p1's Ready)
  R5 two           p1's spell readies two exhausted units of p1's: two triggers
  R6 awaken        p1's Awaken readies p1's two exhausted units (a third already ready): two triggers, before the
                   Beginning Phase
  R7 their awaken  p2's Awaken: p1's watcher wakes for nothing
  R8 no watcher    the Awaken step on a board with no watcher commits the same state it did before this change
  B1 buff          p1's spell buffs p1's unbuffed unit: one trigger
  B2 buffed        p1's spell buffs p1's unit that has a buff: none
  B3 enemy         p1's spell buffs p2's unit: none
  T1 ready it      the buff watch's program "ready it" ({object_ref: trigger_event_object}, the op adopted for it): the
                   buffed exhausted unit is readied on resolution, and no other unit
  T2 gone          that unit killed before the trigger resolves: the instruction is ignored, nothing readied
  G  grammar       the clause grammar lowers both sentences to exactly these watches; near misses stay unparsed

    python skill/scripts/check_ready_buff_watch.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_move_count_and_legend_triggers import descriptor, mine, resolve  # noqa: E402
from check_trigger_referent import program_of, run_trigger  # noqa: E402
from check_turn_cycle import handled, setup_timing  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from turn_cycle import begin_turn, run_awaken_step  # noqa: E402

READY = {"kinds": ["readied"], "scope": "actor", "filter": {"object_kind": "unit", "object_controller_relation": "friendly"},
         "grouping": "each"}
BUFF = {"kinds": ["buffed"], "scope": "actor", "filter": {"object_kind": "unit", "object_controller_relation": "friendly"},
        "grouping": "each"}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(watch, *, with_watcher=True):
    """p1's gear w1 in p1's Base carrying the watch; p1's units a1 (exhausted), a2 (exhausted), a3 (ready, buffed) and p2's
    units e1 (exhausted), e2 (ready) in their Bases."""
    state = base_state()
    state["turn_id"] = "turn-6"
    state["mode"] = {"victory_score": 8, "id": "duel"}
    state["objects"]["w1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False,
                              "event_triggers": [descriptor("w-watch", "w1", "p1", watch=copy.deepcopy(watch))] if with_watcher else []}
    state["players"]["p1"]["zones"]["base"].append("w1")
    for oid, owner, extra in (("a1", "p1", {"exhausted": True}), ("a2", "p1", {"exhausted": True}),
                              ("a3", "p1", {"buffed": True}), ("e1", "p2", {"exhausted": True}), ("e2", "p2", {})):
        state["objects"][oid] = unit(owner, **extra)
        state["players"][owner]["zones"]["base"].append(oid)
    assert not validate_state(state), validate_state(state)
    return state


def woke(result) -> list:
    if result.get("reason_code") == "trigger_order_required":
        # two of the card's triggers at once: their order is its controller's (Core 383.3.d) - counted as asked
        return [t for t in result.get("trigger_ids") or [] if str(t).startswith("w-watch@")]
    return mine(result, "w-watch@")


def objects_of(items) -> list:
    return sorted(((i.get("trigger_event") or {}).get("object")) for i in items)


def awaken(state, player):
    timing = setup_timing()
    if player != "p1":
        timing.update({"turn_order": [player, "p1"], "players": [player, "p1"], "turn_player": player, "priority": player})
    began = begin_turn(timing, state)
    if not began.get("committed"):
        return began
    return run_awaken_step(handled(began["next_timing_state"]), began["next_effect_state"])


def pending(result) -> list:
    if result.get("reason_code") == "trigger_order_required":
        return [t for t in result.get("trigger_ids") or [] if str(t).startswith("w-watch@")]
    timing = result.get("next_timing_state") or {}
    items = [i for i in (timing.get("chain") or {}).get("items", []) if str(i.get("id", "")).startswith("w-watch@")]
    items += [t for t in timing.get("pending_triggers") or [] if str(t.get("trigger_id", "")).startswith("w-watch@")]
    return items


def main() -> int:
    ready = lambda objs, controller="p1": resolve(board(READY), [{"op": "ready", "effect_id": f"rd{i}", "object_id": o}
                                                                 for i, o in enumerate(objs)], controller=controller)
    got = ready(["a1"])
    if not got.get("committed") or len(woke(got)) != 1:
        fail("R1 effect", f"{got.get('reason')} {woke(got)}")
    got = ready(["a3"])
    if not got.get("committed") or woke(got):
        fail("R2 already", f"{got.get('reason')} {woke(got)}")
    got = ready(["e1"])
    if not got.get("committed") or woke(got):
        fail("R3 enemy", f"{got.get('reason')} {woke(got)}")
    got = ready(["e1"], controller="p2")
    if not got.get("committed") or woke(got):
        fail("R4 opponent", f"{got.get('reason')} {woke(got)}")
    got = ready(["a1", "a2"])
    if len(woke(got)) != 2:
        fail("R5 two", f"{got.get('reason')} {woke(got)}")
    got = awaken(board(READY), "p1")
    if len(pending(got)) != 2:
        fail("R6 awaken", f"{got.get('reason_code')} {got.get('reason')} {pending(got)} {(got.get('trace') or {}).get('readied')}")
    got = awaken(board(READY), "p2")
    if not got.get("committed") or pending(got):
        fail("R7 their awaken", f"{got.get('reason_code')} {got.get('reason')} {pending(got)}")
    bare = board(READY, with_watcher=False)
    got = awaken(bare, "p1")
    if not got.get("committed") or "watch_occurrences" in got["next_effect_state"] \
            or (got.get("trace") or {}).get("watch_triggers"):
        fail("R8 no watcher", f"{got.get('reason')} {sorted(got.get('next_effect_state') or {})}")
    buff = lambda obj: resolve(board(BUFF), [{"op": "buff", "effect_id": "bf", "object_id": obj}])
    got = buff("a1")
    if not got.get("committed") or len(woke(got)) != 1:
        fail("B1 buff", f"{got.get('reason')} {woke(got)}")
    got = buff("a3")
    if not got.get("committed") or woke(got):
        fail("B2 buffed", f"{got.get('reason')} {woke(got)}")
    got = buff("e1")
    if not got.get("committed") or woke(got):
        fail("B3 enemy", f"{got.get('reason')} {woke(got)}")
    registry = {"w-watch-effects": program_of("w-watch-effects", "w1",
                                              [{"op": "ready", "effect_id": "rd", "object_id": {"object_ref": "trigger_event_object"}}])}
    buffed = buff("a1")
    if buffed.get("committed"):
        done, why = run_trigger(buffed["next_timing_state"], buffed["next_effect_state"], registry, "w-watch@")
        e = (done or {}).get("next_effect_state") or {}
        if why or e["objects"]["a1"].get("exhausted") or not e["objects"]["a2"].get("exhausted"):
            fail("T1 ready it", why or f"a1 exhausted {e['objects']['a1'].get('exhausted')}, a2 {e['objects']['a2'].get('exhausted')}")

        def kill_a1(effect):
            effect["players"]["p1"]["zones"]["base"].remove("a1")
            effect["players"]["p1"]["zones"]["trash"].append("a1")
            return effect
        done, why = run_trigger(buffed["next_timing_state"], buffed["next_effect_state"], registry, "w-watch@",
                                before_resolve=kill_a1)
        outcomes = [t.get("outcome") for t in ((done or {}).get("trace") or {}).get("effect") or []]
        if why or "ignored_source_unavailable" not in outcomes:
            fail("T2 gone", why or outcomes)
    else:
        fail("T1 ready it", buffed.get("reason"))
    for sentence, watch, near in (
            ("When you ready a friendly unit, draw 1.", READY,
             ("When you ready a unit, draw 1.", "When you ready an enemy unit, draw 1.")),
            ("When you buff a friendly unit, draw 1.", BUFF,
             ("When you buff a unit, draw 1.", "When you buff an enemy unit, draw 1."))):
        lowered = CG.compile_clause(sentence, CG.load_grammar())
        if lowered.get("unsupported") or _watch_of(lowered) != watch:
            fail("G grammar", f"{sentence!r}: {lowered.get('reason')} {_watch_of(lowered)}")
        for other in near:
            if not CG.compile_clause(other, CG.load_grammar()).get("unsupported"):
                fail("G grammar", f"{other!r} was parsed")
    if errors:
        print("FAILED: ready / buff watch checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a Ready or a Buff the player performs on a friendly Unit triggers once per unit - an instruction's or the "
          "Awaken step's; an already ready or buffed unit, an enemy unit and an opponent's do not (R1-R8, B1-B3, T1-T2, G)")
    return 0


def _watch_of(lowered: dict):
    def walk(value):
        if isinstance(value, dict):
            if "watch" in value and isinstance(value["watch"], dict):
                return value["watch"]
            for v in value.values():
                found = walk(v)
                if found is not None:
                    return found
        if isinstance(value, list):
            for v in value:
                found = walk(v)
                if found is not None:
                    return found
        return None
    return walk(lowered)


if __name__ == "__main__":
    raise SystemExit(main())
