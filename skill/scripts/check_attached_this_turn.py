#!/usr/bin/env python3
"""Regression gate: "If this was attached to me this turn, I have an additional +2 [M]." (set 2 package A2: Brutalizer
[Effect Text]; Core 435.1.c, 364.3.a).

  B1  the Equipment attached for real this turn: its Top-Most card has +2 Might; the next turn, still attached, it does
      not; detached, it does not; attached again on that turn, it does
  B2  the Effect Text's "this" is filled in as the Equipment when it is appended; the attach records its turn
  B3  the printed form lowers to the Effect Text bundle; a condition naming no attached card is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, effective_might, validate_condition, validate_state  # noqa: E402

TEXT = "If this was attached to me this turn, I have an additional +2 :rb_might:."


def run(state, *effects):
    done = apply_program(state, program("p", *effects))
    if not done.get("committed"):
        raise SystemExit(f"program refused: {done.get('reason_code')} {done.get('errors') or done.get('reason')}")
    return done["next_state"]


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    fields = (got.get("passive") or {}).get("object_fields") or {}
    if got.get("production_id") != "attached_this_turn_more_might" or "effect_text" not in fields:
        errors.append(f"B3: lowered to {got.get('production_id')} {fields}")
        fields = {}
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["host"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                                "damage": 0, "exhausted": False}
    state["objects"]["brute"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False, "tags": ["Equipment"], **copy.deepcopy(fields)}
    state["players"]["p1"]["zones"]["base"] += ["host", "brute"]
    if validate_state(state):
        errors.append(f"fixture invalid: {validate_state(state)[:2]}")
    on = run(state, {"op": "attach", "effect_id": "a", "object_id": "brute", "to": "host"})
    if effective_might(on, "host") != 5:
        errors.append(f"B1: attached this turn, Might {effective_might(on, 'host')}, wanted 5")
    if on["objects"]["brute"].get("attached_on_turn") != "turn-3":
        errors.append(f"B2: the attach recorded {on['objects']['brute'].get('attached_on_turn')!r}")
    named = [e.get("condition", {}).get("attached") for e in on.get("continuous_effects") or []
             if e.get("kind") == "might_arithmetic"]
    if named != ["brute"]:
        errors.append(f"B2: the appended effect's condition names {named}")
    later = copy.deepcopy(on)
    later["turn_id"] = "turn-4"
    if effective_might(later, "host") != 3:
        errors.append(f"B1: the next turn, still attached, Might {effective_might(later, 'host')}, wanted 3")
    off = run(later, {"op": "detach", "effect_id": "d", "object_id": "brute"})
    if effective_might(off, "host") != 3:
        errors.append(f"B1: detached, Might {effective_might(off, 'host')}, wanted 3")
    again = run(off, {"op": "attach", "effect_id": "a2", "object_id": "brute", "to": "host"})
    if effective_might(again, "host") != 5:
        errors.append(f"B1: attached again on turn-4, Might {effective_might(again, 'host')}, wanted 5")
    if not validate_condition({"kind": "attached_this_turn"}):
        errors.append("B3: a condition naming no attached card was accepted")
    if errors:
        print("attached-this-turn checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("attached-this-turn checks passed: +2 while attached by this turn's attach, not the next turn, not detached, "
          "again on a new attach; the Effect Text's 'this' filled in; lowered; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
