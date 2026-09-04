#!/usr/bin/env python3
"""
riftbound-cost-receipt.v1 — the only evidence a later "If you do" may test.

Standalone on purpose: both the play transaction (which writes receipts) and
the effect IR (which reads them through cost predicates) import this module,
and neither may import the other.

A receipt says, per cost component, what was requested, what every increase
and reduction did to it, which payment events settled it and for how much,
and whether the rules consider it paid. Payment events are unique at the
receipt level; components reference them with exact allocations, so one
Energy payment is never copied into three components.
"""

from __future__ import annotations

from typing import Any

RECEIPT_VERSION = "riftbound-cost-receipt.v1"
RESOURCE_KINDS = {"energy", "power", "power_any"}

_TOP = {"schema_version", "play_id", "actor", "card", "base", "after_base_modifications", "components", "aggregate",
        "discount_order", "order_provenance", "payment_events", "total", "paid", "rule_locators"}
_COMPONENT = {"cost_id", "kind", "mandatory", "intent", "requested", "increases", "reductions", "final",
              "payment_refs", "paid", "rule_locators", "domain", "object_id"}


def _is_resource(value: Any) -> bool:
    return (isinstance(value, dict) and {"energy", "power"} <= set(value) <= {"energy", "power", "power_any"} and isinstance(value["energy"], int) and value["energy"] >= 0
            and (not isinstance(value.get("power_any", 0), bool)) and isinstance(value.get("power_any", 0), int) and value.get("power_any", 0) >= 0
            and isinstance(value["power"], dict) and all(isinstance(v, int) and v >= 0 for v in value["power"].values()))


def validate_cost_receipt(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["cost receipt must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != RECEIPT_VERSION:
        errors.append(f"schema_version must be {RECEIPT_VERSION}")
    if set(value) != _TOP:
        errors.append(f"receipt fields must be exactly {sorted(_TOP)}")
        return errors
    for key in ("play_id", "actor", "card", "order_provenance"):
        if not isinstance(value[key], str) or not value[key]:
            errors.append(f"{key} must be a non-empty string")
    if not _is_resource(value["base"]) or not _is_resource(value["after_base_modifications"]) or not _is_resource(value["total"]):
        errors.append("base, after_base_modifications and total must be {energy, power} resource objects")
    if not isinstance(value["paid"], bool):
        errors.append("paid must be boolean")
    if not isinstance(value["rule_locators"], list) or any(not isinstance(x, str) for x in value["rule_locators"]):
        errors.append("rule_locators must be a string array")

    events = value["payment_events"]
    if not isinstance(events, list):
        errors.append("payment_events must be an array")
        events = []
    event_amount: dict[str, int | None] = {}
    for i, ev in enumerate(events):
        if not isinstance(ev, dict) or not isinstance(ev.get("event_id"), str) or not ev["event_id"] or ev.get("kind") not in {"pay_energy", "pay_power", "pay_exhaust", "pay_kill"}:
            errors.append(f"payment_events[{i}] must carry event_id and a known kind")
            continue
        if ev["event_id"] in event_amount:
            errors.append(f"payment_events[{i}].event_id {ev['event_id']!r} is duplicated")
        if ev["kind"] in {"pay_energy", "pay_power"}:
            if not isinstance(ev.get("amount"), int) or ev["amount"] < 1 or not isinstance(ev.get("before"), int) or not isinstance(ev.get("after"), int) or ev["before"] - ev["amount"] != ev["after"]:
                errors.append(f"payment_events[{i}] resource amounts are inconsistent")
            if ev["kind"] == "pay_power" and (not isinstance(ev.get("domain"), str) or not ev["domain"]):
                errors.append(f"payment_events[{i}] power event needs a domain")
            event_amount[ev["event_id"]] = ev.get("amount") if isinstance(ev.get("amount"), int) else None
        else:
            event_amount[ev["event_id"]] = None

    components = value["components"]
    if not isinstance(components, list) or not components:
        return errors + ["components must be a non-empty array"]
    allocated: dict[str, int] = {}
    seen: set[str] = set()
    expected_paid_all = True
    for i, comp in enumerate(components):
        label = f"components[{i}]"
        if not isinstance(comp, dict) or not {"cost_id", "kind", "mandatory", "intent", "requested", "increases", "reductions", "final", "payment_refs", "paid", "rule_locators"} <= set(comp) or set(comp) - _COMPONENT:
            errors.append(f"{label} has invalid fields")
            continue
        if not isinstance(comp["cost_id"], str) or not comp["cost_id"] or comp["cost_id"] in seen:
            errors.append(f"{label}.cost_id is invalid or duplicated")
        seen.add(comp.get("cost_id", ""))
        if not isinstance(comp["mandatory"], bool) or not isinstance(comp["paid"], bool) or comp["intent"] not in (True, False, None):
            errors.append(f"{label} mandatory/paid/intent are invalid")
            continue
        if comp["mandatory"] and comp["intent"] is not None:
            errors.append(f"{label} mandatory costs carry no intent")
        if not comp["mandatory"] and comp["intent"] is None:
            errors.append(f"{label} optional costs must record intent")
        chosen = comp["mandatory"] or comp["intent"] is True
        if not chosen and comp["paid"]:
            errors.append(f"{label} declined optional cost cannot be paid")
        if chosen and not comp["paid"]:
            expected_paid_all = False
        if comp["kind"] in RESOURCE_KINDS and (not isinstance(comp["final"], int) or comp["final"] < 0):
            errors.append(f"{label}.final must be a non-negative integer for resource costs")
        refs = comp["payment_refs"]
        if not isinstance(refs, list):
            errors.append(f"{label}.payment_refs must be an array")
            continue
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("event_id") not in event_amount:
                errors.append(f"{label}.payment_refs references an unknown payment event")
                continue
            if event_amount[ref["event_id"]] is not None:
                if not isinstance(ref.get("amount"), int) or ref["amount"] < 0:
                    errors.append(f"{label}.payment_refs resource allocation needs an amount")
                    continue
                allocated[ref["event_id"]] = allocated.get(ref["event_id"], 0) + ref["amount"]
    for event_id, amount in event_amount.items():
        if amount is not None and allocated.get(event_id, 0) != amount:
            errors.append(f"payment event {event_id!r} allocates {allocated.get(event_id, 0)} of {amount}")
    if value["paid"] != expected_paid_all:
        errors.append("paid does not agree with the components")

    agg = value["aggregate"]
    if not isinstance(agg, dict) or set(agg) != {"energy"} or not isinstance(agg["energy"], dict) or set(agg["energy"]) != {"before_total_discounts", "reductions", "final"}:
        errors.append("aggregate must carry energy {before_total_discounts, reductions, final}")
    elif agg["energy"]["final"] != value["total"]["energy"]:
        errors.append("total.energy must equal aggregate.energy.final")
    order = value["discount_order"]
    if not isinstance(order, list) or any(not isinstance(o, dict) or not isinstance(o.get("id"), str) or o.get("tier") not in {"component", "total"} for o in order):
        errors.append("discount_order must list {id, tier} in the confirmed order")
    return errors


def component(receipt: dict[str, Any], cost_id: str) -> dict[str, Any] | None:
    return next((c for c in receipt.get("components", []) if c.get("cost_id") == cost_id), None)
