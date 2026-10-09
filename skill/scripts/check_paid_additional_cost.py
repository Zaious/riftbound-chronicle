#!/usr/bin/env python3
"""A play trigger whose condition is "if you paid the additional cost" (package 10, Clockwork Keeper).

"You may pay [C] as an additional cost to play me. When you play me, if you paid the additional cost, draw 1."
The first sentence is the card's own optional additional cost - one Power of its printed Domain (Core 356.2.b); paying
it is the controller's choice as the card is played (355.1.a). The conditional statement right after "When you play me"
is part of the trigger condition (383.2.a.1), read off THIS play's cost receipt as the play completes (356.4.f.1).

  P1 paid          the offer chosen and paid: the calm Power is gone, the ability goes on the Chain
  P2 declined      the offer declined: the Power stays, nothing goes on the Chain (trigger_condition_not_met)
  P3 unaffordable  the offer chosen with no calm Power in the pool: the play is refused, nothing moved
  P4 other offer   a card whose only paid cost is its base cost (no offer of its own): the condition does not hold
  P5 resolution    the card's two clauses compiled by the grammar and resolved: paid draws 1, declined draws 0
  V  validation    the condition only on a play trigger and only as {kind}; a Power payment needs its Domain
  G  grammar       both productions and their near misses

    python skill/scripts/check_paid_additional_cost.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXTS = ["You may pay :rb_rune_calm: as an additional cost to play me.",
         "When you play me, if you paid the additional cost, draw 1."]
OFFER = {"cost_offer_id": "x", "payment": {"kind": "power", "domain": "calm", "amount": 1}}
TRIGGER = {"trigger_id": "c1-on-play", "controller": "p1", "source_object": "c1", "controller_order": 0,
           "effect_program_id": "c1-on-play-effects", "optional_at_finalize": False,
           "condition": {"kind": "paid_additional_cost"}}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(*, offer=True, calm=1, trigger=TRIGGER):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, "play_triggers": [copy.deepcopy(trigger)],
                                   "printed_cost": {"energy": 2, "power": {}}, "domains": ["calm"],
                                   **({"optional_additional_costs": [copy.deepcopy(OFFER)]} if offer else {})})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {"calm": calm} if calm else {}}
    return state


def play(state, pay):
    declared = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": "p1", "card": "c1",
                "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    decisions = None if pay is None else {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                                          "decisions": [{"decision_id": "self_offer:x", "kind": "optional_choice",
                                                         "stage": "play_declaration", "controller": "p1", "value": pay}]}
    return pt.play_card(fixture(), state, declared, engine_decisions=decisions)


def enter(played):
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "unit-1", played["next_effect_state"], None)


def scheduled(done):
    return [i["id"] for i in done["next_timing_state"]["chain"]["items"]]


def main() -> int:
    # P1 / P2: paid and declined
    for label, pay, want_chain, want_calm in (("P1 paid", True, ["c1-on-play"], 0), ("P2 declined", False, [], 1)):
        s = board()
        played = play(s, pay)
        if not played.get("committed"):
            fail(label, f"play refused: {played.get('reason_code')} {played.get('reason')}")
            continue
        calm = played["next_effect_state"]["players"]["p1"]["resources"]["power"].get("calm", 0)
        done = enter(played)
        if not done.get("committed"):
            fail(label, f"entry refused: {done.get('reason_code')} {done.get('reason')}")
            continue
        if scheduled(done) != want_chain or calm != want_calm:
            fail(label, f"chain {scheduled(done)} (wanted {want_chain}), calm left {calm} (wanted {want_calm})")
        if pay is False:
            inactive = [t for t in (done.get("trace") or {}).get("inactive_play_triggers") or []] \
                if isinstance(done.get("trace"), dict) else []
            text = repr(done)
            if "trigger_condition_not_met" not in text:
                fail(label, f"the declined play does not say why the trigger did not trigger ({inactive})")
    # P3: chosen with nothing to pay it
    s = board(calm=0)
    refused = play(s, True)
    if refused.get("committed") or refused.get("next_effect_state_hash") not in (None, hash_value(s)):
        fail("P3 unaffordable", f"{refused.get('committed')} {refused.get('reason_code')}")
    # P4: no offer on the card at all - nothing on the receipt is the card's own offer
    s = board(offer=False)
    played = play(s, None)
    done = enter(played) if played.get("committed") else {}
    if not done.get("committed") or scheduled(done) != []:
        fail("P4 other offer", f"{played.get('reason_code')} {done.get('reason_code')} {done and scheduled(done)}")
    # P5: the card's own clauses, compiled by the grammar, resolved
    card = cg.compile_card([{"text": t} for t in TEXTS], cg.load_grammar())
    if card["unsupported_clauses"]:
        fail("P5 resolution", card["unsupported_clauses"])
    else:
        fields = copy.deepcopy(card["passive"]["object_fields"])
        fields["optional_additional_costs"][0]["cost_offer_id"] = "x"
        trig = fields["play_triggers"][0]
        trig.update({"controller": "p1", "source_object": "c1", "trigger_id": "c1-on-play",
                     "effect_program_id": "c1-on-play-effects"})
        if trig.get("condition") != {"kind": "paid_additional_cost"}:
            fail("P5 resolution", f"the trigger's condition is {trig.get('condition')}")
        for label, pay, want in (("paid", True, 1), ("declined", False, 0)):
            s = board(trigger=trig)
            s["objects"]["c1"]["optional_additional_costs"] = copy.deepcopy(fields["optional_additional_costs"])
            played = play(s, pay)
            if not played.get("committed"):
                fail("P5 resolution", f"{label}: {played.get('reason_code')}")
                continue
            done = enter(played)
            hand = len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"])
            chain = scheduled(done)
            if not chain:
                drew = 0
            else:
                program = {"schema_version": pt.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                           "program_id": "c1-on-play-effects", "controller": "p1", "source_object": "c1",
                           "effects": [{**copy.deepcopy(e), "effect_id": f"e{i}"} for i, e in enumerate(card["program_effects"])]}
                program = cg_bind(program)
                from effect_ir import apply_program
                ran = apply_program(done["next_effect_state"], program)
                drew = (len(ran["next_state"]["players"]["p1"]["zones"]["hand"]) - hand) if ran.get("committed") else None
            if drew != want:
                fail("P5 resolution", f"{label}: drew {drew}, wanted {want}")
    # V: validation
    s = board()
    s["objects"]["c1"]["move_triggers"] = [{**copy.deepcopy(TRIGGER), "trigger_id": "c1-move"}]
    if not any("paid the additional cost" in e for e in validate_state(s)):
        fail("V validation", "the condition was accepted on a move trigger")
    s = board()
    s["objects"]["c1"]["play_triggers"][0]["condition"] = {"kind": "paid_additional_cost", "cost_offer_id": "x"}
    if not any("paid the additional cost" in e for e in validate_state(s)):
        fail("V validation", "the condition was accepted with an extra key")
    s = board()
    s["objects"]["c1"]["optional_additional_costs"][0]["payment"] = {"kind": "power", "amount": 1}
    if not any("kind: power, domain" in e for e in validate_state(s)):
        fail("V validation", "a Power payment with no Domain was accepted")
    if validate_state(board()):
        fail("V validation", f"the witness board itself is invalid: {validate_state(board())}")
    # G: grammar
    grammar = cg.load_grammar()
    offer = cg.compile_clause(TEXTS[0], grammar)
    costs = ((offer.get("passive") or {}).get("object_fields") or {}).get("optional_additional_costs") or []
    if offer.get("production_id") != "you_may_pay_a_rune_as_an_additional_cost_to_play_me" \
            or [c.get("payment") for c in costs] != [{"kind": "power", "domain": "calm", "amount": 1}]:
        fail("G grammar", f"{offer.get('production_id')} {costs}")
    head = cg.compile_clause(TEXTS[1], grammar)
    if head.get("production_id") != "when_you_play_me_if_you_paid_the_additional_cost":
        fail("G grammar", f"{TEXTS[1]!r} -> {head.get('production_id')}")
    for near in ("Pay :rb_rune_calm: as an additional cost to play me.",
                 "You may pay :rb_rune_calm: as an additional cost to play another unit."):
        if cg.compile_clause(near, grammar).get("production_id") == offer.get("production_id"):
            fail("G grammar", f"{near!r} lowered to the offer row")
    for near in ("When you play me, if you paid the cost, draw 1.", "When I move, if you paid the additional cost, draw 1."):
        if cg.compile_clause(near, grammar).get("production_id") == head.get("production_id"):
            fail("G grammar", f"{near!r} lowered to the condition row")
    if errors:
        print("FAILED: paid additional cost checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'if you paid the additional cost' is read off the play's own cost receipt as the play completes - paid "
          "triggers, declined does not, unaffordable is refused (P1-P5, V, G)")
    return 0


def cg_bind(program: dict) -> dict:
    """The compiled draw names its player by the clause grammar's symbol; bound to p1 here, as a card's program is."""
    for effect in program["effects"]:
        for key, value in list(effect.items()):
            if value == "$controller":
                effect[key] = "p1"
    return program


if __name__ == "__main__":
    raise SystemExit(main())
