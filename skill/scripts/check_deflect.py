#!/usr/bin/env python3
"""
Gate for C-23 (ADR-0007 §11): Deflect and any-domain Power.

Must hold:
  - choosing an opponent's Deflect unit adds a mandatory power_any cost of
    its Deflect value, once per choice, summed on the receipt; choosing own
    or teammate's Deflect unit adds nothing; area criteria never trigger it;
  - with one legal allocation the engine pays it; with two or more it stops
    for resource_allocation (engine-check cost_choice) and never picks; a
    supplied allocation pays exactly those domains; an allocation that does
    not sum, exceeds the pool, or comes from another player is refused;
  - the Add window is settled first; a pool still short afterwards is
    illegal; a non-positive Deflect value is invalid_input;
  - the receipt carries power_any components with exact allocations and
    validates; mirrored bindings are the runner's job (C-25).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from cost_receipt import validate_cost_receipt  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, state_hash  # noqa: E402


def scene(power, *, deflect_value=None, own=False):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1"); state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 1, "power": dict(power)}
    target = "u1" if own else "u2"
    state["objects"][target]["keywords"] = ["deflect"]
    if deflect_value is not None:
        state["objects"][target]["deflect_value"] = deflect_value
    state["players"]["p2"]["zones"]["base"].remove("u2"); state["battlefields"]["bf1"]["objects"].append("u2")
    if own:
        state["players"]["p1"]["zones"]["base"].remove("u1"); state["battlefields"]["bf1"]["objects"].append("u1")
    return state


def bolt(target="u2", count=1):
    effects = [{"op": "deal_damage", "amount": 1, "effect_id": f"dmg{i}", "target": {"object_id": target, "chosen_zone_class": "board", "kind": "unit", "location": "battlefield"}, "object_id": target} for i in range(count)]
    return program("spell-1-effects", *effects)


def declaration(payment_context=True):
    value = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "play_id": "play-1", "actor": "p1", "card": "c1",
             "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"}, "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "spell-1-effects"}
    if payment_context:
        value["payment_context"] = {"add_window_closed": True, "confirmed_by": "human"}
    return value


def allocation(state, value, controller="p1"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [{"decision_id": "power_any:play-1", "stage": "play_declaration", "kind": "resource_allocation", "controller": controller, "value": value}]}


def comp(result, cost_id):
    return next((c for c in result.get("cost_receipt", {}).get("components", []) if c["cost_id"] == cost_id), {})


def main() -> int:
    errors: list[str] = []
    timing = fixture()

    one = scene({"fury": 1})
    if validate_state(one):
        errors.append(f"deflect scene invalid: {validate_state(one)}")
    paid = play_card(timing, one, declaration(), effect_program=bolt())
    c = comp(paid, "deflect:u2:1")
    if not paid.get("committed") or c.get("kind") != "power_any" or c.get("final") != 1 or c.get("paid") is not True or paid["next_effect_state"]["players"]["p1"]["resources"]["power"].get("fury") != 0:
        errors.append(f"a sole legal allocation was not paid for the Deflect cost: {paid.get('reason_code')} {paid.get('reason')} {c}")
    else:
        if validate_cost_receipt(paid["cost_receipt"]) or paid["cost_receipt"]["total"].get("power_any") != 1:
            errors.append(f"receipt with power_any invalid: {validate_cost_receipt(paid['cost_receipt'])} {paid['cost_receipt']['total']}")
        if c.get("payment_refs") != [{"event_id": "pay:power_any:fury", "amount": 1}]:
            errors.append(f"power_any allocation not recorded exactly: {c.get('payment_refs')}")
    two = scene({"fury": 1, "calm": 1})
    ask = play_card(timing, two, declaration(), effect_program=bolt())
    if ask.get("committed") or ask.get("reason_code") != "resource_allocation_required" or ask.get("decision_ids") != ["power_any:play-1"] or ask.get("decision_controller") != "p1":
        errors.append(f"two legal allocations were auto-picked instead of asked: {ask.get('reason_code')} {ask.get('reason')}")
    else:
        check = build_engine_check("play", ask, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(two), "play_declaration": "sha256:" + "6" * 64})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "cost_choice":
            errors.append(f"allocation decision did not wrap as cost_choice: {check.get('decision_required')}")
    fury = play_card(timing, two, declaration(), engine_decisions=allocation(two, {"fury": 1}), effect_program=bolt())
    calm = play_card(timing, two, declaration(), engine_decisions=allocation(two, {"calm": 1}), effect_program=bolt())
    if not fury.get("committed") or fury["next_effect_state"]["players"]["p1"]["resources"]["power"] != {"fury": 0, "calm": 1}:
        errors.append(f"allocation to fury was not honoured: {fury.get('reason')} {fury.get('errors')}")
    if not calm.get("committed") or calm["next_effect_state"]["players"]["p1"]["resources"]["power"] != {"fury": 1, "calm": 0}:
        errors.append(f"allocation to calm was not honoured: {calm.get('reason')} {calm.get('errors')}")
    bad_sum = play_card(timing, two, declaration(), engine_decisions=allocation(two, {"fury": 1, "calm": 1}), effect_program=bolt())
    over = play_card(timing, two, declaration(), engine_decisions=allocation(two, {"fury": 2}), effect_program=bolt())
    if bad_sum.get("valid") is not False or over.get("valid") is not False:
        errors.append("an allocation that does not sum or exceeds the pool was accepted")
    other = play_card(timing, two, declaration(), engine_decisions=allocation(two, {"fury": 1}, controller="p2"), effect_program=bolt())
    if other.get("committed") or other.get("valid") is not True or other.get("reason_code") != "decision_controller_mismatch":
        errors.append("another player's allocation was accepted")
    own = play_card(timing, scene({"fury": 1}, own=True), declaration(), effect_program=bolt(target="u1"))
    if not own.get("committed") or comp(own, "deflect:u1:1") or own["cost_receipt"]["total"].get("power_any"):
        errors.append("Deflect on the caster's own unit added a cost")
    team = scene({"fury": 1}); team["players"]["p1"]["team_id"] = "A"; team["players"]["p2"]["team_id"] = "A"
    mate = play_card(timing, team, declaration(), effect_program=bolt())
    if not mate.get("committed") or comp(mate, "deflect:u2:1"):
        errors.append("Deflect on a teammate's unit added a cost")
    twice = play_card(timing, scene({"fury": 2}), declaration(), effect_program=bolt(count=2))
    if not twice.get("committed") or not comp(twice, "deflect:u2:1") or not comp(twice, "deflect:u2:2") or twice["cost_receipt"]["total"].get("power_any") != 2:
        errors.append(f"choosing the same Deflect unit twice did not cost twice (809.1.c): {twice.get('reason')} {twice.get('cost_receipt', {}).get('total')}")
    big = play_card(timing, scene({"fury": 2}, deflect_value=2), declaration(), effect_program=bolt())
    if not big.get("committed") or comp(big, "deflect:u2:1").get("final") != 2:
        errors.append("Deflect 2 did not cost 2")
    area = program("spell-1-effects", {"op": "deal_damage", "amount": 1, "effect_id": "area", "target": {"object_id": "bf1", "kind": "battlefield", "chosen_zone_class": "board"},
                                       "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "target_battlefield"}}})
    affected = play_card(timing, scene({}), declaration(), effect_program=area)
    if not affected.get("committed") or affected["cost_receipt"]["total"].get("power_any"):
        errors.append(f"an area effect over a Deflect unit added a Deflect cost: {affected.get('reason')} {affected.get('cost_receipt', {}).get('total')}")
    unconfirmed = play_card(timing, scene({"fury": 1}), declaration(payment_context=False), effect_program=bolt())
    if unconfirmed.get("reason_code") != "add_window_confirmation_required":
        errors.append("the Add window was not settled before the allocation")
    broke = play_card(timing, scene({}), declaration(), effect_program=bolt())
    if broke.get("committed") or broke.get("reason_code") != "cost_unpayable" or broke.get("valid") is not True:
        errors.append(f"no Power at all did not make the Deflect play illegal: {broke.get('reason_code')}")
    zero = scene({"fury": 1}, deflect_value=0)
    if not validate_state(zero):
        errors.append("a non-positive Deflect value was accepted")
    snap = copy.deepcopy(one)
    if one != snap or play_card(timing, one, declaration(), effect_program=bolt()) != paid:
        errors.append("Deflect scan mutated its input or is not deterministic")

    if errors:
        print("FAILED: deflect checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: choosing an opponent's Deflect unit costs its Deflect value in any-domain Power once per choice; own, teammate's and criteria-affected units add nothing; a sole legal allocation is paid, two or more stop for a resource_allocation that is honoured exactly and refused when it does not sum, overspends, or comes from another player; the Add window comes first and an empty pool is illegal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
