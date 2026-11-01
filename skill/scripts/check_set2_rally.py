#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "When a friendly unit is played this turn, buff it. Draw 1." (Rally the Troops) - the
engine grammar's production lowers to a repeating play-waiting delayed trigger and a draw; "buff it" reads the played
unit (trigger_event_object).

  R1 made      the spell resolves: p1 drew 1; one delayed trigger waits for p1's plays (scope actor), repeating, until
               the end of this turn
  R2 woken     p1 plays a unit and p2 plays one: it wakes once, about p1's, and that unit is buffed (+1 Might, Core 427);
               p2's is not; it still waits - a second play of p1's wakes it again
  R3 referent  buff with object_ref trigger_event_object and no event bound is refused by name
  G  grammar   the sentence lowers to exactly that program; its near misses do not

    python skill/scripts/check_set2_rally.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import game_events  # noqa: E402
import watchers  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, effective_might, object_identity  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "When a friendly unit is played this turn, buff it. Draw 1."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def bind(value):
    if isinstance(value, dict):
        return {k: bind(v) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v) for v in value]
    return {"$controller": "p1", "$chain_item": "spell-1", "$source_object": "rally"}.get(value, value) \
        if isinstance(value, str) else value


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "effects": effects, **extra}


def play(state, player, oid, n):
    state["objects"][oid] = {"owner": player, "controller": player, "kind": "unit", "base_might": 2,
                             "might_modifiers": [], "damage": 0, "exhausted": True}
    state["players"][player]["zones"]["base"].append(oid)
    identity = object_identity(state, oid) or f"{oid}@0"
    return game_events.played_event(play_id=f"p{n}", card=oid, actor=player, object_kind="unit", identity_before=identity,
                                    identity_after=identity, from_hidden=False, turn_player="p1")


def wake(state, events, delayed_effects):
    scheduled, state = watchers.schedule_live(state, events, turn_id=state.get("turn_id", "turn-0"), batch_label="t")
    about = []
    for entry in scheduled:
        if entry.get("watch_kind") != "delayed":
            continue
        ran = apply_program(state, program(entry["effect_program_id"], copy.deepcopy(delayed_effects),
                                           source_object=entry["source_object"], trigger_event=entry["trigger_event"]))
        if not ran.get("committed"):
            return None, f"{ran.get('reason') or ran.get('errors')}"
        state = ran["next_state"]
        about.append(entry["trigger_event"]["object"])
    return state, sorted(about)


def main() -> int:
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    effects = bind(lowered.get("program_effects") or [])
    if [e.get("op") for e in effects] != ["create_delayed_trigger", "draw"]:
        fail("G", f"the sentence lowered to {[e.get('op') for e in effects]}")
        return report()
    state = base_state()
    state["objects"]["rally"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["trash"].append("rally")
    hand = len(state["players"]["p1"]["zones"]["hand"])
    done = apply_program(state, program("rally", effects, source_object="rally"))
    if not done.get("committed"):
        fail("R1", f"refused: {done.get('reason') or done.get('errors')}")
        return report()
    after = done["next_state"]
    waiting = [(d["waits_for"].get("kinds"), d["waits_for"].get("scope"), d.get("repeats"), d.get("until"))
               for d in after.get("delayed_triggers") or []]
    if waiting != [(["played"], "actor", True, "end_of_turn")] or len(after["players"]["p1"]["zones"]["hand"]) != hand + 1:
        fail("R1", f"waiting {waiting}, hand {len(after['players']['p1']['zones']['hand'])}")
    delayed_effects = effects[0]["effects"]
    events = [play(after, "p1", "mine", 0), play(after, "p2", "theirs", 1)]
    state2, about = wake(after, events, delayed_effects)
    if state2 is None:
        fail("R2", about)
        return report()
    if about != ["mine"] or not state2["objects"]["mine"].get("buffed") or effective_might(state2, "mine") != 3 \
            or state2["objects"]["theirs"].get("buffed"):
        fail("R2", f"woke about {about}; mine buffed {state2['objects']['mine'].get('buffed')} at "
                   f"{effective_might(state2, 'mine')}, theirs buffed {state2['objects']['theirs'].get('buffed')}")
    state3, about = wake(state2, [play(state2, "p1", "again", 2)], delayed_effects)
    if state3 is None or about != ["again"] or not state3["objects"]["again"].get("buffed"):
        fail("R2", f"a second play of p1's: woke about {about}")
    bare = apply_program(base_state(), program("bare", [{"op": "buff", "effect_id": "b",
                                                         "object_id": {"object_ref": "trigger_event_object"}}]))
    if bare.get("committed"):
        fail("R3", "buff it with no event bound committed")
    for near in ("when an enemy unit is played this turn, buff it. draw 1.",
                 "when a friendly unit is played, buff it. draw 1."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == "when_a_friendly_unit_is_played_this_turn_buff_it_draw_n":
            fail("G", f"a near miss lowered: {near!r}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: set 2 Rally the Troops")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'when a friendly unit is played this turn, buff it' waits for its controller's plays, repeating, until the "
          "turn ends; each wakes it about the unit played, which is buffed - an opponent's play does not; then the draw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
