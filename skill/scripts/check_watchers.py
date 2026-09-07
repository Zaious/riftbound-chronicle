#!/usr/bin/env python3
"""Regression gate for C-55 (ADR-0014 §2): watchers, delayed triggers,
per-turn counters and trigger multipliers.

Must hold:
  - a watcher reacts to *another* object's event, which the typed trigger
    lists could not express: a Unit whose ability watches for a friendly Unit
    dying fires when its neighbour dies, and the scope really filters —
    `self` sees only its own events, `controller` only its controller's,
    `location` only what happens where it is;
  - the visibility boundary of ADR-0013 §3 holds at the watch: a watcher may
    react to a public fact, but one whose condition would read a card its
    controller may not see is refused by name (`watch_beyond_visibility`)
    instead of being answered from the engine's omniscience;
  - a delayed trigger is bound to the identities it was created with
    (Core 124): it fires once, and a target that became a new object drops it
    with its reason instead of firing on the stranger — the negative mutation
    re-binds the same delayed trigger to the new identity and it fires, so the
    binding is what refuses it, not the fixture;
  - a delayed trigger waiting for the end of the turn fires in the Ending Step
    alongside the printed ones and is then gone from the state;
  - Core 383.3.e: a trigger that has been performed its allowance this turn
    does not trigger at all, a "you may" declined at finalization has *not*
    been performed and keeps its use (383.3.e.2.b), and the counters reset
    with the turn;
  - a multiplier adds its copies at causal depth 1 and never applies to the
    copies it produced, and a depth beyond the declared bound is refused as
    `trigger_multiplier_depth`.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import watchers as w  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, validate_state  # noqa: E402
from resolution_bridge import begin_ending_step  # noqa: E402

TURN = "turn-7"


def descriptor(trigger_id, source, kinds, scope, *, controller="p1", condition=None, limit=None, ability=None):
    entry = {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
             "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False,
             "watch": {"kinds": list(kinds), "scope": scope}}
    if condition is not None:
        entry["watch"]["condition"] = condition
    if limit is not None:
        entry["per_turn_limit"] = limit
    if ability is not None:
        entry["ability_id"] = ability
    return entry


def board(**extra):
    """u1, u2 and u3 all on the board; u1 and u3 are p1's, u2 is p2's."""
    state = base_state()
    state["turn_id"] = TURN
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("u3")
    state.update(extra)
    return state


def kill(state, object_id):
    return apply_program(state, program("k", {"op": "kill", "effect_id": "k", "object_id": object_id}))


def main() -> int:
    errors: list[str] = []

    # --- a watcher reacts to another object's event ------------------------------------------
    state = board()
    state["objects"]["u1"]["event_triggers"] = [descriptor("u1-watch-deaths", "u1", ["died"], "controller")]
    if found := validate_state(state):
        errors.append(f"a watcher descriptor was rejected: {found}")
    result = kill(state, "u3")
    if not result.get("committed"):
        print("FAILED: watcher checks")
        print(f"  - the kill fixture did not commit: {result.get('reason_code')} {result.get('reason')}")
        return 1
    scheduled = w.schedule_watchers(result["next_state"], result["events"], turn_id=TURN)
    if [entry["trigger_id"] for entry in scheduled] != ["u1-watch-deaths"]:
        errors.append(f"a watcher did not react to another object's death: {scheduled}")
    elif scheduled[0]["watched_object"] != "u3" or scheduled[0]["watched_kind"] != "died":
        errors.append(f"the scheduled watcher did not carry the event it woke on: {scheduled[0]}")

    # scope really filters
    enemy = kill(state, "u2")
    if w.schedule_watchers(enemy["next_state"], enemy["events"], turn_id=TURN):
        errors.append("a `controller` watcher reacted to an opponent's Unit dying")
    self_only = copy.deepcopy(state)
    self_only["objects"]["u1"]["event_triggers"] = [descriptor("u1-self", "u1", ["died"], "self")]
    other = kill(self_only, "u3")
    if w.schedule_watchers(other["next_state"], other["events"], turn_id=TURN):
        errors.append("a `self` watcher reacted to another object's death")
    own = kill(self_only, "u1")
    if [entry["trigger_id"] for entry in w.schedule_watchers(own["next_state"], own["events"], turn_id=TURN)] != ["u1-self"]:
        errors.append("a `self` watcher did not react to its own death")
    anything = copy.deepcopy(state)
    anything["objects"]["u1"]["event_triggers"] = [descriptor("u1-any", "u1", ["died"], "any")]
    enemy_any = kill(anything, "u2")
    if [entry["trigger_id"] for entry in w.schedule_watchers(enemy_any["next_state"], enemy_any["events"], turn_id=TURN)] != ["u1-any"]:
        errors.append("negative mutation failed: widening the scope to `any` did not change what matched, so the scope filter is vacuous")

    # a watcher that only reacts to the kind, with no condition, may watch a
    # private event: the fact is public even when the card is not.
    watch_draws = copy.deepcopy(state)
    watch_draws["objects"]["u1"]["event_triggers"] = [descriptor("u1-draws", "u1", ["drawn"], "any")]
    public_fact = apply_program(watch_draws, program("d", {"op": "draw", "effect_id": "d", "player": "p2", "count": 1}))
    if not public_fact.get("committed"):
        errors.append(f"the draw fixture did not commit: {public_fact.get('reason')}")
    elif [e["trigger_id"] for e in w.schedule_watchers(public_fact["next_state"], public_fact["events"], turn_id=TURN)] != ["u1-draws"]:
        errors.append("a watcher could not react to the public fact that an opponent drew")
    # the same watcher with a condition on the drawn card is refused: p1 may
    # not see what p2 drew, and the engine will not answer from omniscience.
    conditioned = copy.deepcopy(public_fact["next_state"])
    conditioned["objects"]["u1"]["event_triggers"] = [
        descriptor("u1-draws-units", "u1", ["drawn"], "any", condition={"kind": "might_at_least", "count": 1})]
    try:
        w.schedule_watchers(conditioned, public_fact["events"], turn_id=TURN)
        errors.append("a watcher tested a condition on a card its controller may not see")
    except w.WatchUnsupported as exc:
        if exc.reason_code != "watch_beyond_visibility":
            errors.append(f"the visibility refusal is not named: {exc.reason_code}")
    # the same condition on the drawing player's own watcher is answered
    own_draw = copy.deepcopy(conditioned)
    own_draw["objects"]["u1"]["event_triggers"][0]["controller"] = "p2"
    own_draw["objects"]["u1"]["controller"] = "p2"
    try:
        w.schedule_watchers(own_draw, public_fact["events"], turn_id=TURN)
    except w.WatchUnsupported:
        errors.append("negative mutation failed: the refusal is not about visibility, since the drawing "
                      "player's own watcher was refused too")

    # --- delayed triggers -----------------------------------------------------------------------
    delayed_spec = {"delayed_id": "revenge", "controller": "p1", "source_object": "u1", "target_object": "u2",
                    "waits_for": {"kind": "event", "kinds": ["died"], "scope": "any"},
                    "effect_program_id": "revenge-effects", "optional_at_finalize": False, "controller_order": 0,
                    "snapshot": {"amount": 2}}
    created = apply_program(board(), program("dt", {"op": "create_delayed_trigger", "effect_id": "dt",
                                                    "delayed": copy.deepcopy(delayed_spec)}))
    if not created.get("committed"):
        errors.append(f"creating a delayed trigger failed: {created.get('reason_code')} {created.get('reason')}")
    else:
        entry = created["next_state"]["delayed_triggers"][0]
        if entry.get("source_identity") != "u1@0" or entry.get("target_identity") != "u2@0" or entry.get("created_turn") != TURN:
            errors.append(f"the delayed trigger did not bind its identities and turn: {entry}")
        if [e["kind"] for e in created["events"]] != ["delayed_trigger_created"]:
            errors.append(f"creating a delayed trigger emitted the wrong events: {[e['kind'] for e in created['events']]}")
        armed = created["next_state"]
        fired_run = kill(armed, "u2")
        fired, dropped = w.delayed_matches(fired_run["next_state"], fired_run["events"], turn_id=TURN)
        if [entry["delayed_id"] for entry in fired] != ["revenge"] or dropped:
            errors.append(f"a delayed trigger bound to a live target did not fire: {fired} {dropped}")
        elif fired[0].get("snapshot") != {"amount": 2}:
            errors.append("the delayed trigger fired without the snapshot it was created with")
        settled = w.settle_delayed(fired_run["next_state"], fired, dropped)
        if settled.get("delayed_triggers"):
            errors.append("a delayed trigger that fired stayed armed")
        again, _ = w.delayed_matches(settled, fired_run["events"], turn_id=TURN)
        if again:
            errors.append("a delayed trigger fired twice")

        # Core 124: the target left and came back, so it is a new object.
        renewed = copy.deepcopy(armed)
        renewed["objects"]["u2"]["identity"] = "u2@1"
        renewed_run = kill(renewed, "u2")
        fired, dropped = w.delayed_matches(renewed_run["next_state"], renewed_run["events"], turn_id=TURN)
        if fired or [entry["reason"] for entry in dropped] != ["target_identity_changed"]:
            errors.append(f"a delayed trigger fired on a target that had become a new object: {fired} {dropped}")
        elif w.settle_delayed(renewed_run["next_state"], fired, dropped).get("delayed_triggers"):
            errors.append("the dropped delayed trigger was left armed")
        # negative mutation: bind it to the identity it now has and it fires,
        # so the binding is what refused it.
        rebound = copy.deepcopy(renewed)
        rebound["delayed_triggers"][0]["target_identity"] = "u2@1"
        rebound_run = kill(rebound, "u2")
        fired, dropped = w.delayed_matches(rebound_run["next_state"], rebound_run["events"], turn_id=TURN)
        if [entry["delayed_id"] for entry in fired] != ["revenge"] or dropped:
            errors.append(f"negative mutation failed: re-binding to the new identity did not make it fire: {fired} {dropped}")

    # the end-of-turn moment, through the real Ending Step
    ending_state = board()
    ending_state["delayed_triggers"] = [{
        "delayed_id": "at-end", "controller": "p1", "source_object": "u1", "source_identity": "u1@0",
        "waits_for": {"kind": "turn", "moment": "end_of_turn", "turn_id": TURN},
        "effect_program_id": "at-end-effects", "optional_at_finalize": False, "controller_order": 0,
        "created_turn": TURN,
    }]
    if found := validate_state(ending_state):
        errors.append(f"a delayed trigger waiting for the end of the turn was rejected: {found}")
    ended = begin_ending_step(fixture(), ending_state)
    if not ended.get("committed"):
        errors.append(f"the Ending Step refused the delayed trigger: {ended.get('reason_code')} {ended.get('reason')}")
    else:
        items = [item["id"] for item in ended["next_timing_state"]["chain"]["items"]]
        if items != ["at-end"]:
            errors.append(f"the delayed trigger did not fire in the Ending Step: {items}")
        if ended["next_effect_state"].get("delayed_triggers"):
            errors.append("the delayed trigger stayed armed after the Ending Step")
        if ended["trace"].get("delayed_triggers") != ["at-end"]:
            errors.append(f"the Ending Step's trace does not name the delayed trigger: {ended['trace']}")
        other_turn = copy.deepcopy(ending_state)
        other_turn["delayed_triggers"][0]["waits_for"]["turn_id"] = "turn-8"
        later = begin_ending_step(fixture(), other_turn)
        if later.get("next_timing_state", {}).get("chain", {}).get("items"):
            errors.append("a delayed trigger waiting for another turn fired this turn")

    # --- per-turn counters (Core 383.3.e) --------------------------------------------------------
    limited = board()
    limited["objects"]["u1"]["event_triggers"] = [descriptor("u1-once", "u1", ["died"], "controller", limit=1,
                                                             ability="once-each-turn")]
    run = kill(limited, "u3")
    first = w.schedule_watchers(run["next_state"], run["events"], turn_id=TURN)
    if len(first) != 1 or first[0].get("per_turn_limit") != 1:
        errors.append(f"a limited trigger did not schedule once with its limit: {first}")
    spent = w.record_performed(run["next_state"], limited["objects"]["u1"]["event_triggers"][0], TURN)
    if w.uses_spent(spent, limited["objects"]["u1"]["event_triggers"][0], TURN) != 1:
        errors.append("performing the ability did not spend its use")
    if w.schedule_watchers(spent, run["events"], turn_id=TURN):
        errors.append("a trigger performed its allowance still triggered (Core 383.3.e)")
    declined = w.record_performed(run["next_state"], limited["objects"]["u1"]["event_triggers"][0], TURN, performed=False)
    if not w.schedule_watchers(declined, run["events"], turn_id=TURN):
        errors.append("declining a `you may` at finalization spent the use (Core 383.3.e.2.b)")
    unlimited = copy.deepcopy(spent)
    unlimited["objects"]["u1"]["event_triggers"][0].pop("per_turn_limit")
    if not w.schedule_watchers(unlimited, run["events"], turn_id=TURN):
        errors.append("negative mutation failed: without the limit the trigger still refused to schedule, "
                      "so the counter is not what stopped it")
    next_turn = w.reset_turn_uses(spent, "turn-8")
    if next_turn.get("trigger_uses"):
        errors.append(f"the per-turn counters survived the turn: {next_turn.get('trigger_uses')}")
    if not w.schedule_watchers({**next_turn, "turn_id": "turn-8"}, run["events"], turn_id="turn-8"):
        errors.append("the trigger did not come back on the next turn")
    same_turn = w.reset_turn_uses(spent, TURN)
    if same_turn.get("trigger_uses") != spent.get("trigger_uses"):
        errors.append("the reset dropped this turn's own counters")

    # --- multipliers ------------------------------------------------------------------------------
    multiplied = board()
    multiplied["objects"]["u1"]["event_triggers"] = [descriptor("u1-watch", "u1", ["died"], "controller")]
    multiplied["trigger_multipliers"] = [{
        "multiplier_id": "echo", "controller": "p1", "source_object": "u1",
        "applies_to": {"kinds": ["died"], "scope": "any"}, "extra_times": 1,
    }]
    if found := validate_state(multiplied):
        errors.append(f"a trigger multiplier was rejected: {found}")
    run = kill(multiplied, "u3")
    base_schedule = w.schedule_watchers(run["next_state"], run["events"], turn_id=TURN)
    expanded = w.apply_multipliers(run["next_state"], base_schedule, run["events"])
    if [entry["causal_depth"] for entry in expanded] != [0, 1]:
        errors.append(f"the multiplier did not add exactly one copy at depth 1: {[e['causal_depth'] for e in expanded]}")
    elif expanded[1].get("multiplied_by") != "echo" or expanded[1]["trigger_id"] != "u1-watch":
        errors.append(f"the copy does not name the multiplier and the trigger it copied: {expanded[1]}")
    if w.apply_multipliers(run["next_state"], [expanded[1]], run["events"]) != [expanded[1]]:
        errors.append("the multiplier applied to the copy it produced")
    beyond = [{**base_schedule[0], "causal_depth": w.MAX_CAUSAL_DEPTH + 1}]
    try:
        w.apply_multipliers(run["next_state"], beyond, run["events"])
        errors.append("a trigger beyond the declared causal depth was scheduled anyway")
    except w.WatchUnsupported as exc:
        if exc.reason_code != "trigger_multiplier_depth":
            errors.append(f"the depth refusal is not named: {exc.reason_code}")
    unwatched = copy.deepcopy(run["next_state"])
    unwatched.pop("trigger_multipliers")
    if w.apply_multipliers(unwatched, base_schedule, run["events"]) != base_schedule:
        errors.append("negative mutation failed: the copies appeared without any multiplier in the state")

    # --- validation ---------------------------------------------------------------------------------
    bad_kind = board()
    bad_kind["objects"]["u1"]["event_triggers"] = [descriptor("bad", "u1", ["exploded"], "any")]
    if not any("catalogue" in error for error in validate_state(bad_kind)):
        errors.append("a watch on an event kind outside the catalogue was accepted")
    bad_scope = board()
    bad_scope["objects"]["u1"]["event_triggers"] = [descriptor("bad", "u1", ["died"], "everywhere")]
    if not validate_state(bad_scope):
        errors.append("a watch with an unknown scope was accepted")
    half_bound = board()
    half_bound["delayed_triggers"] = [{
        "delayed_id": "half", "controller": "p1", "source_object": "u1", "source_identity": "u1@0",
        "target_object": "u2", "waits_for": {"kind": "event", "kinds": ["died"], "scope": "any"},
        "effect_program_id": "x", "optional_at_finalize": False, "controller_order": 0, "created_turn": TURN,
    }]
    if not any("identity" in error for error in validate_state(half_bound)):
        errors.append("a delayed trigger that names a target without binding its identity was accepted")
    duplicate = apply_program(created["next_state"], program("dt2", {"op": "create_delayed_trigger", "effect_id": "dt2",
                                                                     "delayed": copy.deepcopy(delayed_spec)}))
    if duplicate.get("committed"):
        errors.append("the same delayed_id was created twice")

    if errors:
        print("FAILED: watcher checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("watcher, delayed trigger, per-turn counter and multiplier checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
