#!/usr/bin/env python3
"""Regression gate for Vision (Core 817; 436).

    817.1.b  short for "When this is played, predict."
    817.1.c  the trigger is the permanent entering the Board
    817.2.a  the player chooses to recycle or not
    817.3    Vision is a characteristic
    436.1    Predict with no number is Predict 1

Must hold, through the real play transaction, play completion and resolution:
  - a Unit with Vision played to its Base: its play completion schedules one Vision
    trigger bound to the engine's Predict 1 program by content hash;
  - resolving it: recycling the looked card puts it on the bottom; declining keeps it on
    top; nobody else sees the card (the choice is private);
  - "[Vision]" lowered by the engine grammar is the keyword;
  - negatives: the same Unit without Vision schedules nothing; a program with the
    Vision id but other content is refused by dispatch; a Vision Unit already on the
    board is a valid state (placement is no play, so it goes through no play completion);
  - mutation: without the Vision production no trigger is scheduled.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import engine_decisions as ed  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import has_keyword, hash_value, object_identity, validate_state  # noqa: E402
import rules_core as RC  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

CLOSED = {"add_window_closed": True, "confirmed_by": "human"}


def board(*, vision=True):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2})
    if vision:
        state["objects"]["c1"]["keywords"] = ["vision"]
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return state


def declaration():
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
            "payment_context": dict(CLOSED)}


def completed(state):
    played = PT.play_card(fixture(), state, declaration())
    assert played.get("committed"), played.get("reason")
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "unit-1", played["next_effect_state"], None)


def recycle(state, value):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [
        {"decision_id": "vision:recycle", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": value,
         "selection_identities": {i: object_identity(state, i) or f"{i}@0" for i in value}}]}


def main() -> int:
    errors: list[str] = []
    done = completed(board())
    items = done.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not done.get("committed") or [i["id"] for i in items] != ["c1:vision"]:
        errors.append(f"playing a Vision Unit did not schedule its Vision trigger: {done.get('reason')} {[i.get('id') for i in items]}")
        print("FAILED: Vision checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    state, trig = done["next_effect_state"], items[0]
    program = IR.vision_program(state, "c1", "p1")
    got, why = dispatch_program({program["program_id"]: program}, trig)
    if got is None:
        errors.append(f"dispatch refused the engine's own Vision program: {why}")
    forged = copy.deepcopy(program); forged["effects"][0]["count"] = 3
    if dispatch_program({program["program_id"]: forged}, trig)[0] is not None:
        errors.append("dispatch accepted a program under the Vision id with other content")

    # finalize it (383.3, 337.1), pass until it resolves, and the controller chooses
    registry = {program["program_id"]: program}
    finalized = finalize_trigger(done["next_timing_state"], state, registry, None)
    if not finalized.get("committed"):
        errors.append(f"the Vision trigger did not finalize: {finalized.get('reason')}")
        print("FAILED: Vision checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    timing = finalized["next_timing_state"]
    for _ in range(4):
        if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
            break
        timing = RC.pass_priority(timing, timing["priority"])["next_state"]
    top = state["players"]["p1"]["zones"]["main_deck"][0]
    ask = resolve_with_program(timing, "c1:vision", state, program)
    effect = ask.get("effect_result") or {}
    if ask.get("committed") or effect.get("reason_code") != "card_selection_required" or effect.get("decision_ids") != ["vision:recycle"]:
        errors.append(f"Vision did not stop for the recycle choice: {effect.get('reason_code')} {ask.get('reason')}")
    elif effect.get("choice", {}).get("visibility") != "private_to_chooser":
        errors.append("the looked card is not private to its controller")
    kept = resolve_with_program(timing, "c1:vision", state, program, engine_decisions=recycle(state, []))
    if not kept.get("committed") or kept["next_effect_state"]["players"]["p1"]["zones"]["main_deck"][0] != top:
        errors.append(f"declining to recycle did not keep the card on top: {kept.get('reason_code')} {kept.get('reason')}")
    gone = resolve_with_program(timing, "c1:vision", state, program, engine_decisions=recycle(state, [top]))
    if not gone.get("committed") or gone["next_effect_state"]["players"]["p1"]["zones"]["main_deck"][-1] != top:
        errors.append(f"recycling did not put the card on the bottom: {gone.get('reason_code')} {gone.get('reason')}")

    # the keyword, lowered by the engine grammar, and read as a characteristic
    fields = (CG.compile_clause("[Vision]", CG.load_grammar()).get("passive") or {}).get("object_fields") or {}
    if fields.get("keywords") != ["vision"]:
        errors.append(f"[Vision] did not lower to the keyword: {fields}")
    if not has_keyword(state, "c1", "vision"):
        errors.append("Vision is not a characteristic other effects can read (817.3)")

    # negatives
    plain = completed(board(vision=False))
    if not plain.get("committed") or plain["next_timing_state"]["chain"]["items"]:
        errors.append("a Unit without Vision scheduled a trigger at play completion")
    placed = base_state(); placed["objects"]["u1"]["keywords"] = ["vision"]
    if validate_state(placed):
        errors.append(f"a Vision Unit on the board is not a valid state: {validate_state(placed)}")

    # mutation: without the production there is no trigger
    saved = IR.vision_triggers
    try:
        IR.vision_triggers = lambda *_a, **_k: []
        mutated = completed(board())
    finally:
        IR.vision_triggers = saved
    if mutated.get("committed") and mutated["next_timing_state"]["chain"]["items"]:
        errors.append("mutation not caught: with no Vision production the trigger was still scheduled")

    if errors:
        print("FAILED: Vision checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a Vision Unit's play completion schedules one trigger bound to the engine's Predict 1 (817.1.b-c, 436.1); "
          "recycling or keeping the top card is the controller's private choice (817.2.a); a Unit without Vision, a "
          "forged program and a missing production are all caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
