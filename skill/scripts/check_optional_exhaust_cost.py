#!/usr/bin/env python3
"""An optional printed additional cost of exhausting a friendly unit, and what it switches on (package 10, Meditation).

"[Reaction] As an additional cost to play this, you may exhaust a friendly unit. If you do, draw 2. Otherwise, draw 1."
Paying is the controller's choice as the card is played (Core 355.1.a); the unit that pays is the payer's choice, a
friendly Unit on the board that is not already exhausted (203.3); "If you do" / "Otherwise" read that decision on the
cost receipt (356.4.f.1), nothing else.

  X1 undecided     the play asks whether to pay it
  X2 paid          paid with p1's ready unit: that unit exhausted, the component paid
  X3 declined      nothing exhausted, the component on the receipt unpaid
  X4 none ready    paid with only exhausted friendly units on the board: refused (cost_unpayable), nothing moved
  X5 enemy         an enemy unit named to pay it: refused
  X6 linked        the card's three clauses compiled: paid draws 2, declined draws 1
  G  grammar       the production and its near misses

    python skill/scripts/check_optional_exhaust_cost.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_printed_costs import decisions, intent, pick, play, state  # noqa: E402
from effect_ir import apply_program, hash_value, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

EXHAUST = {"printed_additional_costs": [{"cost_offer_id": "x", "mandatory": False, "payment": {"kind": "exhaust", "amount": 1}}]}
TEXTS = ["As an additional cost to play this, you may exhaust a friendly unit.", "If you do, draw 2.", "Otherwise, draw 1."]
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def spell(fields=EXHAUST, **kw):
    return state(fields, kind="spell", printed=(1, None), **kw)


def main() -> int:
    s = spell()
    asked = play(s, kind="spell", printed=(1, None))
    if asked.get("committed") or asked.get("reason_code") != "optional_cost_intent_required":
        fail("X1 undecided", asked.get("reason_code"))
    paid = play(s, kind="spell", printed=(1, None), with_decisions=decisions(s, intent("self_offer:x", True)))
    if not paid.get("committed") or paid["next_effect_state"]["objects"]["u1"].get("exhausted") is not True:
        fail("X2 paid", f"{paid.get('reason_code')} {paid.get('reason')}")
    declined = play(s, kind="spell", printed=(1, None), with_decisions=decisions(s, intent("self_offer:x", False)))
    comp = next((c for c in (declined.get("cost_receipt") or {}).get("components", []) if c["cost_id"] == "self_offer:x"), None)
    if not declined.get("committed") or declined["next_effect_state"]["objects"]["u1"].get("exhausted") \
            or not comp or comp.get("paid"):
        fail("X3 declined", f"{declined.get('reason_code')} {comp}")
    tired = spell()
    tired["objects"]["u1"]["exhausted"] = True
    blocked = play(tired, kind="spell", printed=(1, None), with_decisions=decisions(tired, intent("self_offer:x", True)))
    if blocked.get("committed") or blocked.get("reason_code") != "cost_unpayable" \
            or blocked.get("next_effect_state_hash") != hash_value(tired):
        fail("X4 none ready", blocked.get("reason_code"))
    two = spell(extra_units=[("e5", "p2", "base", {})])
    refused = play(two, kind="spell", printed=(1, None),
                   with_decisions=decisions(two, intent("self_offer:x", True), pick(two, "self_offer:x", ["e5"])))
    if refused.get("committed"):
        fail("X5 enemy", "an enemy unit paid the cost")
    linked = cg.compile_card([{"text": t} for t in TEXTS], cg.load_grammar())
    if linked["unsupported_clauses"]:
        fail("X6 linked", linked["unsupported_clauses"])
    else:
        fields = copy.deepcopy(linked["passive"]["object_fields"])
        for entry in fields["printed_additional_costs"]:
            entry["cost_offer_id"] = "x"
        effects = copy.deepcopy(linked["program_effects"])
        for index, effect in enumerate(effects):
            effect.update({"player": "p1", "effect_id": f"e{index}"})
            effect["predicate"].update({"cost_offer_id": "x", "cost_id": "self_offer:x"})
        for label, pay_it, wanted in (("paid", True, 2), ("declined", False, 1)):
            s = spell(fields)
            s["players"]["p1"]["zones"]["main_deck"] = ["c3", "c4x"]
            s["objects"]["c4x"] = copy.deepcopy(s["objects"]["c3"])
            s["players"]["p1"]["zones"]["trash"] = []
            played = play(s, kind="spell", printed=(1, None), with_decisions=decisions(s, intent("self_offer:x", pay_it)))
            if not played.get("committed"):
                fail("X6 linked", f"{label}: {played.get('reason_code')} {played.get('reason')}")
                continue
            program = {"schema_version": pt.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                       "program_id": "linked", "controller": "p1", "source_object": "c1", "chain_item": "item-1",
                       "cost_receipt": played["cost_receipt"], "effects": effects}
            if validate_program(program):
                fail("X6 linked", f"{label}: {validate_program(program)}")
                continue
            before = len(played["next_effect_state"]["players"]["p1"]["zones"]["hand"])
            ran = apply_program(played["next_effect_state"], program)
            drawn = len(ran["next_state"]["players"]["p1"]["zones"]["hand"]) - before if ran.get("committed") else None
            if drawn != wanted:
                fail("X6 linked", f"{label}: drew {drawn}, wanted {wanted}")
    grammar = cg.load_grammar()
    got = cg.compile_clause(TEXTS[0], grammar)
    costs = ((got.get("passive") or {}).get("object_fields") or {}).get("printed_additional_costs") or []
    if got.get("production_id") != "as_an_additional_cost_to_play_this_you_may_exhaust_a_friendly_unit" or len(costs) != 1 \
            or costs[0].get("mandatory") is not False or costs[0].get("payment") != {"kind": "exhaust", "amount": 1}:
        fail("G grammar", f"{got.get('production_id')} {costs}")
    for near in ("As an additional cost to play this, exhaust a friendly unit.",
                 "As an additional cost to play this, you may exhaust an enemy unit."):
        if cg.compile_clause(near, grammar).get("production_id") == got.get("production_id"):
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: optional exhaust cost checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: an optional printed 'exhaust a friendly unit' cost is the player's choice as the card is played, paid by a "
          "ready friendly unit only, and 'If you do' / 'Otherwise' read that choice (X1-X6, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
