#!/usr/bin/env python3
"""A unit's conquer that counts the excess Combat Damage its controller assigned (package 12, Tryndamere - Barbarian:
"When I conquer after an attack, if you assigned 5 or more excess damage to enemy units, you score 1 point.").

The reading is the site owner's ruling of 2026-10-14 - the community reading (RiftJudge), noted as such; neither the
07-16 nor the 10-09 Core defines "excess damage". The engine's shape: the excess is what the conquering player, as the
Combat's attacker, assigned to each enemy unit beyond the lethal amount for it (Core 2026-10-09 467.2.c.4: only once no
other unit is left to assign to), with the unit's marked damage and the replacements previewed on the assignment counted
(467.2.c.5) - battlefield_control.assigned_excess, read off the Combat's assignment receipt as the conquer is processed
(383.2.a.1). Spell damage is no part of it; a conquer that did not come out of that player's attack has none.

  T1 six over      u1 (9 Might) attacks d1 (3): 6 excess - the conquer trigger goes on the Chain
  T2 four over     u1 (7) against d1 (3): 4 - nothing
  T3 exactly five  u1 (8) against d1 (3): 5 - the trigger
  T4 marked        d1 (5 Might, 3 damage already marked) against u1 (7): lethal is 2, the excess 5 - the trigger
  T5 no attack     the same unit's conquer with no Combat behind it: nothing
  T6 defending     a Combat whose attacker is the other player: nothing
  S  shapes        the condition only on a unit's own conquer trigger, as {kind, at_least >= 1}
  G  grammar       the sentence lowers to that descriptor; near misses do not

    python skill/scripts/check_assigned_excess.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import battlefield_control as BC  # noqa: E402
import clause_grammar as CG  # noqa: E402
from check_combat_damage_assignment import closed_combat  # noqa: E402
from check_effect_ir import settle_contested  # noqa: E402
from combat import assign_combat_damage, combat_cleanup, deal_combat_damage, determine_combat_result  # noqa: E402
from effect_ir import validate_state  # noqa: E402

SENTENCE = "When I conquer after an attack, if you assigned 5 or more excess damage to enemy units, draw 1."
CONDITION = {"kind": "assigned_excess_after_attack", "at_least": 5}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def descriptor(**extra):
    return {"trigger_id": "tr-conquer", "controller": "p1", "source_object": "u1", "controller_order": 0,
            "effect_program_id": "tr-conquer-effects", "optional_at_finalize": False, "scope": "unit_here",
            "condition": dict(CONDITION), **extra}


def decided(attacker_might, defender_might, marked=0):
    t, e = closed_combat([("d1", {"might": defender_might})], attacker_might=attacker_might)
    e["mode"] = {"victory_score": 8}
    e["objects"]["u1"]["conquer_triggers"] = [descriptor()]
    e["objects"]["d1"]["damage"] = marked
    settle_contested(e)
    a = assign_combat_damage(t, e)
    if not a.get("committed"):
        return None, None, f"assign: {a.get('reason_code')} {a.get('reason')}"
    d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"])
    c = combat_cleanup(d["next_timing_state"], d["next_effect_state"])
    r = determine_combat_result(c["next_timing_state"], c["next_effect_state"])
    if not r.get("committed"):
        return None, None, f"result: {r.get('reason') or r.get('errors')}"
    return r["next_timing_state"], r["next_effect_state"], None


def conquer_fires(attacker_might, defender_might, marked=0):
    t, e, problem = decided(attacker_might, defender_might, marked)
    if problem:
        return problem
    resolved = BC.resolve_battlefield_control(t, e)
    if not resolved.get("committed"):
        return f"control: {resolved.get('reason_code')} {resolved.get('reason')}"
    return any(i.get("id") == "tr-conquer" or i.get("trigger_id") == "tr-conquer" or "tr-conquer" in str(i.get("id"))
               for i in resolved["next_timing_state"]["chain"]["items"])


def main() -> int:
    for label, args, want in (("T1 six over", (9, 3), True), ("T2 four over", (7, 3), False),
                              ("T3 exactly five", (8, 3), True), ("T4 marked", (7, 5, 3), True)):
        got = conquer_fires(*args)
        if got is not want:
            fail(label, f"the conquer trigger {'did not go' if want else 'went'} on the Chain: {got}")
    t, e, problem = decided(9, 3)
    if problem:
        fail("board", problem)
    else:
        record = t["combat"]
        if [d for d in BC._score_triggers(e, "p1", "bf1", "conquer", "turn-0", None) if d["trigger_id"] == "tr-conquer"]:
            fail("T5 no attack", "a conquer with no Combat behind it triggered")
        theirs = {**record, "attacker": "p2", "defender": "p1"}
        if [d for d in BC._score_triggers(e, "p1", "bf1", "conquer", "turn-0", theirs) if d["trigger_id"] == "tr-conquer"]:
            fail("T6 defending", "a Combat p2 attacked in counted p1's assignment")
        got = [d for d in BC._score_triggers(e, "p1", "bf1", "conquer", "turn-0", record) if d["trigger_id"] == "tr-conquer"]
        if len(got) != 1 or "condition" in got[0]:
            fail("T1 six over", f"the scheduled descriptor still carries its condition: {got}")
        for label, desc in (("player scope", descriptor(scope="controller")),
                            ("no amount", descriptor(condition={"kind": "assigned_excess_after_attack"})),
                            ("zero", descriptor(condition={"kind": "assigned_excess_after_attack", "at_least": 0}))):
            bad = {**e, "objects": {**e["objects"], "u1": {**e["objects"]["u1"], "conquer_triggers": [desc]}}}
            if not validate_state(bad):
                fail("S shapes", f"{label} accepted")
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    rows = ((lowered.get("passive") or {}).get("object_fields") or {}).get("conquer_triggers") or []
    if lowered.get("production_id") != "when_i_conquer_after_an_attack_if_you_assigned_n_or_more_excess_damage_to_enemy_units" \
            or len(rows) != 1 or rows[0].get("condition") != CONDITION or rows[0].get("scope") != "unit_here":
        fail("G grammar", f"{lowered.get('production_id')} {rows}")
    for near in ("When I conquer after an attack, draw 1.",
                 "When you conquer after an attack, if you assigned 5 or more excess damage to enemy units, draw 1."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == \
                "when_i_conquer_after_an_attack_if_you_assigned_n_or_more_excess_damage_to_enemy_units":
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: the excess-damage conquer")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the conquer trigger reads the excess its controller assigned as the attacker - beyond each enemy unit's "
          "lethal amount, marked damage counted - and needs N of it; no attack, or the other player's, gives none (T1-T6, "
          "S, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
