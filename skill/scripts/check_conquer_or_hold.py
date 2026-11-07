#!/usr/bin/env python3
"""Regression gate: "When I conquer or hold, ..." (set 2 package A2: Last Rites [Effect Text]). One ability with two
trigger conditions - the Unit's own conquer (Core 383.4.c) and its own hold (383.4.d): the same descriptor in both fields,
so a conquer schedules it once and a hold schedules it once.

  H1  u1 at bf1 (p1's) carrying the lowered ability: a conquer of bf1 schedules it once; a hold of bf1 once
  H2  u1 not at bf1: neither schedules it (scope unit_here)
  H3  as an Equipment's Effect Text attached to u1: a hold of bf1 schedules it from u1
  G   the printed form lowers to the descriptor in both fields; near misses do not
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
from battlefield_control import _score_triggers  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program  # noqa: E402

TEXT = "When I conquer or hold, draw 1."


def fields():
    got = CG.compile_clause(TEXT, CG.load_grammar())
    return (got.get("passive") or {}).get("object_fields") or {}


def bound(rows, source):
    return [{**copy.deepcopy(r), "controller": "p1", "source_object": source, "effect_program_id": "lr-1"} for r in rows]


def board(at_bf1=True):
    s = base_state()
    if at_bf1:
        s["players"]["p1"]["zones"]["base"].remove("u1")
        s["battlefields"]["bf1"]["objects"].append("u1")
        s["battlefields"]["bf1"]["controller"] = "p1"
    return settle_contested(s)


def fired(state, how):
    return [d["trigger_id"] for d in _score_triggers(state, "p1", "bf1", how, state.get("turn_id", "turn-0"))
            if d.get("source_object") == "u1"]


def main() -> int:
    errors: list[str] = []
    f = fields()
    if set(f) != {"conquer_triggers", "hold_triggers"} or f["conquer_triggers"] != f["hold_triggers"]:
        errors.append(f"G: lowered to {f}")
    for near in ("When I conquer, draw 1.", "When you conquer or hold, draw 1."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == "when_i_conquer_or_hold":
            errors.append(f"G: the near miss {near!r} lowered to the row")
    for at, want in ((True, ["on-conquer-or-hold"]), (False, [])):
        s = board(at)
        for field in ("conquer_triggers", "hold_triggers"):
            s["objects"]["u1"][field] = bound(f.get(field) or [], "u1")
        if fired(s, "conquer") != want or fired(s, "hold") != want:
            errors.append(f"{'H1' if at else 'H2'}: conquer {fired(s, 'conquer')}, hold {fired(s, 'hold')}")
    s = board()
    s["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Equipment"],
                          "effect_text": {"triggers": {k: bound(v, "g1") for k, v in f.items()}}}
    s["players"]["p1"]["zones"]["base"].append("g1")
    done = apply_program(s, {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                             "program_id": "eq", "controller": "p1",
                             "effects": [{"op": "attach", "effect_id": "at", "object_id": "g1", "to": "u1"}]})
    if not done.get("committed") or fired(done["next_state"], "hold") != ["on-conquer-or-hold"]:
        errors.append(f"H3: {done.get('reason') or done.get('errors')} {fired(done.get('next_state') or s, 'hold')}")
    if errors:
        print("conquer-or-hold checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("conquer-or-hold checks passed: one ability scheduled once by the Unit's conquer and once by its hold, not away "
          "from the Battlefield, and from an Equipment's Effect Text too; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
