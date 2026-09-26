#!/usr/bin/env python3
"""A triggered ability's base cost is paid as it is finalized, or the ability never reaches the Chain.

Core 204.3.a / 383.3.b / 403.1.b.1: "[do X] to [do Y]" that opens a triggered ability's effect -
or follows the "you may" that opens it - makes [do X] the ability's base cost. 383.3.b.1 /
740.4.a.2: it is paid to finalize the ability. 404.2 / 404.2.a: a player may decline to pay it,
and then the ability leaves the Chain and never becomes a Finalized Chain Item (not a counter);
203.3: a cost that cannot be paid is not paid. The program carries the cost as its first
instruction (`trigger_base_cost`); resolution_bridge.finalize_trigger pays it with the play
transaction's cost machinery (trigger_cost.py) and resolution only checks the receipt.

Held here, every trigger scheduled by the engine itself (a play, a kill, the chain scheduler):

  spend a buff    "When you play me, you may spend a buff to buff me and ready me." (Wildclaw
                  Shaman's shape): paid -> the buff is gone from the unit that paid and the card
                  is buffed and ready; declined at the "you may" (383.3.a.2), or the cost declined
                  (404.2) -> removed, nothing paid, nothing happens; no buff anywhere -> removed
                  (203.3); two candidates -> the payer's choice is required, and it is honoured;
                  an enemy's buff, a choice by the opponent, or a stale identity -> refused
  exhaust me      a Legend in its Legend Zone (Volibear, Relentless Storm's shape) and a gear on
                  the board (Solari Shrine's): paid -> exhausted, then the effect; already
                  exhausted -> removed
  Energy          [1]: no Add-window confirmation -> a decision, nothing paid; confirmed and short
                  -> removed; confirmed and paid -> the Energy is gone; "[1] to return me to my
                  owner's hand" (Vayne, Hunter's shape) resolves on the typed self reference
                  return_to_hand adopted, and the unit is in its owner's hand; bounced to hand by
                  something else after paying, "return me" is ignored and the trigger resolves
                  (359.3.e.6) - the card in hand once, the Energy still spent
  Power + exhaust [rune:body] and exhaust this (Mistfall's): all or nothing - Power short, the
                  gear is NOT exhausted
  recycle me      [Deathknell] Recycle me to ready your runes (Ekko, Recurrent - 383.3.b's own
                  example): the card killed, its Deathknell scheduled; paid -> the card is at the
                  bottom of its owner's Main Deck and exactly its controller's Runes are ready
                  (not the opponent's, not a unit); the recycle wakes "When you recycle one or more
                  cards to your Main Deck" (416.2.a), scheduled after the finalized ability; the
                  card no longer in the trash -> removed
  resolution      the receipt is what resolution reads: a finalized item stripped of it, or
                  carrying another cost's hash, is refused; apply_program alone refuses the
                  instruction; a program swapped for one without its cost is refused by hash
  shape           the cost must be first, followed by an effect, carry only typed payments, pay
                  "me" with the ability's own source; a pay decision on a trigger with no cost,
                  or paying a trigger declined at its "you may", is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value,  # noqa: E402
                       object_identity, validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import next_procedure, pass_priority, schedule_triggered_items  # noqa: E402
import trigger_cost as TC  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
SELF = {"object_ref": "program_source"}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def program(program_id: str, source: str, effects: list[dict]) -> dict:
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": program_id,
            "controller": "p1", "source_object": source, "effects": effects}


def cost(*payment: dict) -> dict:
    return {"op": "trigger_base_cost", "effect_id": "cost", "payment": list(payment)}


def to_resolution(timing: dict) -> dict:
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return timing


def resolve(finalized: dict, registry: dict, item_id: str) -> dict:
    ready = to_resolution(finalized["next_timing_state"])
    step = next_procedure(ready)
    if step.get("procedure") != "resolve_newest_finalized" or step.get("subject") != item_id:
        return {"committed": False, "reason": f"next procedure {step}"}
    chain_item = next(i for i in ready["chain"]["items"] if i["id"] == item_id)
    dispatched, refusal = dispatch_program(registry, chain_item)
    if refusal:
        return {"committed": False, "reason": refusal}
    return resolve_with_program(ready, item_id, finalized["next_effect_state"], dispatched)


def choose(state: dict, decision_id: str, object_id: str, *, controller: str = "p1",
           stage: str = "trigger_finalization", identity: str | None = None) -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": decision_id, "stage": stage, "kind": "card_selection", "controller": controller,
                           "value": [object_id],
                           "selection_identities": {object_id: identity or object_identity(state, object_id)}}]}


def removed(result: dict, kind: str) -> bool:
    return (result.get("committed") is True and result.get("removed") is True
            and (result.get("transition") or {}).get("type") == kind
            and not result["next_timing_state"]["chain"]["items"])


# --- spend a buff: a play trigger (Wildclaw Shaman's shape) ------------------------------------

WS_PROGRAM = program("ws-on-play-effects", "ws", [cost({"kind": "spend_buff"}),
                                                   {"op": "buff", "effect_id": "bf", "object_id": SELF},
                                                   {"op": "ready", "effect_id": "rd", "object_id": SELF}])
WS_REGISTRY = {WS_PROGRAM["program_id"]: WS_PROGRAM}


def ws_board(*, buffed=("u1",)) -> dict:
    state = base_state()
    state["objects"]["ws"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False,
                              "play_triggers": [{"trigger_id": "ws-on-play", "controller": "p1", "source_object": "ws",
                                                 "controller_order": 0, "effect_program_id": WS_PROGRAM["program_id"],
                                                 "optional_at_finalize": True, "effect_program_hash": program_hash(WS_PROGRAM)}]}
    state["players"]["p1"]["zones"]["hand"].append("ws")
    state["objects"]["u2"]["buffed"] = True                          # an enemy's buff, never payable by p1
    for unit in buffed:
        state["objects"][unit]["buffed"] = True
    state["players"]["p1"]["resources"] = {"energy": 4, "power": {}}
    return state


def ws_enter(state: dict) -> tuple[dict, dict]:
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-ws", "actor": "p1", "card": "ws",
            "chain_item": {"id": "unit-ws", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 4, "power": {}}}, "payment_context": CLOSED, "entry_location": {"kind": "base"}}
    played = play_card(fixture(), state, decl)
    assert played.get("committed"), played.get("reason")
    timing = fixture(priority="p2", items=[item("unit-ws", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    entered = resolve_with_program(timing, "unit-ws", played["next_effect_state"], None)
    assert entered.get("committed"), entered.get("reason")
    return entered["next_timing_state"], entered["next_effect_state"]


def check_spend_buff() -> None:
    timing, state = ws_enter(ws_board())
    pending = [(i["id"], i["status"]) for i in timing["chain"]["items"]]
    if pending != [("ws-on-play", "pending")]:
        return fail("spend a buff", f"the play did not schedule the trigger: {pending}")
    if not state["objects"]["ws"].get("exhausted"):
        fail("spend a buff", "the unit did not enter exhausted, so 'ready me' would prove nothing")
    # the "you may" is asked first (383.3.a), then whether to pay (404)
    ask = finalize_trigger(timing, state, WS_REGISTRY, None)
    if ask.get("committed") or ask.get("reason") != "trigger_finalize_choice_required":
        fail("spend a buff / no choices", f"expected the 'you may' first, got {ask.get('reason')}")
    ask = finalize_trigger(timing, state, WS_REGISTRY, None, perform_optional_trigger=True)
    if ask.get("committed") or ask.get("reason") != "trigger_cost_choice_required" or ask.get("choices") != ["pay", "decline"]:
        fail("spend a buff / pay not said", f"expected trigger_cost_choice_required, got {ask.get('reason')}")
    # paid -> the buff is gone from u1, and the card is buffed and ready
    paid = finalize_trigger(timing, state, WS_REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not paid.get("committed") or paid.get("removed"):
        return fail("spend a buff / paid", f"not finalized: {paid.get('reason')} {paid.get('message')}")
    after_pay = paid["next_effect_state"]
    chain_item = paid["next_timing_state"]["chain"]["items"][0]
    if after_pay["objects"]["u1"].get("buffed") or not chain_item.get("trigger_cost_receipt"):
        fail("spend a buff / paid", "u1 kept its buff or the chain item has no receipt")
    if chain_item["trigger_cost_receipt"]["cost_hash"] != hash_value(WS_PROGRAM["effects"][0]):
        fail("spend a buff / paid", "the receipt does not name this program's cost")
    if validate_state(after_pay):
        fail("spend a buff / paid", f"the state after payment does not validate: {validate_state(after_pay)[:2]}")
    done = resolve(paid, WS_REGISTRY, "ws-on-play")
    if not done.get("committed"):
        return fail("spend a buff / resolved", f"{done.get('stage')} {done.get('reason')}")
    ws = done["next_effect_state"]["objects"]["ws"]
    outcomes = [s.get("outcome") for s in done["trace"]["effect"]]
    if not ws.get("buffed") or ws.get("exhausted") or outcomes != ["paid_at_finalization", "applied", "applied"]:
        fail("spend a buff / resolved", f"buffed={ws.get('buffed')} exhausted={ws.get('exhausted')} outcomes={outcomes}")
    if done["next_effect_state"]["objects"]["u1"].get("buffed") or not done["next_effect_state"]["objects"]["u2"].get("buffed"):
        fail("spend a buff / resolved", "the buff spent is not u1's alone")
    # declined at the "you may": removed, not triggered (383.3.a.2), nothing paid
    declined = finalize_trigger(timing, state, WS_REGISTRY, None, perform_optional_trigger=False)
    if not declined.get("committed") or declined.get("transition", {}).get("type") != "optional_trigger_declined" \
            or declined["next_timing_state"]["chain"]["items"]:
        fail("spend a buff / declined may", f"{declined.get('reason')} {declined.get('transition')}")
    if hash_value(declined.get("next_effect_state") or state) != hash_value(state):
        fail("spend a buff / declined may", "declining the trigger changed the board")
    # performed, the cost declined: removed, never finalized (404.2), nothing paid
    unpaid = finalize_trigger(timing, state, WS_REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=False)
    if not removed(unpaid, "trigger_cost_declined") or not state["objects"]["u1"].get("buffed") \
            or hash_value(unpaid["next_effect_state"]) != hash_value(state):
        fail("spend a buff / cost declined", f"{unpaid.get('reason')} {unpaid.get('transition')}")
    # nothing to spend: removed (203.3), nothing happens
    t0, s0 = ws_enter(ws_board(buffed=()))
    cannot = finalize_trigger(t0, s0, WS_REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not removed(cannot, "trigger_cost_unpayable") or hash_value(cannot["next_effect_state"]) != hash_value(s0):
        fail("spend a buff / nothing to spend", f"{cannot.get('reason')} {cannot.get('transition')}")
    # two buffed units: the payer chooses; the choice is honoured, the other keeps its buff
    t2, s2 = ws_enter(_two_buffed())
    need = finalize_trigger(t2, s2, WS_REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=True)
    decision_id = TC.spend_buff_decision_id("ws-on-play")
    if need.get("committed") or need.get("reason") != "cost_selection_required" or need.get("decision_ids") != [decision_id]:
        fail("spend a buff / two candidates", f"expected the payer's choice, got {need.get('reason')}")
    chose = finalize_trigger(t2, s2, WS_REGISTRY, choose(s2, decision_id, "u9"), perform_optional_trigger=True, pay_trigger_cost=True)
    if not chose.get("committed") or chose["next_effect_state"]["objects"]["u9"].get("buffed") \
            or not chose["next_effect_state"]["objects"]["u1"].get("buffed"):
        fail("spend a buff / chosen", f"{chose.get('reason')}: the chosen unit did not pay, or the other did")
    for label, envelope, want in (
        ("an enemy's buff", choose(s2, decision_id, "u2"), "cost_choice_illegal"),
        ("the opponent's choice", choose(s2, decision_id, "u9", controller="p2"), "decision_controller_mismatch"),
        ("a stale identity", choose(s2, decision_id, "u9", identity="u9@7"), "selection_identity_mismatch"),
        ("a play-stage choice", choose(s2, decision_id, "u9", stage="play_declaration"), "decision_stage_mismatch"),
    ):
        refused = finalize_trigger(t2, s2, WS_REGISTRY, envelope, perform_optional_trigger=True, pay_trigger_cost=True)
        if refused.get("committed") or refused.get("reason") != want:
            fail(f"spend a buff / {label}", f"expected {want}, got committed={refused.get('committed')} {refused.get('reason')}")
    # paying a trigger declined at its "you may" is contradictory
    both = finalize_trigger(timing, state, WS_REGISTRY, None, perform_optional_trigger=False, pay_trigger_cost=True)
    if both.get("committed") or both.get("reason") != "declined_trigger_cannot_pay_its_cost":
        fail("spend a buff / declined and paid", f"{both.get('reason')}")
    # --- resolution reads the receipt, and only the receipt --------------------------------------
    ready = to_resolution(paid["next_timing_state"])
    stripped = copy.deepcopy(ready)
    stripped["chain"]["items"][0].pop("trigger_cost_receipt")
    no_receipt = resolve_with_program(stripped, "ws-on-play", after_pay, WS_PROGRAM)
    if no_receipt.get("committed") or (no_receipt.get("effect_result") or {}).get("reason_code") != "trigger_base_cost_unpaid":
        fail("resolution / no receipt", f"a finalized item without its receipt resolved: {no_receipt.get('reason')}")
    other = copy.deepcopy(ready)
    other["chain"]["items"][0]["trigger_cost_receipt"]["cost_hash"] = hash_value(cost({"kind": "energy", "amount": 1}))
    wrong = resolve_with_program(other, "ws-on-play", after_pay, WS_PROGRAM)
    if wrong.get("committed") or (wrong.get("effect_result") or {}).get("reason_code") != "trigger_base_cost_unpaid":
        fail("resolution / another cost's receipt", f"resolved: {wrong.get('reason')}")
    from rules_core import validate_state as validate_timing
    malformed = copy.deepcopy(ready)
    malformed["chain"]["items"][0]["trigger_cost_receipt"] = {"cost_hash": hash_value(WS_PROGRAM["effects"][0])}
    unpaid_receipt = copy.deepcopy(ready)
    unpaid_receipt["chain"]["items"][0]["trigger_cost_receipt"]["receipt"]["paid"] = False
    if not validate_timing(malformed) or not validate_timing(unpaid_receipt) or validate_timing(ready):
        fail("resolution / receipt shape", "a receipt with no receipt body or an unpaid one validated, or the real one did not")
    bare = apply_program(after_pay, WS_PROGRAM)
    if bare.get("committed") or bare.get("reason_code") != "trigger_base_cost_unpaid":
        fail("resolution / apply_program alone", f"the cost instruction ran without a receipt: {bare.get('reason_code')}")
    free = {**WS_PROGRAM, "effects": WS_PROGRAM["effects"][1:]}
    swapped = finalize_trigger(timing, state, {WS_PROGRAM["program_id"]: free}, None, perform_optional_trigger=True)
    if swapped.get("committed") or swapped.get("reason") != "effect_program_hash_mismatch":
        fail("resolution / cost removed from the program", f"finalized: {swapped.get('reason')}")


def _two_buffed() -> dict:
    state = ws_board()
    state["objects"]["u9"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "buffed": True}
    state["players"]["p1"]["zones"]["base"].append("u9")
    return state


# --- exhaust me, Energy, Power: a scheduled trigger of a Legend, a gear -------------------------

def pending(state: dict, source: str, prog: dict, *, optional: bool = True) -> dict:
    """The engine's own chain scheduler puts the trigger on the Chain, Pending."""
    descriptor = {"trigger_id": f"{source}-trig", "controller": "p1", "source_object": source, "controller_order": 0,
                  "effect_program_id": prog["program_id"], "optional_at_finalize": optional,
                  "effect_program_hash": program_hash(prog), "trigger_kind": "triggered",
                  "source_identity": object_identity(state, source)}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    assert scheduled.get("applied"), scheduled
    return scheduled["next_state"]


def legend_board(*, exhausted=False) -> dict:
    state = base_state()
    state["objects"]["lg"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": exhausted}
    state["players"]["p1"]["zones"].setdefault("legend_zone", []).append("lg")
    return state


def gear_board(*, exhausted=False, power=None, energy=0) -> dict:
    state = base_state()
    state["objects"]["gr"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": exhausted}
    state["players"]["p1"]["zones"]["base"].append("gr")
    state["players"]["p1"]["resources"] = {"energy": energy, "power": dict(power or {})}
    return state


def check_exhaust_energy_power() -> None:
    # a Legend exhausts itself from its Legend Zone, then channels a Rune exhausted
    lg = program("lg-effects", "lg", [cost({"kind": "exhaust", "object_id": SELF}),
                                       {"op": "channel_rune", "effect_id": "ch", "player": "p1", "count": 1, "entry_state": "exhausted"}])
    reg = {lg["program_id"]: lg}
    state = legend_board()
    timing = pending(state, "lg", lg)
    paid = finalize_trigger(timing, state, reg, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not paid.get("committed") or paid.get("removed") or not paid["next_effect_state"]["objects"]["lg"]["exhausted"]:
        fail("exhaust me / Legend", f"{paid.get('reason')} {paid.get('message')}")
    else:
        done = resolve(paid, reg, "lg-trig")
        base_runes = [o for o in (done.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("base", [])
                      if done["next_effect_state"]["objects"][o]["kind"] == "rune"]
        if not done.get("committed") or base_runes != ["r1"] or not done["next_effect_state"]["objects"]["r1"]["exhausted"]:
            fail("exhaust me / Legend resolved", f"{done.get('reason')} runes={base_runes}")
    tired = legend_board(exhausted=True)
    again = finalize_trigger(pending(tired, "lg", lg), tired, reg, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not removed(again, "trigger_cost_unpayable"):
        fail("exhaust me / Legend already exhausted", f"{again.get('reason')} {again.get('transition')}")
    # a gear exhausts itself on the board, then its controller draws 1
    gr = program("gr-effects", "gr", [cost({"kind": "exhaust", "object_id": SELF}),
                                       {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])
    reg = {gr["program_id"]: gr}
    state = gear_board()
    paid = finalize_trigger(pending(state, "gr", gr), state, reg, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not paid.get("committed") or not paid["next_effect_state"]["objects"]["gr"]["exhausted"]:
        fail("exhaust me / gear", f"{paid.get('reason')} {paid.get('message')}")
    else:
        done = resolve(paid, reg, "gr-trig")
        if not done.get("committed") or len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != 1:
            fail("exhaust me / gear resolved", f"{done.get('reason')}")
    tired = gear_board(exhausted=True)
    again = finalize_trigger(pending(tired, "gr", gr), tired, reg, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not removed(again, "trigger_cost_unpayable"):
        fail("exhaust me / gear already exhausted", f"{again.get('reason')} {again.get('transition')}")
    # the source replaced by a new object since it triggered (Core 124): "me" cannot pay
    moved = gear_board()
    timing = pending(moved, "gr", gr)
    moved["objects"]["gr"]["identity"] = "gr@5"
    stale = finalize_trigger(timing, moved, reg, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not removed(stale, "trigger_cost_unpayable"):
        fail("exhaust me / a new object", f"{stale.get('reason')} {stale.get('transition')}")
    # Energy: the Add window must be confirmed closed; short -> removed; paid -> spent
    en = program("gr-energy", "gr", [cost({"kind": "energy", "amount": 1}),
                                      {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])
    reg = {en["program_id"]: en}
    state = gear_board(energy=1)
    timing = pending(state, "gr", en)
    window = finalize_trigger(timing, state, reg, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if window.get("committed") or window.get("reason") != "add_window_confirmation_required":
        fail("Energy / Add window", f"expected the window question, got {window.get('reason')}")
    paid = finalize_trigger(timing, state, reg, None, perform_optional_trigger=True, pay_trigger_cost=True, payment_context=CLOSED)
    if not paid.get("committed") or paid["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
        fail("Energy / paid", f"{paid.get('reason')} {paid.get('message')}")
    elif paid["next_timing_state"]["chain"]["items"][0]["trigger_cost_receipt"]["receipt"]["total"]["energy"] != 1:
        fail("Energy / receipt", "the receipt does not record the Energy paid")
    broke = gear_board(energy=0)
    short = finalize_trigger(pending(broke, "gr", en), broke, reg, None, perform_optional_trigger=True, pay_trigger_cost=True,
                             payment_context=CLOSED)
    if not removed(short, "trigger_cost_unpayable"):
        fail("Energy / short", f"{short.get('reason')} {short.get('transition')}")
    # [1] to return me to my owner's hand (Vayne, Hunter's shape): return_to_hand on the typed self
    vy = program("u1-return", "u1", [cost({"kind": "energy", "amount": 1}),
                                      {"op": "return_to_hand", "effect_id": "ret", "object_id": SELF}])
    reg = {vy["program_id"]: vy}
    state = base_state()
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    paid = finalize_trigger(pending(state, "u1", vy), state, reg, None, perform_optional_trigger=True, pay_trigger_cost=True,
                            payment_context=CLOSED)
    if not paid.get("committed") or paid.get("removed"):
        fail("Energy / return me", f"{paid.get('reason')} {paid.get('message')}")
    else:
        done = resolve(paid, reg, "u1-trig")
        zones = (done.get("next_effect_state") or {"players": {"p1": {"zones": {}}}})["players"]["p1"]["zones"]
        if not done.get("committed") or "u1" not in zones.get("hand", []) or "u1" in zones.get("base", []):
            fail("Energy / return me resolved", f"{done.get('reason')}: u1 is not in its owner's hand")
        elif done["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
            fail("Energy / return me resolved", "the Energy was refunded or paid twice")
        # review 5 R1-2: paid, then the unit returned to its owner's hand by something else before the
        # trigger resolves (a new object, Core 124). "Return me" cannot be followed and is ignored -
        # the trigger resolves (359.3.e.6), the card stays in hand once, the Energy stays paid
        bounced = copy.deepcopy(paid["next_effect_state"])
        bounced["players"]["p1"]["zones"]["base"].remove("u1")
        bounced["players"]["p1"]["zones"]["hand"].append("u1")
        bounced["objects"]["u1"]["identity"] = "u1@1"
        done = resolve({**paid, "next_effect_state": bounced}, reg, "u1-trig")
        after = done.get("next_effect_state") or bounced
        event = next((e for e in (done.get("trace") or {}).get("effect") or [] if e.get("effect_id") == "ret"), {})
        if not done.get("committed") or after["players"]["p1"]["zones"]["hand"].count("u1") != 1 \
                or after["players"]["p1"]["resources"]["energy"] != 0 or event.get("outcome") != "ignored_source_unavailable":
            fail("Energy / return me, bounced in reaction", f"expected the trigger to resolve with 'return me' ignored, "
                                                             f"got {done.get('reason')} {event.get('outcome')}")
    # Power and exhaust together: all or nothing
    both = program("gr-both", "gr", [cost({"kind": "power", "domain": "body", "amount": 1}, {"kind": "exhaust", "object_id": SELF}),
                                      {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])
    reg = {both["program_id"]: both}
    rich = gear_board(power={"body": 1})
    paid = finalize_trigger(pending(rich, "gr", both), rich, reg, None, perform_optional_trigger=True, pay_trigger_cost=True,
                            payment_context=CLOSED)
    after = paid.get("next_effect_state") or {}
    if not paid.get("committed") or not after["objects"]["gr"]["exhausted"] or after["players"]["p1"]["resources"]["power"].get("body") != 0:
        fail("Power + exhaust / paid", f"{paid.get('reason')} {paid.get('message')}")
    poor = gear_board(power={"fury": 1})
    short = finalize_trigger(pending(poor, "gr", both), poor, reg, None, perform_optional_trigger=True, pay_trigger_cost=True,
                             payment_context=CLOSED)
    if not removed(short, "trigger_cost_unpayable") or short["next_effect_state"]["objects"]["gr"]["exhausted"]:
        fail("Power + exhaust / Power short", "removed with the gear exhausted, or not removed")


# --- recycle me: a Deathknell (Ekko, Recurrent - Core 383.3.b's own example) -----------------

EK_PROGRAM = program("ek-deathknell-effects", "ek", [
    cost({"kind": "recycle", "object_id": SELF}),
    {"op": "ready", "effect_id": "rd", "affected": {"criteria": {"kind": "rune", "location": "board", "controller_relation": "own"}}}])
EK_REGISTRY = {EK_PROGRAM["program_id"]: EK_PROGRAM}


def ek_board(*, karma: bool = False) -> dict:
    state = base_state()
    state["objects"]["ek"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 5, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "keywords": ["deathknell"],
                              "death_triggers": [{"trigger_id": "ek-deathknell", "controller": "p1", "source_object": "ek",
                                                  "controller_order": 0, "effect_program_id": EK_PROGRAM["program_id"],
                                                  "optional_at_finalize": False, "effect_program_hash": program_hash(EK_PROGRAM)}]}
    state["players"]["p1"]["zones"]["base"].append("ek")
    for rune, owner in (("ra", "p1"), ("rb", "p1"), ("rz", "p2")):
        state["objects"][rune] = {"owner": owner, "controller": owner, "kind": "rune", "base_might": 0, "might_modifiers": [],
                                  "damage": 0, "exhausted": True}
        state["players"][owner]["zones"]["base"].append(rune)
    state["objects"]["u1"]["exhausted"] = True                         # a unit: not a Rune, stays exhausted
    if karma:   # "When you recycle one or more cards to your Main Deck" (Karma - Channeler's watch)
        state["objects"]["km"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                                  "damage": 0, "exhausted": False,
                                  "event_triggers": [{"trigger_id": "km-recycle", "controller": "p1", "source_object": "km",
                                                      "controller_order": 0, "effect_program_id": "km-effects",
                                                      "optional_at_finalize": False, "effect_program_hash": "sha256:" + "b" * 64,
                                                      "watch": {"kinds": ["recycled"], "scope": "actor",
                                                                "filter": {"destination_zone": "main_deck"},
                                                                "grouping": "one_or_more"}}]}
        state["players"]["p1"]["zones"]["base"].append("km")
    return state


def ek_killed(state: dict) -> tuple[dict, dict]:
    """p2's spell kills Ekko; the engine notes its Deathknell before the card reaches the trash
    (Core 808.1.d.2) and schedules it."""
    timing = {**fixture(priority="p1", items=[item("spell-2", "p2", "spell", "default", "finalized")], passes=["p2", "p1"]),
              "turn_player": "p2"}
    kill = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "kill-ek", "controller": "p2",
            "effects": [{"op": "kill", "effect_id": "kl", "object_id": "ek"}]}
    killed = resolve_with_program(timing, "spell-2", state, kill)
    assert killed.get("committed"), killed.get("reason")
    return killed["next_timing_state"], killed["next_effect_state"]


def check_recycle_me() -> None:
    timing, state = ek_killed(ek_board())
    if [(i["id"], i["status"]) for i in timing["chain"]["items"]] != [("ek-deathknell", "pending")] \
            or "ek" not in state["players"]["p1"]["zones"]["trash"]:
        return fail("recycle me", f"the Deathknell was not scheduled with the card in the trash: {timing['chain']['items']}")
    ask = finalize_trigger(timing, state, EK_REGISTRY, None)
    if ask.get("committed") or ask.get("reason") != "trigger_cost_choice_required":
        fail("recycle me / pay not said", f"{ask.get('reason')}")
    declined = finalize_trigger(timing, state, EK_REGISTRY, None, pay_trigger_cost=False)
    if not removed(declined, "trigger_cost_declined") or "ek" not in declined["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        fail("recycle me / declined", f"{declined.get('reason')} {declined.get('transition')}")
    paid = finalize_trigger(timing, state, EK_REGISTRY, None, pay_trigger_cost=True)
    if not paid.get("committed") or paid.get("removed"):
        return fail("recycle me / paid", f"{paid.get('reason')} {paid.get('message')}")
    deck = paid["next_effect_state"]["players"]["p1"]["zones"]["main_deck"]
    if deck[-1:] != ["ek"] or "ek" in paid["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        fail("recycle me / paid", f"the card is not at the bottom of its owner's Main Deck: {deck}")
    done = resolve(paid, EK_REGISTRY, "ek-deathknell")
    if not done.get("committed"):
        return fail("recycle me / resolved", f"{done.get('stage')} {done.get('reason')}")
    objects = done["next_effect_state"]["objects"]
    if objects["ra"]["exhausted"] or objects["rb"]["exhausted"]:
        fail("recycle me / resolved", "a Rune of its controller is still exhausted")
    if not objects["rz"]["exhausted"] or not objects["u1"]["exhausted"]:
        fail("recycle me / resolved", "the opponent's Rune or a unit was readied: 'your runes' is its controller's Runes only")
    # the card is no longer in the trash when its ability is finalized: removed (416.3, 203.3)
    gone = copy.deepcopy(state)
    gone["players"]["p1"]["zones"]["trash"].remove("ek")
    gone["players"]["p1"]["zones"]["banishment"].append("ek")
    cannot = finalize_trigger(timing, gone, EK_REGISTRY, None, pay_trigger_cost=True)
    if not removed(cannot, "trigger_cost_unpayable"):
        fail("recycle me / not in the trash", f"{cannot.get('reason')} {cannot.get('transition')}")
    # the recycle as a cost wakes "When you recycle one or more cards to your Main Deck" (416.2.a)
    timing_k, state_k = ek_killed(ek_board(karma=True))
    woke = finalize_trigger(timing_k, state_k, EK_REGISTRY, None, pay_trigger_cost=True)
    items = [(i["id"].split("@")[0], i["status"]) for i in (woke.get("next_timing_state") or {}).get("chain", {}).get("items", [])]
    if not woke.get("committed") or items != [("ek-deathknell", "finalized"), ("km-recycle", "pending")]:
        fail("recycle me / watchers", f"the recycle did not schedule the recycle watcher after the ability: {items} {woke.get('reason')}")


# --- shape --------------------------------------------------------------------------------------

def check_shape() -> None:
    draw = {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}
    for label, effects in (
        ("the cost after an instruction", [draw, cost({"kind": "energy", "amount": 1})]),
        ("the cost alone", [cost({"kind": "energy", "amount": 1})]),
        ("an unknown payment", [cost({"kind": "kill", "object_id": SELF}), draw]),
        ("'me' as a literal id", [cost({"kind": "exhaust", "object_id": "gr"}), draw]),
        ("a zero amount", [cost({"kind": "energy", "amount": 0}), draw]),
        ("a spend_buff naming its unit", [cost({"kind": "spend_buff", "object_id": "u1"}), draw]),
        ("a target on the cost", [{**cost({"kind": "energy", "amount": 1}), "target": {"object_id": "u1", "chosen_zone_class": "board"}}, draw]),
        ("an empty payment", [cost(), draw]),
    ):
        if not validate_program(program("shape", "gr", effects)):
            fail(f"shape / {label}", "validated")
    if validate_program(WS_PROGRAM) or validate_program(EK_PROGRAM):
        fail("shape", f"a well-formed cost did not validate: {validate_program(WS_PROGRAM) + validate_program(EK_PROGRAM)}")
    for label, criteria in (("runes at a battlefield", {"kind": "rune", "location": "any_battlefield"}),
                            ("an unknown relation", {"kind": "rune", "location": "board", "controller_relation": "mine"})):
        bad = program("shape", "gr", [{"op": "ready", "effect_id": "rd", "affected": {"criteria": criteria}}])
        if not validate_program(bad):
            fail(f"shape / {label}", "validated")
    killing = program("shape", "gr", [{"op": "kill", "effect_id": "kl", "affected": {"criteria": {"kind": "rune", "location": "board"}}}])
    if not validate_program(killing):
        fail("shape / killing runes", "validated: a set of Runes is only readied or exhausted here")
    # a pay decision on a trigger that has no cost
    plain = program("gr-plain", "gr", [draw])
    state = gear_board()
    odd = finalize_trigger(pending(state, "gr", plain, optional=False), state, {"gr-plain": plain}, None, pay_trigger_cost=True)
    if odd.get("committed") or odd.get("reason") != "unexpected_trigger_cost_choice":
        fail("shape / pay without a cost", f"{odd.get('reason')}")


def main() -> int:
    check_spend_buff()
    check_exhaust_energy_power()
    check_recycle_me()
    check_shape()
    if errors:
        print("FAILED: trigger base cost" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a triggered ability's base cost is paid as it is finalized, with the play transaction's cost machinery "
          "(spend a buff, exhaust me from the Legend Zone or the board, Energy, Power, recycle me from the trash); "
          "declined or unpayable, the ability leaves the Chain unfinalized and nothing is paid (Core 203.3, 204.3.a, "
          "383.3.b, 383.3.b.1, 404.2); resolution reads the receipt and pays nothing again; the recycle wakes its watcher.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
