#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Rumble - Hotheaded, "When I conquer, you may recycle another friendly unit to play a
Mech from your trash. Reduce its Energy cost by the Might of the unit you recycled.").

"you may X to Y": its controller decides at finalization whether to perform it (Core 383.3.a); performing it, "recycle
another friendly unit" is its base cost (383.3.b), paid then (383.3.b.1) - one unit its controller controls on the board,
not the source, chosen then, recycled (417). The Mech in its trash is the play's target, chosen then too (355.10.a). As it
resolves the Mech is played (420.3) with an Energy discount equal to the Might the recycled unit had as it was paid.

  R1 paid      finalized recycling m1 (Might 3), the Mech chosen: m1 is at the bottom of p1's Main Deck; the receipt keeps
               Might 3
  R2 played    it resolves: the Mech's effect-driven play starts, its cost basis an Energy discount of 3
  R3 small     recycling m2 (Might 1): a discount of 1
  R4 no might  recycling m0 (Might 0): no discount - the printed cost
  R5 asked     with two candidates and no choice, the recycle choice is asked (cost_selection_required)
  R6 only me   no other friendly unit on the board: not payable - the trigger leaves the Chain, nothing recycled
  R7 not a Mech a non-Mech unit in the trash is refused as the play's target
  R8 declined  not performed: nothing recycled, nothing played
  R9 leaves    the recycled unit has a leave trigger and a death trigger: it left the board - the leave trigger is Pending
               behind the finalized ability; a recycle is no death - the death trigger is not (GPT A2 review, blocker 2)
  V            recycle_unit with other false, or another amount_ref, does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, hash_value, object_identity, validate_program  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority, schedule_triggered_items  # noqa: E402

TRIGGER = "rb-conquer"
COST = {"op": "trigger_base_cost", "effect_id": "cost", "payment": [{"kind": "recycle_unit", "other": True}]}
PLAY = {"op": "limited_play", "effect_id": "play",
        "target": {"decision_ref": "mech", "chosen_zone_class": "non_board", "location": "trash", "zone_owner_relation": "own",
                   "kind": "unit", "with_tag": "Mech"},
        "cost_basis": {"kind": "discount_energy", "amount_ref": {"kind": "recycled_unit_might"}}}
PROGRAM = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
           "program_id": "rb-conquer-fx", "controller": "p1", "source_object": "rb", "effects": [COST, PLAY]}
REGISTRY = {"rb-conquer-fx": PROGRAM}
WINDOW = {"add_window_closed": True, "confirmed_by": "harness"}


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(mates=(("m1", 3), ("m2", 1), ("m0", 0))):
    s = base_state()
    s["objects"]["rb"] = unit("p1", 4)
    s["battlefields"]["bf1"]["objects"].append("rb")
    for oid, might in mates:
        s["objects"][oid] = unit("p1", might)
        s["players"]["p1"]["zones"]["base"].append(oid)
    s["objects"]["mc"] = {**unit("p1", 3), "tags": ["Mech"], "printed_cost": {"energy": 5, "power": {}}}
    s["objects"]["nu"] = {**unit("p1", 2), "tags": [], "printed_cost": {"energy": 2, "power": {}}}
    s["players"]["p1"]["zones"]["trash"] += ["mc", "nu"]
    s["players"]["p1"]["resources"] = {"energy": 5, "power": {}}
    return settle_contested(s)


def pending(state):
    descriptor = {"trigger_id": TRIGGER, "controller": "p1", "source_object": "rb", "controller_order": 0,
                  "effect_program_id": "rb-conquer-fx", "optional_at_finalize": True, "trigger_kind": "triggered",
                  "batch_sequence": 0, "batch_id": "conquer:bf1", "source_identity": object_identity(state, "rb")}
    return schedule_triggered_items(fixture(), [descriptor])["next_state"]


def choices(state, mech="mc", recycled="m1"):
    out = [{"decision_id": "mech", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
            "value": [mech], "selection_identities": {mech: object_identity(state, mech)}}]
    if recycled:
        out.append({"decision_id": f"trigger_cost:{TRIGGER}:recycle_unit", "stage": "trigger_finalization",
                    "kind": "card_selection", "controller": "p1", "value": [recycled],
                    "selection_identities": {recycled: object_identity(state, recycled)}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": out}


def finalize(state, *, perform=True, **kw):
    return finalize_trigger(pending(state), state, REGISTRY, choices(state, **kw), perform_optional_trigger=perform,
                            **({"pay_trigger_cost": True, "payment_context": WINDOW} if perform else {}))


def resolve(finalized):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, TRIGGER, effect, PROGRAM)


def started(done):
    """The cost basis of the effect-driven play the resolution started, or None."""
    items = (done.get("next_timing_state") or {}).get("chain", {}).get("items", [])
    records = [((done.get("next_effect_state") or {}).get("chain_items") or {}).get(i.get("id"), {}).get("limited_play")
               for i in items]
    records = [r for r in records if r]
    return records[0].get("cost_basis") if len(records) == 1 else None


def main() -> int:
    errors: list[str] = []
    if validate_program(PROGRAM):
        errors.append(f"V: {validate_program(PROGRAM)[:2]}")
    for label, recycled, want in (("R1/R2", "m1", {"kind": "discount_energy", "amount": 3}),
                                  ("R3 small", "m2", {"kind": "discount_energy", "amount": 1}),
                                  ("R4 no might", "m0", {"kind": "printed"})):
        s = board()
        fin = finalize(s, recycled=recycled)
        after = fin.get("next_effect_state") or {}
        deck = (after.get("players") or {}).get("p1", {}).get("zones", {}).get("main_deck", [])
        if not fin.get("committed") or fin.get("removed") or not deck or deck[-1] != recycled:
            errors.append(f"{label}: finalization {fin.get('reason')} {fin.get('message')} deck {deck[-2:]}")
            continue
        done = resolve(fin)
        basis = started(done) if done.get("committed") else None
        if basis != want:
            errors.append(f"{label}: the play's cost basis {basis} ({done.get('reason') or done.get('reason_code')})")
    s = board()
    asked = finalize_trigger(pending(s), s, REGISTRY, choices(s, recycled=None), perform_optional_trigger=True,
                             pay_trigger_cost=True, payment_context=WINDOW)
    if asked.get("committed") or asked.get("reason") != "cost_selection_required":
        errors.append(f"R5 asked: {asked.get('committed')} {asked.get('reason')}")
    alone = board(mates=())
    alone["players"]["p1"]["zones"]["base"].remove("u1")
    del alone["objects"]["u1"]
    left = finalize(alone, recycled=None)
    if not left.get("committed") or not left.get("removed") or (left.get("transition") or {}).get("type") != "trigger_cost_unpayable":
        errors.append(f"R6 only me: {left.get('reason')} {left.get('transition')}")
    wrong = finalize(board(), mech="nu")
    if wrong.get("committed") and not wrong.get("removed"):
        errors.append("R7 not a Mech: a non-Mech unit was finalized as the play's target")
    s = board()
    no = finalize_trigger(pending(s), s, REGISTRY, None, perform_optional_trigger=False)
    after = no.get("next_effect_state") or {}
    if not no.get("committed") or (no.get("transition") or {}).get("type") != "optional_trigger_declined" \
            or "m1" not in after["players"]["p1"]["zones"]["base"]:
        errors.append(f"R8 declined: {no.get('reason')} {no.get('transition')}")
    # R9 (GPT A2 review, blocker 2): the unit recycled as the cost leaves the board - its leave trigger goes on the Chain,
    # Pending, behind the finalized ability (Core 383.3); a recycle is no death, so its death trigger does not
    s = board()
    s["objects"]["m1"]["leave_board_triggers"] = [{"trigger_id": "m1-leave", "controller": "p1", "source_object": "m1",
                                                   "controller_order": 0, "effect_program_id": "m1-leave-fx",
                                                   "optional_at_finalize": False}]
    s["objects"]["m1"]["death_triggers"] = [{"trigger_id": "m1-dies", "controller": "p1", "source_object": "m1",
                                             "controller_order": 0, "effect_program_id": "m1-dies-fx",
                                             "optional_at_finalize": False}]
    fin = finalize(s, recycled="m1")
    chain = [(i["id"], i.get("status")) for i in (fin.get("next_timing_state") or {}).get("chain", {}).get("items", [])]
    deck = ((fin.get("next_effect_state") or {}).get("players") or {}).get("p1", {}).get("zones", {}).get("main_deck", [])
    if not fin.get("committed") or chain != [(TRIGGER, "finalized"), ("m1-leave", "pending")] or deck[-1:] != ["m1"]:
        errors.append(f"R9 leaves: {fin.get('reason')} chain {chain} deck {deck[-1:]}")
    bad = copy.deepcopy(PROGRAM)
    bad["effects"][0]["payment"][0]["other"] = False
    if not validate_program(bad):
        errors.append("V: recycle_unit other false validated")
    bad = copy.deepcopy(PROGRAM)
    bad["effects"][1]["cost_basis"]["amount_ref"] = {"kind": "linked_paid_amount"}
    if not validate_program(bad):
        errors.append("V: another amount_ref validated")
    return report(errors)


def report(errors) -> int:
    if errors:
        print("rumble-hotheaded checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("rumble-hotheaded checks passed: another friendly unit recycled as the trigger's base cost at finalization (its "
          "Might kept), the Mech in the trash played with that much Energy off (none for Might 0); the choice asked; only "
          "the source - unpayable; a non-Mech refused; declined - nothing; the recycled unit's leave trigger Pending, no death "
          "trigger (R1-R9); validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
