#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "When you play me or when I hold" (Ornn - Blacksmith) - one Unit ability with a
Play Effect (Core 383.4.a, 420.4.a) and a Hold Effect (383.4.d, 383.4.d.2.a). The clause grammar lowers it to the same
descriptor in play_triggers and hold_triggers.

  lowering   both fields carry one identical descriptor; "When you play me" and "When I hold" alone still lower to
             their one field
  played     the Unit played to its Base and resolved schedules exactly one Pending triggered item, in the play batch
  hold       the Scoring Step's hold pass over a Battlefield where the Unit stands yields exactly one descriptor for it;
             from its Base none; a Conquer of that Battlefield none
  neither    a Unit without the ability yields nothing

    python skill/scripts/check_set2_play_or_hold.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_played_and_conquer_trigger import fields_of, played, scored  # noqa: E402

TEXT = "When you play me or when I hold, draw 1."


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    pid, fields = fields_of(TEXT, grammar)
    if pid != "when_you_play_me_or_when_i_hold" or set(fields) != {"play_triggers", "hold_triggers"}:
        errors.append(f"lowering: expected play_triggers and hold_triggers, got {pid} {sorted(fields)}")
    elif fields["play_triggers"] != fields["hold_triggers"] or len(fields["play_triggers"]) != 1:
        errors.append("lowering: the two fields do not carry one identical descriptor")
    for text, only in (("When you play me, draw 1.", {"play_triggers"}), ("When I hold, draw 1.", {"hold_triggers"})):
        if set(fields_of(text, grammar)[1]) != only:
            errors.append(f"lowering: {text!r} no longer lowers to {sorted(only)} alone")
    descriptor = {**fields.get("play_triggers", [{}])[0], "controller": "p1", "effect_program_id": "c1-ph"}
    both = {"play_triggers": [copy.deepcopy(descriptor)], "hold_triggers": [copy.deepcopy(descriptor)]}
    try:
        items = played(both)
        mine = [i for i in items if i.get("id") == descriptor["trigger_id"]]
        if len(items) != 1 or len(mine) != 1 or mine[0].get("status") != "pending" or mine[0].get("batch_id") != "play:unit-1":
            errors.append(f"played: {[(i.get('id'), i.get('status'), i.get('batch_id')) for i in items]}")
        if played(None):
            errors.append("neither: a Unit without the ability scheduled something on play")
    except AssertionError as why:
        errors.append(f"played: {why}")
    try:
        found = scored(both, where="bf1", how="hold")
        if len(found) != 1 or found[0].get("trigger_id") != descriptor["trigger_id"] or found[0].get("how") != "hold":
            errors.append(f"hold: expected exactly one descriptor for the Unit at the Battlefield, got {found}")
        if scored(both, where="base", how="hold"):
            errors.append("hold: the Unit in its Base triggered on a Hold of bf1")
        if scored(both, where="bf1", how="conquer"):
            errors.append("hold: a Conquer of the Battlefield triggered the ability")
        if scored(None, where="bf1", how="hold"):
            errors.append("neither: a Unit without the ability triggered on hold")
    except AssertionError as why:
        errors.append(f"hold: {why}")
    if errors:
        print("FAILED: when you play me or when I hold")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("OK: when you play me or when I hold - one descriptor in both fields; one item on play, one descriptor on a "
          "Hold where the Unit stands, none from its Base, a Conquer, or a Unit without the ability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
