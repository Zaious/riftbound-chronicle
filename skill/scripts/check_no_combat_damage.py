#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Ezreal - Dashing, "I don't deal combat damage."): the card's own statement - as
its side's combat damage is summed (Core 467.2.a), it contributes nothing, as a Stunned unit does (424.1.b); its Might,
its lethal threshold and its being a combatant are untouched.

  N1 alone     an attacker with the statement, Might 5: its side has 0 combat damage; its Might is still 5
  N2 beside    beside another attacker of Might 3: the side has 3
  N3 without   the same unit without the statement contributes its Might
  N4 combat    a closed combat, the attacker with the statement against a 2 Might defender: the attacker's side has
               nothing to assign; the defender assigns its 2 to it and it is dealt them
  G  grammar   the sentence lowers to the field; near misses do not
  M  move me   its activated line's body, "Move me to your base.", moves the source from a Battlefield to its
               controller's Base, choosing nothing; near misses do not parse to it
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
from check_combat_damage_assignment import add_unit, closed_combat  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from combat import assign_combat_damage, available_combat_damage  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, effective_might  # noqa: E402


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause("I don't deal combat damage.", CG.load_grammar())
    if got.get("production_id") != "i_dont_deal_combat_damage" \
            or (got.get("passive") or {}).get("object_fields") != {"deals_no_combat_damage": True}:
        errors.append(f"G grammar: {got.get('production_id')} {got.get('passive')}")
    for near in ("I don't take combat damage.", "Friendly units don't deal combat damage.", "I don't deal damage."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == "i_dont_deal_combat_damage":
            errors.append(f"G grammar: the near miss {near!r} parsed")
    s = base_state()
    add_unit(s, "z1", "p1", "bf1", might=5, deals_no_combat_damage=True)
    add_unit(s, "z2", "p1", "bf1", might=3)
    add_unit(s, "z3", "p1", "bf1", might=5)
    total, parts = available_combat_damage(s, ["z1"])
    if total != 0 or parts[0]["might"] != 5 or effective_might(s, "z1") != 5:
        errors.append(f"N1 alone: {total} {parts}")
    total, _ = available_combat_damage(s, ["z1", "z2"])
    if total != 3:
        errors.append(f"N2 beside: {total}")
    total, _ = available_combat_damage(s, ["z3"])
    if total != 5:
        errors.append(f"N3 without: {total}")
    timing, effect = closed_combat([("d1", {"might": 2})], attacker_might=5)
    effect["objects"]["u1"]["deals_no_combat_damage"] = True
    done = assign_combat_damage(timing, effect, None)
    rows = ((done.get("next_timing_state") or {}).get("combat") or {}).get("assignments") or {}
    attacker, defender = rows.get("attacker") or {}, rows.get("defender") or {}
    seen = (attacker.get("available"), [(e["unit"], e["raw_assigned"]) for e in attacker.get("entries") or []],
            defender.get("available"), [(e["unit"], e["raw_assigned"]) for e in defender.get("entries") or []])
    if done.get("committed") is not True or seen != (0, [("d1", 0)], 2, [("u1", 2)]):
        errors.append(f"N4 combat: {done.get('reason_code')} {done.get('reason')} {seen}")
    move = CG.compile_clause("Move me to your base.", CG.load_grammar())
    for near in ("Move a friendly unit to your base.", "Move me to a battlefield.", "Move me."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == "move_me_to_your_base":
            errors.append(f"M move me: the near miss {near!r} parsed")
    s = base_state()
    s["battlefields"]["bf1"]["controller"] = "p1"
    add_unit(s, "z1", "p1", "bf1", might=2)
    effects = move.get("program_effects") or []
    done = apply_program(s, {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                             "program_id": "dash", "controller": "p1", "source_object": "z1", "effects": effects})
    after = done.get("next_state") or {}
    if move.get("production_id") != "move_me_to_your_base" or not done.get("committed") \
            or "z1" not in after["players"]["p1"]["zones"]["base"] or "z1" in after["battlefields"]["bf1"]["objects"]:
        errors.append(f"M move me: {move.get('production_id')} {done.get('reason') or done.get('errors')}")
    if errors:
        print("no-combat-damage checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("no-combat-damage checks passed: a unit that says it deals no combat damage adds nothing to its side's total "
          "(alone, beside another, without the statement as before); its Might stays; in a combat its side assigns nothing "
          "while it is still assigned damage; grammar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
