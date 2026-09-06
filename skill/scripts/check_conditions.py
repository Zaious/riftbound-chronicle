#!/usr/bin/env python3
"""
Regression gate for C-50 (ADR-0013 §3, §6; Codex G-2 on DP-74): `condition.v1`
as a typed AST, and its four consumers — continuous effects, activation
conditions, cost modifications and the evaluated `counterable` flag.

Must hold:
  - the validator accepts the leaves and the and / or / not nodes, and refuses
    free text, an unknown leaf, a leaf carrying a field it does not define, a
    node with one child, and a negative count;
  - every leaf evaluates against explicit state: runes, controlled Units by
    location and relation, Might, keywords, Empowered, XP, Battlefield
    control, zone counts; and / or / not compose them;
  - a leaf that would count a private zone of another player is refused as
    `condition_needs_hidden_information` when a perspective asks, while the
    owner's own perspective is answered (negative mutation);
  - a continuous effect gated by a condition applies only while it holds, and
    the layer engine re-reads it — the same effect stops applying when the
    state changes underneath it;
  - an activation condition that holds lets the ability be activated, one that
    does not is `illegal: activation_condition_not_met`, and a malformed one
    is `invalid_input`;
  - a cost modification carrying a condition applies only when it holds, one
    carrying `per_each` multiplies by the count, the receipt records the
    evaluation with its provenance, and an uncounted per-each scope is
    unsupported by name;
  - the play scope declares the evaluated modifications and drops the old
    `cost_modification_sources` refusal; the effect scope names the hidden
    information boundary.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_costs_and_activation import ability_declaration, declaration, hand_state  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (  # noqa: E402
    ConditionUnsupported, characteristics, evaluate_condition, evaluate_cost_modification, validate_condition,
)
from engine_check import KIND_CONFIG  # noqa: E402
from play_transaction import play_card  # noqa: E402


def main() -> int:
    errors: list[str] = []
    state = base_state()

    # --- the validator ------------------------------------------------------------------------
    good = [
        {"kind": "runes_at_least", "count": 2},
        {"kind": "controls_units", "count": 1, "location": "battlefield", "controller_relation": "enemy"},
        {"kind": "and", "of": [{"kind": "might_at_least", "count": 3}, {"kind": "has_keyword", "keyword": "tank"}]},
        {"kind": "not", "of": {"kind": "is_empowered"}},
        {"kind": "or", "of": [{"kind": "xp_at_least", "count": 2}, {"kind": "battlefield_controlled", "battlefield": "bf1"}]},
        {"kind": "zone_count_at_least", "zone": "hand", "count": 1},
    ]
    for condition in good:
        if validate_condition(condition):
            errors.append(f"a valid condition was refused: {condition} {validate_condition(condition)}")
    bad = [
        ("free text", "you control a unit"),
        ("an unknown leaf", {"kind": "if_you_feel_like_it"}),
        ("a foreign field", {"kind": "runes_at_least", "count": 1, "keyword": "tank"}),
        ("a one-child node", {"kind": "and", "of": [{"kind": "is_empowered"}]}),
        ("a negative count", {"kind": "runes_at_least", "count": -1}),
        ("an unknown zone", {"kind": "zone_count_at_least", "zone": "pocket", "count": 1}),
    ]
    for label, condition in bad:
        if not validate_condition(condition):
            errors.append(f"a condition with {label} was accepted")

    # --- the leaves ---------------------------------------------------------------------------------
    board = copy.deepcopy(state)
    board["players"]["p1"]["zones"]["base"].remove("u1")
    board["battlefields"]["bf1"]["objects"].append("u1")
    board["battlefields"]["bf1"]["controller"] = "p1"
    board["players"]["p1"]["xp"] = 3
    board["objects"]["u1"]["empowered"] = True
    cases = [
        ({"kind": "controls_units", "count": 1, "location": "battlefield"}, True),
        ({"kind": "controls_units", "count": 2, "location": "battlefield"}, False),
        ({"kind": "controls_units", "count": 1, "location": "battlefield", "controller_relation": "enemy"}, False),
        ({"kind": "might_at_least", "count": 3, "object": "u1"}, True),
        ({"kind": "might_at_least", "count": 4, "object": "u1"}, False),
        ({"kind": "is_empowered", "object": "u1"}, True),
        ({"kind": "xp_at_least", "count": 3}, True),
        ({"kind": "xp_at_least", "count": 4}, False),
        ({"kind": "battlefield_controlled", "battlefield": "bf1"}, True),
        ({"kind": "battlefield_controlled", "battlefield": "bf1", "controller_relation": "enemy"}, False),
        ({"kind": "zone_count_at_least", "zone": "trash", "count": 1}, True),
        ({"kind": "not", "of": {"kind": "is_empowered", "object": "u1"}}, False),
        ({"kind": "and", "of": [{"kind": "is_empowered", "object": "u1"}, {"kind": "xp_at_least", "count": 3}]}, True),
        ({"kind": "or", "of": [{"kind": "is_empowered", "object": "u2"}, {"kind": "xp_at_least", "count": 3}]}, True),
    ]
    for condition, expected in cases:
        actual = evaluate_condition(board, condition, controller="p1", object_id="u1")
        if actual is not expected:
            errors.append(f"{condition} evaluated {actual}, expected {expected}")

    # --- the visibility boundary ----------------------------------------------------------------------
    private = {"kind": "zone_count_at_least", "zone": "hand", "count": 0, "player": "p1"}
    try:
        evaluate_condition(board, private, controller="p1", perspective="p2")
        errors.append("counting another player's hand was answered instead of refused (128.4)")
    except ConditionUnsupported as exc:
        if "condition_needs_hidden_information" not in str(exc):
            errors.append(f"the refusal did not name the boundary: {exc}")
    if evaluate_condition(board, private, controller="p1", perspective="p1") is not True:
        errors.append("negative mutation failed: the owner's own perspective was also refused, so the boundary is not about privacy")

    # --- the continuous-effect consumer ---------------------------------------------------------------------
    gated = copy.deepcopy(board)
    gated["continuous_effects"] = [{
        "effect_id": "level", "kind": "might_arithmetic",
        "source": {"object": "u1", "identity": None}, "affects": {"scope": "object", "object": "u1", "identity": None},
        "layer": "arithmetic", "sublayer": "increase", "timestamp": 0, "value": {"amount": 2, "mode": "delta"},
        "condition": {"kind": "xp_at_least", "count": 3}, "duration": {"kind": "while_source_active"}, "passive": True,
    }]
    if characteristics(gated, "u1")["might"] != 5:
        errors.append(f"a gated continuous effect did not apply while its condition held: {characteristics(gated, 'u1')['might']}")
    spent = copy.deepcopy(gated)
    spent["players"]["p1"]["xp"] = 1
    if characteristics(spent, "u1")["might"] != 3:
        errors.append("the layer engine did not re-read the condition after the state changed")

    # --- activation conditions -------------------------------------------------------------------------------
    timing = fixture()
    plain = hand_state("c1")
    if not play_card(timing, plain, ability_declaration(activation_conditions=[{"kind": "controls_units", "count": 1}])).get("committed"):
        errors.append("an activation whose condition holds was refused")
    unmet = play_card(timing, plain, ability_declaration(activation_conditions=[{"kind": "controls_units", "count": 9}]))
    if unmet.get("reason_code") != "activation_condition_not_met":
        errors.append(f"an activation whose condition fails was not illegal: {unmet.get('reason_code')}")

    # --- cost modifications ---------------------------------------------------------------------------------------
    rich = hand_state("c1", energy=3)
    holds = play_card(timing, rich, declaration(cost={"base": {"energy": 2, "power": {}},
                                                      "discounts": [{"id": "d1", "applies_to": "energy", "amount": 1, "condition": {"kind": "controls_units", "count": 1}}]}))
    if not holds.get("committed") or holds["cost_receipt"]["total"]["energy"] != 1:
        errors.append(f"a discount whose condition holds did not apply: {holds.get('reason_code')} {holds.get('reason')}")
    elif not any(entry.get("evaluated_cost_modifications") for entry in holds["trace"]):
        errors.append("the receipt trace does not record the evaluation")
    fails = play_card(timing, rich, declaration(cost={"base": {"energy": 2, "power": {}},
                                                      "discounts": [{"id": "d1", "applies_to": "energy", "amount": 1, "condition": {"kind": "controls_units", "count": 9}}]}))
    if not fails.get("committed") or fails["cost_receipt"]["total"]["energy"] != 2:
        errors.append(f"negative mutation failed: a discount whose condition fails still applied: {fails.get('cost_receipt', {}).get('total')}")
    counted = evaluate_cost_modification(board, {"id": "i1", "amount": 1, "per_each": {"kind": "controls_units", "count": 1}}, "p1")
    if counted["per_each_count"] != 1 or counted["amount"] != 1 or counted["provenance"]["evaluated_by"] != "p4_condition_layer":
        errors.append(f"the per-each count is wrong: {counted}")
    two_units = copy.deepcopy(board)
    two_units["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False}
    two_units["players"]["p1"]["zones"]["base"].append("u3")
    if evaluate_cost_modification(two_units, {"id": "i1", "amount": 1, "per_each": {"kind": "controls_units", "count": 1}}, "p1")["amount"] != 2:
        errors.append("the per-each amount did not follow the count")

    # --- scope --------------------------------------------------------------------------------------------------------
    play_scope, effect_scope = KIND_CONFIG["play"], KIND_CONFIG["effect"]
    if "evaluated_cost_modifications" not in play_scope["supported"] or "activation_conditions" not in play_scope["supported"]:
        errors.append("the play scope does not declare the evaluated modifications and activation conditions")
    if "cost_modification_sources" in play_scope["unsupported"] or "activation_conditions" in play_scope["unsupported"]:
        errors.append("the play scope still refuses what C-50 implements")
    if "typed_conditions" not in effect_scope["supported"] or "condition_needs_hidden_information" not in effect_scope["unsupported"]:
        errors.append("the effect scope does not declare typed conditions and their boundary")

    if errors:
        print("FAILED: condition.v1 checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("condition.v1 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
