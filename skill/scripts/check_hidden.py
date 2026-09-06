#!/usr/bin/env python3
"""
Regression gate for C-45 (ADR-0012 §3; Codex G-1 on DP-65): the Battlefield's
Facedown Zone, the Hide action, and playing a card from Hidden.

Must hold:
  - a Facedown Zone is state on the Battlefield (107.3.b): the validator
    accepts it, counts its cards as the object's one location, refuses more
    cards than the capacity, an unknown object, a duplicate and a bad turn
    stamp; the location is not the Board (a facedown card is `non_board`);
  - hide_card puts one card from the hand or Champion Zone facedown at a
    Battlefield the actor controls, pays the cost through the receipt, makes
    the card a new object (124), leaves the timing state untouched (811.2:
    Hide opens no chain) and records who may see the card — never the card
    itself in a public field;
  - it refuses: another player's turn or a Closed State, a card without the
    Hidden keyword, a Battlefield the actor does not control, a full zone, a
    card that is not in the declared source, and an unpayable cost; a
    resource restricted to playing cannot pay a Hide (811.2), while the same
    pool pays the play it names (negative mutation);
  - playing from Hidden: refused on the turn the card was hidden (811.1),
    accepted the next turn with the base cost ignored, taking the card out of
    the Facedown Zone and onto the chain; a permanent must enter that
    Battlefield, and Gear may (overriding the Base-only rule, 811.4); a
    choice outside that Battlefield is refused, and the same play with
    hidden_targeting free_by_restriction is allowed (negative mutation);
  - engine-check has the hide_step kind with its scope, a refused hide wraps
    as illegal and a committed one as supported; the manifest carries
    hidden.py; determinism and purity.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from capability_manifest import ENGINE_SOURCES  # noqa: E402
from check_costs_and_activation import declaration, hand_state  # noqa: E402
from check_effect_ir import program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, find_location, hash_value, object_identity, validate_state, zone_class  # noqa: E402
from engine_check import KIND_CONFIG, build_engine_check  # noqa: E402
from hidden import HIDE_DECLARATION_VERSION, facedown_zone, hide_card, hidden_card  # noqa: E402
from play_transaction import play_card  # noqa: E402

CLOSED = {"add_window_closed": True, "confirmed_by": "human"}


def hide_declaration(**overrides):
    value = {
        "schema_version": HIDE_DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "hide_id": "hide-1", "actor": "p1", "card": "c1", "source": "hand", "battlefield": "bf1",
        "cost": {"base": {"energy": 0, "power": {"fury": 1}}}, "payment_context": dict(CLOSED),
    }
    value.update(overrides)
    return {k: v for k, v in value.items() if v is not None}


def hideable(energy=0, power=None):
    state = hand_state("c1", "c2", energy=energy)  # c2 is a second card in hand without Hidden
    state["players"]["p1"]["resources"]["power"] = dict(power if power is not None else {"fury": 1})
    state["objects"]["c1"]["hidden"] = True
    state["battlefields"]["bf1"]["controller"] = "p1"
    return state


def hashes(effect_state):
    return {"timing_state": "sha256:" + "1" * 64, "effect_state": hash_value(effect_state), "hide_declaration": "sha256:" + "2" * 64}


def main() -> int:
    errors: list[str] = []
    timing = fixture()
    state = hideable()

    # --- the Facedown Zone as state --------------------------------------------------------------
    hidden_state = copy.deepcopy(state)
    hidden_state["players"]["p1"]["zones"]["hand"] = ["c2"]
    hidden_state["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": [{"object_id": "c1", "controller": "p1", "hidden_on_turn": "turn-1"}]}
    if validate_state(hidden_state):
        errors.append(f"a state with a facedown card is invalid: {validate_state(hidden_state)}")
    if find_location(hidden_state, "c1") != ("facedown", "bf1", "p1") or zone_class(find_location(hidden_state, "c1")) != "non_board":
        errors.append(f"a facedown card's location is wrong: {find_location(hidden_state, 'c1')}")
    for label, mutate in (
        ("over capacity", lambda s: s["battlefields"]["bf1"]["facedown"].update({"capacity": 0})),
        ("unknown object", lambda s: s["battlefields"]["bf1"]["facedown"]["cards"].append({"object_id": "zz", "controller": "p1", "hidden_on_turn": "turn-1"})),
        ("bad controller", lambda s: s["battlefields"]["bf1"]["facedown"]["cards"][0].update({"controller": "p9"})),
        ("bad turn stamp", lambda s: s["battlefields"]["bf1"]["facedown"]["cards"][0].update({"hidden_on_turn": ""})),
        ("also in hand", lambda s: s["players"]["p1"]["zones"]["hand"].append("c1")),
    ):
        broken = copy.deepcopy(hidden_state)
        mutate(broken)
        if not validate_state(broken):
            errors.append(f"a facedown zone {label} was accepted")

    # --- hide_card ---------------------------------------------------------------------------------
    hidden_result = hide_card(timing, state, hide_declaration())
    if not hidden_result.get("committed"):
        errors.append(f"hiding a Hidden card at a controlled Battlefield failed: {hidden_result.get('reason_code')} {hidden_result.get('reason')}")
    else:
        after = hidden_result["next_effect_state"]
        entry = hidden_card(after, "bf1", "c1")
        if entry is None or entry["controller"] != "p1" or entry["hidden_on_turn"] != after.get("turn_id", "turn-0"):
            errors.append(f"the card did not enter the Facedown Zone with its turn stamp: {entry}")
        if after["players"]["p1"]["zones"]["hand"] != ["c2"] or object_identity(after, "c1") != "c1@1":
            errors.append("the hidden card did not leave the hand as a new object (124)")
        if hidden_result["next_timing_state_hash"] != hidden_result["input_timing_state_hash"]:
            errors.append("Hide changed the timing state; it opens no chain (811.2)")
        if after["players"]["p1"]["resources"]["power"].get("fury", 0) != 0 or not hidden_result["cost_receipt"]["paid"]:
            errors.append(f"the Hide cost was not paid: {after['players']['p1']['resources']}")
        if hidden_result["trace"][-1].get("card_visible_to") != ["p1"] or hidden_result["trace"][-1].get("not_a_play") is not True:
            errors.append(f"the hide trace is wrong: {hidden_result['trace'][-1]}")
        check = build_engine_check("hide_step", hidden_result, input_hashes=hashes(state))
        if check["outcome"] != "supported" or check["component"]["name"] != "hidden":
            errors.append(f"a committed hide wrapped as {check['outcome']} {check['component']}")

    for label, kwargs, code in (
        ("another player's turn", {"actor": "p2", "card": "c4"}, "hide_timing_illegal"),
        ("a card without Hidden", {"card": "c2"}, "card_has_no_hidden"),
        ("a card that is not in the source", {"source": "champion_zone"}, "card_not_in_source"),
    ):
        refused = hide_card(timing, state, hide_declaration(**kwargs))
        if refused.get("committed") or refused.get("reason_code") != code:
            errors.append(f"hiding with {label} was not refused as {code}: {refused.get('reason_code')} {refused.get('reason')}")
        elif build_engine_check("hide_step", refused, input_hashes=hashes(state))["outcome"] != "illegal":
            errors.append(f"a refused hide ({label}) did not wrap as illegal")
    not_mine = copy.deepcopy(state)
    not_mine["battlefields"]["bf1"]["controller"] = "p2"
    if hide_card(timing, not_mine, hide_declaration()).get("reason_code") != "battlefield_not_controlled":
        errors.append("hiding at a Battlefield the actor does not control was accepted")
    full = copy.deepcopy(state)
    full["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": [{"object_id": "c3", "controller": "p1", "hidden_on_turn": "turn-0"}]}
    full["players"]["p1"]["zones"]["trash"] = []
    if hide_card(timing, full, hide_declaration()).get("reason_code") != "facedown_zone_full":
        errors.append("hiding into a full Facedown Zone was accepted")
    broke = copy.deepcopy(state)
    broke["players"]["p1"]["resources"]["power"] = {}
    if hide_card(timing, broke, hide_declaration()).get("reason_code") != "cost_unpayable":
        errors.append("an unpayable Hide cost was accepted")

    # a resource restricted to playing cannot pay a Hide (811.2)
    restricted = copy.deepcopy(state)
    restricted["players"]["p1"]["resources"] = {"energy": 0, "power": {}, "restricted": [{"restriction_id": "lux", "kind": "energy", "amount": 1, "uses": ["play_spell"]}]}
    hide_energy = hide_declaration(cost={"base": {"energy": 1, "power": {}}})
    blocked = hide_card(timing, restricted, hide_energy)
    if blocked.get("reason_code") != "cost_unpayable" or blocked.get("restricted_not_applicable") != ["lux"]:
        errors.append(f"a play-restricted resource paid for a Hide: {blocked.get('reason_code')} {blocked.get('restricted_not_applicable')}")
    if not play_card(timing, restricted, declaration(cost={"base": {"energy": 1, "power": {}}})).get("committed"):
        errors.append("negative mutation failed: the same restricted pool did not pay the play it names, so the Hide refusal proves nothing")

    # --- playing from Hidden -------------------------------------------------------------------------------
    committed = hide_card(timing, state, hide_declaration())["next_effect_state"]
    same_turn = play_card(timing, committed, declaration(source={"kind": "facedown", "battlefield": "bf1"},
                                                         cost_override={"kind": "ignore_base_cost", "source": "hidden"}, payment_context=None))
    if same_turn.get("committed") or same_turn.get("reason_code") != "hidden_same_turn":
        errors.append(f"a card hidden this turn was playable: {same_turn.get('reason_code')} {same_turn.get('reason')}")
    next_turn = copy.deepcopy(committed)
    next_turn["turn_id"] = "turn-2"
    played = play_card(timing, next_turn, declaration(source={"kind": "facedown", "battlefield": "bf1"},
                                                      cost_override={"kind": "ignore_base_cost", "source": "hidden"}, payment_context=None))
    if not played.get("committed"):
        errors.append(f"playing from Hidden on a later turn failed: {played.get('reason_code')} {played.get('reason')}")
    else:
        after = played["next_effect_state"]
        if facedown_zone(after, "bf1")["cards"] or after["chain_items"]["spell-1"]["card"] != "c1":
            errors.append("the played card did not leave the Facedown Zone for the chain")
        if played["cost_receipt"]["total"] != {"energy": 0, "power": {}} or played["trace"][0].get("hidden", {}).get("battlefield") != "bf1":
            errors.append(f"the hidden play did not ignore its base cost or record its battlefield: {played['trace'][0].get('hidden')}")
    gear = copy.deepcopy(next_turn)
    gear["objects"]["c1"]["kind"] = "gear"
    gear_decl = declaration(source={"kind": "facedown", "battlefield": "bf1"}, cost_override={"kind": "ignore_base_cost", "source": "hidden"}, payment_context=None,
                            chain_item={"id": "gear-1", "object_kind": "gear", "timing": "default"}, entry_location={"kind": "battlefield", "battlefield": "bf1"})
    if not play_card(timing, gear, gear_decl).get("committed"):
        errors.append(f"a hidden Gear could not enter its Battlefield (811.4): {play_card(timing, gear, gear_decl).get('reason')}")
    base_entry = {**gear_decl, "entry_location": {"kind": "base"}}
    if play_card(timing, gear, base_entry).get("reason_code") != "hidden_entry_location":
        errors.append("a hidden permanent was allowed to enter somewhere other than its Battlefield")
    targeting = copy.deepcopy(next_turn)
    targeting["objects"]["u2"]["controller"] = "p2"
    target_program = program("spell-1-effects", {"op": "deal_damage", "effect_id": "d", "amount": 1, "object_id": "u2",
                                                 "target": {"object_id": "u2", "chosen_zone_class": "board", "controller_relation": "enemy"}})
    outside = play_card(timing, targeting, declaration(source={"kind": "facedown", "battlefield": "bf1"}, cost_override={"kind": "ignore_base_cost", "source": "hidden"},
                                                       payment_context=None, effect_program_id="spell-1-effects"), effect_program=target_program)
    if outside.get("reason_code") != "hidden_target_outside_battlefield":
        errors.append(f"a hidden play chose outside its Battlefield: {outside.get('reason_code')} {outside.get('reason')}")
    freed = play_card(timing, targeting, declaration(source={"kind": "facedown", "battlefield": "bf1"}, cost_override={"kind": "ignore_base_cost", "source": "hidden"},
                                                     payment_context=None, effect_program_id="spell-1-effects", hidden_targeting="free_by_restriction"), effect_program=target_program)
    if not freed.get("committed"):
        errors.append(f"negative mutation failed: free_by_restriction did not lift the 811.4 restriction: {freed.get('reason_code')} {freed.get('reason')}")
    at_battlefield = copy.deepcopy(targeting)
    at_battlefield["players"]["p2"]["zones"]["base"].remove("u2")
    at_battlefield["battlefields"]["bf1"]["objects"].append("u2")
    if not play_card(timing, at_battlefield, declaration(source={"kind": "facedown", "battlefield": "bf1"}, cost_override={"kind": "ignore_base_cost", "source": "hidden"},
                                                          payment_context=None, effect_program_id="spell-1-effects"), effect_program=target_program).get("committed"):
        errors.append("a hidden play choosing at its own Battlefield was refused")

    # --- scope, manifest, determinism -------------------------------------------------------------------------
    scope = KIND_CONFIG.get("hide_step")
    if not scope or "facedown_zone" not in scope["supported"] or "hidden_removal_on_control_change" not in scope["unsupported"]:
        errors.append("the hide_step scope is missing or does not declare its boundary")
    if "play_from_hidden" not in KIND_CONFIG["play"]["supported"]:
        errors.append("the play scope does not declare play_from_hidden")
    if "hidden.py" not in ENGINE_SOURCES:
        errors.append("hidden.py is not part of the engine identity the manifest hashes")
    schema = json.loads((SKILL_DIR / "schemas" / "effect-state.schema.json").read_text(encoding="utf-8"))
    if "facedown" not in schema["$defs"]["battlefield"]["properties"]:
        errors.append("the effect-state schema lacks the Facedown Zone")
    snapshot = copy.deepcopy(state)
    if hide_card(timing, state, hide_declaration()) != hidden_result or state != snapshot:
        errors.append("hide_card is not deterministic or mutated its input")

    if errors:
        print("FAILED: hidden / facedown zone checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("hidden / facedown zone checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
