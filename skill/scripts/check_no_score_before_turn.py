#!/usr/bin/env python3
"""Regression gate: "Players can't score here until their third turn." (set 2 package A2: Forgotten Monument).

  S1  a player who has begun two turns does not score the Battlefield by a conquer or a hold: no point, the ledger
      untouched; one who has begun three scores it
  S2  with the player's turns not recorded the score is refused by name, never guessed
  S3  the printed form lowers to the Battlefield field (third -> 3); a turn below 2 is refused by the validator
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from battlefield_control import ScoringUnsupported, score_battlefield  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import validate_state  # noqa: E402


def state_with(n=3):
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["battlefields"]["bf1"]["no_score_before_own_turn"] = n
    return state


def main() -> int:
    errors: list[str] = []
    for how in ("conquer", "hold"):
        for taken, want in ((2, False), (3, True)):
            after, record, _ = score_battlefield(state_with(), "p1", "bf1", how, "turn-9", turns_taken={"p1": taken, "p2": 1})
            if bool(record.get("scored")) != want:
                errors.append(f"S1 {how}: with {taken} turns begun, scored {record.get('scored')} ({record.get('reason')})")
            if not want and (after["players"]["p1"].get("points", 0) != 0 or after["players"]["p1"].get("scored_this_turn")):
                errors.append(f"S1 {how}: the refused score still moved points or the ledger")
    try:
        score_battlefield(state_with(), "p1", "bf1", "conquer", "turn-9")
        errors.append("S2: a score with no turns recorded was decided")
    except ScoringUnsupported:
        pass
    got = CG.compile_clause("Players can't score here until their third turn.", CG.load_grammar())
    if ((got.get("passive") or {}).get("battlefield_fields") or {}) != {"no_score_before_own_turn": 3}:
        errors.append(f"S3: lowered to {got.get('production_id')} {got.get('passive')}")
    if not any("no_score_before_own_turn" in e for e in validate_state(state_with(1))):
        errors.append("S3: a turn below 2 was accepted")
    if errors:
        print("no-score-before-turn checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("no-score-before-turn checks passed: no score here before the player's Nth turn, by conquer or hold; unrecorded "
          "turns refused by name; lowered; a bad turn refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
