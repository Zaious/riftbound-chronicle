#!/usr/bin/env python3
"""Regression gate: up to three targets that are all at one Location - "Deal 1 to up to three units at the same
location." (set 2 package A2: Bellows Breath). A Location is a Battlefield or a Base (Core 198.1); the group requirement
same_location is met by the chosen targets together (Core 355.11.a), as same_battlefield is, but a Base counts too.

  L1  three units at bf1: committed; resolved, each took 1
  L2  u5 alone, in p1's Base: committed (a Base is a Location); resolved, it took 1
  L3  u1 at bf1 with u5 in the Base: refused at play (target_group_requirement_failed)
  L4  none chosen: committed (up to three); resolved, nothing changed
  L5  (GPT A2 ruling 9; Core 355.11.b.1's own example) u1, u3, u6 chosen at bf1, then u3 and u6 recalled to p1's Base
      before it resolves: the group no longer holds, so the controller keeps a subset as it resolves - u1 alone, or u3
      and u6 together; u3 without u6 is refused (a subset keeps every target it can); unanswered, it waits
  V   same_location other than true does not validate
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_rules_core import fixture, item  # noqa: E402
from check_target_counts import board, play, refused, resolve, spell_program  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402


def recalled(played, *objects):
    """p2's response: the objects recalled to their owner's Base (as Flash moves them in the rule's example)."""
    state = played["next_effect_state"]
    done = apply_program(state, {**spell_program([{"op": "recall", "effect_id": f"r{k}", "object_id": o}
                                                  for k, o in enumerate(objects)]),
                                 "program_id": "response", "controller": "p2"})
    return done["next_state"]


def kept(state, keep):
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    decisions = None if keep is None else {
        "schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
            {"decision_id": "keep", "stage": "resolution", "kind": "card_selection", "controller": "p1",
             "value": list(keep), "selection_identities": {o: object_identity(state, o) for o in keep}}]}
    return resolve_with_program(timing, "spell-1", state, spell_program(DEAL), engine_decisions=decisions)

DEAL = {"op": "deal_damage", "effect_id": "dmg", "amount": 1,
        "targets": {"min": 0, "max": 3, "decision_ref": "t", "subset_ref": "keep",
                    "restrictions": {"chosen_zone_class": "board", "kind": "unit"}, "group": {"same_location": True}}}


def main() -> int:
    errors: list[str] = []
    s = board()
    if validate_state(s):
        errors.append(f"board: {validate_state(s)[:2]}")
    if validate_program(spell_program(DEAL)):
        errors.append(f"V: the program does not validate: {validate_program(spell_program(DEAL))[:2]}")
    for label, chosen in (("L1 three at bf1", ["u1", "u2", "u4"]), ("L2 one in a Base", ["u5"]), ("L4 none", [])):
        played = play(s, DEAL, t=chosen)
        if not played.get("committed"):
            errors.append(f"{label}: refused {played.get('reason_code')} {played.get('reason')}")
            continue
        done = resolve(played, DEAL)
        after = (done.get("next_effect_state") or {}).get("objects") or {}
        if not done.get("committed"):
            errors.append(f"{label}: resolution refused {done.get('reason')}")
            continue
        for o in s["objects"]:
            if s["objects"][o].get("kind") != "unit" or o not in after:
                continue
            want = s["objects"][o].get("damage", 0) + (1 if o in chosen else 0)
            if after[o].get("damage", 0) != want:
                errors.append(f"{label}: {o} has damage {after[o].get('damage', 0)}, expected {want}")
    if problem := refused(play(s, DEAL, t=["u1", "u5"]), "target_group_requirement_failed"):
        errors.append(f"L3 bf1 and a Base: {problem}")
    played = play(s, DEAL, t=["u1", "u3", "u6"])
    if not played.get("committed"):
        errors.append(f"L5: the play was refused {played.get('reason_code')}")
    else:
        moved = recalled(played, "u3", "u6")
        waits = kept(moved, None)
        if waits.get("committed") or "target_group_subset_required" not in (
                str(waits.get("reason_code")) + str(waits.get("reason")) + str(waits.get("stage"))
                + str((waits.get("effect_result") or {}).get("reason_code"))):
            errors.append(f"L5 unanswered: {waits.get('committed')} {waits.get('reason_code')} {waits.get('reason')}")
        for label, keep, ok in (("u1 alone", ["u1"], True), ("u3 and u6", ["u3", "u6"], True),
                                ("u3 without u6", ["u3"], False)):
            got = kept(moved, keep)
            after = (got.get("next_effect_state") or {}).get("objects") or {}
            if ok and (not got.get("committed") or any(after[o].get("damage", 0) != moved["objects"][o].get("damage", 0)
                                                       + (1 if o in keep else 0) for o in ("u1", "u3", "u6"))):
                errors.append(f"L5 {label}: {got.get('committed')} {got.get('reason')} {got.get('errors')}")
            if not ok and got.get("committed"):
                errors.append(f"L5 {label}: a subset leaving out a target it could keep was accepted")
    bad = {**DEAL, "targets": {**DEAL["targets"], "group": {"same_location": "yes"}}}
    if not validate_program(spell_program(bad)):
        errors.append("V: same_location 'yes' validated")
    if errors:
        print("same-location target group checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("same-location target group checks passed: up to three units at one Battlefield or one Base, none at all, and "
          "a Battlefield beside a Base refused; moved apart before it resolves, a maximal subset at one Location is kept "
          "(Core 355.11.b.1's example)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
