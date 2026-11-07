#!/usr/bin/env python3
"""Regression gate (set 2 package A2, Ezreal - Prodigal Explorer: ":rb_exhaust:: [Reaction] - Draw 1. Use only if you've
chosen enemy units and/or gear twice this turn with spells or unit abilities."): each spell, and each ability whose
source is a Unit, that a player finalizes choosing at least one enemy Unit or Gear counts once for that turn
(enemy_choices_this_turn, Core 355.5); the condition enemy_choices_this_turn_at_least reads it. Kept only in a game where
some card's ability condition reads it.

  E1 spells        two spells of p1's each choosing p2's u2: the count is 1, then 2; the condition at 2 holds after both
  E2 friendly      a spell choosing p1's own u1: not counted
  E3 unit trigger  a triggered ability of p1's unit u1, finalized choosing u2: counted
  E4 gear trigger  the same ability on a Gear of p1's: not counted
  E5 no reader     a game where no card reads it keeps no ledger
  V                the condition's shape; a negative count does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (PROGRAM_VERSION, evaluate_condition, hash_value, object_identity,  # noqa: E402
                       validate_condition)
from resolution_bridge import finalize_trigger, program_hash  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, schedule_triggered_items  # noqa: E402

errors: list[str] = []
COND = {"kind": "enemy_choices_this_turn_at_least", "count": 2}
DEAL = {"op": "deal_damage", "effect_id": "d", "amount": 1,
        "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}


def board(*, reader=True):
    s = base_state()
    s["turn_id"] = "turn-5"
    s["players"]["p1"]["resources"] = {"energy": 9, "power": {}}
    s["players"]["p1"]["zones"]["main_deck"] = []
    s["players"]["p1"]["zones"]["hand"] = ["c1", "c2"]
    s["objects"]["gr"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("gr")
    if reader:
        s["objects"]["ez"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False,
                              "ability_conditions": {"ez:a1": dict(COND)}}
        s["players"]["p1"]["zones"].setdefault("legend_zone", []).append("ez")
    return s


def count(s):
    return int((s["players"]["p1"].get("enemy_choices_this_turn") or {}).get("turn-5", 0))


def cast(s, card, target):
    prog = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": f"{card}-fx", "controller": "p1", "source_object": card, "effects": [copy.deepcopy(DEAL)]}
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"play-{card}", "actor": "p1", "card": card,
            "chain_item": {"id": f"spell-{card}", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": prog["program_id"],
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    s = copy.deepcopy(s)
    s["objects"][card]["printed_cost"] = {"energy": 1, "power": {}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": [target], "selection_identities": {target: object_identity(s, target)}}]}
    got = PT.play_card(fixture(), s, decl, engine_decisions=decisions, effect_program=prog)
    assert got.get("committed"), (got.get("reason_code"), got.get("reason"))
    return got["next_effect_state"]


def trigger(s, source, target):
    prog = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "tr-fx", "controller": "p1", "source_object": source, "effects": [copy.deepcopy(DEAL)]}
    descriptor = {"trigger_id": "tr", "controller": "p1", "source_object": source, "controller_order": 0,
                  "effect_program_id": "tr-fx", "optional_at_finalize": False, "effect_program_hash": program_hash(prog),
                  "trigger_kind": "triggered"}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [target], "selection_identities": {target: object_identity(s, target)}}]}
    got = finalize_trigger(scheduled["next_state"], s, {"tr-fx": prog}, decisions)
    assert got.get("committed"), (got.get("reason"), got.get("message"))
    return got["next_effect_state"]


def main() -> int:
    s = board()
    one = cast(s, "c1", "u2")
    two = cast(one, "c2", "u2")
    if (count(one), count(two)) != (1, 2) or evaluate_condition(one, COND, controller="p1") \
            or not evaluate_condition(two, COND, controller="p1"):
        errors.append(f"E1 spells: counts {count(one)}, {count(two)}")
    if count(cast(s, "c1", "u1")) != 0:
        errors.append("E2 friendly: a spell choosing p1's own unit counted")
    if count(trigger(s, "u1", "u2")) != 1:
        errors.append(f"E3 unit trigger: count {count(trigger(s, 'u1', 'u2'))}")
    if count(trigger(s, "gr", "u2")) != 0:
        errors.append("E4 gear trigger: a Gear's ability counted")
    plain = cast(board(reader=False), "c1", "u2")
    if "enemy_choices_this_turn" in plain["players"]["p1"]:
        errors.append("E5 no reader: a game with no reader kept a ledger")
    if validate_condition(COND) or not validate_condition({**COND, "count": -1}) and not validate_condition({"kind": COND["kind"]}):
        errors.append(f"V: {validate_condition(COND)}")
    if errors:
        print("FAILED: enemy choices this turn")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: each spell or Unit ability of p1's that chose an enemy Unit or Gear counts once this turn; a friendly "
          "choice or a Gear's ability does not; no reader, no ledger (E1-E5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
