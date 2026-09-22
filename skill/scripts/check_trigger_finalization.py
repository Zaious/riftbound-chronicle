#!/usr/bin/env python3
"""A triggered ability's targets are bound when it is finalized; its program is dispatched by content.

Core 355.5.b: choices for a permanent's triggered ability are not made as the permanent
is played. Core 383.3 / 337.1: the ability goes on the Chain and its controller completes
the steps of playing it until it is Finalized - Core 355.5's choice among them. Core
359.3.e: a target illegal at resolution is mistargeted; it is never chosen again.

The engine already knew the `trigger_finalization` decision stage, but nothing checked a
target at finalization, a caller could hand resolution a fresh selection, and a chain
item bound only the ID of its program. Held here:

  the path          play -> trigger scheduled -> finalize_trigger (dispatch + target
                    binding, recorded on the chain item) -> priority -> resolve with NO
                    decisions supplied: the recorded target is what gets hit
  no decision       a trigger with a targeted instruction and no target selection is
                    not finalized; nor with one for the wrong stage, by the wrong
                    player, or naming an illegal target
  mistarget         bound, then illegal before resolution: the instruction is ignored
                    and nothing else is hit; a different selection handed to
                    resolution is refused, not honoured
  another unit      the source exclusion is bound when the target is chosen: the ability's
                    own source is refused, a different friendly unit is accepted
  battlefield       a Battlefield's own Hold trigger (no controller on the descriptor, Core
                    190.6.a) is scheduled by the Scoring Step with its program hash,
                    finalized, dispatched and resolved the same way; a malformed hash on its
                    descriptor does not validate, a swapped body is refused
  program identity  an unregistered ID, a registry body swapped under the right ID, and
                    a swapped program handed straight to resolution are each refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import hash_value, object_identity, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, next_procedure, pass_priority  # noqa: E402
from battlefield_control import SCORING_TASK, run_scoring_step  # noqa: E402

TRIGGER, PROGRAM_ID = "c1-on-play", "c1-on-play-effects"
RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}


def program(amount: int = 2) -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": PROGRAM_ID,
            "controller": "p1", "source_object": "c1",
            "effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                         "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                    "controller_relation": "enemy", "location": "base"}}]}


def board(*, with_hash: bool = True) -> dict:
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"]["kind"] = "unit"
    state["objects"]["c1"]["base_might"] = 2
    descriptor = {"trigger_id": TRIGGER, "controller": "p1", "source_object": "c1", "controller_order": 0,
                  "effect_program_id": PROGRAM_ID, "optional_at_finalize": False}
    if with_hash:
        descriptor["effect_program_hash"] = program_hash(program())
    state["objects"]["c1"]["play_triggers"] = [descriptor]
    # a second enemy unit, so "a different target" exists to be wrongly chosen later
    state["objects"]["u9"] = copy.deepcopy(state["objects"]["u2"])
    state["players"]["p2"]["zones"]["base"].append("u9")
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return state


def enter(state: dict) -> tuple[dict, dict]:
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                   "cost": {"base": {"energy": 2, "power": {}}},
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"},
                   "entry_location": {"kind": "base"}}
    played = play_card(fixture(), state, declaration)
    assert played.get("committed"), played.get("reason")
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    entered = resolve_with_program(timing, "unit-1", played["next_effect_state"], None)
    assert entered.get("committed"), entered.get("reason")
    return entered["next_timing_state"], entered["next_effect_state"]


def choose(state: dict, object_id: str, *, stage: str = "trigger_finalization", controller: str = "p1") -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": "t", "stage": stage, "kind": "target_selection", "controller": controller,
                           "value": [object_id], "selection_identities": {object_id: object_identity(state, object_id)}}]}


def to_resolution(timing: dict) -> dict:
    for actor in ("p1", "p2"):
        timing = pass_priority(timing, actor).get("next_state") or timing
    return timing


def main() -> int:
    errors: list[str] = []
    registry = {PROGRAM_ID: program()}

    # --- the path -------------------------------------------------------------------
    timing, state = enter(board())
    pending = [(i["id"], i["status"], i.get("effect_program_hash")) for i in timing["chain"]["items"]]
    if pending != [(TRIGGER, "pending", program_hash(program()))]:
        errors.append(f"the trigger did not reach the Chain pending with its program hash: {pending}")
    finalized = finalize_trigger(timing, state, registry, choose(state, "u2"))
    if not finalized.get("committed"):
        errors.append(f"finalization with a legal target was refused: {finalized.get('stage')} {finalized.get('reason')}")
        print("FAILED: trigger finalization" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    chain_item = finalized["next_timing_state"]["chain"]["items"][0]
    if chain_item["status"] != "finalized" or [e["value"] for e in chain_item.get("finalized_targets", [])] != [["u2"]]:
        errors.append(f"the chosen target was not recorded on the finalized item: {chain_item.get('finalized_targets')}")
    ready = to_resolution(finalized["next_timing_state"])
    if next_procedure(ready).get("subject") != TRIGGER:
        errors.append(f"after both passes the engine's next procedure is {next_procedure(ready).get('procedure')}")
    dispatched, refusal = dispatch_program(registry, ready["chain"]["items"][0])
    if refusal is not None:
        errors.append(f"dispatch refused the registered program: {refusal}")
    done = resolve_with_program(ready, TRIGGER, state, dispatched)          # no decisions supplied
    if not done.get("committed") or done["next_effect_state"]["objects"]["u2"].get("damage") != 2:
        errors.append(f"resolution did not hit the recorded target: {done.get('stage')} {done.get('reason')}")
    elif done["next_effect_state"]["objects"]["u9"].get("damage"):
        errors.append("resolution hit a unit that was never chosen")
    if done.get("committed") and validate_state(done["next_effect_state"]):
        errors.append("the state after resolution does not validate")

    # --- counter-example 1: no target decision, no finalization -----------------------
    for label, decisions, want in (
        ("no decision", None, "target_selection_required"),
        ("a play_declaration decision", choose(state, "u2", stage="play_declaration"), "decision_stage_mismatch"),
        ("the opponent's decision", choose(state, "u2", controller="p2"), "decision_controller_mismatch"),
        ("a friendly unit for an enemy selector", choose(state, "u1"), "target_illegal_at_play"),
    ):
        refused = finalize_trigger(timing, state, registry, decisions)
        if refused.get("committed") or refused.get("reason") != want:
            errors.append(f"{label}: expected {want}, got committed={refused.get('committed')} reason={refused.get('reason')}")
        if refused.get("next_timing_state") is not None:
            errors.append(f"{label}: a refused finalization returned a next timing state")
    if [i["status"] for i in timing["chain"]["items"]] != ["pending"]:
        errors.append("a refused finalization mutated the timing state it was given")

    # --- counter-example 2: bound, then illegal - mistargeted, never re-chosen -----------
    moved = copy.deepcopy(state)
    moved["players"]["p2"]["zones"]["base"].remove("u2")
    moved["battlefields"]["bf1"]["objects"].append("u2")        # no longer "in its base"
    settle_contested(moved)
    if validate_state(moved):
        errors.append(f"the mistarget board does not validate: {validate_state(moved)[:2]}")
    miss = resolve_with_program(ready, TRIGGER, moved, dispatched)
    outcomes = [step.get("outcome") for step in (miss.get("trace") or {}).get("effect") or []]
    if not miss.get("committed") or outcomes != ["ignored_illegal_target"]:
        errors.append(f"a target illegal at resolution was not mistargeted: committed={miss.get('committed')} {outcomes} {miss.get('reason')}")
    elif any(miss["next_effect_state"]["objects"][o].get("damage") for o in ("u2", "u9")):
        errors.append("mistargeting still damaged a unit")
    rechoose = resolve_with_program(ready, TRIGGER, moved, dispatched, engine_decisions=choose(moved, "u9"))
    if rechoose.get("committed") or rechoose.get("reason") != "target_changed_after_finalization":
        errors.append(f"a new target handed to resolution was not refused: committed={rechoose.get('committed')} reason={rechoose.get('reason')}")
    same = resolve_with_program(ready, TRIGGER, state, dispatched, engine_decisions=choose(state, "u2"))
    if not same.get("committed"):
        errors.append(f"re-supplying the SAME recorded selection was refused: {same.get('reason')}")

    # --- counter-example 3: the right ID over a different program --------------------------
    swapped = {PROGRAM_ID: program(amount=9)}
    at_finalize = finalize_trigger(timing, state, swapped, choose(state, "u2"))
    if at_finalize.get("committed") or at_finalize.get("reason") != "effect_program_hash_mismatch":
        errors.append(f"a swapped registry body was finalized: {at_finalize.get('reason')}")
    at_resolve = resolve_with_program(ready, TRIGGER, state, program(amount=9))
    if at_resolve.get("committed") or at_resolve.get("reason") != "effect_program_hash_mismatch":
        errors.append(f"a swapped program handed to resolution ran: {at_resolve.get('reason')}")
    _none, unregistered = dispatch_program({}, ready["chain"]["items"][0])
    if (unregistered or {}).get("reason") != "effect_program_not_registered":
        errors.append(f"an unregistered program ID was not refused: {unregistered}")
    # a descriptor WITHOUT a hash still gets one at finalization, so resolution is bound too
    timing_plain, state_plain = enter(board(with_hash=False))
    late = finalize_trigger(timing_plain, state_plain, registry, choose(state_plain, "u2"))
    late_item = (late.get("next_timing_state") or {"chain": {"items": [{}]}})["chain"]["items"][0]
    if late_item.get("effect_program_hash") != program_hash(program()):
        errors.append("finalization did not bind the dispatched program's hash onto the chain item")
    elif resolve_with_program(to_resolution(late["next_timing_state"]), TRIGGER, state_plain, program(amount=9)).get("reason") != "effect_program_hash_mismatch":
        errors.append("a program swapped after finalization ran on an item whose descriptor had no hash")

    # --- "another unit": the source exclusion is bound when the target is chosen ------------
    another = program()
    another["effects"][0]["target"] = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                       "controller_relation": "friendly", "exclude_source_identity": "$source_identity"}
    timing_a, state_a = enter(board(with_hash=False))
    own_source = finalize_trigger(timing_a, state_a, {PROGRAM_ID: another}, choose(state_a, "c1"))
    if own_source.get("committed") or "target_excludes_source" not in (own_source.get("message") or ""):
        errors.append(f"'another unit' accepted its own source as the target: {own_source.get('reason')} {own_source.get('message')}")
    other_unit = finalize_trigger(timing_a, state_a, {PROGRAM_ID: another}, choose(state_a, "u1"))
    if not other_unit.get("committed"):
        errors.append(f"'another unit' refused a different friendly unit: {other_unit.get('reason')} {other_unit.get('message')}")

    # --- a Battlefield's own trigger: "When you hold here" (Core 190.6.a, 469.2, 383.4.d) --------
    # Its descriptor names no controller (the Battlefield's controller when it triggers) and
    # lives on the Battlefield, not an object; the Scoring Step schedules it. It is finalized
    # and dispatched exactly like an object's trigger, and its program hash binds the same way.
    hold_id, hold_program_id = "bf1-on-hold", "bf1-on-hold-effects"
    hold_program = {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": hold_program_id,
                    "controller": "p1", "source_object": "bf1",
                    "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]}
    grove = base_state()
    grove["mode"] = {"victory_score": 8}
    grove["battlefields"]["bf1"]["controller"] = "p1"
    grove["battlefields"]["bf1"]["hold_triggers"] = [{"trigger_id": hold_id, "controller_order": 0, "effect_program_id": hold_program_id,
                                                    "optional_at_finalize": False, "effect_program_hash": program_hash(hold_program)}]
    if validate_state(grove):
        errors.append(f"a hashed Battlefield trigger descriptor did not validate: {validate_state(grove)[:2]}")
    bad_hash = copy.deepcopy(grove)
    bad_hash["battlefields"]["bf1"]["hold_triggers"][0]["effect_program_hash"] = "not-a-hash"
    if not validate_state(bad_hash):
        errors.append("a Battlefield trigger descriptor with a malformed program hash validated")
    beginning = {**fixture(tasks=[SCORING_TASK]), "phase": "beginning", "priority": None}
    held = run_scoring_step(beginning, grove)
    held_items = [(i["id"], i["status"], i.get("source_object"), i.get("effect_program_hash")) for i in held.get("next_timing_state", {}).get("chain", {}).get("items", [])]
    if not held.get("committed") or held_items != [(hold_id, "pending", "bf1", program_hash(hold_program))]:
        errors.append(f"the Hold did not schedule the Battlefield's trigger with its program hash: {held.get('reason_code')} {held_items}")
    else:
        hold_registry = {hold_program_id: hold_program}
        bound = finalize_trigger(held["next_timing_state"], held["next_effect_state"], hold_registry, None)
        swapped_hold = finalize_trigger(held["next_timing_state"], held["next_effect_state"],
                                        {hold_program_id: {**hold_program, "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 5}]}}, None)
        if swapped_hold.get("committed") or swapped_hold.get("reason") != "effect_program_hash_mismatch":
            errors.append(f"a swapped Battlefield trigger program was finalized: {swapped_hold.get('reason')}")
        if not bound.get("committed"):
            errors.append(f"the Battlefield's Hold trigger was not finalized: {bound.get('stage')} {bound.get('reason')}")
        else:
            ready_hold = to_resolution(bound["next_timing_state"])
            hold_program_found, hold_refusal = dispatch_program(hold_registry, ready_hold["chain"]["items"][0])
            drew = resolve_with_program(ready_hold, hold_id, held["next_effect_state"], hold_program_found) if hold_refusal is None else {}
            before_hand = len(held["next_effect_state"]["players"]["p1"]["zones"]["hand"])
            if not drew.get("committed") or len(drew["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != before_hand + 1:
                errors.append(f"the Battlefield's Hold trigger did not resolve and draw 1: {hold_refusal} {drew.get('reason')}")

    if errors:
        print("FAILED: trigger finalization" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a triggered ability's target is bound at finalization and recorded on the chain item (Core 355.5.b, 383.3, "
          "337.1); without a legal, right-stage, right-player selection it is not finalized; a target illegal by resolution "
          "is mistargeted and never re-chosen (Core 359.3.e); and its program is dispatched by ID and refused if the content "
          "under that ID changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
