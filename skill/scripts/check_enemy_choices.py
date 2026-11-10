#!/usr/bin/env python3
"""Regression gate (set 2 package A2, Ezreal - Prodigal Explorer: ":rb_exhaust:: [Reaction] - Draw 1. Use only if you've
chosen enemy units and/or gear twice this turn with spells or unit abilities."): each enemy Unit or Gear a spell,
or an ability whose source is a Unit, targets as a player finalizes it counts for that turn (set 2 A3: per target)
(enemy_choices_this_turn, Core 355.5); the condition enemy_choices_this_turn_at_least reads it. Kept only in a game where
some card's ability condition reads it.

  E1 spells        two spells of p1's each choosing p2's u2: the count is 1, then 2; the condition at 2 holds after both
  E2 friendly      a spell choosing p1's own u1: not counted
  E3 unit trigger  a triggered ability of p1's unit u1, finalized choosing u2: counted
  E4 gear trigger  the same ability on a Gear of p1's: not counted
  E5 no reader     a game where no card reads it keeps no ledger
  E6 two targets   set 2 A3: one spell targeting u2 and u3 (both p2's): the count is 2 and the condition holds
  E7 mixed         one spell targeting p2's u2 and p1's u1: 1
  E8 reflexive     a triggered ability whose source is a spell (a Reflexive Trigger the spell created, Core 389.1) choosing
                   u2: kept apart (enemy_choices_unresolved_this_turn), never counted - no source settles whether that new
                   ability chooses "with spells" (GPT's A3 review)
  E9 hinge         one counted and one kept apart: the condition is refused by name (enemy_choices_unresolved); two
                   counted and one apart: holds; one apart alone: does not hold
  E10 same object  one spell choosing u2 in both of its target slots: 2 (each slot its own target, 355.5)
  E11 repeat       a [Repeat] paid, the execution choosing u3 at play (Core 820.2): 2 with the first target
  E12 new choices  p1 gains control of p2's spell and remakes its target onto p2's e1 (Core 751-753): kept apart, never
                   counted - no source settles whether remaking a spell's choices is choosing "with spells"
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
from effect_ir import (PROGRAM_VERSION, ConditionUnsupported, evaluate_condition, hash_value,  # noqa: E402
                       object_identity, validate_condition)
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


def unresolved(s, turn="turn-5"):
    return int((s["players"]["p1"].get("enemy_choices_unresolved_this_turn") or {}).get(turn, 0))


def cast(s, card, target, second=None, repeat_target=None):
    effects = [copy.deepcopy(DEAL)]
    if second is not None:
        # set 2 A3: a second target slot of the same spell (each slot its own target, 355.5)
        effects.append({**copy.deepcopy(DEAL), "effect_id": "d2", "target": {**DEAL["target"], "decision_ref": "t2"}})
    prog = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": f"{card}-fx", "controller": "p1", "source_object": card, "effects": effects}
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"play-{card}", "actor": "p1", "card": card,
            "chain_item": {"id": f"spell-{card}", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": prog["program_id"],
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if repeat_target is not None:
        # set 2 A3: a [Repeat] paid - the execution's own choices made at play (Core 820.2), its refs suffixed #1
        decl["cost"]["additional"] = [{"cost_id": "rep", "mandatory": False, "repeat": True,
                                       "payment": {"kind": "energy", "amount": 2}}]
    s = copy.deepcopy(s)
    s["objects"][card]["printed_cost"] = {"energy": 1, "power": {}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": [target], "selection_identities": {target: object_identity(s, target)}}]
        + ([{"decision_id": "t2", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
             "value": [second], "selection_identities": {second: object_identity(s, second)}}] if second else [])
        + ([{"decision_id": "rep", "stage": "play_declaration", "kind": "optional_choice", "controller": "p1", "value": True},
            {"decision_id": "t#1", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
             "value": [repeat_target], "selection_identities": {repeat_target: object_identity(s, repeat_target)}}]
           if repeat_target is not None else [])}
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
    # set 2 A3 (community rulings RiftJudge #276, #3169): each target counts - one spell targeting two enemies is two
    s3 = board()
    s3["objects"]["u3"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                           "damage": 0, "exhausted": False}
    s3["players"]["p2"]["zones"]["base"].append("u3")
    both = cast(s3, "c1", "u2", second="u3")
    if count(both) != 2 or not evaluate_condition(both, COND, controller="p1"):
        errors.append(f"E6 one spell, two enemies: count {count(both)}")
    mixed = cast(s3, "c1", "u2", second="u1")
    if count(mixed) != 1:
        errors.append(f"E7 one spell, an enemy and a friendly: count {count(mixed)}")
    # E8: a Reflexive Trigger a spell created (Core 389.1) is a new ability whose source is the spell - whether it
    # chooses "with spells" no source settles (GPT's A3 review): kept apart, never counted. The spell card is its
    # source - in the trash by then
    s8 = board()
    s8["players"]["p1"]["zones"]["hand"].remove("c1")
    s8["players"]["p1"]["zones"]["trash"].append("c1")
    s8["objects"]["c1"]["kind"] = "spell"
    reflexive = trigger(s8, "c1", "u2")
    if (count(reflexive), unresolved(reflexive)) != (0, 1):
        errors.append(f"E8 a spell's reflexive trigger: counted {count(reflexive)}, kept apart {unresolved(reflexive)}")
    # E9: the activation hangs on it - one counted and one kept apart: refused by name, never decided; two counted and
    # one apart: holds; none counted, one apart: does not hold
    hinge = trigger(cast(s8, "c2", "u2"), "c1", "u2")
    try:
        evaluate_condition(hinge, COND, controller="p1")
        errors.append("E9 hinge: one counted and one kept apart was decided")
    except ConditionUnsupported as exc:
        if "enemy_choices_unresolved" not in str(exc):
            errors.append(f"E9 hinge: refused as {exc}")
    two_and_one = copy.deepcopy(hinge)
    two_and_one["players"]["p1"]["enemy_choices_this_turn"] = {"turn-5": 2}
    if not evaluate_condition(two_and_one, COND, controller="p1") or evaluate_condition(reflexive, COND, controller="p1"):
        errors.append("E9 hinge: two counted did not hold, or one kept apart alone held")
    # E10: the same enemy in two target slots of one spell - two targets (each slot its own, 355.5)
    same = cast(s3, "c1", "u2", second="u2")
    if count(same) != 2:
        errors.append(f"E10 one object, two slots: count {count(same)}")
    # E11: a [Repeat] paid - its execution's own targets are chosen at play (Core 820.2) and counted with the rest
    repeated = cast(s3, "c1", "u2", repeat_target="u3")
    if count(repeated) != 2:
        errors.append(f"E11 repeat: count {count(repeated)}")
    # E12: targets remade for a spell whose control p1 gained (Core 751-753, make_new_choices) - whether that is choosing
    # "with spells" no source settles: kept apart, never counted
    import check_spell_control as SC
    sc = SC.board()
    sc["objects"]["ez"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                           "damage": 0, "exhausted": False, "ability_conditions": {"ez:a1": dict(COND)}}
    sc["players"]["p1"]["zones"].setdefault("legend_zone", []).append("ez")
    remade = SC.reverse(sc, may=True, remake={"t": ["e1"]})
    after = remade.get("next_effect_state") or {}
    turn = sc.get("turn_id", "turn-0")
    if not remade.get("committed") or int((after["players"]["p1"].get("enemy_choices_this_turn") or {}).get(turn, 0)) != 0 \
            or unresolved(after, turn) != 1:
        errors.append(f"E12 new choices: {remade.get('reason') or remade.get('reason_code')} "
                      f"apart {unresolved(after, turn) if after else None}")
    if validate_condition(COND) or not validate_condition({**COND, "count": -1}) and not validate_condition({"kind": COND["kind"]}):
        errors.append(f"V: {validate_condition(COND)}")
    if errors:
        print("FAILED: enemy choices this turn")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: each enemy Unit or Gear a spell or Unit ability of p1's targeted counts this turn, once per target (one "
          "spell, two enemies: two; one object in two slots two; a [Repeat]'s targets counted); a spell's Reflexive "
          "Trigger's and remade targets kept apart, an activation hanging on them refused by name; a friendly choice or "
          "a Gear's ability does not count; no reader, no ledger (E1-E12, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
