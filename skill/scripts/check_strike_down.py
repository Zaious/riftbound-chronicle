#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Strike Down, "Choose an equipped friendly unit. It deals damage equal to its Might to
an enemy unit. Then detach an Equipment from it."): the pair op one way (mutual_damage_current_might one_way, Core
418.6.b.3), its first slot an equipped friendly unit (selector state equipped), then a detach of one Equipment attached to
that unit, picked as it resolves when there are several (Core 436.1, 436.1.a).

  S1 strike       p1's u3 (Might 3) with one Equipment, p2's e1: e1 takes 3 (u3 is the source), u3 takes nothing; the
                  Equipment is detached
  S2 two          u3 with two Equipment: the resolution asks p1 which (card_selection_required, both named); eq2 picked:
                  eq2 detached, eq1 still on u3
  S3 unequipped   p1's u1 (no Equipment) chosen: refused as it is played (the state is read at play, Core 355.9)
  S4 gone         u3 has left the board before it resolves: no damage, nothing detached (Core 359.3.e.6)
  G  grammar      the text lowers to exactly the two instructions; near misses do not
  V  validation   one_way other than true, and a detach with a pick but no from, do not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXT = "Choose an equipped friendly unit. It deals damage equal to its Might to an enemy unit. Then detach an Equipment from it."
errors: list[str] = []


def lowered():
    return CG.compile_clause(TEXT, CG.load_grammar()).get("program_effects")


def board(equipment=("eq1",)):
    s = base_state()
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["objects"]["e1"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 5, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("u3")
    s["players"]["p2"]["zones"]["base"].append("e1")
    for oid in equipment:
        s["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False, "tags": ["Equipment"], "attached_to": "u3"}
        s["players"]["p1"]["zones"]["base"].append(oid)
    return s


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "strike", "controller": "p1", "effects": copy.deepcopy(effects)}


def decisions(s, unit="u3", enemy="e1", pick=None):
    out = [{"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [oid],
            "selection_identities": {oid: object_identity(s, oid)}} for ref, oid in (("u", unit), ("e", enemy))]
    if pick:
        out.append({"decision_id": "dt-card", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                    "value": [pick], "selection_identities": {pick: object_identity(s, pick)}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": out}


def report() -> int:
    if errors:
        print("strike-down checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("strike-down checks passed: an equipped friendly unit deals its Might to an enemy unit, one way, then one "
          "Equipment of its is detached (picked when several); an unequipped unit refused at play; gone, nothing")
    return 0


def main() -> int:
    effects = lowered()
    if [e.get("op") for e in effects or []] != ["mutual_damage_current_might", "detach"] or not effects[0].get("one_way") \
            or effects[0]["units"][0].get("equipped") is not True:
        errors.append(f"G grammar: {effects}")
        return report()
    for near in ("Choose a friendly unit. It deals damage equal to its Might to an enemy unit. Then detach an Equipment from it.",
                 "Choose an equipped friendly unit. It deals damage equal to its Might to an enemy unit."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == \
                "choose_an_equipped_friendly_unit_it_deals_damage_equal_to_its_might_to_an_enemy_unit_then_detach":
            errors.append(f"G grammar: the near miss {near!r} parsed")
    if validate_program(program(effects)):
        errors.append(f"V: {validate_program(program(effects))[:2]}")
    s = board()
    done = apply_program(s, program(effects), decisions=decisions(s))
    after = done.get("next_state") or {}
    if not done.get("committed") or after["objects"]["e1"]["damage"] != 3 or after["objects"]["u3"]["damage"] != 0 \
            or after["objects"]["eq1"].get("attached_to"):
        errors.append(f"S1 strike: {done.get('reason_code')} {done.get('reason') or done.get('errors')} "
                      f"{ {o: after.get('objects', {}).get(o) for o in ('e1', 'u3', 'eq1')} }")
    s = board(("eq1", "eq2"))
    asked = apply_program(s, program(effects), decisions=decisions(s))
    if asked.get("committed") or asked.get("reason_code") != "card_selection_required" \
            or sorted(asked.get("candidates") or []) != ["eq1", "eq2"]:
        errors.append(f"S2 two: {asked.get('reason_code')} {asked.get('candidates')}")
    done = apply_program(s, program(effects), decisions=decisions(s, pick="eq2"))
    after = done.get("next_state") or {}
    if not done.get("committed") or after["objects"]["eq2"].get("attached_to") or after["objects"]["eq1"].get("attached_to") != "u3":
        errors.append(f"S2 two: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    s = board()
    s["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s["players"]["p1"]["zones"]["hand"].append("c1")
    s["objects"]["c1"].update({"kind": "spell", "printed_cost": {"energy": 0, "power": {}}})
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-sd", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-sd", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}}, "effect_program_id": "strike",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if not PT.play_card(fixture(), s, decl, engine_decisions=decisions(s), effect_program=program(effects)).get("committed"):
        errors.append("S3 unequipped: the equipped unit's play was refused")
    if PT.play_card(fixture(), s, decl, engine_decisions=decisions(s, unit="u1"), effect_program=program(effects)).get("committed"):
        errors.append("S3 unequipped: an unequipped unit was chosen")
    s = board()
    gone = copy.deepcopy(s)
    gone["players"]["p1"]["zones"]["base"].remove("u3")
    gone["players"]["p1"]["zones"]["trash"].append("u3")
    gone["objects"]["eq1"].pop("attached_to")
    env = decisions(s)   # chosen on the board before it left (its identity then)
    env["input_hash"] = hash_value(gone)
    done = apply_program(gone, program(effects), decisions=env)
    after = done.get("next_state") or {}
    if not done.get("committed") or after["objects"]["e1"]["damage"] != 0:
        errors.append(f"S4 gone: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    bad = copy.deepcopy(effects)
    bad[0]["one_way"] = False
    if not validate_program(program(bad)):
        errors.append("V: one_way false validated")
    bad = copy.deepcopy(effects)
    del bad[1]["from"]
    if not validate_program(program(bad)):
        errors.append("V: a detach with a pick and no from validated")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
