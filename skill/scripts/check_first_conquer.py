#!/usr/bin/env python3
"""Regression gate: "The first time I conquer each turn, ..." (set 2 package A2: Lucian - Merciless; Core 471.1, 383.1).

  F1  u1 conquers bf1 for real (a decided Combat, control established): its first-time trigger is on the Chain, and the
      ledger records u1's identity conquering once this turn
  F2  the same conquer when u1 has already conquered once this turn: the first-time trigger is not scheduled; a plain
      "When I conquer" trigger beside it still is
  F3  the printed form lowers to the conquer trigger marked first_each_turn; the marker on another trigger kind, and a
      ledger with a non-positive count, are refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from battlefield_control import resolve_battlefield_control  # noqa: E402
from check_control_resolution import decided_combat  # noqa: E402
from effect_ir import object_identity, validate_state  # noqa: E402

TEXT = "The first time I conquer each turn, draw 1."


def trig(trigger_id, **extra):
    return {"trigger_id": trigger_id, "controller": "p1", "source_object": "u1", "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False, "scope": "unit_here", **extra}


def run(already: int, *, with_plain: bool):
    def extra(e):
        e["objects"]["u1"]["conquer_triggers"] = [trig("first", occurrence="first_each_turn")] + ([trig("every")] if with_plain else [])
        if already:
            turn = e.get("turn_id", "turn-0")
            e["players"]["p1"]["unit_conquests_this_turn"] = {turn: {object_identity(e, "u1") or "u1@0": already}}
    t, e = decided_combat(extra=extra)
    resolved = resolve_battlefield_control(t, e)
    ids = sorted(i["id"] for i in (resolved.get("next_timing_state") or {}).get("chain", {}).get("items", []))
    return resolved, ids


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    rows = ((got.get("passive") or {}).get("object_fields") or {}).get("conquer_triggers") or []
    if got.get("production_id") != "the_first_time_i_conquer_each_turn" or len(rows) != 1 \
            or rows[0].get("occurrence") != "first_each_turn" or rows[0].get("scope") != "unit_here":
        errors.append(f"F3: lowered to {got.get('production_id')} {rows}")
    first, ids = run(0, with_plain=False)
    if not first.get("committed"):
        errors.append(f"F1: control resolution refused: {first.get('reason_code')} {first.get('reason') or first.get('errors')}")
    else:
        if not any(i.startswith("first") for i in ids):
            errors.append(f"F1: the first conquer scheduled {ids}")
        after = first["next_effect_state"]
        ledger = (after["players"]["p1"].get("unit_conquests_this_turn") or {}).get(after.get("turn_id", "turn-0")) or {}
        if ledger.get(object_identity(after, "u1") or "u1@0") != 1 or validate_state(after):
            errors.append(f"F1: the ledger reads {ledger} ({validate_state(after)[:1]})")
    second, ids = run(1, with_plain=True)
    if not second.get("committed") or any(i.startswith("first") for i in ids) or not any(i.startswith("every") for i in ids):
        errors.append(f"F2: a second conquer this turn scheduled {ids} ({second.get('reason_code')})")
    t, e = decided_combat()
    bad = copy.deepcopy(e)
    bad["objects"]["u1"]["hold_triggers"] = [trig("h", occurrence="first_each_turn")]
    if not any("occurrence" in p for p in validate_state(bad)):
        errors.append("F3: first_each_turn on a hold trigger was accepted")
    bad = copy.deepcopy(e)
    bad["players"]["p1"]["unit_conquests_this_turn"] = {"turn-0": {"u1@0": 0}}
    if not any("unit_conquests_this_turn" in p for p in validate_state(bad)):
        errors.append("F3: a ledger count of 0 was accepted")
    if errors:
        print("first-conquer checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("first-conquer checks passed: the first conquer of the turn schedules the first-time trigger and is counted per "
          "identity; a second does not, a plain conquer trigger still does; lowered; the marker and ledger validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
