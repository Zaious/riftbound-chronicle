#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "If it is a unit, you may play it here." (Rek'Sai - Swarm Queen) - the effect
does not name the unit's location; it adds the source's current Battlefield to the ones its player may choose from
as the play is finalized (Core 355.2.b), read as the instruction executes (359.3.f.2). limited_play entry
unit_may_enter_source_battlefield; the record keeps entry_permitted, never entry_location.

  Q1 offered          the source at bf1 (p2 controls it, contested by the source): the finalization asks for the
                      location, and bf1 is among the candidates beside p1's Base
  Q2 here taken       completed at bf1: the unit is at bf1
  Q3 base taken       completed at the Base: the unit is in p1's Base - "you may" declined is the play as usual
  Q4 no here          the source left bf1 before the instruction: no option recorded, bf1 not offered and refused
  Q5 not a unit       a gear played by the same instruction: nothing permitted, it enters where it would
  V                   a record carrying both entry_location and entry_permitted does not validate

    python skill/scripts/check_set2_play_here_option.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_limited_play import BASE, CLOSED, ava_board, card, pending_play, program, to_resolution  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, object_identity, validate_state  # noqa: E402
from resolution_bridge import (complete_limited_play, dispatch_program, finalize_limited_play,  # noqa: E402
                               finalize_trigger, program_hash, resolve_with_program)
from rules_core import schedule_triggered_items  # noqa: E402

errors: list[str] = []
QUEEN = program("queen-on-attack-effects", "ava", [
    {"op": "limited_play", "effect_id": "lp", "decision_ref": "c",
     "choice": {"from": "hand", "selection_kind": "unordered_set", "count": {"up_to": 1}, "by": "controller",
                "visibility": "private_to_chooser"}, "card_filter": {"hidden": True},
     "entry": {"kind": "unit_may_enter_source_battlefield"}, "cost_basis": {"kind": "ignore_all"}}])
REGISTRY = {QUEEN["program_id"]: QUEEN}
BF1 = {"kind": "battlefield", "battlefield": "bf1"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def resolved(state: dict, chosen: list[str], *, move_away: bool = False) -> dict:
    descriptor = {"trigger_id": "queen-on-attack", "controller": "p1", "source_object": "ava", "controller_order": 0,
                  "effect_program_id": QUEEN["program_id"], "optional_at_finalize": False,
                  "effect_program_hash": program_hash(QUEEN), "trigger_kind": "triggered",
                  "source_identity": object_identity(state, "ava")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    assert scheduled.get("applied"), scheduled
    fin = finalize_trigger(scheduled["next_state"], state, REGISTRY, None, payment_context=CLOSED)
    assert fin.get("committed") and not fin.get("removed"), (fin.get("reason"), fin.get("message"))
    board_now = copy.deepcopy(fin["next_effect_state"])
    if move_away:
        board_now["battlefields"]["bf1"]["objects"].remove("ava")
        board_now["players"]["p1"]["zones"]["base"].append("ava")
        board_now["battlefields"]["bf1"].update({"contested": False, "contested_by": None})
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(board_now),
                 "decisions": [{"decision_id": "c", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                                "value": list(chosen), "selection_identities": {c: object_identity(board_now, c) for c in chosen}}]}
    ready = to_resolution(fin["next_timing_state"])
    item_ = next(i for i in ready["chain"]["items"] if i["id"] == "queen-on-attack")
    prog, refusal = dispatch_program(REGISTRY, item_)
    assert refusal is None, refusal
    done = resolve_with_program(ready, "queen-on-attack", board_now, prog, engine_decisions=decisions)
    assert done.get("committed"), (done.get("stage"), done.get("reason"))
    return done


def record_of(done: dict) -> dict:
    lp = pending_play(done["next_timing_state"])
    return ((done["next_effect_state"].get("chain_items") or {}).get((lp or {}).get("id")) or {}).get("limited_play") or {}


def main() -> int:
    state = ava_board()
    done = resolved(state, ["hid-unit"])
    record = record_of(done)
    if record.get("entry_permitted") != BF1 or "entry_location" in record:
        fail("Q1 record", f"{record}")
    ask = finalize_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
    if ask.get("reason") != "entry_location_required" or BF1 not in ask.get("location_candidates", []) \
            or BASE not in ask.get("location_candidates", []):
        fail("Q1 offered", f"{ask.get('reason')} {ask.get('location_candidates')}")
    here = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BF1,
                                 payment_context=CLOSED)
    if not here.get("committed") or "hid-unit" not in here["next_effect_state"]["battlefields"]["bf1"]["objects"]:
        fail("Q2 here", f"{here.get('reason')} {here.get('message')}")
    home = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE,
                                 payment_context=CLOSED)
    if not home.get("committed") or "hid-unit" not in home["next_effect_state"]["players"]["p1"]["zones"]["base"]:
        fail("Q3 base", f"{home.get('reason')} {home.get('message')}")
    gone = resolved(state, ["hid-unit"], move_away=True)
    if "entry_permitted" in record_of(gone):
        fail("Q4 record", f"{record_of(gone)}")
    ask = finalize_limited_play(gone["next_timing_state"], gone["next_effect_state"], payment_context=CLOSED)
    if BF1 in ask.get("location_candidates", []):
        fail("Q4 offered", f"{ask.get('location_candidates')}")
    refused = finalize_limited_play(gone["next_timing_state"], gone["next_effect_state"], entry_location=BF1,
                                    payment_context=CLOSED)
    if refused.get("committed") or refused.get("reason") != "entry_location_illegal":
        fail("Q4 refused", f"{refused.get('reason')}")
    gear = resolved(state, ["hid-gear"])
    if "entry_permitted" in record_of(gear) or "entry_location" in record_of(gear):
        fail("Q5 gear", f"{record_of(gear)}")
    bad = copy.deepcopy(done["next_effect_state"])
    lp = pending_play(done["next_timing_state"])
    bad["chain_items"][lp["id"]]["limited_play"]["entry_location"] = BF1
    if not validate_state(bad):
        fail("V", "a record with both entry_location and entry_permitted validated")
    if errors:
        print("FAILED: set 2 'you may play it here'")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'you may play it here' offers the source's Battlefield beside the usual locations (355.2.b), read as the "
          "instruction executes; taken or declined, the unit enters there or where its player chooses; no 'here', no option")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
