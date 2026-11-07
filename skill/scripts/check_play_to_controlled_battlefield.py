#!/usr/bin/env python3
"""Regression gate (set 2 package A2, Here to Help: "You may play a unit from hand to a battlefield you control,
reducing its cost by [3]."): an effect-driven play whose unit enters a Battlefield its player controls, chosen as the
play is finalized - never its Base (Core 355.2.b). limited_play entry unit_at_battlefield_you_control; the record keeps
entry_restricted.

  H1 record       the play started: entry_restricted battlefield_you_control, no entry_location
  H2 offered      the finalization asks for the location; only bf2 (p1 controls it) - not p1's Base, not bf1 (p2's)
  H3 completed    completed at bf2: the unit is at bf2, its Energy cost reduced by 3
  H4 base         p1's Base named: refused
  H5 not p1's     bf1, which p2 controls, named: refused
  H6 nowhere      p1 controls no Battlefield: the unit is not played and stays in p1's hand
  H7 declined     "you may": no card chosen - nothing played, the unit in hand, the Energy unspent
  V               a record carrying entry_restricted beside an entry_location does not validate

    python skill/scripts/check_play_to_controlled_battlefield.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_limited_play import BASE, CLOSED, ava_board, pending_play, program, to_resolution  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, object_identity, validate_state  # noqa: E402
from resolution_bridge import (complete_limited_play, dispatch_program, finalize_limited_play,  # noqa: E402
                               finalize_trigger, program_hash, resolve_with_program)
from rules_core import schedule_triggered_items  # noqa: E402

errors: list[str] = []
HELP = program("here-to-help-effects", "ava", [
    {"op": "limited_play", "effect_id": "lp", "decision_ref": "c",
     "choice": {"from": "hand", "selection_kind": "unordered_set", "count": {"up_to": 1}, "by": "controller",
                "visibility": "private_to_chooser"}, "card_filter": {"kind": "unit"},
     "entry": {"kind": "unit_at_battlefield_you_control"}, "cost_basis": {"kind": "discount_energy", "amount": 3}}])
REGISTRY = {HELP["program_id"]: HELP}
BF1 = {"kind": "battlefield", "battlefield": "bf1"}
BF2 = {"kind": "battlefield", "battlefield": "bf2"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(*, controls_bf2=True) -> dict:
    state = ava_board()
    state["battlefields"]["bf2"] = {"controller": "p1" if controls_bf2 else None, "objects": []}
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {"mind": 2}}
    return state


def resolved(state: dict, chosen: list[str]) -> dict:
    descriptor = {"trigger_id": "help", "controller": "p1", "source_object": "ava", "controller_order": 0,
                  "effect_program_id": HELP["program_id"], "optional_at_finalize": False,
                  "effect_program_hash": program_hash(HELP), "trigger_kind": "triggered",
                  "source_identity": object_identity(state, "ava")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    assert scheduled.get("applied"), scheduled
    fin = finalize_trigger(scheduled["next_state"], state, REGISTRY, None, payment_context=CLOSED)
    assert fin.get("committed") and not fin.get("removed"), (fin.get("reason"), fin.get("message"))
    now = fin["next_effect_state"]
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(now),
                 "decisions": [{"decision_id": "c", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                                "value": list(chosen), "selection_identities": {c: object_identity(now, c) for c in chosen}}]}
    ready = to_resolution(fin["next_timing_state"])
    item_ = next(i for i in ready["chain"]["items"] if i["id"] == "help")
    prog, refusal = dispatch_program(REGISTRY, item_)
    assert refusal is None, refusal
    done = resolve_with_program(ready, "help", now, prog, engine_decisions=decisions)
    assert done.get("committed"), (done.get("stage"), done.get("reason"))
    return done


def record_of(done: dict) -> dict:
    lp = pending_play(done["next_timing_state"])
    return ((done["next_effect_state"].get("chain_items") or {}).get((lp or {}).get("id")) or {}).get("limited_play") or {}


def main() -> int:
    done = resolved(board(), ["hid-unit"])
    record = record_of(done)
    if record.get("entry_restricted") != "battlefield_you_control" or "entry_location" in record:
        fail("H1 record", f"{record}")
    ask = finalize_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
    if ask.get("reason") != "entry_location_required" or ask.get("location_candidates") != [BF2]:
        fail("H2 offered", f"{ask.get('reason')} {ask.get('location_candidates')}")
    there = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BF2,
                                  payment_context=CLOSED)
    ns = there.get("next_effect_state") or {}
    if not there.get("committed") or "hid-unit" not in ns["battlefields"]["bf2"]["objects"] \
            or ns["players"]["p1"]["resources"]["energy"] != 0:
        fail("H3 completed", f"{there.get('reason')} {there.get('message')} {(ns.get('players') or {}).get('p1', {}).get('resources')}")
    for label, where in (("H4 base", BASE), ("H5 not p1's", BF1)):
        refused = finalize_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=where,
                                        payment_context=CLOSED)
        if refused.get("committed") or refused.get("reason") != "entry_location_restricted_by_effect":
            fail(label, f"{refused.get('committed')} {refused.get('reason')}")
    nowhere = resolved(board(controls_bf2=False), ["hid-unit"])
    if pending_play(nowhere["next_timing_state"]) is not None \
            or "hid-unit" not in nowhere["next_effect_state"]["players"]["p1"]["zones"]["hand"]:
        fail("H6 nowhere", "the unit was put on the Chain with no Battlefield of p1's to enter")
    # "You may": the choice is up to one card, made as it resolves (contract v2.9 MAYCHOOSE on limited_play) -
    # choosing none plays nothing, the unit stays in hand, the Energy is not spent
    declined = resolved(board(), [])
    if pending_play(declined["next_timing_state"]) is not None \
            or "hid-unit" not in declined["next_effect_state"]["players"]["p1"]["zones"]["hand"] \
            or declined["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 2:
        fail("H7 declined", "choosing no card still started a play or spent the Energy")
    bad = copy.deepcopy(done["next_effect_state"])
    lp = pending_play(done["next_timing_state"])
    bad["chain_items"][lp["id"]]["limited_play"]["entry_location"] = BF2
    if not validate_state(bad):
        fail("V", "a record with both entry_location and entry_restricted validated")
    if errors:
        print("FAILED: play a unit to a battlefield you control")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'play a unit from hand to a battlefield you control' offers only the Battlefields its player controls "
          "(355.2.b) - not the Base, not an opponent's; none controlled, the unit stays in hand; none chosen, nothing is played (H1-H7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
