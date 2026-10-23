#!/usr/bin/env python3
"""Pay any amount as it resolves, and deal that much (package 10, Bullet Time; GPT 2026-10-08 ruling 8).

The card pays any amount of Power of any Domain to deal that much damage to each enemy unit at the Battlefield it
targets. The amount is chosen and paid as the instruction resolves (Core 204.3.a); 0 may be paid, and then the Deal deals
nothing (418.1.e); choosing not to pay at all is a receipt of its own (declined), and the Deal is ignored with it.

  B1 asked         the resolution stops for p1: pay at all? (optional_choice_required)
  B2 declined      not paid: the Power stays, the Deal skipped as linked to it, the receipt says declined
  B3 paid 0        {} paid: the payment applied with paid_total 0, the Deal a no_op, the Power stays
  B4 paid 3        2 fury + 1 calm paid: the pool empties, u2 at bf1 takes 3, p1's own unit there takes nothing
  B5 overpay       4 fury named with 2 in the pool: refused, nothing paid
  B6 at play       the allocation supplied for the play stage: refused
  V  validation    the op's closed shape; the paid amount read by a deal over a targeted battlefield only, naming a payment

    python skill/scripts/check_pay_any_amount.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
PAY = {"op": "pay_any_amount", "effect_id": "pay", "resource": "power_any", "decision_ref": "amt", "pay_ref": "payq"}
DEAL = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "linked_paid_amount", "effect_id": "pay"},
        "target": {"object_id": "bf1", "chosen_zone_class": "board", "kind": "battlefield", "bound_identity": "bf1@0"},
        "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "target_battlefield"}}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board():
    state = base_state()
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"] = {"controller": None, "objects": ["u2", "u1"], "contested": True, "contested_by": "p1"}
    state["objects"]["u2"]["base_might"] = 9
    state["objects"]["u1"]["damage"] = 0
    state["players"]["p1"]["resources"] = {"energy": 0, "power": {"fury": 2, "calm": 1}}
    return state


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "bullet-time", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def decide(state, pay=None, allocation=None, stage="resolution"):
    entries = []
    if pay is not None:
        entries.append({"decision_id": "payq", "kind": "optional_choice", "stage": "resolution", "controller": "p1", "value": pay})
    if allocation is not None:
        entries.append({"decision_id": "amt", "kind": "resource_allocation", "stage": stage, "controller": "p1", "value": allocation})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": entries}


def outcomes(result):
    return [t.get("outcome") for t in result.get("trace") or []]


def main() -> int:
    s = board()
    asked = apply_program(s, program(PAY, DEAL))
    if asked.get("reason_code") != "optional_choice_required" or asked.get("decision_controller") != "p1":
        fail("B1 asked", asked.get("reason_code"))
    declined = apply_program(s, program(PAY, DEAL), decisions=decide(s, False))
    if not declined.get("committed") or outcomes(declined) != ["declined", "skipped_linked_dependency"] \
            or declined["next_state"]["players"]["p1"]["resources"]["power"] != {"fury": 2, "calm": 1}:
        fail("B2 declined", f"{declined.get('reason')} {outcomes(declined)}")
    zero = apply_program(s, program(PAY, DEAL), decisions=decide(s, True, {}))
    if not zero.get("committed") or outcomes(zero) != ["applied", "no_op"] or zero["trace"][0].get("paid_total") != 0 \
            or zero["next_state"]["objects"]["u2"]["damage"] != 0:
        fail("B3 paid 0", f"{zero.get('reason') or zero.get('errors')} {outcomes(zero)}")
    three = apply_program(s, program(PAY, DEAL), decisions=decide(s, True, {"fury": 2, "calm": 1}))
    if not three.get("committed") or three["next_state"]["objects"]["u2"]["damage"] != 3 \
            or three["next_state"]["objects"]["u1"]["damage"] != 0 \
            or three["next_state"]["players"]["p1"]["resources"]["power"] != {"fury": 0, "calm": 0}:
        fail("B4 paid 3", f"{three.get('reason') or three.get('errors')} {outcomes(three)}")
    over = apply_program(s, program(PAY, DEAL), decisions=decide(s, True, {"fury": 4}))
    if over.get("committed") or over.get("reason_code") != "illegal_operation":
        fail("B5 overpay", f"{over.get('committed')} {over.get('reason_code')}")
    early = apply_program(s, program(PAY, DEAL), decisions=decide(s, True, {"fury": 1}, stage="play_declaration"))
    if early.get("committed"):
        fail("B6 at play", "an allocation made for the play stage paid the resolution's amount")
    for label, effects in (("an extra key on the op", [{**PAY, "amount": 2}, DEAL]),
                           ("another resource", [{**PAY, "resource": "energy"}, DEAL]),
                           ("the paid amount naming no payment", [PAY, {**DEAL, "amount_ref": {"kind": "linked_paid_amount", "effect_id": "zz"}}]),
                           ("the paid amount on a deal to one unit", [PAY, {k: v for k, v in DEAL.items() if k != "affected"}])):
        if not validate_program(program(*effects)):
            fail("V validation", f"{label} was accepted")
    if validate_program(program(PAY, DEAL)):
        fail("V validation", f"the card's own program is invalid: {validate_program(program(PAY, DEAL))}")
    if errors:
        print("FAILED: pay-any-amount checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a variable payment sizes the damage - chosen and paid as it resolves; declined is its own receipt and "
          "ignores the Deal; 0 paid deals nothing; overpaying refused (B1-B6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
