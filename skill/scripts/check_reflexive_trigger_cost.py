#!/usr/bin/env python3
"""Regression gate: a reflexive trigger after a token played, whose effect opens "you may pay [X] to ..." (set 2 package
A2, Guards!: "Play a 2 [M] Sand Soldier unit token. Then do this: You may pay [Order] to ready it.").

GPT A2 ruling 19: "Then do this:" is a Reflexive Trigger with no condition (Core 388.1, 388.2). Its controller decides at
finalization whether to perform it (388.4, 383.3.a); performing it, the cost right after the "you may" is its base cost
(383.3.b), paid to finalize it (383.3.b.1) - never asked again as it resolves. Declined or not payable, it leaves the
Chain and never becomes a Finalized Chain Item (405.2). "it" is the token the spell played, carried as the trigger's
event; a token gone after the payment is not refunded and the ready changes nothing. A token gone before finalization
leaves no choice to make (the ready names no target), so the trigger is not removed for lack of choices (403.4): it may
still be performed and paid, and readies nothing.

  R1 added        the spell resolves: the token in p1's Base, exhausted; one reflexive item pending, carrying the token
  R2 asked        finalizing asks first whether to perform it (383.3.a)
  R3 not done     not performed: it leaves the Chain, nothing paid, the token exhausted
  R4 cost asked   performed: its base cost is asked before it is finalized (trigger_cost_choice_required)
  R5 paid         performed and paid: the Order Power leaves the pool AT FINALIZATION; it resolves: the token ready
  R6 cost refused performed, the cost declined: it leaves the Chain (405.2), nothing paid, the token exhausted
  R7 unpayable    no Order Power: it leaves the Chain (trigger_cost_unpayable), nothing paid
  R8 gone after   paid, then the token killed before it resolves: the Power stays spent, it resolves readying nothing
  R9 gone before  the token killed before finalization: performed and paid, it resolves readying nothing
  N  no ask       resolving the paid trigger asks nothing more (no resolution-time payment choice)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, validate_program  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

TRIGGER = "guards-reflexive"
REFLEXIVE = "guards-reflexive-fx"
TOKEN = {"op": "play_token", "effect_id": "tok", "object_id": "sand-1", "owner": "p1", "controller": "p1",
         "token_kind": "unit", "base_might": 2, "destination": {"kind": "base", "player": "p1"}}
COST = {"op": "trigger_base_cost", "effect_id": "cost", "payment": [{"kind": "power", "domain": "order", "amount": 1}]}
READY = {"op": "ready", "effect_id": "rdy", "object_id": {"object_ref": "trigger_event_object"}}
WINDOW = {"add_window_closed": True, "confirmed_by": "harness"}


def board(order=1):
    s = base_state()
    s["players"]["p1"]["resources"] = {"energy": 0, "power": {"order": order, "fury": 1}}
    return s


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "spell-1",
            "effects": [copy.deepcopy(e) for e in effects], **extra}


def spell():
    return program("spell-1-effects", [TOKEN], conditional_triggers=[
        {"trigger_id": TRIGGER, "controller": "p1", "source_object": "spell-1", "controller_order": 0,
         "effect_program_id": REFLEXIVE, "optional_at_finalize": True,
         "condition": {"kind": "unconditional", "effect_id": "tok"}}])


REGISTRY = {REFLEXIVE: program(REFLEXIVE, [COST, READY])}


def resolve_spell(state):
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "spell-1", state, spell())


def kill_token(state):
    return apply_program(state, program("k", [{"op": "kill", "effect_id": "k", "object_id": "sand-1"}]))["next_state"]


def resolve_trigger(finalized, *, kill=False):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    if kill:
        effect = kill_token(effect)
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, TRIGGER, effect, REGISTRY[REFLEXIVE])


def order(state):
    return ((state.get("players") or {}).get("p1") or {}).get("resources", {}).get("power", {}).get("order")


def main() -> int:
    errors: list[str] = []
    done = resolve_spell(board())
    items = [i for i in (done.get("next_timing_state") or {}).get("chain", {}).get("items", [])
             if i.get("trigger_kind") == "reflexive"]
    after = done.get("next_effect_state") or {}
    event = (items[0].get("trigger_event") or {}) if len(items) == 1 else {}
    if not done.get("committed") or event.get("object") != "sand-1" or event.get("kind") != "played" \
            or after["objects"]["sand-1"]["exhausted"] is not True:
        errors.append(f"R1 added: {done.get('reason')} {[i.get('trigger_event') for i in items]}")
        return report(errors)
    timing = done["next_timing_state"]
    asked = finalize_trigger(timing, after, REGISTRY, None)
    if asked.get("committed") or asked.get("rule_locators") != ["Core 383.3.a"]:
        errors.append(f"R2 asked: {asked.get('committed')} {asked.get('reason')}")
    no = finalize_trigger(timing, after, REGISTRY, None, perform_optional_trigger=False)
    st = no.get("next_effect_state") or {}
    if not no.get("committed") or (no.get("transition") or {}).get("type") != "optional_trigger_declined" \
            or no["next_timing_state"]["chain"]["items"] or st["objects"]["sand-1"]["exhausted"] is not True \
            or order(st) != 1:
        errors.append(f"R3 not done: {no.get('reason')} {no.get('transition')}")
    cost_asked = finalize_trigger(timing, after, REGISTRY, None, perform_optional_trigger=True)
    if cost_asked.get("committed") or cost_asked.get("reason") != "trigger_cost_choice_required":
        errors.append(f"R4 cost asked: {cost_asked.get('committed')} {cost_asked.get('reason')}")
    yes = finalize_trigger(timing, after, REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=True,
                           payment_context=WINDOW)
    if not yes.get("committed") or yes.get("removed") or order(yes.get("next_effect_state") or {}) != 0:
        errors.append(f"R5 paid: finalization {yes.get('reason')} {yes.get('message')}")
    else:
        res = resolve_trigger(yes)
        st = res.get("next_effect_state") or {}
        if not res.get("committed") or st["objects"]["sand-1"]["exhausted"] is not False or order(st) != 0:
            errors.append(f"R5 paid: resolution {res.get('reason')} {res.get('reason_code')}")
        if res.get("optional_choice_required") or res.get("reason_code") == "optional_choice_required":
            errors.append("N no ask: resolving the paid trigger asked for a choice")
        gone = resolve_trigger(yes, kill=True)
        st = gone.get("next_effect_state") or {}
        if not gone.get("committed") or "sand-1" in (st["players"]["p1"]["zones"]["base"]) or order(st) != 0:
            errors.append(f"R8 gone after: {gone.get('reason')} {gone.get('reason_code')} order {order(st)}")
    refused = finalize_trigger(timing, after, REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=False)
    st = refused.get("next_effect_state") or {}
    if not refused.get("committed") or not refused.get("removed") or refused["next_timing_state"]["chain"]["items"] \
            or order(st) != 1 or st["objects"]["sand-1"]["exhausted"] is not True:
        errors.append(f"R6 cost refused: {refused.get('reason')} {refused.get('transition')}")
    poor = resolve_spell(board(order=0))
    short = finalize_trigger(poor["next_timing_state"], poor["next_effect_state"], REGISTRY, None,
                             perform_optional_trigger=True, pay_trigger_cost=True, payment_context=WINDOW)
    if not short.get("committed") or not short.get("removed") \
            or (short.get("transition") or {}).get("type") != "trigger_cost_unpayable":
        errors.append(f"R7 unpayable: {short.get('reason')} {short.get('transition')}")
    early = kill_token(after)
    before = finalize_trigger(timing, early, REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=True,
                              payment_context=WINDOW)
    if not before.get("committed") or before.get("removed") or order(before.get("next_effect_state") or {}) != 0:
        errors.append(f"R9 gone before: finalization {before.get('reason')} {before.get('transition')}")
    else:
        res = resolve_trigger(before)
        if not res.get("committed") or order(res.get("next_effect_state") or {}) != 0:
            errors.append(f"R9 gone before: resolution {res.get('reason')} {res.get('reason_code')}")
    if validate_program(REGISTRY[REFLEXIVE]) or validate_program(spell()):
        errors.append(f"V: {validate_program(REGISTRY[REFLEXIVE]) or validate_program(spell())}")
    return report(errors)


def report(errors: list[str]) -> int:
    if errors:
        print("reflexive trigger base cost checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("reflexive trigger base cost checks passed: performed or not decided at finalization; performing, the cost "
          "is paid then (declined or unpayable -> it leaves the Chain, nothing paid); resolving asks nothing more; the "
          "token gone before or after finalization -> the Power stays spent and nothing is readied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
