#!/usr/bin/env python3
"""
Regression gate for C-52 (ADR-0013 §5; Codex G-2 on DP-71 / DP-72): Empower,
Disempower, Buff, XP and the three costs that spend them.

Must hold:
  - Empowered is a binary state for an object on the board (442.1): the action
    sets it and records the event hook P5 will emit; an object that is already
    Empowered is a no_op with `became_empowered: false` — nothing additional
    happens (441.1.b, 441.1.c.1) — while the first Empower on the same object
    does emit it (negative mutation); an object off the board is illegal;
  - Disempower removes the state and does nothing to a card that is not
    Empowered (443.2.a);
  - a Buff is one counter on a Unit (426.1.b): buffing a Unit that already has
    one is a no_op with `was_buffed: false`, which is what "chosen but not
    Buffed" (426.1.c) needs; buffing a non-Unit or an off-board Unit is
    illegal;
  - XP is a non-negative value on the player (730.1) and `gain_xp` adds to it;
  - the three costs spend real state: `spend_xp` needs the XP (730.2),
    `spend_buff` needs a Buff counter on a Unit the payer controls (702.2.b),
    `disempower_self` needs the source to be Empowered (443.2.a); each writes
    its own receipt event, and each refuses when the state is not there while
    the same play with the state commits (negative mutation);
  - a Level ability is expressible as a continuous effect gated by
    `xp_at_least`, and it stops applying when the XP is spent;
  - the scopes declare the states and the costs, and the keyword catalogue's
    Empower entry gains its production.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_costs_and_activation import ability_declaration, declaration, hand_state  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from cost_receipt import PAYMENT_EVENT_KINDS  # noqa: E402
from effect_ir import apply_program, characteristics, validate_state  # noqa: E402
from engine_check import KIND_CONFIG  # noqa: E402
from keyword_catalog import keyword_supported, load_catalog, verify  # noqa: E402
from play_transaction import play_card  # noqa: E402


def ev(result, index=0):
    return result["trace"][index] if result.get("committed") else {}


def event(result, kind):
    return next((e for e in result.get("cost_receipt", {}).get("payment_events", []) if e["kind"] == kind), None)


def main() -> int:
    errors: list[str] = []
    state = base_state()
    timing = fixture()

    # --- Empower -----------------------------------------------------------------------------
    empowered = apply_program(state, program("e", {"op": "empower", "effect_id": "e", "object_id": "u1"}))
    if not empowered.get("committed") or empowered["next_state"]["objects"]["u1"].get("empowered") is not True:
        errors.append(f"empower did not set the state: {empowered.get('reason') or empowered.get('errors')}")
    elif ev(empowered).get("became_empowered") is not True or ev(empowered).get("event_hook", {}).get("kind") != "become_empowered":
        errors.append(f"the first Empower did not record the event hook: {ev(empowered)}")
    if validate_state(empowered["next_state"]):
        errors.append(f"the Empowered state is invalid: {validate_state(empowered['next_state'])}")
    again = apply_program(empowered["next_state"], program("e2", {"op": "empower", "effect_id": "e", "object_id": "u1"}))
    if not again.get("committed") or ev(again).get("outcome") != "no_op" or ev(again).get("became_empowered") is not False:
        errors.append(f"Empowering an Empowered object was not a no_op without an event (441.1.c.1): {ev(again)}")
    if ev(again).get("event_hook"):
        errors.append("negative mutation failed: the second Empower still recorded the event hook")
    off_board = copy.deepcopy(state)
    off_board["players"]["p1"]["zones"]["base"].remove("u1")
    off_board["players"]["p1"]["zones"]["hand"].append("u1")
    if apply_program(off_board, program("e", {"op": "empower", "effect_id": "e", "object_id": "u1"})).get("reason_code") != "illegal_operation":
        errors.append("Empowering an object off the board was accepted (442.1)")
    dis = apply_program(empowered["next_state"], program("d", {"op": "disempower", "effect_id": "d", "object_id": "u1"}))
    if not dis.get("committed") or dis["next_state"]["objects"]["u1"].get("empowered"):
        errors.append("disempower did not remove the state")
    idle = apply_program(state, program("d", {"op": "disempower", "effect_id": "d", "object_id": "u1"}))
    if not idle.get("committed") or ev(idle).get("outcome") != "no_op":
        errors.append("disempowering a card that is not Empowered was not a no_op (443.2.a)")

    # --- Buff --------------------------------------------------------------------------------------
    buffed = apply_program(state, program("b", {"op": "buff", "effect_id": "b", "object_id": "u1"}))
    if not buffed.get("committed") or buffed["next_state"]["objects"]["u1"].get("buffed") is not True or ev(buffed).get("was_buffed") is not True:
        errors.append(f"buff did not place the counter: {ev(buffed)}")
    twice = apply_program(buffed["next_state"], program("b2", {"op": "buff", "effect_id": "b", "object_id": "u1"}))
    if ev(twice).get("outcome") != "no_op" or ev(twice).get("was_buffed") is not False:
        errors.append(f"a second Buff counter was placed (426.1.b): {ev(twice)}")
    if apply_program(state, program("b3", {"op": "buff", "effect_id": "b", "object_id": "c1"})).get("reason_code") != "illegal_operation":
        errors.append("buffing a non-Unit was accepted (702)")
    bad_state = copy.deepcopy(state)
    bad_state["objects"]["c1"]["buffed"] = True
    if not any("Units only" in e for e in validate_state(bad_state)):
        errors.append("a Buff counter on a non-Unit was accepted by the validator")

    # --- XP ---------------------------------------------------------------------------------------------
    gained = apply_program(state, program("x", {"op": "gain_xp", "effect_id": "x", "player": "p1", "amount": 2}))
    if not gained.get("committed") or gained["next_state"]["players"]["p1"].get("xp") != 2:
        errors.append(f"gain_xp did not add XP: {gained.get('reason') or gained.get('errors')}")
    negative = copy.deepcopy(state)
    negative["players"]["p1"]["xp"] = -1
    if not any("xp" in e for e in validate_state(negative)):
        errors.append("a negative XP value was accepted")

    # --- the three costs ------------------------------------------------------------------------------------
    rich = hand_state("c1")
    rich["players"]["p1"]["xp"] = 2
    xp_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "xp", "mandatory": True, "payment": {"kind": "spend_xp", "amount": 2}}]}
    paid = play_card(timing, rich, declaration(cost=xp_cost, payment_context=None))
    if not paid.get("committed") or paid["next_effect_state"]["players"]["p1"]["xp"] != 0 or not event(paid, "pay_spend_xp"):
        errors.append(f"spend_xp did not spend the XP: {paid.get('reason_code')} {paid.get('reason')}")
    poor = hand_state("c1")
    poor["players"]["p1"]["xp"] = 1
    if play_card(timing, poor, declaration(cost=xp_cost, payment_context=None)).get("reason_code") != "cost_unpayable":
        errors.append("negative mutation failed: spending 2 XP with 1 was accepted")

    buff_state = hand_state("c1")
    buff_state["objects"]["u1"]["buffed"] = True
    buff_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "bf", "mandatory": True, "payment": {"kind": "spend_buff", "object_id": "u1"}}]}
    spent = play_card(timing, buff_state, declaration(cost=buff_cost, payment_context=None))
    if not spent.get("committed") or spent["next_effect_state"]["objects"]["u1"].get("buffed") or not event(spent, "pay_spend_buff"):
        errors.append(f"spend_buff did not remove the counter: {spent.get('reason_code')} {spent.get('reason')}")
    if play_card(timing, hand_state("c1"), declaration(cost=buff_cost, payment_context=None)).get("reason_code") != "cost_unpayable":
        errors.append("negative mutation failed: spending a Buff that is not there was accepted")
    theirs = copy.deepcopy(buff_state)
    theirs["objects"]["u1"]["controller"] = "p2"
    if play_card(timing, theirs, declaration(cost=buff_cost, payment_context=None)).get("reason_code") != "cost_unpayable":
        errors.append("a Buff on a Unit the payer does not control was spent (702.2)")

    empowered_state = hand_state("c1")
    empowered_state["objects"]["u1"]["empowered"] = True
    self_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "de", "mandatory": True, "payment": {"kind": "disempower_self"}}]}
    used = play_card(timing, empowered_state, ability_declaration(cost=self_cost))
    if not used.get("committed") or used["next_effect_state"]["objects"]["u1"].get("empowered") or not event(used, "pay_disempower_self"):
        errors.append(f"disempower_self did not spend the state: {used.get('reason_code')} {used.get('reason')}")
    if play_card(timing, hand_state("c1"), ability_declaration(cost=self_cost)).get("reason_code") != "cost_unpayable":
        errors.append("negative mutation failed: disempowering a source that is not Empowered was accepted")

    # --- Level as a gated continuous effect --------------------------------------------------------------------
    levelled = copy.deepcopy(state)
    levelled["players"]["p1"]["xp"] = 3
    levelled["continuous_effects"] = [{
        "effect_id": "level-3", "kind": "keyword_grant", "source": {"object": "u1", "identity": None},
        "affects": {"scope": "object", "object": "u1", "identity": None}, "layer": "ability", "timestamp": 0,
        "value": {"keyword": "tank"}, "condition": {"kind": "xp_at_least", "count": 3},
        "duration": {"kind": "while_source_active"}, "passive": True,
    }]
    if "tank" not in characteristics(levelled, "u1")["keywords"]:
        errors.append("a Level ability expressed as a gated effect did not apply while the XP held")
    spent_xp = copy.deepcopy(levelled)
    spent_xp["players"]["p1"]["xp"] = 2
    if "tank" in characteristics(spent_xp, "u1")["keywords"]:
        errors.append("the Level ability survived the XP dropping below its threshold (824.2)")

    # --- scopes and the catalogue ------------------------------------------------------------------------------------
    effect_scope, play_scope = KIND_CONFIG["effect"], KIND_CONFIG["play"]
    if not {"empower_state", "buff_counters", "xp"} <= set(effect_scope["supported"]):
        errors.append("the effect scope does not declare the P4 states")
    if "spend_costs" not in play_scope["supported"] or "xp_buff_costs" in play_scope["unsupported"]:
        errors.append("the play scope does not declare the spend costs, or still refuses them")
    if not {"pay_spend_xp", "pay_spend_buff", "pay_disempower_self"} <= PAYMENT_EVENT_KINDS:
        errors.append("the receipt does not carry the three payment kinds")
    catalog = load_catalog()
    supported, note = keyword_supported(catalog, "empower")
    if not supported or "keyword_not_implemented" in note:
        errors.append(f"the keyword catalogue still claims Empower has no production: {note}")
    if verify(catalog):
        errors.append(f"the catalogue disagrees with the engine after C-52: {verify(catalog)}")

    if errors:
        print("FAILED: Empower / Buff / XP checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Empower / Buff / XP checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
