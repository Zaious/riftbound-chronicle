#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Vex - Cheerless, "While I'm in combat, friendly spells cost [1][A] less to a minimum
of [1], and enemy spells cost [1][A] more."): a permanent's passive while it is in a Combat (designated an attacker or a
defender, Core 466.2.c.3) - its controller's spells cost one Energy (never below 1 by this discount, Core 356.4.e) and one
Power of any Domain less (Core 356.4; the payer chooses the Domain when the cost has Power of more than one, 356.4.c.1);
its opponents' spells cost one Energy and one Power of any Domain more (Core 356.3).

  G1 grammar      the sentence lowers to the two discounts and the two increases; the negatives do not parse
  F1 friendly     p1's spell [3][Fury] with p1's Vex attacking: 2 Energy and no Power paid
  F2 minimum      p1's spell [1][Fury]: still 1 Energy (the minimum), no Power
  F3 no Power     p1's spell [3] (no Power): 2 Energy - the [A] has nothing to reduce
  F7 below min    p1's spell [0][Fury]: 0 Energy (the minimum never raises a cost) and no Power
  F4 two Domains  p1's spell [3][Fury][Calm]: waits for the Domain (discount_choice_required, options power:calm /
                  power:fury); Calm declared - 2 Energy and the Fury paid, the Calm not
  F5 out of combat the same Vex in its Base, undesignated: the full cost
  F6 not a spell  p1's unit [3][Fury] with Vex attacking: the full cost
  E1 enemy        p2's Vex defending, p1's spell [2][Fury]: 3 Energy, the Fury and one Power of any Domain more (Calm)
  E2 enemy short  the same with no Power left for the [A]: not payable
  E3 own          p2's Vex never raises p2's own spell (only opponents')
  V  validation   source_at other than battlefield / combat, an increase of another kind, only other than power: refused
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
from effect_ir import validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

VEX = ("While I'm in combat, friendly spells cost :rb_energy_1::rb_rune_rainbow: less to a minimum of :rb_energy_1:, and "
       "enemy spells cost :rb_energy_1::rb_rune_rainbow: more.")


def lowered(text):
    got = CG.compile_clause(text, CG.load_grammar())
    fields = copy.deepcopy((got.get("passive") or {}).get("object_fields") or {})
    for entry in fields.get("granted_cost_discounts") or []:
        if entry["discount_id"] == "$clause_id":
            entry["discount_id"] = "vex-statement"
    return fields, got.get("production_id")


def board(fields, *, vex_owner="p1", role="attacker", kind="spell", power=None, energy=4, pool=None, actor="p1"):
    """`actor` holds c1 (a `kind` costing `power`); Vex (`vex_owner`'s) at bf1 designated `role`, or in its Base when
    role is None."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["objects"]["c1"].update({"kind": kind, "owner": actor, "controller": actor})
    state["players"][actor]["zones"]["hand"].append("c1")
    vex = {"owner": vex_owner, "controller": vex_owner, "kind": "unit", "base_might": 3, "might_modifiers": [],
           "damage": 0, "exhausted": False, **copy.deepcopy(fields)}
    state["objects"]["vex"] = vex
    if role:
        vex["combat_designation"] = {"combat_id": "cb1", "role": role}
        state["battlefields"]["bf1"]["objects"].append("vex")
        # a Combat at bf1: contested by the attacker's side (Core 190.3.a)
        other = "p2" if vex_owner == "p1" else "p1"
        bf = state["battlefields"]["bf1"]
        attacker = vex_owner if role == "attacker" else other
        bf.update({"controller": other if role == "attacker" else vex_owner, "contested": True, "contested_by": attacker})
    else:
        state["players"][vex_owner]["zones"]["base"].append("vex")
    state["players"][actor]["resources"] = {"energy": energy, "power": dict(pool or {})}
    return state


def play(state, energy, power, *, actor="p1", kind="spell", choices=None):
    cost = {"base": {"energy": energy, "power": dict(power)}}
    if choices:
        cost["discount_choices"] = choices
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": actor, "card": "c1",
            "chain_item": {"id": "item-1", "object_kind": kind, "timing": "default"},
            "cost": cost, "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if kind == "unit":
        decl["entry_location"] = {"kind": "base"}
    timing = fixture(priority=actor)
    timing["turn_player"] = actor
    return PT.play_card(timing, state, decl)


def spent(state, got, actor="p1"):
    if not got.get("committed"):
        return None
    before = state["players"][actor]["resources"]
    after = got["next_effect_state"]["players"][actor]["resources"]
    return (before["energy"] - after["energy"],
            {d: before["power"].get(d, 0) - after["power"].get(d, 0) for d in before["power"]
             if before["power"].get(d, 0) != after["power"].get(d, 0)})


def main() -> int:
    errors: list[str] = []
    fields, pid = lowered(VEX)
    if pid != "while_im_in_combat_friendly_spells_cost_less_enemy_spells_cost_more" \
            or len(fields.get("granted_cost_discounts") or []) != 2 or len(fields.get("granted_cost_increases") or []) != 2:
        errors.append(f"G1 grammar: {pid} {fields}")
    for negative in ("While I'm in combat, friendly spells cost :rb_energy_1: less.",
                     "While I'm at a battlefield, friendly spells cost :rb_energy_1::rb_rune_rainbow: less to a minimum of "
                     ":rb_energy_1:, and enemy spells cost :rb_energy_1::rb_rune_rainbow: more."):
        if lowered(negative)[1] == pid:
            errors.append(f"G1 grammar: the negative {negative!r} parsed")
    s = board(fields, pool={"fury": 1})
    if validate_state(s):
        errors.append(f"board: {validate_state(s)[:2]}")
    got = play(s, 3, {"fury": 1})
    if spent(s, got) != (2, {}):
        errors.append(f"F1 friendly: {spent(s, got)} {got.get('reason_code')} {got.get('reason')}")
    s = board(fields, pool={"fury": 1})
    got = play(s, 1, {"fury": 1})
    if spent(s, got) != (1, {}):
        errors.append(f"F2 minimum: {spent(s, got)} {got.get('reason_code')}")
    # F7: the minimum bounds the Energy discount only - a spell whose Energy is already below it is not raised to it, and
    # the Power is still reduced (GPT's A2 review, reading 2)
    s = board(fields, pool={"fury": 1})
    got = play(s, 0, {"fury": 1})
    if spent(s, got) != (0, {}):
        errors.append(f"F7 below the minimum: {spent(s, got)} {got.get('reason_code')}")
    s = board(fields)
    got = play(s, 3, {})
    if spent(s, got) != (2, {}):
        errors.append(f"F3 no Power: {spent(s, got)} {got.get('reason_code')}")
    s = board(fields, pool={"fury": 1, "calm": 1})
    waited = play(s, 3, {"fury": 1, "calm": 1})
    options = sorted((waited.get("discount_choice_options") or {}).get("granted:vex:in-combat-power") or [])
    chose = play(s, 3, {"fury": 1, "calm": 1}, choices={"granted:vex:in-combat-power": "power:calm"})
    if waited.get("committed") or waited.get("reason_code") != "discount_choice_required" \
            or options != ["power:calm", "power:fury"] or spent(s, chose) != (2, {"fury": 1}):
        errors.append(f"F4 two Domains: {waited.get('reason_code')} {options} {spent(s, chose)} {chose.get('reason')}")
    s = board(fields, role=None, pool={"fury": 1})
    got = play(s, 3, {"fury": 1})
    if spent(s, got) != (3, {"fury": 1}):
        errors.append(f"F5 out of combat: {spent(s, got)} {got.get('reason_code')}")
    s = board(fields, kind="unit", pool={"fury": 1})
    got = play(s, 3, {"fury": 1}, kind="unit")
    if spent(s, got) != (3, {"fury": 1}):
        errors.append(f"F6 not a spell: {spent(s, got)} {got.get('reason_code')} {got.get('reason')}")
    s = board(fields, vex_owner="p2", role="defender", pool={"fury": 1, "calm": 1})
    got = play(s, 2, {"fury": 1})
    if spent(s, got) != (3, {"fury": 1, "calm": 1}):
        errors.append(f"E1 enemy: {spent(s, got)} {got.get('reason_code')} {got.get('reason')}")
    s = board(fields, vex_owner="p2", role="defender", pool={"fury": 1})
    got = play(s, 2, {"fury": 1})
    if got.get("committed"):
        errors.append("E2 enemy short: paid with no Power for the [A]")
    s = board(fields, vex_owner="p2", role="defender", pool={"fury": 1}, actor="p2")
    got = play(s, 2, {"fury": 1}, actor="p2")
    if spent(s, got, "p2") not in ((1, {}),):
        errors.append(f"E3 own: {spent(s, got, 'p2')} {got.get('reason_code')} {got.get('reason')}")
    for label, change in (("source_at", lambda f: f["granted_cost_discounts"][0].update(source_at="hand")),
                          ("increase kind", lambda f: f["granted_cost_increases"][0].update(applies_to="power:fury")),
                          ("only", lambda f: f["granted_cost_discounts"][1].update(only="energy"))):
        bad = copy.deepcopy(fields)
        change(bad)
        if not validate_state(board(bad)):
            errors.append(f"V: {label} validated")
    if errors:
        print("cost-in-combat checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("cost-in-combat checks passed: while Vex is in a Combat its controller's spells cost [1] (to a minimum of 1) and "
          "one Power of any Domain less - the Domain chosen when there are two - and its opponents' spells [1] and one Power "
          "of any Domain more; out of combat, or a unit, nothing; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
