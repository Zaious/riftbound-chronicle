#!/usr/bin/env python3
"""
Atomic play/cost transaction (ADR-0005 §4, Core 354–358).

Playing a card is one transaction: choices (355), total-cost determination
(356), payment (357), legality and chain insertion (358). Either every step
commits and both next states are returned, or nothing does and the input
hashes are the next hashes — Core 358.5 restores the pre-play state, and this
module never returns a half-paid state.

Costs are typed `cost_payment` records with a receipt, not effects with a
`cost: true` flag. The receipt records, per component: the intent for an
optional cost (355.1.a), the requested and final amounts with every increase
and reduction that touched them (356.1–356.6), the payment events (357.1,
357.2), and whether the rules consider the cost paid — for an optional cost
that is the decision to pay it, whatever was actually paid (356.4.f.1); a
payment replaced by a replacement effect still counts (357.2.a).

Failure vocabulary (ADR-0005 §10):
  invalid_input    malformed declaration, state, or decision envelope
  decision_required an optional cost whose intent the controller has not declared
  unsupported      a cost mechanic the engine does not type (e.g. discard)
  illegal          an unpayable supported cost, a card not in hand, a target
                   illegal at play, or a timing rule that refuses the play

What this deliberately does not model: reaction "Add" abilities used during
payment (357.1.a) — the pool is what the state says; the *sources* of cost
modifications (the declaration states them, the engine applies them); and
non-standard costs beyond exhaust and kill.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from effect_ir import (  # noqa: E402
    CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, _bump_identity, apply_program, evaluate_target,
    find_location, hash_value, object_identity, validate_program, validate_state,
)
from rules_core import add_pending_item, state_hash  # noqa: E402

DECLARATION_VERSION = "riftbound-play-declaration.v1"
RESULT_VERSION = "riftbound-play-result.v1"
RECEIPT_VERSION = "riftbound-cost-receipt.v1"

# Non-standard costs the engine can pay by reusing a primitive operation
# (356.7, 357.2). Anything else is `unsupported` by name.
SUPPORTED_NON_STANDARD = {"exhaust": "exhaust", "kill": "kill"}
PAID_OUTCOMES = {"applied", "replaced_prevented", "replaced_modified_applied", "replaced_modified_prevented", "augmented_applied", "augmented_original_replaced"}

RULES = {
    "choices": ["Core 355.1", "Core 355.1.a", "Core 355.5", "Core 355.9"],
    "cost": ["Core 356.1", "Core 356.2", "Core 356.3", "Core 356.4", "Core 356.5", "Core 356.6", "Core 356.7"],
    "payment": ["Core 357.1", "Core 357.2", "Core 357.2.a"],
    "legality": ["Core 358", "Core 358.4", "Core 358.5"],
    "identity": ["Core 124"],
}


class PlayError(ValueError):
    def __init__(self, stage: str, reason_code: str, message: str, **extra: Any):
        super().__init__(message)
        self.stage, self.reason_code, self.extra = stage, reason_code, extra


# ----------------------------------------------------------------- validation --

def _is_resource_cost(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"energy", "power"} and isinstance(value["energy"], int) and value["energy"] >= 0
            and isinstance(value["power"], dict) and all(isinstance(k, str) and k and isinstance(v, int) and v >= 0 for k, v in value["power"].items()))


def validate_declaration(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["declaration must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != DECLARATION_VERSION:
        errors.append(f"schema_version must be {DECLARATION_VERSION}")
    if value.get("ruleset") != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("ruleset must match the engine ruleset")
    if set(value) - {"schema_version", "ruleset", "play_id", "actor", "card", "effect_program_id", "chain_item", "cost"}:
        errors.append("declaration contains unsupported fields")
    for key in ("play_id", "actor", "card"):
        if not isinstance(value.get(key), str) or not value.get(key):
            errors.append(f"{key} must be a non-empty string")
    item = value.get("chain_item")
    if not isinstance(item, dict) or set(item) - {"id", "object_kind", "timing", "ability_kind"} or not {"id", "object_kind", "timing"} <= set(item):
        errors.append("chain_item must carry id, object_kind, timing")
    else:
        if item.get("object_kind") not in {"spell", "unit", "gear"}:
            errors.append("chain_item.object_kind is invalid")
        if item.get("timing") not in {"default", "action", "reaction"}:
            errors.append("chain_item.timing is invalid")
        if item.get("ability_kind", None) not in {"standard", "add", None}:
            errors.append("chain_item.ability_kind is invalid")
    cost = value.get("cost")
    if not isinstance(cost, dict) or "base" not in cost or set(cost) - {"base", "base_modifications", "additional", "increases", "discounts", "total_modifications"}:
        return errors + ["cost must carry base and only the typed modification lists"]
    if not _is_resource_cost(cost["base"]):
        errors.append("cost.base must be {energy, power{domain: n}} with non-negative integers")
    for i, mod in enumerate(cost.get("base_modifications", []) or []):
        if not isinstance(mod, dict) or mod.get("kind") not in {"for_cost", "ignore_energy", "ignore_power", "ignore_all"} or set(mod) - {"kind", "cost", "source"}:
            errors.append(f"cost.base_modifications[{i}] is invalid")
        elif mod["kind"] == "for_cost" and not _is_resource_cost(mod.get("cost")):
            errors.append(f"cost.base_modifications[{i}].cost is required for for_cost")
    seen: set[str] = set()
    for i, add in enumerate(cost.get("additional", []) or []):
        if not isinstance(add, dict) or not {"cost_id", "mandatory", "payment"} <= set(add) or set(add) - {"cost_id", "mandatory", "payment", "source"}:
            errors.append(f"cost.additional[{i}] is invalid")
            continue
        if not isinstance(add["cost_id"], str) or not add["cost_id"] or add["cost_id"] in seen or add["cost_id"].startswith("base:"):
            errors.append(f"cost.additional[{i}].cost_id is invalid or duplicated")
        seen.add(add.get("cost_id", ""))
        if not isinstance(add["mandatory"], bool):
            errors.append(f"cost.additional[{i}].mandatory must be boolean")
        pay = add["payment"]
        if not isinstance(pay, dict) or not isinstance(pay.get("kind"), str) or not pay.get("kind"):
            errors.append(f"cost.additional[{i}].payment.kind is required")
            continue
        if pay["kind"] == "energy" and (not isinstance(pay.get("amount"), int) or pay["amount"] < 0):
            errors.append(f"cost.additional[{i}].payment.amount is required for energy")
        if pay["kind"] == "power" and (not isinstance(pay.get("amount"), int) or pay["amount"] < 0 or not isinstance(pay.get("domain"), str) or not pay.get("domain")):
            errors.append(f"cost.additional[{i}].payment needs domain and amount for power")
        if pay["kind"] in SUPPORTED_NON_STANDARD and (not isinstance(pay.get("object_id"), str) or not pay.get("object_id")):
            errors.append(f"cost.additional[{i}].payment.object_id is required for {pay['kind']}")
    for i, inc in enumerate(cost.get("increases", []) or []):
        if not isinstance(inc, dict) or not {"id", "component", "amount"} <= set(inc) or set(inc) - {"id", "component", "amount", "source"} or not isinstance(inc["amount"], int) or inc["amount"] < 1 or not (inc["component"] == "energy" or str(inc["component"]).startswith("power:")):
            errors.append(f"cost.increases[{i}] is invalid")
    for i, disc in enumerate(cost.get("discounts", []) or []):
        if not isinstance(disc, dict) or not {"id", "applies_to", "amount"} <= set(disc) or set(disc) - {"id", "applies_to", "amount", "minimum", "source"} or not isinstance(disc["amount"], int) or disc["amount"] < 1:
            errors.append(f"cost.discounts[{i}] is invalid")
            continue
        target = disc["applies_to"]
        if not (target in {"energy", "total", "optional_additional"} or str(target).startswith("power:")):
            errors.append(f"cost.discounts[{i}].applies_to is invalid")
        if "minimum" in disc and (not isinstance(disc["minimum"], int) or disc["minimum"] < 0):
            errors.append(f"cost.discounts[{i}].minimum must be a non-negative integer")
    for i, mod in enumerate(cost.get("total_modifications", []) or []):
        if not isinstance(mod, dict) or mod.get("kind") != "ignore_any_and_all" or set(mod) - {"kind", "source"}:
            errors.append(f"cost.total_modifications[{i}] is invalid")
    return errors


# ------------------------------------------------------------- cost arithmetic --

def _apply_discount(amount: int, discount: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    floor = discount.get("minimum", 0)
    reduced = max(min(amount, floor), amount - discount["amount"]) if amount > floor else amount
    reduced = max(reduced, 0)
    return reduced, {"discount_id": discount["id"], "applies_to": discount["applies_to"], "amount": amount - reduced, "minimum": discount.get("minimum"), "rule_locators": ["Core 356.4.e"] if "minimum" in discount else ["Core 356.4"]}


def determine_total_cost(cost: dict[str, Any], intents: dict[str, bool]) -> dict[str, Any]:
    """Core 356 in order: base modifications, additional costs, increases,
    discounts (component before total, each minimum its own), total
    modifications, floor at zero. Returns the receipt skeleton before payment."""
    base = copy.deepcopy(cost["base"])
    current = copy.deepcopy(base)
    base_mods = []
    for mod in cost.get("base_modifications", []) or []:
        if mod["kind"] == "for_cost":
            current = copy.deepcopy(mod["cost"])
        elif mod["kind"] == "ignore_energy":
            current["energy"] = 0
        elif mod["kind"] == "ignore_power":
            current["power"] = {}
        elif mod["kind"] == "ignore_all":
            current = {"energy": 0, "power": {}}
        base_mods.append({"kind": mod["kind"], "source": mod.get("source"), "rule_locators": ["Core 356.1.a" if mod["kind"] == "for_cost" else "Core 356.1.b"]})
    after_base = copy.deepcopy(current)

    components: list[dict[str, Any]] = [{
        "cost_id": "base:energy", "kind": "energy", "mandatory": True, "intent": None,
        "requested": current["energy"], "increases": [], "reductions": [], "final": current["energy"], "payment_events": [], "paid": False,
        "rule_locators": ["Core 356.1", "Core 357.1"],
    }]
    for domain, amount in sorted(current["power"].items()):
        components.append({
            "cost_id": f"base:power:{domain}", "kind": "power", "mandatory": True, "intent": None,
            "requested": amount, "increases": [], "reductions": [], "final": amount, "payment_events": [], "paid": False,
            "rule_locators": ["Core 356.1", "Core 357.1"],
        })
    # 356.2 additional costs: mandatory always; optional only when the intent
    # decision said so (356.2.b.1). An optional cost declined is still a
    # component on the receipt — `paid: false` is what "Otherwise" tests.
    for add in cost.get("additional", []) or []:
        pay = add["payment"]
        intent = None if add["mandatory"] else bool(intents.get(add["cost_id"], False))
        requested = pay.get("amount") if pay["kind"] in {"energy", "power"} else {k: v for k, v in pay.items() if k != "kind"}
        components.append({
            "cost_id": add["cost_id"], "kind": pay["kind"], "mandatory": add["mandatory"], "intent": intent,
            "requested": requested, "increases": [], "reductions": [], "final": requested, "payment_events": [], "paid": False,
            "domain": pay.get("domain"), "object_id": pay.get("object_id"),
            "rule_locators": ["Core 356.2.a"] if add["mandatory"] else ["Core 356.2.b", "Core 356.4.f.1"],
        })
    by_id = {c["cost_id"]: c for c in components}

    # 356.3 increases (component-addressed).
    for inc in cost.get("increases", []) or []:
        target = "base:energy" if inc["component"] == "energy" else f"base:{inc['component']}"
        comp = by_id.get(target)
        if comp is None and inc["component"].startswith("power:"):
            comp = {"cost_id": target, "kind": "power", "mandatory": True, "intent": None, "requested": 0, "increases": [], "reductions": [], "final": 0, "payment_events": [], "paid": False, "rule_locators": ["Core 356.3", "Core 357.1"]}
            components.append(comp); by_id[target] = comp
        if comp is not None:
            comp["final"] += inc["amount"]
            comp["increases"].append({"increase_id": inc["id"], "amount": inc["amount"], "source": inc.get("source"), "rule_locators": ["Core 356.3"]})

    # 356.4 discounts: component discounts first, in declared order (356.4.c),
    # then total discounts (356.4.d). "optional_additional" discounts apply to
    # every optional additional energy/power cost the player chose to pay.
    discounts = cost.get("discounts", []) or []
    for disc in [d for d in discounts if d["applies_to"] != "total"]:
        if disc["applies_to"] == "optional_additional":
            targets = [c for c in components if not c["mandatory"] and c["intent"] and c["kind"] in {"energy", "power"}]
        elif disc["applies_to"] == "energy":
            targets = [by_id["base:energy"]]
        else:
            targets = [c for c in components if c["cost_id"] == f"base:{disc['applies_to']}"]
        for comp in targets:
            comp["final"], record = _apply_discount(comp["final"], disc)
            comp["reductions"].append(record)
    for disc in [d for d in discounts if d["applies_to"] == "total"]:
        comp = by_id["base:energy"]
        comp["final"], record = _apply_discount(comp["final"], disc)
        record["rule_locators"] = ["Core 356.4.d"] + record["rule_locators"]
        comp["reductions"].append(record)

    # 356.5 total modifications.
    for mod in cost.get("total_modifications", []) or []:
        for comp in components:
            if comp["kind"] in {"energy", "power"} and (comp["mandatory"] or comp["intent"]):
                if comp["final"]:
                    comp["reductions"].append({"discount_id": None, "applies_to": "any_and_all", "amount": comp["final"], "minimum": None, "rule_locators": ["Core 356.5.a"]})
                comp["final"] = 0
    # 356.6 floor.
    for comp in components:
        if comp["kind"] in {"energy", "power"} and isinstance(comp["final"], int) and comp["final"] < 0:
            comp["final"] = 0

    total = {"energy": 0, "power": {}}
    for comp in components:
        if comp["mandatory"] is False and not comp["intent"]:
            continue
        if comp["kind"] == "energy":
            total["energy"] += comp["final"]
        elif comp["kind"] == "power":
            domain = comp["cost_id"].split("power:", 1)[1] if comp["cost_id"].startswith("base:power:") else comp.get("domain")
            total["power"][domain] = total["power"].get(domain, 0) + comp["final"]
    return {"base": base, "base_modifications": base_mods, "after_base_modifications": after_base, "components": components, "total": total}


# -------------------------------------------------------------------- payment --

def _pay(effect_state: dict[str, Any], declaration: dict[str, Any], skeleton: dict[str, Any], decisions: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Core 357: pay energy and power in total (357.1), then non-standard
    costs in declared order (357.2). Mutates the working copy; the caller
    discards it on any failure (358.5)."""
    actor = declaration["actor"]
    working = effect_state
    events: list[dict[str, Any]] = []
    resources = working["players"][actor]["resources"]
    total = skeleton["total"]
    if resources["energy"] < total["energy"]:
        raise PlayError("payment", "cost_unpayable", f"{actor} has {resources['energy']} energy; the total cost is {total['energy']}", rule_locators=["Core 357.1"])
    for domain, amount in total["power"].items():
        if resources["power"].get(domain, 0) < amount:
            raise PlayError("payment", "cost_unpayable", f"{actor} has {resources['power'].get(domain, 0)} {domain} power; the total cost is {amount}", rule_locators=["Core 357.1"])
    if total["energy"]:
        before = resources["energy"]; resources["energy"] -= total["energy"]
        events.append({"kind": "pay_energy", "amount": total["energy"], "before": before, "after": resources["energy"], "rule_locators": ["Core 357.1"]})
    for domain, amount in sorted(total["power"].items()):
        if amount:
            before = resources["power"][domain]; resources["power"][domain] -= amount
            events.append({"kind": "pay_power", "domain": domain, "amount": amount, "before": before, "after": resources["power"][domain], "rule_locators": ["Core 357.1"]})
    for comp in skeleton["components"]:
        if comp["kind"] in {"energy", "power"}:
            if comp["mandatory"] or comp["intent"]:
                comp["paid"] = True
                comp["payment_events"] = [e for e in events if (e["kind"] == "pay_energy") == (comp["kind"] == "energy")]
            continue
        if not comp["mandatory"] and not comp["intent"]:
            continue  # declined: nothing to pay, receipt says not paid (356.2.b.1)
        op = SUPPORTED_NON_STANDARD[comp["kind"]]
        selector = {"object_id": comp["object_id"], "chosen_zone_class": "board", "controller_relation": "friendly", "bound_identity": object_identity(working, comp["object_id"]) or f"{comp['object_id']}@0"}
        program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "program_id": f"cost:{declaration['play_id']}:{comp['cost_id']}", "controller": actor,
                   "effects": [{"op": op, "effect_id": comp["cost_id"], "object_id": comp["object_id"], "target": selector}]}
        # The envelope is keyed to the pre-play hash; by now the pool has been
        # debited, so it cannot be handed to the sub-program. A replacement
        # that needs a choice during payment surfaces as decision_required.
        result = apply_program(working, program)
        if result.get("replacement_decision_required"):
            raise PlayError("payment", "replacement_decision_required", str(result.get("reason")), replacement_ids=result.get("replacement_ids", []), decision_controller=result.get("decision_controller"))
        if result.get("committed") is not True:
            raise PlayError("payment", "cost_unpayable", f"cost {comp['cost_id']!r} ({comp['kind']}) cannot be paid: {result.get('reason') or '; '.join(result.get('errors', []))}", rule_locators=["Core 357.2"])
        outcome = result["trace"][0].get("outcome")
        if outcome not in PAID_OUTCOMES:
            raise PlayError("payment", "cost_unpayable", f"cost {comp['cost_id']!r} ({comp['kind']}) did not happen: {outcome}", rule_locators=["Core 357.2"])
        working.clear(); working.update(result["next_state"])
        resources = working["players"][actor]["resources"]
        comp["paid"] = True
        comp["payment_events"] = copy.deepcopy(result["trace"])
        if outcome != "applied":
            comp["rule_locators"] = list(dict.fromkeys(comp["rule_locators"] + ["Core 357.2.a"]))
        events.append({"kind": f"pay_{comp['kind']}", "cost_id": comp["cost_id"], "object_id": comp["object_id"], "outcome": outcome, "rule_locators": ["Core 357.2"] + (["Core 357.2.a"] if outcome != "applied" else [])})
    return working, events


# ---------------------------------------------------------------- transaction --

def play_card(timing_state: dict[str, Any], effect_state: dict[str, Any], declaration: dict[str, Any], *,
              engine_decisions: dict[str, Any] | None = None, effect_program: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {
        "schema_version": RESULT_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": declaration.get("play_id") if isinstance(declaration, dict) else None,
        "input_timing_state_hash": state_hash(timing_state) if isinstance(timing_state, dict) else hash_value(timing_state),
        "input_effect_state_hash": hash_value(effect_state),
    }
    errors = validate_declaration(declaration)
    errors += [f"effect state: {e}" for e in validate_state(effect_state)]
    errors += [f"engine_decisions: {e}" for e in ed.validate_engine_decisions(engine_decisions)]
    if engine_decisions is not None and not errors and engine_decisions.get("input_hash") != hash_value(effect_state):
        errors.append("engine_decisions.input_hash does not match the effect state")
    if effect_program is not None:
        errors += [f"effect program: {e}" for e in validate_program(effect_program)]
    if errors:
        return {**base, "valid": False, "committed": False, "unsupported": False, "rolled_back": False, "stage": "declaration", "reason_code": "invalid_input", "reason": "; ".join(errors), "errors": errors, "trace": [], "rule_locators": []}

    trace: list[dict[str, Any]] = []
    locators: list[str] = []
    try:
        actor, card = declaration["actor"], declaration["card"]
        if actor not in effect_state["players"]:
            raise PlayError("declaration", "unknown_actor", f"{actor!r} is not a player in the effect state")
        location = find_location(effect_state, card)
        if location != ("player", actor, "hand"):
            raise PlayError("choices", "card_not_in_hand", f"{card!r} is not in {actor}'s hand", rule_locators=["Core 354"])
        if effect_state["objects"][card]["kind"] != declaration["chain_item"]["object_kind"]:
            raise PlayError("choices", "object_kind_mismatch", f"{card!r} is a {effect_state['objects'][card]['kind']}, the chain item says {declaration['chain_item']['object_kind']}")

        # --- 355: choices. Optional-cost intent is a decision the controller
        # owns; the engine never assumes it. Targets named by a supplied
        # program are checked for legality now (355.9), not only at resolution.
        intents: dict[str, bool] = {}
        missing: list[str] = []
        for add in declaration["cost"].get("additional", []) or []:
            if add["mandatory"]:
                continue
            entry = next((e for e in ed.entries(engine_decisions, kind="optional_choice", stage="play_declaration") if e["decision_id"] == add["cost_id"]), None)
            if entry is None:
                missing.append(add["cost_id"])
                continue
            if entry["controller"] != actor:
                raise PlayError("choices", "decision_controller_mismatch", f"optional cost {add['cost_id']!r} was chosen by {entry['controller']!r}, not the card's controller", rule_locators=["Core 355.1.a"])
            intents[add["cost_id"]] = bool(entry["value"])
        if missing:
            raise PlayError("choices", "optional_cost_intent_required", f"optional cost intent not declared for {missing}", decision_ids=missing, decision_controller=actor, rule_locators=["Core 355.1.a", "Core 356.2.b.1"])
        if effect_program is not None:
            for index, effect in enumerate(effect_program.get("effects", [])):
                refs = []
                if isinstance(effect.get("target"), dict) and "decision_ref" in effect["target"]:
                    refs.append((effect["target"]["decision_ref"], effect["target"]))
                if isinstance(effect.get("targets"), dict) and "decision_ref" in effect["targets"]:
                    refs.append((effect["targets"]["decision_ref"], effect["targets"].get("restrictions", {})))
                for ref, template in refs:
                    entry = ed.target_selection(engine_decisions, ref)
                    if entry is None:
                        raise PlayError("choices", "target_selection_required", f"target selection {ref!r} is made at play (355.5) and was not supplied", decision_ids=[ref], decision_controller=actor, rule_locators=["Core 355.5"])
                    for object_id in entry["value"]:
                        selector = {k: v for k, v in template.items() if k not in {"decision_ref", "object_id"}}
                        selector.update({"object_id": object_id, "chosen_zone_class": template.get("chosen_zone_class") or ("board" if find_location(effect_state, object_id) and (find_location(effect_state, object_id)[0] == "battlefield" or find_location(effect_state, object_id)[2] == "base") else "non_board")})
                        ok, reason = evaluate_target(effect_state, selector, actor)
                        if not ok:
                            raise PlayError("choices", "target_illegal_at_play", f"effects[{index}] target {object_id!r}: {reason}", rule_locators=["Core 355.9"])
        trace.append({"stage": "choices", "outcome": "applied", "optional_cost_intents": intents, "rule_locators": RULES["choices"]})
        locators += RULES["choices"]

        # --- 356: total cost.
        for add in declaration["cost"].get("additional", []) or []:
            kind = add["payment"]["kind"]
            if kind not in {"energy", "power"} and kind not in SUPPORTED_NON_STANDARD and (add["mandatory"] or intents.get(add["cost_id"])):
                raise PlayError("cost_determination", "unsupported_cost_kind", f"cost {add['cost_id']!r} uses {kind!r}, which the engine does not type", unsupported=True, rule_locators=["Core 356.7"])
        skeleton = determine_total_cost(declaration["cost"], intents)
        trace.append({"stage": "cost_determination", "outcome": "applied", "total": copy.deepcopy(skeleton["total"]), "rule_locators": RULES["cost"]})
        locators += RULES["cost"]

        # --- 357: payment, on a working copy.
        working = copy.deepcopy(effect_state)
        before_pay = hash_value(working)
        working, pay_events = _pay(working, declaration, skeleton, engine_decisions)
        trace.append({"stage": "payment", "outcome": "applied", "events": pay_events, "before_state_hash": before_pay, "after_state_hash": hash_value(working), "rule_locators": RULES["payment"]})
        locators += RULES["payment"]

        # The card leaves the hand for the chain: a non-board → non-board zone
        # change, so it is a new object (Core 124).
        working["players"][actor]["zones"]["hand"].remove(card)
        working["players"][actor]["zones"].setdefault("chain", []).append(card)
        identity_after = _bump_identity(working, card)
        state_errors = validate_state(working)
        if state_errors:
            raise PlayError("payment", "invalid_working_state", "; ".join(state_errors))

        # --- 358: legality and chain insertion through the timing kernel.
        item = {**declaration["chain_item"], "ability_kind": declaration["chain_item"].get("ability_kind")}
        proposal = {"actor": actor, "kind": "play_card", "item": item, "initiated_by": "played_card"}
        insertion = add_pending_item(timing_state, proposal)
        if insertion.get("valid") is False:
            raise PlayError("legality", "invalid_timing_state", "; ".join(insertion.get("errors", [])), invalid=True)
        if insertion.get("applied") is not True:
            raise PlayError("legality", insertion.get("reason_code") or "play_illegal", f"the timing kernel refused the play: {insertion.get('reason_code')}", legality=insertion.get("legality"), rule_locators=RULES["legality"])
        trace.append({"stage": "legality", "outcome": "applied", "chain_item_id": item["id"], "card_identity_after": identity_after, "rule_locators": RULES["legality"] + RULES["identity"]})
        locators += RULES["legality"] + RULES["identity"]
    except PlayError as exc:
        extra = dict(exc.extra)
        rule_locators = extra.pop("rule_locators", [])
        result = {
            **base, "valid": not extra.pop("invalid", False), "committed": False, "unsupported": bool(extra.pop("unsupported", False)),
            "rolled_back": True, "stage": exc.stage, "reason_code": exc.reason_code, "reason": str(exc),
            "trace": trace + [{"stage": exc.stage, "outcome": "rolled_back", "reason_code": exc.reason_code, "rule_locators": ["Core 358.5"]}],
            "rule_locators": list(dict.fromkeys(locators + rule_locators + ["Core 358.5"])),
            "next_timing_state_hash": base["input_timing_state_hash"], "next_effect_state_hash": base["input_effect_state_hash"],
        }
        if exc.reason_code in {"optional_cost_intent_required", "target_selection_required"}:
            result["optional_cost_decision_required"] = exc.reason_code == "optional_cost_intent_required"
        if exc.reason_code == "replacement_decision_required":
            result["replacement_decision_required"] = True
        if result["valid"] is False:
            result["errors"] = [str(exc)]
        result.update(extra)
        return result

    receipt = {
        "schema_version": RECEIPT_VERSION, "play_id": declaration["play_id"], "actor": actor, "card": card,
        "base": skeleton["base"], "after_base_modifications": skeleton["after_base_modifications"],
        "components": skeleton["components"], "total": skeleton["total"],
        "paid": all(c["paid"] for c in skeleton["components"] if c["mandatory"] or c["intent"]),
        "rule_locators": list(dict.fromkeys(RULES["cost"] + RULES["payment"] + ["Core 356.4.f.1"])),
    }
    next_timing = insertion["next_state"]
    return {
        **base, "valid": True, "committed": True, "unsupported": False, "rolled_back": False, "stage": "commit", "reason_code": "ok",
        "chain_item_id": item["id"], "cost_receipt": receipt,
        "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
        "next_effect_state": working, "next_effect_state_hash": hash_value(working),
        "trace": trace + [{"stage": "commit", "outcome": "applied", "rule_locators": ["Core 358.4"]}],
        "rule_locators": list(dict.fromkeys(locators)),
    }


# ------------------------------------------------------------------------ CLI --

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atomic play/cost transaction (ADR-0005 §4).")
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("effect_state", type=Path)
    parser.add_argument("declaration", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--program", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = play_card(_load(args.timing_state), _load(args.effect_state), _load(args.declaration),
                           engine_decisions=_load(args.decisions) if args.decisions else None,
                           effect_program=_load(args.program) if args.program else None)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
