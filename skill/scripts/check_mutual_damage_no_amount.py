#!/usr/bin/env python3
"""
Regression gate: mutual_damage_current_might carries no `amount`.

Codex's P1b ruling (2026-09-09) let a DYNAMIC modifier phrase into one mapping's
scope, on the ground that "damage equal to their current Mights" is not a
modifier rewriting an instruction - it is this op's own definition. The ruling
attached a condition: the op must neither accept nor emit a general `amount`,
and the damage must be read at resolution from each bound Unit's
effective_might. Either the validator refuses the field, or an audit proves
nothing reads it.

An audit could not prove it. The op's own branch never reads `amount`, but the
generic reduce_damage replacement path in apply_program reads `amount` off
whichever effect it is applied to, so an accepted-but-unread field was a field
that looked authoritative and was not. The validator now refuses it.

Held here:
  - a program with `amount` is refused, and the message says why;
  - the same program without it validates;
  - the damage is the CURRENT Might: a Unit buffed after the program is built
    deals the buffed amount, so the value cannot have been captured earlier;
  - the exception is this op alone - deal_damage still requires its `amount`;
  - the two Units still come from `units`, not from target/targets/object_id.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, validate_program  # noqa: E402


def program(*effects, controller="p1"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "mutual", "controller": controller, "effects": list(effects)}


FRIENDLY = {"object_id": "u1", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}
ENEMY = {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}
DUEL = {"op": "mutual_damage_current_might", "effect_id": "duel", "units": [FRIENDLY, ENEMY]}


def main() -> int:
    errors: list[str] = []

    with_amount = validate_program(program({**DUEL, "amount": 3}))
    if not any("takes no `amount`" in e for e in with_amount):
        errors.append(f"an authored amount was accepted: {with_amount}")
    clean = validate_program(program(dict(DUEL)))
    if clean:
        errors.append(f"the amount-free program no longer validates: {clean}")

    # deal_damage is untouched: it still needs its own amount.
    dmg = {"op": "deal_damage", "effect_id": "d", "amount": 2,
           "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}
    if validate_program(program(dmg)):
        errors.append("the exception leaked: deal_damage with an amount no longer validates")

    # The damage is read at resolution, not captured when the program is built.
    # A Might modifier present in the state must change what u1 deals.
    def damage_to(result, oid):
        nxt = (result or {}).get("next_state") or {}
        return ((nxt.get("objects") or {}).get(oid) or {}).get("damage")

    plain_state = base_state()
    plain_state["objects"]["u1"].update(base_might=2, might_modifiers=[])
    plain_state["objects"]["u2"].update(base_might=2, might_modifiers=[])
    plain = apply_program(plain_state, program(dict(DUEL)))

    buffed_state = base_state()
    buffed_state["objects"]["u1"].update(base_might=2)
    buffed_state["objects"]["u2"].update(base_might=2, might_modifiers=[])
    # {amount, duration, source} plus an optional STRING turn_id - the shape
    # validate_state enforces. An earlier draft of this gate used modifier_id /
    # timestamp / a dict duration, the state was refused, the program never
    # committed, and the assertion below was skipped while the gate still
    # reported PASS. Hence the explicit unexercised check that follows.
    buffed_state["objects"]["u1"]["might_modifiers"] = [
        {"amount": 3, "duration": "permanent", "source": "$chain_item"}]
    buffed = apply_program(buffed_state, program(dict(DUEL)))

    plain_dmg, buffed_dmg = damage_to(plain, "u2"), damage_to(buffed, "u2")
    if plain_dmg is None or buffed_dmg is None:
        errors.append(
            f"the run-time-Might assertion never ran: plain committed="
            f"{plain.get('committed')} ({plain.get('reason_code')} {plain.get('errors')}), "
            f"buffed committed={buffed.get('committed')} ({buffed.get('reason_code')} "
            f"{buffed.get('errors')}). An assertion that cannot run is a failure, not a pass.")
    elif buffed_dmg <= plain_dmg:
        errors.append(
            f"a Might modifier did not change the damage dealt ({plain_dmg} vs {buffed_dmg}); "
            f"the value looks captured when the program was built, not read at resolution")

    if validate_program(program({**DUEL, "target": dict(FRIENDLY)})) == []:
        errors.append("mutual_damage_current_might accepted a `target` beside its units")

    if errors:
        print("FAILED: mutual_damage_current_might amount")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("mutual_damage_current_might refuses an authored `amount`, validates without one, "
          "leaves deal_damage's amount untouched, and still takes its two Units from `units`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
