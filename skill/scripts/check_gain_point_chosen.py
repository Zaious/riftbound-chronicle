#!/usr/bin/env python3
"""Regression gate: "Choose an opponent. They score 1 point." (set 2 package A2: Draven - Audacious). gain_point's player
may be the one an earlier choose_player of the same program chose ({decision_ref}), read through resolve_player_ref.

  P1  p1 chooses p2: p2 gains 1 point, p1 none
  P2  no choice supplied: the program waits for it (player_selection_required)
  P3  the choice made by p2 (not the program's controller): refused
  V   a player given as anything else than a name or {decision_ref} does not validate
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

EFFECTS = [{"op": "choose_player", "effect_id": "opp", "decision_ref": "chosen-opponent",
            "choice": {"selection_kind": "single", "from": "players", "players": "opponents", "count": {"one": True}}},
           {"op": "gain_point", "effect_id": "pt", "player": {"decision_ref": "chosen-opponent"}, "amount": 1}]


def program(effects=EFFECTS):
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": "dv", "controller": "p1", "effects": effects}


def run(chooser=None):
    s = base_state()
    decisions = None
    if chooser:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s), "decisions": [
            {"decision_id": "chosen-opponent", "stage": "resolution", "kind": "player_selection", "controller": chooser,
             "value": "p2"}]}
    return IR.apply_program(s, program(), decisions=decisions)


def main() -> int:
    errors: list[str] = []
    if IR.validate_program(program()):
        errors.append(f"V: the program does not validate: {IR.validate_program(program())[:2]}")
    done = run("p1")
    if not done.get("committed") or done["next_state"]["players"]["p2"].get("points", 0) != 1 \
            or done["next_state"]["players"]["p1"].get("points", 0) != 0:
        errors.append(f"P1: {done.get('reason_code')} {done.get('errors') or done.get('reason')}")
    if run().get("reason_code") != "player_selection_required":
        errors.append(f"P2: {run().get('reason_code')}")
    if run("p2").get("committed"):
        errors.append("P3: the opponent's choice was accepted")
    bad = [EFFECTS[0], {**EFFECTS[1], "player": {"object_ref": "x"}}]
    if not IR.validate_program(program(bad)):
        errors.append("V: a player {object_ref} validated")
    if errors:
        print("chosen-player point checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("chosen-player point checks passed: the chosen opponent gains the point; no choice waits for one; another "
          "player's choice is refused; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
