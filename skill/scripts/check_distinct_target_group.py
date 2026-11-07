#!/usr/bin/env python3
"""Regression gate: a bounded set of Targets that must be another unit than an earlier target (distinct_from on the set's
restrictions) - "Deal 2 to a unit at a battlefield, then deal 2 to up to one other unit." (set 2 package A2: Piercing
Light).

  G1  played with the first target u2 and the set naming u1: committed; resolved, both took 2 (the set's expansion into
      one-target instructions carries no distinct_from, which names a decision of the whole program)
  G2  the set naming u2 again is refused as the card is played (target_not_distinct)
  G3  a Repeat's copy (suffix_decision_refs) suffixes a distinct_from that names one of the same instructions' own
      decisions, and leaves one naming a decision outside them as it is
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

EFFECTS = [{"op": "deal_damage", "effect_id": "dmg", "amount": 2,
            "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "location": "battlefield"}},
           {"op": "deal_damage", "effect_id": "dmg-2", "amount": 2,
            "targets": {"min": 0, "max": 1, "decision_ref": "t-2",
                        "restrictions": {"chosen_zone_class": "board", "kind": "unit", "distinct_from": ["t"]}}}]


def scene():
    s = base_state()
    s["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s["players"]["p1"]["zones"]["hand"].append("c1")
    s["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    s["players"]["p2"]["zones"]["base"].remove("u2")
    s["battlefields"]["bf1"]["objects"].append("u2")
    return settle_contested(s)


def play(s, second):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "pl",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    pick = lambda ref, objs: {"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
                              "value": objs, "selection_identities": {o: IR.object_identity(s, o) for o in objs}}
    dec = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s),
           "decisions": [pick("t", ["u2"]), pick("t-2", second)]}
    return play_card(fixture(), s, decl, engine_decisions=dec, effect_program=program("pl", *EFFECTS))


def main() -> int:
    errors: list[str] = []
    s = scene()
    played = play(s, ["u1"])
    if not played.get("committed"):
        errors.append(f"G1: the play was refused: {played.get('reason_code')}")
    else:
        timing = RC.finalize_oldest_pending(played["next_timing_state"]).get("next_state") or played["next_timing_state"]
        timing["chain"]["consecutive_passes"] = ["p1", "p2"]
        done = resolve_with_program(timing, "spell-1", played["next_effect_state"], program("pl", *EFFECTS))
        if not done.get("committed"):
            errors.append(f"G1: resolution refused: {done.get('reason')}")
        else:
            after = done["next_effect_state"]
            if after["objects"]["u2"].get("damage") != 2 or after["objects"]["u1"].get("damage", 0) - s["objects"]["u1"].get("damage", 0) != 2:
                errors.append(f"G1: damage u2 {after['objects']['u2'].get('damage')}, u1 {after['objects']['u1'].get('damage')}")
    again = play(s, ["u2"])
    if again.get("committed") or again.get("reason_code") != "target_not_distinct":
        errors.append(f"G2: the same unit twice: {again.get('committed')} {again.get('reason_code')}")
    copied = IR.suffix_decision_refs(EFFECTS, "#1")
    if copied[1]["targets"]["restrictions"]["distinct_from"] != ["t#1"]:
        errors.append(f"G3: the copy's distinct_from is {copied[1]['targets']['restrictions']['distinct_from']}")
    alone = IR.suffix_decision_refs(EFFECTS[1:], "-x")
    if alone[0]["targets"]["restrictions"]["distinct_from"] != ["t"]:
        errors.append(f"G3: a part renamed alone changed its outside reference: {alone[0]['targets']['restrictions']['distinct_from']}")
    if errors:
        print("distinct target-set checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("distinct target-set checks passed: an 'other unit' set plays and resolves on a different unit, the same unit is "
          "refused, and a Repeat copy follows its own reference only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
