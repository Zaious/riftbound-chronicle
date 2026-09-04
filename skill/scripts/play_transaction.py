#!/usr/bin/env python3
"""
Atomic play/cost transaction (ADR-0005 §4, Core 354–358).

Playing a card is one transaction: choices (355), total-cost determination
(356), payment (357), legality and chain insertion (358). Either every step
commits and both next states are returned, or nothing does and the input
hashes are the next hashes — Core 358.5 restores the pre-play state, and this
module never returns a half-paid state.

Costs are typed `cost_payment` records with a receipt (`cost_receipt.py`), not
effects with a `cost: true` flag. The receipt records, per component: the
intent for an optional cost (355.1.a), the requested and final amounts with
every increase and reduction that touched them (356.1–356.6), which unique
payment events settled it and for how much (357.1, 357.2), and whether the
rules consider it paid — for an optional cost that is the decision to pay it,
whatever was actually paid (356.4.f.1); a payment replaced by a replacement
effect still counts (357.2.a).

Failure vocabulary (ADR-0005 §10):
  invalid_input     malformed declaration, state, envelope, or a program that
                    does not bind to the declaration
  decision_required an optional cost whose intent the controller has not
                    declared; a play-time target selection not supplied; or a
                    pool short of the total while the Add window (429.3) has
                    not been confirmed closed by a human
  unsupported       a cost mechanic the engine does not type; a replacement
                    that needs a choice during payment
  illegal           an unpayable supported cost once the Add window is closed,
                    a card not in hand, a target illegal at play (355.9), a
                    decision owned by the wrong player, or a timing refusal

The chain is a shared zone: the played card lives in the effect state's
top-level `chain_items[item_id]`, bound to the timing item and its controller,
never in a per-player zone.
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
from cost_receipt import RECEIPT_VERSION, validate_cost_receipt  # noqa: E402
from effect_ir import (  # noqa: E402
    CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, _bump_identity, apply_program, derive_targeted, evaluate_target,
    find_location, hash_value, object_identity, validate_program, validate_state, zone_class,
)
from rules_core import add_pending_item, state_hash  # noqa: E402

DECLARATION_VERSION = "riftbound-play-declaration.v1"
RESULT_VERSION = "riftbound-play-result.v1"

# Non-standard costs the engine can pay by reusing a primitive operation
# (356.7, 357.2). Anything else is `unsupported` by name.
SUPPORTED_NON_STANDARD = {"exhaust": "exhaust", "kill": "kill"}
PAID_OUTCOMES = {"applied", "replaced_prevented", "replaced_modified_applied", "replaced_modified_prevented", "augmented_applied", "augmented_original_replaced"}
STAGES = ("declaration", "choices", "cost_determination", "payment", "legality", "commit")
DECISION_REASONS = {"optional_cost_intent_required", "target_selection_required", "add_window_confirmation_required"}

RULES = {
    "choices": ["Core 355.1", "Core 355.1.a", "Core 355.5", "Core 355.9"],
    "cost": ["Core 356.1", "Core 356.2", "Core 356.3", "Core 356.4", "Core 356.5", "Core 356.6", "Core 356.7"],
    "payment": ["Core 357.1", "Core 357.2", "Core 357.2.a", "Core 429.3"],
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
    if set(value) - {"schema_version", "ruleset", "play_id", "actor", "card", "effect_program_id", "chain_item", "cost", "payment_context"}:
        errors.append("declaration contains unsupported fields")
    for key in ("play_id", "actor", "card"):
        if not isinstance(value.get(key), str) or not value.get(key):
            errors.append(f"{key} must be a non-empty string")
    if "effect_program_id" in value and (not isinstance(value["effect_program_id"], str) or not value["effect_program_id"]):
        errors.append("effect_program_id must be a non-empty string when supplied")
    ctx = value.get("payment_context")
    if ctx is not None and (not isinstance(ctx, dict) or set(ctx) != {"add_window_closed", "confirmed_by"} or not isinstance(ctx["add_window_closed"], bool) or not isinstance(ctx["confirmed_by"], str) or not ctx["confirmed_by"]):
        errors.append("payment_context must be {add_window_closed: bool, confirmed_by: non-empty string}")
    item = value.get("chain_item")
    if not isinstance(item, dict) or set(item) - {"id", "object_kind", "timing", "ability_kind"} or not {"id", "object_kind", "timing"} <= set(item):
        errors.append("chain_item must carry id, object_kind, timing")
    else:
        if not isinstance(item.get("id"), str) or not item.get("id"):
            errors.append("chain_item.id must be a non-empty string")
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
    ids: set[str] = set()
    for i, disc in enumerate(cost.get("discounts", []) or []):
        if not isinstance(disc, dict) or not {"id", "applies_to", "amount"} <= set(disc) or set(disc) - {"id", "applies_to", "amount", "minimum", "resource", "source"} or not isinstance(disc["amount"], int) or disc["amount"] < 1:
            errors.append(f"cost.discounts[{i}] is invalid")
            continue
        if not isinstance(disc["id"], str) or not disc["id"] or disc["id"] in ids:
            errors.append(f"cost.discounts[{i}].id is invalid or duplicated")
        ids.add(disc.get("id", ""))
        target = disc["applies_to"]
        if not (target in {"energy", "total", "optional_additional"} or str(target).startswith("power:")):
            errors.append(f"cost.discounts[{i}].applies_to is invalid")
        if target == "optional_additional" and not (disc.get("resource") == "energy" or str(disc.get("resource", "")).startswith("power:")):
            errors.append(f"cost.discounts[{i}] optional_additional discounts must name the resource they reduce")
        if target != "optional_additional" and "resource" in disc:
            errors.append(f"cost.discounts[{i}].resource is only for optional_additional discounts")
        if "minimum" in disc and (not isinstance(disc["minimum"], int) or disc["minimum"] < 0):
            errors.append(f"cost.discounts[{i}].minimum must be a non-negative integer")
    for i, mod in enumerate(cost.get("total_modifications", []) or []):
        if not isinstance(mod, dict) or mod.get("kind") != "ignore_any_and_all" or set(mod) - {"kind", "source"}:
            errors.append(f"cost.total_modifications[{i}] is invalid")
    return errors


def validate_play_result(value: Any) -> list[str]:
    """Shape plus the relations that make a result trustworthy: a committed
    result carries both next states, matching hashes, and a valid paid
    receipt; anything else carries neither state and points its next hashes
    at the inputs (358.5)."""
    if not isinstance(value, dict):
        return ["play result must be an object"]
    errors: list[str] = []
    required = {"schema_version", "ruleset", "play_id", "input_timing_state_hash", "input_effect_state_hash", "valid", "committed", "unsupported", "rolled_back", "stage", "reason_code", "trace", "rule_locators"}
    if not required <= set(value):
        return [f"missing fields: {sorted(required - set(value))}"]
    if value["schema_version"] != RESULT_VERSION:
        errors.append(f"schema_version must be {RESULT_VERSION}")
    for key in ("valid", "committed", "unsupported", "rolled_back"):
        if not isinstance(value[key], bool):
            errors.append(f"{key} must be boolean")
    if errors:
        return errors
    if value["stage"] not in STAGES:
        errors.append("stage is invalid")
    if not isinstance(value["trace"], list) or not isinstance(value["rule_locators"], list):
        errors.append("trace and rule_locators must be arrays")
    has_states = "next_timing_state" in value or "next_effect_state" in value
    if value["committed"]:
        if not value["valid"] or value["unsupported"] or value["rolled_back"] or value["stage"] != "commit" or value["reason_code"] != "ok":
            errors.append("a committed result must be valid, supported, not rolled back, at stage commit with reason ok")
        for key in ("next_timing_state", "next_effect_state", "next_timing_state_hash", "next_effect_state_hash", "cost_receipt", "chain_item_id"):
            if key not in value:
                errors.append(f"committed result lacks {key}")
        if errors:
            return errors
        if value["next_timing_state_hash"] != state_hash(value["next_timing_state"]) or value["next_effect_state_hash"] != hash_value(value["next_effect_state"]):
            errors.append("next hashes do not match next states")
        receipt_errors = validate_cost_receipt(value["cost_receipt"])
        if receipt_errors:
            errors.append("cost_receipt invalid: " + "; ".join(receipt_errors))
        elif not value["cost_receipt"]["paid"] or value["cost_receipt"]["play_id"] != value["play_id"]:
            errors.append("committed result must carry a paid receipt for this play")
        entry = (value["next_effect_state"].get("chain_items") or {}).get(value["chain_item_id"])
        if not isinstance(entry, dict) or entry.get("card") != value["cost_receipt"].get("card") if not receipt_errors else False:
            errors.append("committed result must leave the played card on the shared chain under chain_item_id")
        if any(item.get("id") == value["chain_item_id"] for item in value["next_timing_state"].get("chain", {}).get("items", [])) is False:
            errors.append("committed result must insert chain_item_id into the timing chain")
        if any(k in value for k in ("decision_ids", "decision_controller", "errors")):
            errors.append("committed result carries failure-only fields")
    else:
        if has_states or "cost_receipt" in value or "chain_item_id" in value:
            errors.append("an uncommitted result must carry no next states, receipt, or chain item")
        if value["stage"] == "commit" or value["reason_code"] == "ok":
            errors.append("an uncommitted result cannot claim stage commit or reason ok")
        for key, source in (("next_timing_state_hash", "input_timing_state_hash"), ("next_effect_state_hash", "input_effect_state_hash")):
            if key in value and value[key] != value[source]:
                errors.append(f"uncommitted {key} must equal {source} (Core 358.5)")
        if value["valid"] and not value["rolled_back"]:
            errors.append("a valid uncommitted result must be rolled back")
        if not value["valid"] and (value["rolled_back"] or value["unsupported"] or value["reason_code"] != "invalid_input" or not isinstance(value.get("errors"), list)):
            errors.append("an invalid result is invalid_input with errors and nothing rolled back")
        if value["unsupported"] and not value["valid"]:
            errors.append("unsupported requires a valid input")
        if value["reason_code"] in DECISION_REASONS and (not isinstance(value.get("decision_ids"), list) or not value["decision_ids"] or not isinstance(value.get("decision_controller"), str)):
            errors.append("a decision_required result must name decision_ids and the controller")
        if value["reason_code"] not in DECISION_REASONS and "decision_ids" in value:
            errors.append("decision_ids only accompany a decision_required reason")
    return errors


# ------------------------------------------------------------- cost arithmetic --

def _apply_discount(amount: int, discount: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    floor = discount.get("minimum", 0)
    reduced = max(min(amount, floor), amount - discount["amount"]) if amount > floor else amount
    reduced = max(reduced, 0)
    return reduced, {"discount_id": discount["id"], "applies_to": discount["applies_to"], "amount": amount - reduced, "minimum": discount.get("minimum"),
                     "rule_locators": ["Core 356.4.e"] if "minimum" in discount else ["Core 356.4"]}


def determine_total_cost(cost: dict[str, Any], intents: dict[str, bool], *, actor: str = "controller") -> dict[str, Any]:
    """Core 356 in order: base modifications, additional costs, increases,
    component discounts in declared order, total discounts on the aggregate
    Energy (base plus every chosen additional Energy cost), total
    modifications, floor at zero. Returns the receipt skeleton before payment."""
    base = copy.deepcopy(cost["base"])
    current = copy.deepcopy(base)
    for mod in cost.get("base_modifications", []) or []:
        if mod["kind"] == "for_cost":
            current = copy.deepcopy(mod["cost"])
        elif mod["kind"] == "ignore_energy":
            current["energy"] = 0
        elif mod["kind"] == "ignore_power":
            current["power"] = {}
        elif mod["kind"] == "ignore_all":
            current = {"energy": 0, "power": {}}
    after_base = copy.deepcopy(current)

    def component(cost_id, kind, mandatory, intent, requested, locators, **extra):
        return {"cost_id": cost_id, "kind": kind, "mandatory": mandatory, "intent": intent, "requested": requested,
                "increases": [], "reductions": [], "final": requested, "payment_refs": [], "paid": False, "rule_locators": locators, **extra}

    components = [component("base:energy", "energy", True, None, current["energy"], ["Core 356.1", "Core 357.1"])]
    for domain, amount in sorted(current["power"].items()):
        components.append(component(f"base:power:{domain}", "power", True, None, amount, ["Core 356.1", "Core 357.1"], domain=domain))
    # 356.2: mandatory always; optional only when the intent decision said so
    # (356.2.b.1). A declined optional cost stays on the receipt, unpaid —
    # that is what "Otherwise" tests.
    for add in cost.get("additional", []) or []:
        pay = add["payment"]
        intent = None if add["mandatory"] else bool(intents.get(add["cost_id"], False))
        requested = pay.get("amount") if pay["kind"] in {"energy", "power"} else {k: v for k, v in pay.items() if k != "kind"}
        components.append(component(add["cost_id"], pay["kind"], add["mandatory"], intent, requested,
                                    ["Core 356.2.a"] if add["mandatory"] else ["Core 356.2.b", "Core 356.4.f.1"],
                                    domain=pay.get("domain"), object_id=pay.get("object_id")))
    by_id = {c["cost_id"]: c for c in components}

    def chosen(c):
        return c["mandatory"] or c["intent"] is True

    # 356.3 increases.
    for inc in cost.get("increases", []) or []:
        target = "base:energy" if inc["component"] == "energy" else f"base:{inc['component']}"
        comp = by_id.get(target)
        if comp is None and inc["component"].startswith("power:"):
            comp = component(target, "power", True, None, 0, ["Core 356.3", "Core 357.1"], domain=inc["component"].split(":", 1)[1])
            components.append(comp); by_id[target] = comp
        if comp is not None:
            comp["final"] += inc["amount"]
            comp["increases"].append({"increase_id": inc["id"], "amount": inc["amount"], "source": inc.get("source"), "rule_locators": ["Core 356.3"]})

    # 356.4: component discounts in the declared (player-confirmed) order
    # (356.4.c), then total discounts on the aggregate Energy (356.4.d). Each
    # minimum belongs to its own discount (356.4.e).
    discounts = cost.get("discounts", []) or []
    order = []
    for disc in discounts:
        if disc["applies_to"] == "total":
            continue
        order.append({"id": disc["id"], "tier": "component"})
        if disc["applies_to"] == "optional_additional":
            res = disc["resource"]
            targets = [c for c in components if not c["mandatory"] and c["intent"] is True and c["kind"] in {"energy", "power"}
                       and ((res == "energy" and c["kind"] == "energy") or (res.startswith("power:") and c["kind"] == "power" and c.get("domain") == res.split(":", 1)[1]))]
        elif disc["applies_to"] == "energy":
            targets = [by_id["base:energy"]]
        else:
            targets = [c for c in components if c["cost_id"] == f"base:{disc['applies_to']}"]
        for comp in targets:
            comp["final"], record = _apply_discount(comp["final"], disc)
            comp["reductions"].append(record)
    aggregate_before = sum(c["final"] for c in components if c["kind"] == "energy" and chosen(c))
    aggregate = aggregate_before
    aggregate_reductions = []
    for disc in discounts:
        if disc["applies_to"] != "total":
            continue
        order.append({"id": disc["id"], "tier": "total"})
        aggregate, record = _apply_discount(aggregate, disc)
        record["rule_locators"] = ["Core 356.4.d"] + record["rule_locators"]
        aggregate_reductions.append(record)

    # 356.5 total modifications.
    for mod in cost.get("total_modifications", []) or []:
        for comp in components:
            if comp["kind"] in {"energy", "power"} and chosen(comp) and comp["final"]:
                comp["reductions"].append({"discount_id": None, "applies_to": "any_and_all", "amount": comp["final"], "minimum": None, "rule_locators": ["Core 356.5.a"]})
                comp["final"] = 0
        if aggregate:
            aggregate_reductions.append({"discount_id": None, "applies_to": "any_and_all", "amount": aggregate, "minimum": None, "rule_locators": ["Core 356.5.a"]})
        aggregate = 0
    # 356.6 floor.
    aggregate = max(aggregate, 0)
    for comp in components:
        if comp["kind"] in {"energy", "power"} and isinstance(comp["final"], int) and comp["final"] < 0:
            comp["final"] = 0

    total = {"energy": aggregate, "power": {}}
    for comp in components:
        if comp["kind"] == "power" and chosen(comp):
            total["power"][comp["domain"]] = total["power"].get(comp["domain"], 0) + comp["final"]
    return {
        "base": base, "after_base_modifications": after_base, "components": components,
        "aggregate": {"energy": {"before_total_discounts": aggregate_before, "reductions": aggregate_reductions, "final": aggregate}},
        "discount_order": order, "order_provenance": f"declaration order, confirmed by {actor}",
        "total": total,
    }


# -------------------------------------------------------------------- payment --

def _pay(working: dict[str, Any], declaration: dict[str, Any], skeleton: dict[str, Any]) -> list[dict[str, Any]]:
    """Core 357: Energy and Power in total (357.1), then non-standard costs in
    declared order (357.2). Payment events are unique; components reference
    them with exact allocations. Mutates `working`; the caller discards it on
    any failure (358.5)."""
    actor = declaration["actor"]
    resources = working["players"][actor]["resources"]
    total = skeleton["total"]
    ctx = declaration.get("payment_context") or {}
    short = resources["energy"] < total["energy"] or any(resources["power"].get(d, 0) < a for d, a in total["power"].items())
    if short:
        # Core 429.3: the controller may use Add reactions during payment. The
        # engine cannot see whether they will; a human must say the window is
        # closed before a short pool becomes an illegal play.
        if ctx.get("add_window_closed") is not True:
            raise PlayError("payment", "add_window_confirmation_required",
                            f"{actor}'s pool is short of the total cost and the Add window (Core 429.3) has not been confirmed closed",
                            decision_ids=[f"add_window:{declaration['play_id']}"], decision_controller=actor, rule_locators=["Core 429.3", "Core 357.1.a"])
        raise PlayError("payment", "cost_unpayable", f"{actor} cannot pay {total} from {resources} with the Add window closed", rule_locators=["Core 357.1"])

    events: list[dict[str, Any]] = []
    if total["energy"]:
        before = resources["energy"]; resources["energy"] -= total["energy"]
        events.append({"event_id": "pay:energy", "kind": "pay_energy", "amount": total["energy"], "before": before, "after": resources["energy"], "rule_locators": ["Core 357.1"]})
        remaining = total["energy"]
        for comp in skeleton["components"]:
            if comp["kind"] == "energy" and (comp["mandatory"] or comp["intent"] is True):
                share = min(comp["final"], remaining)
                if share:
                    comp["payment_refs"].append({"event_id": "pay:energy", "amount": share})
                remaining -= share
    for domain, amount in sorted(total["power"].items()):
        if not amount:
            continue
        before = resources["power"][domain]; resources["power"][domain] -= amount
        event_id = f"pay:power:{domain}"
        events.append({"event_id": event_id, "kind": "pay_power", "domain": domain, "amount": amount, "before": before, "after": resources["power"][domain], "rule_locators": ["Core 357.1"]})
        remaining = amount
        for comp in skeleton["components"]:
            if comp["kind"] == "power" and comp.get("domain") == domain and (comp["mandatory"] or comp["intent"] is True):
                share = min(comp["final"], remaining)
                if share:
                    comp["payment_refs"].append({"event_id": event_id, "amount": share})
                remaining -= share
    for comp in skeleton["components"]:
        if comp["kind"] in {"energy", "power"} and (comp["mandatory"] or comp["intent"] is True):
            comp["paid"] = True

    for comp in skeleton["components"]:
        if comp["kind"] in {"energy", "power"} or not (comp["mandatory"] or comp["intent"] is True):
            continue
        op = SUPPORTED_NON_STANDARD[comp["kind"]]
        selector = {"object_id": comp["object_id"], "chosen_zone_class": "board", "controller_relation": "friendly",
                    "bound_identity": object_identity(working, comp["object_id"]) or f"{comp['object_id']}@0"}
        program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "program_id": f"cost:{declaration['play_id']}:{comp['cost_id']}", "controller": actor,
                   "effects": [{"op": op, "effect_id": comp["cost_id"], "object_id": comp["object_id"], "target": selector}]}
        # No envelope here: it is keyed to the pre-play hash and the pool is
        # already debited. A replacement that needs a choice mid-payment is a
        # contract the engine does not have yet.
        result = apply_program(working, program)
        if result.get("replacement_decision_required"):
            raise PlayError("payment", "payment_replacement_decision_not_modelled",
                            f"cost {comp['cost_id']!r} needs a replacement choice during payment: {result.get('reason')}",
                            unsupported=True, replacement_ids=result.get("replacement_ids", []), rule_locators=["Core 357.2.a"])
        if result.get("committed") is not True:
            raise PlayError("payment", "cost_unpayable", f"cost {comp['cost_id']!r} ({comp['kind']}) cannot be paid: {result.get('reason') or '; '.join(result.get('errors', []))}", rule_locators=["Core 357.2", "Core 203.3"])
        outcome = result["trace"][0].get("outcome")
        if outcome not in PAID_OUTCOMES:
            raise PlayError("payment", "cost_unpayable", f"cost {comp['cost_id']!r} ({comp['kind']}) did not happen: {outcome}", rule_locators=["Core 357.2", "Core 203.3"])
        working.clear(); working.update(result["next_state"])
        event_id = f"pay:{comp['cost_id']}"
        events.append({"event_id": event_id, "kind": f"pay_{comp['kind']}", "cost_id": comp["cost_id"], "object_id": comp["object_id"], "outcome": outcome,
                       "trace": copy.deepcopy(result["trace"]), "rule_locators": ["Core 357.2"] + (["Core 357.2.a"] if outcome != "applied" else [])})
        comp["payment_refs"].append({"event_id": event_id})
        comp["paid"] = True
        if outcome != "applied":
            comp["rule_locators"] = list(dict.fromkeys(comp["rule_locators"] + ["Core 357.2.a"]))
    return events


# ------------------------------------------------------------------- choices --

def _check_play_targets(effect_state: dict[str, Any], actor: str, program: dict[str, Any], decisions: dict[str, Any] | None) -> None:
    """Core 355.5 / 355.9: every selector that targets is chosen and legal at
    play — concrete selectors and decision-supplied ones alike. A supplied
    decision must be for this stage, owned by the actor, and bound to the
    objects' current identities."""
    for index, effect in enumerate(program.get("effects", [])):
        candidates: list[tuple[dict[str, Any], str | None]] = []
        if isinstance(effect.get("target"), dict):
            candidates.append((effect["target"], effect["target"].get("decision_ref")))
        if isinstance(effect.get("targets"), dict):
            for sel in effect["targets"].get("selectors", []) or []:
                candidates.append((sel, None))
            if "decision_ref" in effect["targets"]:
                candidates.append((dict(effect["targets"].get("restrictions", {}), chosen_zone_class=effect["targets"].get("restrictions", {}).get("chosen_zone_class", "board")), effect["targets"]["decision_ref"]))
        for template, ref in candidates:
            if ref is None:
                if derive_targeted(template):
                    ok, reason = evaluate_target(effect_state, template, actor)
                    if not ok:
                        raise PlayError("choices", "target_illegal_at_play", f"effects[{index}] target {template.get('object_id')!r}: {reason}", rule_locators=["Core 355.9"])
                continue
            entry = ed.target_selection(decisions, ref)
            if entry is None:
                raise PlayError("choices", "target_selection_required", f"target selection {ref!r} is made at play (Core 355.5) and was not supplied", decision_ids=[ref], decision_controller=actor, rule_locators=["Core 355.5"])
            if entry["stage"] != "play_declaration":
                raise PlayError("choices", "decision_stage_mismatch", f"target selection {ref!r} was supplied for stage {entry['stage']!r}, not play_declaration", invalid=True)
            if entry["controller"] != actor:
                raise PlayError("choices", "decision_controller_mismatch", f"target selection {ref!r} was made by {entry['controller']!r}, not the card's controller", rule_locators=["Core 355.5"])
            identities = entry.get("selection_identities") or {}
            for object_id in entry["value"]:
                if object_id in identities and identities[object_id] != object_identity(effect_state, object_id):
                    raise PlayError("choices", "selection_identity_mismatch", f"target selection {ref!r} was bound to {identities[object_id]!r}; the object is now {object_identity(effect_state, object_id)!r}", invalid=True)
                selector = {k: v for k, v in template.items() if k not in {"decision_ref", "object_id"}}
                selector["object_id"] = object_id
                selector.setdefault("chosen_zone_class", zone_class(find_location(effect_state, object_id)) or "non_board")
                if derive_targeted(selector):
                    ok, reason = evaluate_target(effect_state, selector, actor)
                    if not ok:
                        raise PlayError("choices", "target_illegal_at_play", f"effects[{index}] target {object_id!r}: {reason}", rule_locators=["Core 355.9"])


# ---------------------------------------------------------------- transaction --

def play_card(timing_state: dict[str, Any], effect_state: dict[str, Any], declaration: dict[str, Any], *,
              engine_decisions: dict[str, Any] | None = None, effect_program: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {
        "schema_version": RESULT_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": declaration.get("play_id") if isinstance(declaration, dict) and isinstance(declaration.get("play_id"), str) else None,
        "input_timing_state_hash": state_hash(timing_state) if isinstance(timing_state, dict) else hash_value(timing_state),
        "input_effect_state_hash": hash_value(effect_state),
    }

    def invalid(errors: list[str], stage: str = "declaration") -> dict[str, Any]:
        return {**base, "valid": False, "committed": False, "unsupported": False, "rolled_back": False, "stage": stage,
                "reason_code": "invalid_input", "reason": "; ".join(errors), "errors": errors, "trace": [], "rule_locators": []}

    errors = validate_declaration(declaration)
    errors += [f"effect state: {e}" for e in validate_state(effect_state)]
    errors += [f"engine_decisions: {e}" for e in ed.validate_engine_decisions(engine_decisions)]
    if engine_decisions is not None and not errors and engine_decisions.get("input_hash") != hash_value(effect_state):
        errors.append("engine_decisions.input_hash does not match the effect state")
    if effect_program is not None:
        errors += [f"effect program: {e}" for e in validate_program(effect_program)]
        if not errors:
            if declaration.get("effect_program_id") != effect_program.get("program_id"):
                errors.append(f"declaration.effect_program_id {declaration.get('effect_program_id')!r} does not bind to program {effect_program.get('program_id')!r}")
            if effect_program.get("controller") not in (None, declaration.get("actor")):
                errors.append("effect program controller is not the declaring actor")
    if errors:
        return invalid(errors)

    trace: list[dict[str, Any]] = []
    locators: list[str] = []
    try:
        actor, card = declaration["actor"], declaration["card"]
        item_id = declaration["chain_item"]["id"]
        if actor not in effect_state["players"]:
            raise PlayError("declaration", "unknown_actor", f"{actor!r} is not a player in the effect state", invalid=True)
        if item_id in (effect_state.get("chain_items") or {}) or any(i.get("id") == item_id for i in timing_state.get("chain", {}).get("items", [])):
            raise PlayError("declaration", "chain_item_id_collision", f"chain item {item_id!r} already exists", invalid=True)
        if find_location(effect_state, card) != ("player", actor, "hand"):
            raise PlayError("choices", "card_not_in_hand", f"{card!r} is not in {actor}'s hand", rule_locators=["Core 354"])
        if effect_state["objects"][card]["kind"] != declaration["chain_item"]["object_kind"]:
            raise PlayError("choices", "object_kind_mismatch", f"{card!r} is a {effect_state['objects'][card]['kind']}; the chain item says {declaration['chain_item']['object_kind']}", invalid=True)

        # --- 355: choices.
        intents: dict[str, bool] = {}
        missing: list[str] = []
        for add in declaration["cost"].get("additional", []) or []:
            if add["mandatory"]:
                continue
            entry = next((e for e in ed.entries(engine_decisions, kind="optional_choice") if e["decision_id"] == add["cost_id"]), None)
            if entry is None:
                missing.append(add["cost_id"])
                continue
            if entry["stage"] != "play_declaration":
                raise PlayError("choices", "decision_stage_mismatch", f"optional cost {add['cost_id']!r} intent was supplied for stage {entry['stage']!r}", invalid=True)
            if entry["controller"] != actor:
                raise PlayError("choices", "decision_controller_mismatch", f"optional cost {add['cost_id']!r} was chosen by {entry['controller']!r}, not the card's controller", rule_locators=["Core 355.1.a"])
            intents[add["cost_id"]] = bool(entry["value"])
        if missing:
            raise PlayError("choices", "optional_cost_intent_required", f"optional cost intent not declared for {missing}", decision_ids=missing, decision_controller=actor, rule_locators=["Core 355.1.a", "Core 356.2.b.1"])
        if effect_program is not None:
            _check_play_targets(effect_state, actor, effect_program, engine_decisions)
        trace.append({"stage": "choices", "outcome": "applied", "optional_cost_intents": intents, "rule_locators": RULES["choices"]})
        locators += RULES["choices"]

        # --- 356: total cost.
        for add in declaration["cost"].get("additional", []) or []:
            kind = add["payment"]["kind"]
            if kind not in {"energy", "power"} and kind not in SUPPORTED_NON_STANDARD and (add["mandatory"] or intents.get(add["cost_id"])):
                raise PlayError("cost_determination", "unsupported_cost_kind", f"cost {add['cost_id']!r} uses {kind!r}, which the engine does not type", unsupported=True, rule_locators=["Core 356.7"])
        skeleton = determine_total_cost(declaration["cost"], intents, actor=actor)
        trace.append({"stage": "cost_determination", "outcome": "applied", "total": copy.deepcopy(skeleton["total"]), "rule_locators": RULES["cost"]})
        locators += RULES["cost"]

        # --- 357: payment on a working copy.
        working = copy.deepcopy(effect_state)
        before_pay = hash_value(working)
        pay_events = _pay(working, declaration, skeleton)
        trace.append({"stage": "payment", "outcome": "applied", "event_ids": [e["event_id"] for e in pay_events], "before_state_hash": before_pay, "after_state_hash": hash_value(working), "rule_locators": RULES["payment"]})
        locators += RULES["payment"]

        # The card leaves the hand for the shared chain: a zone change, so a
        # new object (Core 124). The chain entry binds card, controller, and
        # program to the timing item.
        working["players"][actor]["zones"]["hand"].remove(card)
        entry = {"card": card, "controller": actor}
        if declaration.get("effect_program_id"):
            entry["effect_program_id"] = declaration["effect_program_id"]
        working.setdefault("chain_items", {})[item_id] = entry
        identity_after = _bump_identity(working, card)
        state_errors = validate_state(working)
        if state_errors:
            raise PlayError("payment", "invalid_working_state", "; ".join(state_errors), invalid=True)

        # --- 358: legality and chain insertion through the timing kernel.
        item = {**declaration["chain_item"], "ability_kind": declaration["chain_item"].get("ability_kind")}
        if declaration.get("effect_program_id"):
            item["effect_program_id"] = declaration["effect_program_id"]
        insertion = add_pending_item(timing_state, {"actor": actor, "kind": "play_card", "item": item, "initiated_by": "played_card"})
        if insertion.get("valid") is False:
            raise PlayError("legality", "invalid_timing_state", "; ".join(insertion.get("errors", [])), invalid=True)
        if insertion.get("applied") is not True:
            raise PlayError("legality", insertion.get("reason_code") or "play_illegal", f"the timing kernel refused the play: {insertion.get('reason_code')}", legality=insertion.get("legality"), rule_locators=RULES["legality"])
        trace.append({"stage": "legality", "outcome": "applied", "chain_item_id": item_id, "card_identity_after": identity_after, "rule_locators": RULES["legality"] + RULES["identity"]})
        locators += RULES["legality"] + RULES["identity"]
    except PlayError as exc:
        extra = dict(exc.extra)
        rule_locators = extra.pop("rule_locators", [])
        is_invalid = bool(extra.pop("invalid", False))
        if is_invalid:
            return invalid([str(exc)], exc.stage) | {"reason_code": "invalid_input", "reason": str(exc)}
        result = {
            **base, "valid": True, "committed": False, "unsupported": bool(extra.pop("unsupported", False)), "rolled_back": True,
            "stage": exc.stage, "reason_code": exc.reason_code, "reason": str(exc),
            "trace": trace + [{"stage": exc.stage, "outcome": "rolled_back", "reason_code": exc.reason_code, "rule_locators": ["Core 358.5"]}],
            "rule_locators": list(dict.fromkeys(locators + rule_locators + ["Core 358.5"])),
            "next_timing_state_hash": base["input_timing_state_hash"], "next_effect_state_hash": base["input_effect_state_hash"],
        }
        result.update(extra)
        return result

    receipt = {
        "schema_version": RECEIPT_VERSION, "play_id": declaration["play_id"], "actor": actor, "card": card,
        "base": skeleton["base"], "after_base_modifications": skeleton["after_base_modifications"],
        "components": skeleton["components"], "aggregate": skeleton["aggregate"],
        "discount_order": skeleton["discount_order"], "order_provenance": skeleton["order_provenance"],
        "payment_events": pay_events, "total": skeleton["total"],
        "paid": all(c["paid"] for c in skeleton["components"] if c["mandatory"] or c["intent"] is True),
        "rule_locators": list(dict.fromkeys(RULES["cost"] + RULES["payment"] + ["Core 356.4.f.1"])),
    }
    next_timing = insertion["next_state"]
    result = {
        **base, "valid": True, "committed": True, "unsupported": False, "rolled_back": False, "stage": "commit", "reason_code": "ok",
        "chain_item_id": item_id, "cost_receipt": receipt,
        "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
        "next_effect_state": working, "next_effect_state_hash": hash_value(working),
        "trace": trace + [{"stage": "commit", "outcome": "applied", "rule_locators": ["Core 358.4"]}],
        "rule_locators": list(dict.fromkeys(locators)),
    }
    problems = validate_play_result(result)
    if problems:
        raise RuntimeError("play transaction produced an inconsistent result: " + "; ".join(problems))
    return result


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
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
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
