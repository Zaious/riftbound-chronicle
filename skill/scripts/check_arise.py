#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Arise!, "Play a 2 [M] Sand Soldier unit token for each Equipment you control. Then
do this: Ready up to two of them."): a play_token repeated once per Equipment its controller controls as it executes
(repeat_per friendly_objects; each copy its own place, Core 185.2.a), then "Then do this:" - a Reflexive Trigger with no
condition (Core 388.1, 388.2), its own Chain item (389.1), as Dragon's Rage's and Guards!'s are. It carries every token the
plays made (trigger_event kind played_group, the identities they entered with); "up to two of them" are its targets,
chosen among those tokens as it is finalized (Core 355.5), checked again as it resolves.

  R1 added       three of p1's Equipment (one attached), one of p2's, an untagged gear: three Sand Soldiers, 2 Might,
                 p1's, exhausted, each where its own place choice put it; one reflexive item pending, carrying all three
  R2 two         finalized choosing two of them: it resolves - those two ready, the third exhausted
  R3 illegal     a unit that is not one of them, or three of them, are refused at finalization
  R4 gone after  two chosen, one killed before it resolves: the other is readied, the dead one is not
  R5 zero        finalized choosing none: it resolves readying nothing
  R6 none made   no Equipment: no token; the trigger is still added (388.2) carrying an empty group
  R7 unbound     the same selector in a program whose event is not a group refuses every object by name
  V              repeat_per friendly_objects on another op, or counting a spell, does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, evaluate_target, hash_value, object_identity, validate_program  # noqa: E402
from effect_ir import _bind_referent_exclusion  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

TRIGGER = "arise-reflexive"
REFLEXIVE = "arise-reflexive-fx"
TOKEN = {"op": "play_token", "effect_id": "tok", "owner": "p1", "controller": "p1", "token_kind": "unit", "base_might": 2,
         "token_id": "sand_soldier", "object_id_ref": {"kind": "fresh"}, "destination": {"decision_ref": "token-place"},
         "repeat_per": {"kind": "friendly_objects", "of": {"kind": "gear", "with_tag": "Equipment"}}}
THEM = {"chosen_zone_class": "board", "kind": "unit", "among_trigger_event_objects": True}
READY = {"op": "ready", "effect_id": "rdy", "targets": {"decision_ref": "them", "min": 0, "max": 2, "restrictions": dict(THEM)}}


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "spell-1",
            "effects": [copy.deepcopy(e) for e in effects], **extra}


def spell():
    return program("spell-1-effects", [TOKEN], conditional_triggers=[
        {"trigger_id": TRIGGER, "controller": "p1", "source_object": "spell-1", "controller_order": 0,
         "effect_program_id": REFLEXIVE, "optional_at_finalize": False,
         "condition": {"kind": "unconditional", "effect_id": "tok"}}])


REGISTRY = {REFLEXIVE: program(REFLEXIVE, [READY])}


def board(mine=3):
    s = base_state()
    gears = [(f"eq{k + 1}", "p1", ["Equipment"]) for k in range(mine)] + [("xq1", "p2", ["Equipment"]), ("g1", "p1", [])]
    for oid, owner, tags in gears:
        s["objects"][oid] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False, "tags": tags}
        if oid == "eq1":
            s["objects"][oid]["attached_to"] = "u1"
        s["players"][owner]["zones"]["base"].append(oid)
    return s


def resolve_spell(state, count):
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    places = [{"decision_id": f"token-place#{k + 1}", "stage": "resolution", "kind": "location_selection",
               "controller": "p1", "value": "base:p1"} for k in range(count)]
    envelope = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": places} \
        if places else None
    return resolve_with_program(timing, "spell-1", state, spell(), engine_decisions=envelope)


def choose(state, values):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "them", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": list(values), "selection_identities": {v: object_identity(state, v) for v in values}}]}


def pending(done):
    return [i for i in (done.get("next_timing_state") or {}).get("chain", {}).get("items", [])
            if i.get("trigger_kind") == "reflexive"]


def resolve_trigger(finalized, *, between=None):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    if between is not None:
        effect = between(effect)
    return resolve_with_program(timing, TRIGGER, effect, REGISTRY[REFLEXIVE])


def kill(state, oid):
    return apply_program(state, {**program("k", [{"op": "kill", "effect_id": "k", "object_id": oid}]),
                                 "controller": "p2"})["next_state"]


def soldiers(state):
    return sorted(o for o, obj in state["objects"].items() if obj.get("token_id") == "sand_soldier"
                  and o in state["players"]["p1"]["zones"]["base"])


def main() -> int:
    errors: list[str] = []
    if validate_program(spell()) or validate_program(REGISTRY[REFLEXIVE]):
        errors.append(f"V: {validate_program(spell())[:2]} {validate_program(REGISTRY[REFLEXIVE])[:2]}")
    done = resolve_spell(board(), 3)
    after = done.get("next_effect_state") or {}
    made = soldiers(after) if done.get("committed") else []
    items = pending(done)
    event = (items[0].get("trigger_event") or {}) if len(items) == 1 else {}
    if not done.get("committed") or len(made) != 3 or event.get("kind") != "played_group" \
            or sorted(event.get("objects") or []) != made \
            or any(after["objects"][o]["exhausted"] is not True or after["objects"][o]["base_might"] != 2 for o in made):
        errors.append(f"R1 added: {done.get('reason') or done.get('reason_code')} {made} {event}")
        return report(errors)
    timing = done["next_timing_state"]
    two = finalize_trigger(timing, after, REGISTRY, choose(after, made[:2]))
    if not two.get("committed") or two.get("removed"):
        errors.append(f"R2 two: not finalized: {two.get('reason')} {two.get('message')}")
    else:
        got = resolve_trigger(two)
        st = got.get("next_effect_state") or {}
        states = [bool(st["objects"][o]["exhausted"]) for o in made] if got.get("committed") else None
        if states != [False, False, True]:
            errors.append(f"R2 two: {states} {got.get('reason') or got.get('reason_code')}")
        gone = resolve_trigger(two, between=lambda s: kill(s, made[0]))
        st = gone.get("next_effect_state") or {}
        if not gone.get("committed") or made[0] in st["objects"] and made[0] in soldiers(st) \
                or st["objects"][made[1]]["exhausted"] is not False or st["objects"][made[2]]["exhausted"] is not True:
            errors.append(f"R4 gone after: {gone.get('reason') or gone.get('reason_code')}")
    for label, values in (("a unit not of them", [made[0], "u1"]), ("three of them", made)):
        refused = finalize_trigger(timing, after, REGISTRY, choose(after, values))
        if refused.get("committed") and not refused.get("removed"):
            errors.append(f"R3 illegal: {label} was finalized")
    zero = finalize_trigger(timing, after, REGISTRY, choose(after, []))
    if not zero.get("committed") or zero.get("removed"):
        errors.append(f"R5 zero: not finalized: {zero.get('reason')} {zero.get('message')} {zero.get('transition')}")
    else:
        got = resolve_trigger(zero)
        st = got.get("next_effect_state") or {}
        if not got.get("committed") or any(st["objects"][o]["exhausted"] is not True for o in made):
            errors.append(f"R5 zero: {got.get('reason') or got.get('reason_code')}")
    none = resolve_spell(board(mine=0), 0)
    items = pending(none)
    if not none.get("committed") or soldiers(none.get("next_effect_state") or {}) or len(items) != 1 \
            or (items[0].get("trigger_event") or {}).get("objects") != []:
        errors.append(f"R6 none made: {none.get('reason') or none.get('reason_code')} {[i.get('trigger_event') for i in items]}")
    for label, event in (("a single played object", {"kind": "played", "object": made[0],
                                                     "identity": object_identity(after, made[0])}), ("no event", None)):
        bound = _bind_referent_exclusion({**THEM, "object_id": made[0]},
                                         {"trigger_event": event} if event else {})
        ok, why = evaluate_target(after, bound, "p1")
        if ok or why != "target_referent_group_not_recorded":
            errors.append(f"R7 unbound: {label}: {ok} {why}")
    bad = program("x", [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1,
                         "repeat_per": {"kind": "friendly_objects", "of": {"kind": "gear"}}}])
    if not validate_program(bad):
        errors.append("V: repeat_per friendly_objects on a draw validated")
    bad = program("x", [{**TOKEN, "repeat_per": {"kind": "friendly_objects", "of": {"kind": "spell"}}}])
    if not validate_program(bad):
        errors.append("V: repeat_per counting spells validated")
    return report(errors)


def report(errors) -> int:
    if errors:
        print("arise checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("arise checks passed: one Sand Soldier per Equipment its controller controls (theirs and untagged gear not "
          "counted), each placed by its own choice; 'Then do this:' a reflexive item carrying them all; up to two of them "
          "chosen at finalization (another unit or three refused), checked again as it resolves; none made, an empty "
          "group; an unbound group refused by name; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
