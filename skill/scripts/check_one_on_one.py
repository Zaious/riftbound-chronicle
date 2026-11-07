#!/usr/bin/env python3
"""Regression gate: "When I attack or defend one on one, double my Might this combat." (set 2 package A2: Fiora -
Peerless; Core 740.2.b: no other Unit of its side beside it, and a single opposing Unit there).

  O1  the card attacks alone into one enemy Unit: its trigger is scheduled; resolved, its Might is doubled, the
      modifier lasting this combat
  O2  it attacks beside another of p1's Units: nothing; alone into two enemy Units: nothing
  O3  it defends alone against one attacker: its trigger is scheduled
  O4  the printed form lowers to the watch (self, one_on_one); the designation event carries one_on_one
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_trigger_referent import board, into_combat, items, program_of, run_trigger, unit  # noqa: E402

TEXT = "When I attack or defend one on one, draw 1."
DOUBLE = [{"op": "modify_might", "effect_id": "dbl", "object_id": {"object_ref": "program_source"},
           "amount_ref": {"kind": "program_source_current_might"}, "duration": "this_combat", "source": "$chain_item"}]


def with_fiora(state, descriptor, *, battlefield=None):
    unit(state, "fio", "p1", might=3, battlefield=battlefield)
    state["objects"]["fio"]["event_triggers"] = [{**copy.deepcopy(descriptor), "controller": "p1", "source_object": "fio",
                                                  "effect_program_id": "fio-program"}]
    return state


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT)
    rows = ((got.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or []
    if got.get("production_id") != "when_i_attack_or_defend_one_on_one" or len(rows) != 1 \
            or rows[0]["watch"] != {"kinds": ["attacked", "defended"], "scope": "self", "filter": {"one_on_one": True}}:
        errors.append(f"O4: lowered to {got.get('production_id')} {rows}")
        rows = [{"trigger_id": "on-one-on-one", "controller_order": 0, "optional_at_finalize": False,
                 "watch": {"kinds": ["attacked", "defended"], "scope": "self", "filter": {"one_on_one": True}}}]
    descriptor = rows[0]
    registry = {"fio-program": program_of("fio-program", "fio", DOUBLE)}
    # O1: alone into one enemy
    one = with_fiora(board(bf1_controller="p2", p2_at_bf1=("e1",)), descriptor)
    opened, why = into_combat(one, "fio", actor="p1")
    if opened is None:
        errors.append(f"O1: the attack did not open a combat ({why})")
    elif len(items(opened[0], "on-one-on-one@")) != 1:
        errors.append(f"O1: one on one scheduled {[i['id'] for i in opened[0]['chain']['items']]}")
    else:
        before = IR.effective_might(opened[1], "fio")
        done, why = run_trigger(*opened, registry, "on-one-on-one@")
        if done is None:
            errors.append(f"O1: the trigger did not resolve ({why})")
        else:
            after = done["next_effect_state"]
            mods = [e for e in after.get("continuous_effects") or [] if e.get("kind") == "might_arithmetic"
                    and (e.get("affects") or {}).get("object") == "fio" and (e.get("duration") or {}).get("kind") == "this_combat"]
            if IR.effective_might(after, "fio") != 2 * before or not mods:
                errors.append(f"O1: Might {before} -> {IR.effective_might(after, 'fio')}, this-combat modifiers {mods}")
    # O2: beside another friendly unit; alone into two enemies
    pair = with_fiora(board(bf1_controller="p2", p2_at_bf1=("e1",), p1_base=("mate",)), descriptor)
    opened, why = into_combat(pair, ["fio", "mate"], actor="p1")
    if opened is None or items(opened[0], "on-one-on-one@"):
        errors.append(f"O2: attacking beside another unit triggered it, or no combat ({why})")
    crowd = with_fiora(board(bf1_controller="p2", p2_at_bf1=("e1", "e2")), descriptor)
    opened, why = into_combat(crowd, "fio", actor="p1")
    if opened is None or items(opened[0], "on-one-on-one@"):
        errors.append(f"O2: alone into two enemies triggered it, or no combat ({why})")
    # O3: defends alone against one attacker
    guard = with_fiora(board(bf1_controller="p1", p2_base=("e1",)), descriptor, battlefield="bf1")
    opened, why = into_combat(guard, "e1", actor="p2")
    if opened is None or len(items(opened[0], "on-one-on-one@")) != 1:
        errors.append(f"O3: the lone defence did not schedule it ({why or [i['id'] for i in opened[0]['chain']['items']]})")
    if errors:
        print("one-on-one checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("one-on-one checks passed: attacking or defending one on one schedules the card's trigger, doubling its Might "
          "this combat; beside a friend or against two, nothing; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
