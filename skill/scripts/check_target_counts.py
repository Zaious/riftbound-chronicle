#!/usr/bin/env python3
"""How many targets an instruction takes, and whether two target slots are different objects.

Two shapes of choice the engine already executes, held at the moment the targets are
chosen - a spell's play (Core 355.5) and a triggered ability's finalization (Core 383.3) -
rather than discovered when the instruction resolves:

  a bounded count   `targets {min, max, decision_ref}`. "Up to N" is 0..N (Core 355.13:
                    zero targets is a legal choice and the spell is played without any);
                    "N" (exactly) is N..N. Core 355.8: a spell goes on the Chain only with
                    valid choices for all of its targets, so a count outside the bounds is
                    refused at play by name (target_count_out_of_range), the pool and the
                    card untouched. Before this gate a wrong count was accepted at play and
                    failed only at resolution.
  a pair of slots   `units [slot, slot]` of a composite instruction ("they deal damage equal
                    to their Mights to each other"): each slot is one Unit, chosen at play
                    like any target, each legal on its own, and the two are different objects
                    (GPT 2026-09-25). One object in both slots is refused at play and at
                    finalization (target_slots_not_distinct); resolution re-checks the pair
                    and never chooses again.

At resolution (Core 359.3.e.8): an instruction with several targets, some of which became
illegal, executes on the ones still legal; one whose every target is illegal does not
execute (359.3.e.7). A pair with one illegal Unit deals no damage at all (359.3.e.5).

The programs run here are the shapes the overlay maps card sentences to (up to two units /
two friendly units / up to two friendly units at battlefields to their Base / a friendly
and an enemy unit dealing damage to each other). Every fixture is synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (effective_might, find_location, hash_value, object_identity,  # noqa: E402
                       validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
UNIT = {"chosen_zone_class": "board", "kind": "unit"}
FRIENDLY = {**UNIT, "controller_relation": "friendly"}
ENEMY = {**UNIT, "controller_relation": "enemy"}

UP_TO_TWO_UNITS = {"op": "deal_damage", "effect_id": "dmg", "amount": 6,
                   "targets": {"min": 0, "max": 2, "decision_ref": "t", "restrictions": dict(UNIT)}}
TWO_FRIENDLY = {"op": "modify_might", "effect_id": "mm", "amount": 2, "duration": "this_turn", "source": "spell-1",
                "targets": {"min": 2, "max": 2, "decision_ref": "t", "restrictions": dict(FRIENDLY)}}
UP_TO_TWO_TO_BASE = {"op": "move_board_object", "effect_id": "mv",
                     "destination": {"kind": "base", "player_relation": "object_controller"},
                     "targets": {"min": 0, "max": 2, "decision_ref": "t",
                                 "restrictions": {**FRIENDLY, "location": "battlefield"}}}
PAIR = {"op": "mutual_damage_current_might", "effect_id": "duel",
        "units": [{"decision_ref": "a", **FRIENDLY}, {"decision_ref": "b", **ENEMY}]}
ANY_PAIR = {"op": "mutual_damage_current_might", "effect_id": "duel",
            "units": [{"decision_ref": "a", **UNIT}, {"decision_ref": "b", **UNIT}]}


def board() -> dict:
    """p1: u1 (3 Might, 1 damage), u3 and u6 (2 Might) at bf1, u5 (5 Might) in its Base.
    p2: u2 (4 Might) and u4 (1 Might) at bf1. c1 is the spell, in p1's hand."""
    state = base_state()
    p1, p2 = state["players"]["p1"]["zones"], state["players"]["p2"]["zones"]
    p1["main_deck"].remove("c1")
    p1["hand"].append("c1")
    for object_id, owner, might in (("u3", "p1", 2), ("u5", "p1", 5), ("u4", "p2", 1), ("u6", "p1", 2)):
        state["objects"][object_id] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": might,
                                       "might_modifiers": [], "damage": 0, "exhausted": False}
    p1["base"], p2["base"] = ["u5"], []
    state["battlefields"]["bf1"]["objects"] = ["u1", "u3", "u2", "u4", "u6"]
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return settle_contested(state)


def spell_program(effect: dict) -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": "c1-effects",
            "controller": "p1", "effects": [copy.deepcopy(effect)]}


def choose(state: dict, stage: str = "play_declaration", **slots) -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": ref, "stage": stage, "kind": "target_selection", "controller": "p1",
                           "value": list(value), "selection_identities": {o: object_identity(state, o) for o in value}}
                          for ref, value in slots.items()]}


def play(state: dict, effect: dict, **slots) -> dict:
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
                   "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "c1-effects",
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return play_card(fixture(), state, declaration, engine_decisions=choose(state, **slots),
                     effect_program=spell_program(effect))


def resolve(played: dict, effect: dict, state: dict | None = None, **slots) -> dict:
    """Both players pass; the spell resolves. No decisions are handed to resolution: the
    targets it was played with ride on its chain entry. Slots given here are handed over
    as a resolution-time selection, which must be refused unless it IS the recorded one."""
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    effect_state = state if state is not None else played["next_effect_state"]
    decisions = None
    if slots:
        decisions = {**choose(played["_state"], **slots), "input_hash": hash_value(effect_state)}
    return resolve_with_program(timing, "spell-1", effect_state, spell_program(effect), engine_decisions=decisions)


def played_with(state: dict, effect: dict, **slots) -> dict:
    result = play(state, effect, **slots)
    result["_state"] = state
    return result


def refused(result: dict, reason: str) -> str | None:
    if result.get("committed") or result.get("reason_code") != reason:
        return f"expected {reason}, got committed={result.get('committed')} reason={result.get('reason_code')} {result.get('reason')}"
    if result.get("next_effect_state_hash") not in (None, result.get("input_effect_state_hash")):
        return "a refused play moved the effect state"
    return None


def main() -> int:
    errors: list[str] = []
    state = board()
    if validate_state(state):
        errors.append(f"the fixture board does not validate: {validate_state(state)[:2]}")

    # --- up to two units: 0, 1 and 2 are legal; 3 is refused at play -------------------------------
    for label, chosen in (("two", ["u1", "u2"]), ("one", ["u2"]), ("zero", [])):
        played = played_with(state, UP_TO_TWO_UNITS, t=chosen)
        if not played.get("committed"):
            errors.append(f"up to two units, {label} chosen: the play was refused ({played.get('reason_code')} {played.get('reason')})")
            continue
        done = resolve(played, UP_TO_TWO_UNITS)
        if not done.get("committed"):
            errors.append(f"up to two units, {label} chosen: resolution refused ({done.get('reason')})")
            continue
        after = done["next_effect_state"]
        for object_id in ("u1", "u2", "u3", "u4", "u5"):
            want = state["objects"][object_id]["damage"] + (6 if object_id in chosen else 0)
            if after["objects"][object_id]["damage"] != want:
                errors.append(f"up to two units, {label} chosen: {object_id} has {after['objects'][object_id]['damage']} damage, not {want}")
    three = play(state, UP_TO_TWO_UNITS, t=["u1", "u2", "u3"])
    if problem := refused(three, "target_count_out_of_range"):
        errors.append(f"up to two units, three chosen: {problem}")

    # one of two targets leaves the board before resolution: the other is still dealt 6 (359.3.e.8)
    played = played_with(state, UP_TO_TWO_UNITS, t=["u1", "u2"])
    if played.get("committed"):
        gone = copy.deepcopy(played["next_effect_state"])
        gone["battlefields"]["bf1"]["objects"].remove("u2")
        gone["players"]["p2"]["zones"]["trash"].append("u2")
        gone["objects"]["u2"]["identity"] = "u2@1"            # a new object in the trash (Core 124)
        gone["objects"]["u2"]["damage"] = 0
        subset = resolve(played, UP_TO_TWO_UNITS, state=gone)
        event = ((subset.get("trace") or {}).get("effect") or [{}])[0]
        if not subset.get("committed") or event.get("target_outcome") != "applied_to_subset" \
                or subset["next_effect_state"]["objects"]["u1"]["damage"] != 7:
            errors.append(f"a target gone before resolution stopped the instruction for the other: "
                          f"committed={subset.get('committed')} {event.get('target_outcome')} {subset.get('reason')}")

    # --- two friendly units: exactly two, both friendly --------------------------------------------
    played = played_with(state, TWO_FRIENDLY, t=["u1", "u3"])
    if not played.get("committed"):
        errors.append(f"two friendly units: the play was refused ({played.get('reason_code')} {played.get('reason')})")
    else:
        done = resolve(played, TWO_FRIENDLY)
        after = done.get("next_effect_state") or {}
        got = {o: effective_might(after, o) for o in ("u1", "u3", "u5", "u2")} if after else None
        if got != {"u1": 5, "u3": 4, "u5": 5, "u2": 4}:
            errors.append(f"two friendly units +2: Mights are {got}")
    for label, chosen, reason in (("one", ["u1"], "target_count_out_of_range"),
                                  ("three", ["u1", "u3", "u5"], "target_count_out_of_range"),
                                  ("a friendly and an enemy", ["u1", "u2"], "target_illegal_at_play")):
        if problem := refused(play(state, TWO_FRIENDLY, t=chosen), reason):
            errors.append(f"two friendly units, {label}: {problem}")
    lonely = board()
    lonely["battlefields"]["bf1"]["objects"] = ["u1", "u2", "u4"]
    lonely["players"]["p1"]["zones"]["base"] = []
    del lonely["objects"]["u3"], lonely["objects"]["u5"], lonely["objects"]["u6"]
    if problem := refused(play(lonely, TWO_FRIENDLY, t=["u1"]), "target_count_out_of_range"):
        errors.append(f"two friendly units with only one on the board: {problem}")

    # --- up to two friendly units at battlefields to their Base ------------------------------------
    played = played_with(state, UP_TO_TWO_TO_BASE, t=["u1", "u3"])
    if not played.get("committed"):
        errors.append(f"move up to two to base: the play was refused ({played.get('reason_code')} {played.get('reason')})")
    else:
        after = resolve(played, UP_TO_TWO_TO_BASE).get("next_effect_state") or {}
        where = {o: find_location(after, o) for o in ("u1", "u3", "u2", "u5", "u6")} if after else {}
        if where != {"u1": ("player", "p1", "base"), "u3": ("player", "p1", "base"), "u2": ("battlefield", "bf1", None),
                     "u5": ("player", "p1", "base"), "u6": ("battlefield", "bf1", None)}:
            errors.append(f"move up to two to base: locations are {where}")
    for label, chosen, reason in (("a unit already in its Base", ["u5"], "target_illegal_at_play"),
                                  ("an enemy unit", ["u2"], "target_illegal_at_play"),
                                  ("three", ["u1", "u3", "u6"], "target_count_out_of_range")):
        if problem := refused(play(state, UP_TO_TWO_TO_BASE, t=chosen), reason):
            errors.append(f"move up to two to base, {label}: {problem}")
    none_moved = played_with(state, UP_TO_TWO_TO_BASE, t=[])
    if not none_moved.get("committed") or resolve(none_moved, UP_TO_TWO_TO_BASE).get("next_effect_state", {}).get("battlefields", {}).get("bf1", {}).get("objects") != ["u1", "u3", "u2", "u4", "u6"]:
        errors.append("move up to two to base with none chosen did not play and leave the board as it was")

    # --- a pair of slots: legal, different, re-checked at resolution -------------------------------
    played = played_with(state, PAIR, a=["u1"], b=["u2"])
    if not played.get("committed"):
        errors.append(f"a friendly and an enemy unit: the play was refused ({played.get('reason_code')} {played.get('reason')})")
    else:
        after = resolve(played, PAIR).get("next_effect_state") or {}
        got = {o: after["objects"][o]["damage"] for o in ("u1", "u2", "u3")} if after else None
        if got != {"u1": 1 + 4, "u2": 0 + 3, "u3": 0}:
            errors.append(f"the pair did not deal each other its Might: damage {got}")
        # resolution with the pair re-supplied differently is refused, never re-chosen;
        # the same selection handed back is accepted
        rechoose = resolve(played, PAIR, a=["u3"], b=["u2"])
        if rechoose.get("committed") or rechoose.get("reason") != "target_changed_after_play":
            errors.append(f"a different friendly unit handed to resolution was not refused: {rechoose.get('reason')}")
        if not resolve(played, PAIR, a=["u1"], b=["u2"]).get("committed"):
            errors.append("handing resolution the SAME recorded pair was refused")
        slots = [e["decision_id"] for e in played["next_effect_state"]["chain_items"]["spell-1"].get("played_targets") or []]
        if slots != ["a", "b"]:
            errors.append(f"the pair chosen at play is not recorded on the chain entry: {slots}")
    for label, effect, slots, reason in (
            ("the same unit in both slots", ANY_PAIR, {"a": ["u2"], "b": ["u2"]}, "target_slots_not_distinct"),
            ("two units in one slot", ANY_PAIR, {"a": ["u1", "u3"], "b": ["u2"]}, "target_count_out_of_range"),
            ("an enemy in the friendly slot", PAIR, {"a": ["u4"], "b": ["u2"]}, "target_illegal_at_play")):
        if problem := refused(play(state, effect, **slots), reason):
            errors.append(f"pair, {label}: {problem}")
    # one Unit of the pair illegal at resolution: neither deals damage (359.3.e.5)
    played = played_with(state, PAIR, a=["u1"], b=["u2"])
    if played.get("committed"):
        moved = copy.deepcopy(played["next_effect_state"])
        moved["objects"]["u1"]["controller"] = "p2"          # no longer friendly
        settle_contested(moved)
        miss = resolve(played, PAIR, state=moved)
        outcome = [e.get("outcome") for e in (miss.get("trace") or {}).get("effect") or []]
        if not miss.get("committed") or outcome != ["ignored_illegal_target"] \
                or miss["next_effect_state"]["objects"]["u2"]["damage"] != 0:
            errors.append(f"a pair with one illegal Unit at resolution still dealt damage: {outcome} {miss.get('reason')}")

    # --- the pair in a triggered ability: the same check at finalization ---------------------------
    trigger_program = {**spell_program(ANY_PAIR), "program_id": "c1-on-play-effects", "source_object": "c1"}
    registry = {"c1-on-play-effects": trigger_program}
    unit_board = board()
    unit_board["objects"]["c1"].update({"kind": "unit", "base_might": 2})
    unit_board["objects"]["c1"]["play_triggers"] = [{
        "trigger_id": "c1-on-play", "controller": "p1", "source_object": "c1", "controller_order": 0,
        "effect_program_id": "c1-on-play-effects", "optional_at_finalize": False,
        "effect_program_hash": program_hash(trigger_program)}]
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-2", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                   "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    entered_play = play_card(fixture(), unit_board, declaration)
    if not entered_play.get("committed"):
        errors.append(f"the triggering unit could not be played: {entered_play.get('reason')}")
    else:
        timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
        entered = resolve_with_program(timing, "unit-1", entered_play["next_effect_state"], None)
        t_state, e_state = entered["next_timing_state"], entered["next_effect_state"]
        same = finalize_trigger(t_state, e_state, registry, choose(e_state, "trigger_finalization", a=["u2"], b=["u2"]))
        if same.get("committed") or same.get("reason") != "target_slots_not_distinct":
            errors.append(f"a trigger finalized one Unit in both slots: {same.get('reason')}")
        distinct = finalize_trigger(t_state, e_state, registry, choose(e_state, "trigger_finalization", a=["u1"], b=["u2"]))
        if not distinct.get("committed"):
            errors.append(f"a trigger with two different Units was not finalized: {distinct.get('reason')} {distinct.get('message')}")

    if errors:
        print("FAILED: target counts and target slots")
        for problem in errors:
            print("  - " + problem)
        return 1
    print("target counts and slots: up to N (0..N) and exactly N held at play; a wrong count and one object "
          "in two slots refused at play and at finalization; a partly illegal set executes on the rest, "
          "an illegal pair deals nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
