#!/usr/bin/env python3
"""Regression gate (set 2 package A3: Hostile Takeover, "Take control of an enemy unit at a battlefield. Ready it. ...
Lose control of that unit and recall it at end of turn."): a control effect that ends at the end of the turn.

Readings (Core 2026-10-09 and the official Spiritforged FAQ): Controller is a layer-2 trait (479.2.a) - the control effect
ends and the unit's controller is again whoever controls it without that effect, its owner here; "at end of turn" is a
delayed triggered ability (359.3.e.16), bound to the unit, recalling it to the base of whoever controls it then (457); a
unit that left the board is a new object (124) and the trigger is dropped; played during this turn's Ending Phase the
delayed trigger is not generated (359.3.e.16). Taken at a Battlefield, the control change applies Contested (190.3.a.2):
with no other enemy unit there a non-combat showdown is staged (the FAQ: no conquer at once), with one a combat.

  G1 grammar        the body lowers to gain_control (until_ended) -> ready -> create_delayed_trigger bound to the unit,
                    whose own program is lose_control -> recall of that unit; the near misses do not parse
  T1 taken          p1 plays it on p2's exhausted e1 alone at bf1 (p2 controls bf1): e1 is p1's, ready, owner p2; bf1
                    Contested by p1; one delayed trigger bound to e1
  T2 showdown       the board then stages a non-combat showdown at bf1, not a combat; bf1 is still p2's (no conquer yet)
  T3 combat         the same with p2's e3 also at bf1: no non-combat showdown; a combat is staged
  T4 end of turn    the Ending Step fires the trigger with e1 as "it"; resolved: e1 is p2's again, in p2's base
  T5 left board     e1 killed before the end of the turn: nothing fires, the trigger is dropped (target_identity_changed)
  T6 ending phase   resolved during this turn's Ending Phase: no delayed trigger is generated; e1 stays p1's
  T7 another effect after it, p2 takes e1 back with a control effect of its own: at the end of the turn the takeover's
                    effect ends, the newer one stays - e1 is p2's, recalled to p2's base
  V  validation     a gain_control with a duration and no control_id, a lose_control with no control_id, and a state whose
                    controller is not the newest control effect's player do not validate

    python skill/scripts/check_hostile_takeover.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as cg  # noqa: E402
import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from battlefield_control import stage_showdown  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from combat import stage_combat  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import begin_ending_step, finalize_trigger, resolve_with_program  # noqa: E402

RULESET = {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
TEXT = "Take control of an enemy unit at a battlefield. Ready it. Lose control of that unit and recall it at end of turn."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def substitute(value, mapping):
    if isinstance(value, dict):
        return {k: substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def lowered():
    return cg.compile_clause(TEXT, cg.load_grammar())


def program():
    effects = substitute(lowered().get("program_effects") or [], {"$controller": "p1", "$source_object": "ht"})
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "ht-effects", "controller": "p1",
            "source_object": "ht", "effects": effects}


def nested():
    made = next(e for e in program()["effects"] if e["op"] == "create_delayed_trigger")
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "hostile-takeover-end",
            "controller": "p1", "effects": copy.deepcopy(made["effects"])}


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(*, other_enemy=False):
    """p2's exhausted e1 at bf1, which p2 controls (and p2's e3 there too when asked); Hostile Takeover in p1's hand."""
    state = base_state()
    state["objects"].update({"e1": unit("p2", exhausted=True),
                             "ht": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                    "might_modifiers": [], "damage": 0, "exhausted": False, "play_timing": "action"}})
    state["battlefields"]["bf1"] = {"controller": "p2", "objects": ["e1"]}
    if other_enemy:
        state["objects"]["e3"] = unit("p2")
        state["battlefields"]["bf1"]["objects"].append("e3")
    state["players"]["p1"]["zones"]["hand"].append("ht")
    state["players"]["p1"]["resources"] = {"energy": 3, "power": {}}
    return settle_contested(state)


def cast(state, pick="e1", *, ending=False):
    prog = program()
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [pick],
         "selection_identities": {pick: IR.object_identity(state, pick)}}]}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-ht", "actor": "p1", "card": "ht",
            "effect_program_id": prog["program_id"], "chain_item": {"id": "spell-ht", "object_kind": "spell", "timing": "action"},
            "cost": {"base": {"energy": 3, "power": {}}}, "payment_context": CLOSED}
    played = play_card(fixture(), state, decl, engine_decisions=decisions, effect_program=prog)
    if not played.get("committed"):
        return {"refused": played.get("reason_code") or played.get("reason")}
    t = played["next_timing_state"]
    if RC.next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = RC.finalize_oldest_pending(t)["next_state"]
    for actor in ("p1", "p2"):
        t = (RC.pass_priority(t, actor) or {}).get("next_state") or t
    if ending:
        t = {**t, "phase": "ending", "ending_step": {"status": "triggers_scheduled",
                                                     "turn_id": state.get("turn_id", IR.DEFAULT_TURN_ID)}}
    effect = played["next_effect_state"]
    return resolve_with_program(t, "spell-ht", effect, prog, engine_decisions={**decisions, "input_hash": IR.hash_value(effect)})


def where(state, oid):
    loc = IR.find_location(state, oid) if state.get("players") else None
    return None if loc is None else (f"{loc[1]}:{loc[2]}" if loc[0] == "player" else loc[1])


def end_of_turn(state):
    """The Ending Step; the delayed trigger (if it fires) finalized and resolved. (fired ids, final state or None, why)."""
    began = begin_ending_step(fixture(), state)
    if not began.get("committed"):
        return [], None, f"ending refused: {began.get('reason')}"
    timing, effects = began["next_timing_state"], began["next_effect_state"]
    fired = [i["id"] for i in timing["chain"]["items"]]
    if not fired:
        return fired, effects, "nothing fired"
    done_state = effects
    for item_id in fired:
        finalized = finalize_trigger(timing, done_state, {"hostile-takeover-end": nested()}, None)
        if not finalized.get("committed"):
            return fired, None, f"finalize refused: {finalized.get('reason')}"
        timing = finalized["next_timing_state"]
        for _ in range(4):
            if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
                break
            timing = RC.pass_priority(timing, timing["priority"])["next_state"]
        done = resolve_with_program(timing, item_id, finalized["next_effect_state"], nested())
        if not done.get("committed"):
            return fired, None, f"resolve refused: {done.get('reason') or done.get('reason_code')}"
        timing, done_state = done["next_timing_state"], done["next_effect_state"]
    return fired, done_state, "resolved"


def main() -> int:
    # G1
    got = lowered()
    ops = [e.get("op") for e in got.get("program_effects") or []]
    made = next((e for e in got.get("program_effects") or [] if e.get("op") == "create_delayed_trigger"), {})
    if got.get("production_id") is None or ops != ["gain_control", "ready", "create_delayed_trigger"] \
            or [e.get("op") for e in made.get("effects") or []] != ["lose_control", "recall"] \
            or made.get("delayed", {}).get("target_object") != IR.DELAYED_OWN_TARGET:
        fail("G1 grammar", f"{got.get('production_id')} {ops}")
    near_misses = ("Take control of an enemy unit at a battlefield. Ready it.",
                   "Take control of an enemy unit. Ready it. Lose control of that unit and recall it at end of turn.")
    for near in near_misses:
        parsed = cg.compile_clause(near, cg.load_grammar()).get("production_id")
        if parsed == got.get("production_id"):
            fail("G1 grammar", f"a near miss parsed: {near!r}")
    # T1
    s = board()
    if IR.validate_state(s):
        fail("board", IR.validate_state(s)[:2])
        return report()
    done = cast(s)
    after = done.get("next_effect_state") or {}
    e1 = (after.get("objects") or {}).get("e1") or {}
    delayed = after.get("delayed_triggers") or []
    bf1 = (after.get("battlefields") or {}).get("bf1") or {}
    if not done.get("committed") or e1.get("controller") != "p1" or e1.get("owner") != "p2" or e1.get("exhausted") \
            or not bf1.get("contested") or bf1.get("contested_by") != "p1" or len(delayed) != 1 \
            or delayed[0].get("target_object") != "e1":
        fail("T1 taken", f"{done.get('refused') or done.get('reason') or done.get('reason_code')} e1={e1} bf1={bf1} "
                         f"delayed={[d.get('delayed_id') for d in delayed]}")
        return report()
    if IR.validate_state(after):
        fail("T1 taken", f"the state does not validate: {IR.validate_state(after)[:2]}")
    # T2: no other enemy there - a non-combat showdown, not a conquer
    staged = stage_showdown(fixture(), after)
    shows = (staged.get("next_timing_state") or {}).get("staged_showdowns") or []
    lone_combat = (stage_combat(fixture(), after).get("next_timing_state") or {}).get("combat")
    if not shows or bf1.get("controller") != "p2" or lone_combat is not None:
        fail("T2 showdown", f"staged {shows} {staged.get('reason')}; bf1 controller {bf1.get('controller')}")
    # T3: another enemy unit there - a combat, not a non-combat showdown
    with_other = cast(board(other_enemy=True))
    other_after = with_other.get("next_effect_state") or {}
    other_show = (stage_showdown(fixture(), other_after).get("next_timing_state") or {}).get("staged_showdowns") or []
    combat = stage_combat(fixture(), other_after)
    staged_combat = (combat.get("next_timing_state") or {}).get("combat") or {}
    if not with_other.get("committed") or other_show or staged_combat.get("participants") != ["p1", "p2"]:
        fail("T3 combat", f"{with_other.get('reason')} showdown {other_show} combat {combat.get('reason')}")
    # T4: end of turn - control reverts, recalled to the owner's base
    fired, final, why = end_of_turn(after)
    if why != "resolved" or len(fired) != 1:
        fail("T4 end of turn", f"{fired} {why}")
    else:
        e1_end = final["objects"]["e1"]
        if e1_end.get("controller") != "p2" or where(final, "e1") != "p2:base" or e1_end.get("control_effects") \
                or final.get("delayed_triggers") or IR.validate_state(final):
            fail("T4 end of turn", f"e1 {e1_end.get('controller')} at {where(final, 'e1')} {e1_end.get('control_effects')}")
    # T5: e1 left the board - nothing fires
    killed = IR.apply_program(after, {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "k",
                                      "controller": "p2", "effects": [{"op": "kill", "effect_id": "k", "object_id": "e1"}]})
    if not killed.get("committed"):
        fail("T5 left board", f"kill refused: {killed.get('errors') or killed.get('reason')}")
    else:
        fired, final, why = end_of_turn(killed["next_state"])
        if fired or where(killed["next_state"], "e1") != "p2:trash":
            fail("T5 left board", f"fired {fired} ({why}); e1 at {where(killed['next_state'], 'e1')}")
    # T6: during this turn's Ending Phase - not generated, the control stays
    late = cast(board(), ending=True)
    late_after = late.get("next_effect_state") or {}
    if not late.get("committed") or late_after.get("delayed_triggers") \
            or (late_after.get("objects") or {}).get("e1", {}).get("controller") != "p1":
        fail("T6 ending phase", f"{late.get('reason')} delayed {late_after.get('delayed_triggers')}")
    # T7: a newer control effect stays when the takeover's ends
    back = IR.apply_program(after, {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "back",
                                    "controller": "p2", "effects": [{"op": "gain_control", "effect_id": "g", "object_id": "e1",
                                                                     "player": "p2"}]})
    if not back.get("committed") or back["next_state"]["objects"]["e1"]["controller"] != "p2":
        fail("T7 another effect", f"taking it back: {back.get('errors') or back.get('reason')}")
    else:
        fired, final, why = end_of_turn(back["next_state"])
        e1_end = (final or {}).get("objects", {}).get("e1") or {}
        if why != "resolved" or e1_end.get("controller") != "p2" or where(final, "e1") != "p2:base":
            fail("T7 another effect", f"{why}: e1 {e1_end.get('controller')} at {where(final or {}, 'e1')} "
                                      f"{e1_end.get('control_effects')}")
    # V
    base_prog = {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "v", "controller": "p1"}
    if not IR.validate_program({**base_prog, "effects": [{"op": "gain_control", "effect_id": "g", "object_id": "e1",
                                                          "player": "p1", "duration": "until_ended"}]}):
        fail("V", "a gain_control with a duration and no control_id validated")
    if not IR.validate_program({**base_prog, "effects": [{"op": "lose_control", "effect_id": "l", "object_id": "e1"}]}):
        fail("V", "a lose_control with no control_id validated")
    bad = copy.deepcopy(after)
    bad["objects"]["e1"]["controller"] = "p2"
    if not IR.validate_state(bad):
        fail("V", "a controller that is not the newest control effect's player validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: Hostile Takeover")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: Hostile Takeover takes control of an enemy unit at a battlefield until the end of the turn (a control "
          "effect, Contested there: a non-combat showdown alone, a combat with other enemies) and readies it; at the end "
          "of the turn the delayed trigger bound to it ends that effect and recalls it to its controller's base - not for "
          "a unit that left the board, not generated in the Ending Phase, a newer control effect kept (G1, T1-T7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
