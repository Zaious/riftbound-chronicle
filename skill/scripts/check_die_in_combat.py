#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Draven - Audacious): "When I die in combat, ..." - a death trigger met only when the
card was in a Combat (an Attacker or a Defender) as its death was noted (Core 383.2.a.1, 466); and "The first time I win
a combat each turn, ..." lowered to the won-combat watch on the card itself, first of the turn only.

  C1  the card attacking at bf1, killed: its trigger is noted
  C2  the same card defending, killed: noted
  C3  the card in its Base (no Combat), killed: not noted
  G   both printed forms lower exactly; their near misses do not
  V   died_in_combat on a play trigger is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import clause_grammar as CG  # noqa: E402
from check_set2_deathknell import descriptor, program, unit  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import apply_program, validate_state  # noqa: E402


def board(role=None):
    state = base_state()
    state["objects"]["dk-unit"] = unit("p1", 3, death_triggers=[descriptor("died_in_combat")])
    if role is None:
        state["players"]["p1"]["zones"]["base"].append("dk-unit")
    else:
        state["objects"]["e1"] = unit("p2")
        state["battlefields"]["bf1"]["objects"] = ["dk-unit", "e1"]
        state["objects"]["dk-unit"]["combat_designation"] = {"combat_id": "cb1", "role": role}
        state["objects"]["e1"]["combat_designation"] = {"combat_id": "cb1",
                                                        "role": "defender" if role == "attacker" else "attacker"}
    return settle_contested(state)


def noted(state):
    if problems := validate_state(state):
        return f"invalid board: {problems[:2]}"
    done = apply_program(state, program("kill", [{"op": "kill", "effect_id": "k", "object_id": "dk-unit"}], controller="p2"))
    if not done.get("committed"):
        return f"refused: {done.get('errors') or done.get('reason')}"
    return [t["trigger_id"] for t in done.get("pending_triggers") or [] if t.get("source_object") == "dk-unit"]


def main() -> int:
    errors: list[str] = []
    for label, role, want in (("C1 attacking", "attacker", ["dk"]), ("C2 defending", "defender", ["dk"]),
                              ("C3 in its Base", None, [])):
        got = noted(board(role))
        if got != want:
            errors.append(f"{label}: {got}")
    g = CG.load_grammar()
    die = CG.compile_clause("When I die in combat, draw 1.", g)
    rows = ((die.get("passive") or {}).get("object_fields") or {}).get("death_triggers") or []
    if len(rows) != 1 or rows[0].get("condition") != {"kind": "died_in_combat"}:
        errors.append(f"G: 'when i die in combat' lowered to {die.get('production_id')} {rows}")
    first = CG.compile_clause("The first time I win a combat each turn, draw 1.", g)
    watch = ((((first.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or [{}])[0]).get("watch") or {}
    if watch.get("kinds") != ["won_combat"] or watch.get("scope") != "self" or watch.get("occurrence") != "first_each_turn":
        errors.append(f"G: 'the first time i win a combat each turn' lowered to {first.get('production_id')} {watch}")
    for near in ("When I die, draw 1.", "When a unit dies in combat, draw 1."):
        if CG.compile_clause(near, g).get("production_id") == "when_i_die_in_combat":
            errors.append(f"G: the near miss {near!r} lowered to the row")
    bad = board()
    bad["objects"]["dk-unit"]["play_triggers"] = [descriptor("died_in_combat")]
    if not validate_state(bad):
        errors.append("V: died_in_combat on a play trigger validated")
    if errors:
        print("die-in-combat checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("die-in-combat checks passed: the death trigger is noted when the card dies attacking or defending, not out of "
          "combat; both printed forms lowered; the condition only on a death trigger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
