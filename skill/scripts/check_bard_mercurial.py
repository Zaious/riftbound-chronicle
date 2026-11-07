#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Bard - Mercurial, "You may exhaust your legend as an additional cost to play me. When
you play me, if you paid the additional cost, move any number of your units to an open battlefield.").

  L1 chosen     p1's Legend in its Legend Zone exhausted, the offer paid on the receipt
  L2 declined   the Legend stays ready, the offer unpaid
  L3 exhausted  the Legend already exhausted: chosen, the play is refused (Core 203.3); the text lowers to the offer
  O1 group      u1 and u3 move to bf2 - open (no unit, no controller): both arrive
  O2 occupied   bf1 (a unit there) is no destination of the Move (Core 170.11.c)
  O3 controlled bf3, p1's with no unit: not open - no destination
  F1 finalized  the trigger finalized with its units but no destination: refused (move_destination_required)
  F2 recorded   finalized with bf2: the destination is on the item's finalized_targets beside the units
  F3 kept       at resolution another destination is refused (destination_changed_after_finalization); with none
                supplied every unit goes to the recorded bf2 - the expansion never chooses again (Core 170.11.c)
  V  validation an authored moving_with on another restriction does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_printed_costs import component, decisions, intent, play, state, where  # noqa: E402
from effect_ir import (PROGRAM_VERSION, CORE_RULESET, FAQ_AS_OF, apply_program, hash_value, move_destination_candidates,  # noqa: E402
                       object_identity, validate_program, validate_state)
from check_effect_ir import base_state  # noqa: E402

TEXT = "You may exhaust your legend as an additional cost to play me."
MOVE = {"op": "move_board_object", "effect_id": "mv",
        "targets": {"min": 0, "any_number": True, "decision_ref": "t",
                    "restrictions": {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}},
        "destination": {"decision_ref": "d", "restriction": "open_battlefield"}}


def legend_board(fields, exhausted=False):
    s = state(fields, energy=6, printed=(4, None))
    s["objects"]["lg"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": exhausted}
    s["players"]["p1"]["zones"].setdefault("legend_zone", []).append("lg")
    return s


def move_board():
    s = base_state()
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("u3")
    s["battlefields"]["bf2"] = {"controller": None, "objects": []}
    # bf1 occupied: p2's u2 there, p2's
    s["players"]["p2"]["zones"]["base"].remove("u2")
    s["battlefields"]["bf1"] = {"controller": "p2", "objects": ["u2"]}
    s["battlefields"]["bf3"] = {"controller": "p1", "objects": []}
    return s


def program():
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "bard", "controller": "p1", "effects": [copy.deepcopy(MOVE)]}


def finalized_destination(s) -> list[str]:
    """F1-F3 (GPT's A2 review, Bard: Core 170.11.c): the open Battlefield is chosen as the trigger is finalized and recorded
    with its targets; the expansion over the units reads that record and never chooses again."""
    from check_rules_core import fixture
    from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program
    from rules_core import complete_resolution, schedule_triggered_items  # noqa: F401
    import rules_core as RC
    out = []
    s = copy.deepcopy(s)
    s["objects"]["bd"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("bd")
    prog = {**program(), "source_object": "bd"}
    registry = {prog["program_id"]: prog}
    descriptor = {"trigger_id": "bard", "controller": "p1", "source_object": "bd", "controller_order": 0,
                  "effect_program_id": prog["program_id"], "optional_at_finalize": False,
                  "effect_program_hash": program_hash(prog), "trigger_kind": "triggered",
                  "source_identity": object_identity(s, "bd")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    targets = {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
               "value": ["u1", "u3"], "selection_identities": {o: object_identity(s, o) for o in ("u1", "u3")}}

    def env(*entries):
        return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": list(entries)}
    place = {"decision_id": "d", "stage": "trigger_finalization", "kind": "location_selection", "controller": "p1",
             "value": "battlefield:bf2"}
    missing = finalize_trigger(scheduled["next_state"], s, registry, env(targets))
    if missing.get("committed") or missing.get("reason") not in ("move_destination_required", "target_selection_required",
                                                                  "location_selection_required"):
        out.append(f"F1 at finalization: finalized with no destination chosen ({missing.get('reason')})")
    fin = finalize_trigger(scheduled["next_state"], s, registry, env(targets, place))
    if not fin.get("committed"):
        return out + [f"F2 recorded: {fin.get('reason')} {fin.get('message')}"]
    t, state_now = fin["next_timing_state"], fin["next_effect_state"]
    item = next(i for i in t["chain"]["items"] if i["id"] == "bard")
    if not any(e.get("decision_id") == "d" and e.get("value") == "battlefield:bf2" for e in item.get("finalized_targets") or []):
        out.append(f"F2 recorded: the destination is not on the finalized item {item.get('finalized_targets')}")
    while RC.next_procedure(t).get("procedure") != "resolve_newest_finalized":
        holder = t.get("priority")
        passed = RC.pass_priority(t, holder) if holder else {}
        if not passed.get("next_state"):
            break
        t = passed["next_state"]
    prog_now, _ = dispatch_program(registry, item)
    other = {**place, "stage": "resolution", "value": "battlefield:bf3"}
    changed = resolve_with_program(t, "bard", state_now, prog_now,
                                   engine_decisions={"schema_version": "engine-decisions.v1",
                                                     "input_hash": hash_value(state_now), "decisions": [other]})
    if changed.get("committed") or changed.get("reason") != "destination_changed_after_finalization":
        out.append(f"F3 not re-chosen: another destination at resolution gave {changed.get('reason')}")
    done = resolve_with_program(t, "bard", state_now, prog_now)
    if not done.get("committed") or sorted(done["next_effect_state"]["battlefields"]["bf2"]["objects"]) != ["u1", "u3"]:
        out.append(f"F3 the record: {done.get('reason')} {done.get('stage')}")
    return out


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    fields = copy.deepcopy((got.get("passive") or {}).get("object_fields") or {})
    if got.get("production_id") != "you_may_exhaust_your_legend_as_an_additional_cost_to_play_me" \
            or (fields.get("printed_additional_costs") or [{}])[0].get("payment") != {"kind": "exhaust", "amount": 1,
                                                                                       "object_kind": "legend"}:
        errors.append(f"L3: lowered to {got.get('production_id')} {fields}")
    for offer in fields.get("printed_additional_costs") or []:
        offer["cost_offer_id"] = "b"
    one = legend_board(fields)
    if validate_state(one):
        errors.append(f"fixture invalid: {validate_state(one)[:2]}")
    paid = play(one, printed=(4, None), with_decisions=decisions(one, intent("self_offer:b", True)))
    if not paid.get("committed") or not paid["next_effect_state"]["objects"]["lg"].get("exhausted") \
            or not (component(paid, "self_offer:b") or {}).get("paid"):
        errors.append(f"L1 chosen: {paid.get('reason_code')} {paid.get('reason')}")
    declined = play(one, printed=(4, None), with_decisions=decisions(one, intent("self_offer:b", False)))
    if not declined.get("committed") or declined["next_effect_state"]["objects"]["lg"].get("exhausted"):
        errors.append(f"L2 declined: {declined.get('reason_code')}")
    tired = legend_board(fields, exhausted=True)
    if play(tired, printed=(4, None), with_decisions=decisions(tired, intent("self_offer:b", True))).get("committed"):
        errors.append("L3 exhausted: an exhausted Legend paid the offer")
    s = move_board()
    if validate_program(program()):
        errors.append(f"V: {validate_program(program())[:2]}")
    offered = move_destination_candidates(s, "u1", MOVE["destination"])
    if offered != ["battlefield:bf2"]:
        errors.append(f"O2/O3: destinations offered {offered}")
    env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": ["u1", "u3"], "selection_identities": {o: object_identity(s, o) for o in ("u1", "u3")}},
        {"decision_id": "d", "stage": "play_declaration", "kind": "location_selection", "controller": "p1",
         "value": "battlefield:bf2"}]}
    done = apply_program(s, program(), decisions=env)
    after = done.get("next_state") or {}
    if not done.get("committed") or sorted(after["battlefields"]["bf2"]["objects"]) != ["u1", "u3"]:
        errors.append(f"O1 group: {done.get('reason_code')} {done.get('reason') or done.get('errors')} "
                      f"{after.get('battlefields', {}).get('bf2')}")
    errors += finalized_destination(s)
    bad = copy.deepcopy(MOVE)
    bad["destination"] = {"decision_ref": "d", "restriction": "battlefield", "moving_with": ["u1"]}
    if not validate_program({**program(), "effects": [bad]}):
        errors.append("V: moving_with on another restriction validated")
    if errors:
        print("bard-mercurial checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("bard-mercurial checks passed: the Legend exhausted as the optional cost (declined, ready; already exhausted, "
          "refused); a group Move to an open Battlefield - every unit arrives, an occupied or controlled one offered none; the destination chosen and recorded at finalization, never re-chosen (F1-F3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
