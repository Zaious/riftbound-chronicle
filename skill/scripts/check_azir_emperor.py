#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Azir - Emperor of the Sands, a Legend: "Your Sand Soldiers have [Weaponmaster].
:rb_energy_1:, :rb_exhaust:: Play a 2 :rb_might: Sand Soldier unit token to your base. Use only if you've played an
Equipment this turn.").

  E1 aura       the Legend in p1's Legend Zone: p1's Sand Soldier token has Weaponmaster; p1's other unit, p2's Sand Soldier
                token do not; with the Legend gone from its Legend Zone, none does
                - by name, not tag: a Shurima unit that is no Sand Soldier gains nothing; a Sand Soldier with no
                tag has it
  E2 played     a Sand Soldier token played (play_token) with the aura: its Weaponmaster play trigger is raised
                (Core 185.2.a, 821.1.c) - p1's, optional, the engine's Weaponmaster program; without the aura none is
  E3 condition  finalized_this_turn_with_tag Equipment: a card with the Equipment tag among p1's cards Finalized this turn
                holds; a non-Equipment card, another player's ledger, or another turn's do not
  E4 activated  the Legend's line activated in its Legend Zone (Energy and [Exhaust] paid) with an Equipment Finalized this
                turn: committed; with none: refused (activation_condition_not_met)
  G  grammar    the aura and the body lower; near misses do not
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, evaluate_condition, has_keyword  # noqa: E402

AURA = "Your Sand Soldiers have [Weaponmaster]."
BODY = "Play a 2 :rb_might: Sand Soldier unit token to your base."
GATE = {"kind": "finalized_this_turn_with_tag", "tag": "Equipment"}


def soldier(owner):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": True, "is_token": True, "token_id": "sand_soldier"}


def board(legend=True):
    s = base_state()
    aura = CG.compile_clause(AURA, CG.load_grammar())["passive"]["object_fields"]
    s["objects"]["az"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, **copy.deepcopy(aura),
                          "ability_conditions": {"az:a1": dict(GATE)}}
    if legend:
        s["players"]["p1"]["zones"].setdefault("legend_zone", []).append("az")
    else:
        # a Legend that left its Legend Zone is in Banishment (Core 107.4.d)
        s["players"]["p1"]["zones"]["banishment"].append("az")
    s["objects"]["s1"] = soldier("p1")
    s["objects"]["s2"] = soldier("p2")
    s["players"]["p1"]["zones"]["base"].append("s1")
    s["players"]["p2"]["zones"]["base"].append("s2")
    return s


def program(effects, pid="az-ability"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "az", "effects": copy.deepcopy(effects)}


def bind(effects):
    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return "p1" if v == "$controller" else v
    return walk(effects)


def activate(state, n=1):
    s = copy.deepcopy(state)
    s["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    effects = bind(CG.compile_clause(BODY, CG.load_grammar())["program_effects"])
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"activate-az-{n}", "actor": "p1", "card": "az",
            "chain_item": {"id": f"ab-az-{n}", "object_kind": "ability", "timing": "default", "ability_kind": "standard"},
            "activation": {"source_object": "az", "ability_id": "az:a1"},
            "cost": {"base": {"energy": 1, "power": {}},
                     "additional": [{"cost_id": "exhaust-self", "mandatory": True,
                                     "payment": {"kind": "exhaust", "object_id": "az"}}]},
            "effect_program_id": "az-ability", "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return PT.play_card(fixture(), s, decl, effect_program=program(effects))


def main() -> int:
    errors: list[str] = []
    aura = CG.compile_clause(AURA, CG.load_grammar())
    body = CG.compile_clause(BODY, CG.load_grammar())
    if aura.get("production_id") != "your_named_units_have_keywords" \
            or body.get("production_id") != "play_a_n_might_sand_soldier_unit_token_to_your_base":
        errors.append(f"G grammar: {aura.get('production_id')} {body.get('production_id')}")
    for near in ("Your Mechs have [Weaponmaster].", "Enemy Sand Soldiers have [Weaponmaster].",
                 "Play a 2 :rb_might: Sand Soldier unit token here.", "Play a 2 :rb_might: Sand Soldier unit token."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") in (
                "your_named_units_have_keywords", "play_a_n_might_sand_soldier_unit_token_to_your_base"):
            errors.append(f"G grammar: the near miss {near!r} parsed")
    s = board()
    if IR.validate_state(s):
        errors.append(f"the board is not valid: {IR.validate_state(s)[:2]}")
    s["objects"]["u9"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("u9")
    got = (has_keyword(s, "s1", "weaponmaster"), has_keyword(s, "u9", "weaponmaster"), has_keyword(s, "s2", "weaponmaster"))
    if got != (True, False, False):
        errors.append(f"E1 aura: {got}")
    # E1 by name (GPT's A2 review, Azir's Sand Soldier): the aura names Sand Soldiers, never the Shurima tag - p1's Shurima
    # unit that is no Sand Soldier gains nothing; s1, a Sand Soldier token carrying no tag at all, has it
    s["objects"]["u8"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Shurima"]}
    s["players"]["p1"]["zones"]["base"].append("u8")
    if has_keyword(s, "u8", "weaponmaster") or s["objects"]["s1"].get("tags") or not has_keyword(s, "s1", "weaponmaster"):
        errors.append("E1 by name: a Shurima unit gained Weaponmaster, or the untagged Sand Soldier lost it")
    gone = board(legend=False)
    if IR.validate_state(gone) or has_keyword(gone, "s1", "weaponmaster"):
        errors.append("E1 aura: the Legend gone, its Sand Soldier still has Weaponmaster")
    effects = bind(body.get("program_effects") or [])
    played = apply_program(board(), program(effects, "az-play"))
    pending = played.get("pending_triggers") or []
    if not played.get("committed") or len(pending) != 1 or not str(pending[0].get("trigger_id", "")).endswith(":weaponmaster") \
            or pending[0].get("controller") != "p1" or pending[0].get("optional_at_finalize") is not True \
            or not str(pending[0].get("effect_program_id", "")).startswith(IR.WEAPONMASTER_PROGRAM_PREFIX):
        errors.append(f"E2 played: {played.get('reason') or played.get('errors')} {pending}")
    plain = board()
    plain["objects"]["az"].pop("static_auras")
    bare = apply_program(plain, program(effects, "az-play"))
    if not bare.get("committed") or bare.get("pending_triggers"):
        errors.append(f"E2 played: without the aura {bare.get('pending_triggers')}")
    s3 = board()
    s3["objects"]["eq"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                           "damage": 0, "exhausted": False, "tags": ["Equipment"]}
    s3["objects"]["sp"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                           "damage": 0, "exhausted": False, "tags": []}
    s3["players"]["p1"]["zones"]["base"].append("eq")
    s3["players"]["p1"]["zones"]["trash"].append("sp")
    turn = s3.get("turn_id", "turn-0")
    with_eq = copy.deepcopy(s3)
    with_eq["players"]["p1"]["cards_finalized_this_turn"] = {turn: ["sp", "eq"]}
    no_eq = copy.deepcopy(s3)
    no_eq["players"]["p1"]["cards_finalized_this_turn"] = {turn: ["sp"]}
    theirs = copy.deepcopy(s3)
    theirs["players"]["p2"]["cards_finalized_this_turn"] = {turn: ["eq"]}
    old = copy.deepcopy(s3)
    old["players"]["p1"]["cards_finalized_this_turn"] = {"turn-earlier": ["eq"]}
    got = tuple(evaluate_condition(x, GATE, controller="p1", object_id="az") for x in (with_eq, no_eq, theirs, old))
    if got != (True, False, False, False):
        errors.append(f"E3 condition: {got}")
    yes = activate(with_eq)
    no = activate(no_eq, n=2)
    if not yes.get("committed") or no.get("committed") or no.get("reason_code") != "activation_condition_not_met":
        errors.append(f"E4 activated: {yes.get('reason_code')} {yes.get('reason')} / {no.get('reason_code')}")
    if errors:
        print("azir-emperor checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("azir-emperor checks passed: the Legend's aura gives its controller's Sand Soldiers Weaponmaster (not other "
          "units, not the opponent's, not once it is gone); a Sand Soldier token played raises its Weaponmaster trigger; "
          "'played an Equipment this turn' reads the Finalized ledger; the line activated only then; grammar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
