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
    entity_identity, evaluate_condition, evaluate_cost_modification, find_location, hash_value, object_identity,
    suffix_decision_refs, validate_condition, validate_program, validate_state, zone_class,
)
from effect_ir import ConditionUnsupported  # noqa: E402
from rules_core import is_terminal, add_pending_item, state_hash  # noqa: E402

DECLARATION_VERSION = "riftbound-play-declaration.v1"
RESULT_VERSION = "riftbound-play-result.v1"

# Non-standard costs the engine can pay by reusing a primitive operation
# (356.7, 357.2). Anything else is `unsupported` by name.
SUPPORTED_NON_STANDARD = {"exhaust": "exhaust", "kill": "kill", "kill_this": "kill", "recall_self": "recall"}
# ADR-0011 §4: costs paid by the chain item's own source (204.2); the object
# is the activation's source_object unless the declaration names one.
SELF_COSTS = {"kill_this", "recall_self", "banish_self"}
# ADR-0012 §1: where a card is played from. The hand is the default; the
# Champion Zone plays as normal (108.3.e); a trash source needs a granted
# permission. Facedown arrives with C-45.
PLAY_SOURCES = {"hand", "champion_zone", "trash", "facedown"}
PERMISSION_REQUIRED_SOURCES = {"trash"}
# ADR-0012 §3: playing a hidden card needs no separate permission — the
# Hidden keyword itself grants it from the next turn (811.1).
HIDDEN_TARGETING = {"restricted", "free_by_restriction"}
# ADR-0011 §4: costs paid by the payer's card choice at play stage.
CHOICE_COSTS = {"discard", "recycle_trash"}
# Costs whose sources live in P4 (XP, Buff, Empower): typed, refused by name.
# C-52 (ADR-0013 §5): the three costs that spend the P4 states.
SPEND_COSTS = {"spend_xp": "Core 730.2", "spend_buff": "Core 702.2.b", "disempower_self": "Core 443.1.b"}
DEFERRED_COST_KINDS: set[str] = set()
PAID_OUTCOMES = {"applied", "replaced_prevented", "replaced_modified_applied", "replaced_modified_prevented", "augmented_applied", "augmented_original_replaced"}
STAGES = ("declaration", "choices", "cost_determination", "payment", "legality", "commit")
DECISION_REASONS = {"optional_cost_intent_required", "target_selection_required", "add_window_confirmation_required", "resource_allocation_required", "mode_selection_required", "card_selection_required", "card_ordering_required"}

RULES = {
    "choices": ["Core 355.1", "Core 355.1.a", "Core 355.2", "Core 355.5", "Core 355.9"],
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
    if set(value) - {"schema_version", "ruleset", "play_id", "actor", "card", "effect_program_id", "chain_item", "cost", "payment_context", "entry_location", "activation", "activation_conditions", "source", "source_permission", "cost_override", "timing_source", "hidden_targeting"}:
        errors.append("declaration contains unsupported fields")
    source = value.get("source")
    if source is not None:
        if not isinstance(source, dict) or set(source) - {"kind", "battlefield"} or source.get("kind") not in PLAY_SOURCES:
            errors.append(f"source.kind must be one of {sorted(PLAY_SOURCES)}")
    permission = value.get("source_permission")
    if permission is not None and (not isinstance(permission, dict) or set(permission) - {"granted_by"} or not isinstance(permission.get("granted_by"), str) or not permission["granted_by"]):
        errors.append("source_permission must be {granted_by: non-empty string}")
    override = value.get("cost_override")
    if override is not None:
        if not isinstance(override, dict) or set(override) - {"kind", "cost", "source"} or override.get("kind") not in {"ignore_base_cost", "for_cost"} or not isinstance(override.get("source"), str) or not override.get("source"):
            errors.append("cost_override must be {kind: ignore_base_cost | for_cost, cost?, source}")
        elif override["kind"] == "for_cost" and not _is_resource_cost(override.get("cost")):
            errors.append("cost_override.for_cost needs a resource cost")
        elif override["kind"] == "ignore_base_cost" and "cost" in override:
            errors.append("cost_override.ignore_base_cost carries no cost")
    if "timing_source" in value and value["timing_source"] not in {"ambush", "hidden"}:
        errors.append("timing_source may only name ambush (Core 822.1) or hidden (Core 811.1)")
    if isinstance(source, dict) and source.get("kind") == "facedown" and (not isinstance(source.get("battlefield"), str) or not source["battlefield"]):
        errors.append("a facedown source names the battlefield the card was hidden at (Core 811.1)")
    if "hidden_targeting" in value and value["hidden_targeting"] not in HIDDEN_TARGETING:
        errors.append(f"hidden_targeting must be one of {sorted(HIDDEN_TARGETING)} (Core 811.4)")
    activation = value.get("activation")
    item_kind_early = (value.get("chain_item") or {}).get("object_kind") if isinstance(value.get("chain_item"), dict) else None
    if item_kind_early == "ability":
        # ADR-0011 §4 / Core 377, 402: an activated ability is declared with its
        # source and ability id; `card` names the source (nothing leaves the hand).
        if not isinstance(activation, dict) or set(activation) - {"source_object", "ability_id"} or not {"source_object", "ability_id"} <= set(activation) or any(not isinstance(activation[k], str) or not activation[k] for k in activation):
            errors.append("an ability declaration needs activation {source_object, ability_id}")
        elif value.get("card") != activation["source_object"]:
            errors.append("an ability declaration's card must be its activation.source_object")
    elif activation is not None:
        errors.append("activation only applies to an ability chain item")
    if "activation_conditions" in value and (not isinstance(value["activation_conditions"], list) or any(not isinstance(c, dict) for c in value["activation_conditions"])):
        errors.append("activation_conditions must be an array of typed conditions")
    location = value.get("entry_location")
    if location is not None and (not isinstance(location, dict) or location.get("kind") not in {"base", "battlefield"} or set(location) - {"kind", "battlefield"}
                                 or (location.get("kind") == "battlefield" and (not isinstance(location.get("battlefield"), str) or not location.get("battlefield")))):
        errors.append("entry_location must be {kind: base} or {kind: battlefield, battlefield: <id>}")
    item_kind = (value.get("chain_item") or {}).get("object_kind") if isinstance(value.get("chain_item"), dict) else None
    if item_kind == "unit" and location is None:
        errors.append("a Unit's entry_location is chosen while playing (Core 355.2) and must be declared")
    hidden_source = isinstance(value.get("source"), dict) and value["source"].get("kind") == "facedown"
    if item_kind == "gear" and location is not None and location.get("kind") != "base" and not hidden_source:
        errors.append("a Non-Unit Gear enters the controller's Base (Core 359.2.d); entry_location may only be base")
    if item_kind in {"spell", "ability"} and location is not None:
        errors.append(f"a {item_kind} has no entry_location")
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
        if item.get("object_kind") not in {"spell", "unit", "gear", "ability"}:
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
        if not isinstance(add, dict) or not {"cost_id", "mandatory", "payment"} <= set(add) or set(add) - {"cost_id", "mandatory", "payment", "source", "repeat"}:
            errors.append(f"cost.additional[{i}] is invalid")
            continue
        if "repeat" in add and (not isinstance(add["repeat"], bool) or (add["repeat"] and add.get("mandatory") is True)):
            errors.append(f"cost.additional[{i}].repeat must be boolean and a Repeat cost is optional (Core 820.1.a)")
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
        if pay["kind"] == "power_any" and (not isinstance(pay.get("amount"), int) or pay["amount"] < 0):
            errors.append(f"cost.additional[{i}].payment.amount is required for power_any")
        if pay["kind"] in {"exhaust", "kill"} and (not isinstance(pay.get("object_id"), str) or not pay.get("object_id")):
            errors.append(f"cost.additional[{i}].payment.object_id is required for {pay['kind']}")
        if pay["kind"] in SELF_COSTS and "object_id" in pay and (not isinstance(pay["object_id"], str) or not pay["object_id"]):
            errors.append(f"cost.additional[{i}].payment.object_id must be a non-empty string when supplied")
        if pay["kind"] in SELF_COSTS and "object_id" not in pay and item_kind_early != "ability":
            errors.append(f"cost.additional[{i}].payment {pay['kind']} needs the activation's source or an object_id (Core 204.2)")
        if pay["kind"] == "spend_xp" and (not isinstance(pay.get("amount"), int) or isinstance(pay.get("amount"), bool) or pay["amount"] < 1):
            errors.append(f"cost.additional[{i}].payment spend_xp needs a positive amount (Core 730.2)")
        if pay["kind"] == "spend_buff" and (not isinstance(pay.get("object_id"), str) or not pay.get("object_id")):
            errors.append(f"cost.additional[{i}].payment spend_buff names the Unit whose Buff is spent (Core 702.2.b)")
        if pay["kind"] in CHOICE_COSTS and (not isinstance(pay.get("amount"), int) or isinstance(pay.get("amount"), bool) or pay["amount"] < 1 or set(pay) - {"kind", "amount", "decision_ref", "order_ref"}
                                            or any(not isinstance(pay.get(k), str) or not pay.get(k) for k in ("decision_ref", "order_ref") if k in pay)):
            errors.append(f"cost.additional[{i}].payment {pay['kind']} needs a positive amount (and optional decision_ref / order_ref)")
    for i, inc in enumerate(cost.get("increases", []) or []):
        errors.extend(f"cost.increases[{i}] {e}" for e in _provenance_errors(inc))
        if not isinstance(inc, dict) or not {"id", "component", "amount"} <= set(inc) or set(inc) - {"id", "component", "amount", "source", "provenance", "condition", "per_each"} or not isinstance(inc["amount"], int) or inc["amount"] < 1 or not (inc["component"] == "energy" or str(inc["component"]).startswith("power:")):
            errors.append(f"cost.increases[{i}] is invalid")
    ids: set[str] = set()
    for i, disc in enumerate(cost.get("discounts", []) or []):
        errors.extend(f"cost.discounts[{i}] {e}" for e in _provenance_errors(disc))
        if not isinstance(disc, dict) or not {"id", "applies_to", "amount"} <= set(disc) or set(disc) - {"id", "applies_to", "amount", "minimum", "resource", "source", "provenance", "condition", "per_each"} or not isinstance(disc["amount"], int) or disc["amount"] < 1:
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


def _provenance_errors(mod: Any) -> list[str]:
    """ADR-0011 §4: a cost modification is typed input; its provenance says
    who evaluated it. A condition or per-each source is carried only so the
    engine can refuse it by name (P4)."""
    if not isinstance(mod, dict) or "provenance" not in mod:
        return []
    prov = mod["provenance"]
    if not isinstance(prov, dict) or set(prov) - {"evaluated_by", "source"} or prov.get("evaluated_by") not in {"declaration", "p4_condition_layer"} or ("source" in prov and (not isinstance(prov["source"], str) or not prov["source"])):
        return ["provenance must be {evaluated_by: declaration | p4_condition_layer, source?}"]
    return []


def unsupported_modification_sources(cost: dict[str, Any]) -> list[str]:
    """The ids of modifications whose source the engine would have to evaluate (P4)."""
    return [m["id"] for key in ("increases", "discounts") for m in (cost.get(key, []) or []) if isinstance(m, dict) and ("condition" in m or "per_each" in m)]


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
        if not isinstance(entry, dict) or entry.get("card", entry.get("source_object")) != value["cost_receipt"].get("card") if not receipt_errors else False:
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
        requested = pay.get("amount") if pay["kind"] in {"energy", "power", "power_any"} else {k: v for k, v in pay.items() if k != "kind"}
        components.append(component(add["cost_id"], pay["kind"], add["mandatory"], intent, requested,
                                    (["Core 356.2.a"] if add["mandatory"] else ["Core 356.2.b", "Core 356.4.f.1"]) + (["Core 820.1.a", "Core 820.1.c"] if add.get("repeat") else []),
                                    domain=pay.get("domain"), object_id=pay.get("object_id"), **({"repeat": True} if add.get("repeat") else {})))
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
            if comp["kind"] in {"energy", "power", "power_any"} and chosen(comp) and comp["final"]:
                comp["reductions"].append({"discount_id": None, "applies_to": "any_and_all", "amount": comp["final"], "minimum": None, "rule_locators": ["Core 356.5.a"]})
                comp["final"] = 0
        if aggregate:
            aggregate_reductions.append({"discount_id": None, "applies_to": "any_and_all", "amount": aggregate, "minimum": None, "rule_locators": ["Core 356.5.a"]})
        aggregate = 0
    # 356.6 floor.
    aggregate = max(aggregate, 0)
    for comp in components:
        if comp["kind"] in {"energy", "power", "power_any"} and isinstance(comp["final"], int) and comp["final"] < 0:
            comp["final"] = 0

    total = {"energy": aggregate, "power": {}}
    for comp in components:
        if comp["kind"] == "power" and chosen(comp):
            total["power"][comp["domain"]] = total["power"].get(comp["domain"], 0) + comp["final"]
        if comp["kind"] == "power_any" and chosen(comp) and comp["final"]:
            total["power_any"] = total.get("power_any", 0) + comp["final"]
    return {
        "base": base, "after_base_modifications": after_base, "components": components,
        "aggregate": {"energy": {"before_total_discounts": aggregate_before, "reductions": aggregate_reductions, "final": aggregate}},
        "discount_order": order, "order_provenance": f"declaration order, confirmed by {actor}",
        "total": total,
    }


# -------------------------------------------------------------------- payment --

def _allocations(remaining: dict[str, int], amount: int) -> list[dict[str, int]]:
    """Every way to pay `amount` any-domain Power from what is left in the pool."""
    domains = [d for d, n in sorted(remaining.items()) if n > 0]
    out: list[dict[str, int]] = []

    def walk(index: int, left: int, current: dict[str, int]) -> None:
        if len(out) > 64:
            return
        if index == len(domains):
            if left == 0:
                out.append({d: n for d, n in current.items() if n})
            return
        domain = domains[index]
        for take in range(min(left, remaining[domain]) + 1):
            current[domain] = take
            walk(index + 1, left - take, current)
        current.pop(domain, None)

    walk(0, amount, {})
    return out


def _play_use(declaration: dict[str, Any], state: dict[str, Any]) -> str:
    """What this transaction spends resources on, for restricted pools (ADR-0011 §4)."""
    kind = declaration["chain_item"]["object_kind"]
    if kind == "ability":
        source_kind = state["objects"].get(declaration["activation"]["source_object"], {}).get("kind")
        return f"activate_{source_kind}_ability"
    return f"play_{kind}"


def _restricted_entries(resources: dict[str, Any], use: str, kind: str, domain: str | None = None) -> list[dict[str, Any]]:
    return [r for r in resources.get("restricted", []) if r["kind"] == kind and (kind == "energy" or r.get("domain") == domain) and use in r["uses"]]


def _allocate(events: list[dict[str, Any]], components: list[dict[str, Any]]) -> None:
    """Reference each payment event from the components it settles, in order, with exact amounts."""
    for event in events:
        remaining = event["amount"]
        for comp in components:
            if remaining <= 0:
                break
            already = sum(r.get("amount", 0) for r in comp["payment_refs"])
            share = min(comp["final"] - already, remaining)
            if share > 0:
                comp["payment_refs"].append({"event_id": event["event_id"], "amount": share})
                remaining -= share


def _pay_resource(resources: dict[str, Any], kind: str, amount: int, use: str, domain: str | None = None) -> list[dict[str, Any]]:
    """Core 357.1: pay `amount` of a resource — a matching restricted pool first
    (ADR-0011 §4), then the general pool. Unique events with before / after."""
    events: list[dict[str, Any]] = []
    due = amount
    for entry in _restricted_entries(resources, use, kind, domain):
        take = min(entry["amount"], due)
        if take <= 0:
            continue
        before = entry["amount"]
        entry["amount"] -= take
        due -= take
        events.append({"event_id": f"pay:{kind}{':' + domain if domain else ''}:restricted:{entry['restriction_id']}", "kind": f"pay_{kind}", **({"domain": domain} if domain else {}),
                       "amount": take, "before": before, "after": entry["amount"], "restricted_from": entry["restriction_id"], "use": use, "rule_locators": ["Core 357.1", "Core 446.3", "Core 447.2"]})
    resources["restricted"] = [r for r in resources.get("restricted", []) if r["amount"] > 0]
    if not resources["restricted"]:
        del resources["restricted"]
    if due > 0:
        pool = resources["power"] if kind == "power" else resources
        key = domain if kind == "power" else "energy"
        before = pool[key]
        pool[key] -= due
        events.append({"event_id": f"pay:{kind}{':' + domain if domain else ''}", "kind": f"pay_{kind}", **({"domain": domain} if domain else {}),
                       "amount": due, "before": before, "after": pool[key], "rule_locators": ["Core 357.1"]})
    return events


def _pay(working: dict[str, Any], declaration: dict[str, Any], skeleton: dict[str, Any], decisions: dict[str, Any] | None = None, *, use: str | None = None) -> list[dict[str, Any]]:
    """Core 357: Energy and Power in total (357.1), then non-standard costs in
    declared order (357.2). Payment events are unique; components reference
    them with exact allocations. Mutates `working`; the caller discards it on
    any failure (358.5)."""
    from effect_ir import ChoiceRequired, IllegalDecision, IllegalOperation, _recycle_batch, resolve_choice
    actor = declaration["actor"]
    resources = working["players"][actor]["resources"]
    total = skeleton["total"]
    ctx = declaration.get("payment_context") or {}
    use = use or _play_use(declaration, working)
    any_amount = total.get("power_any", 0)
    restricted_energy = sum(r["amount"] for r in _restricted_entries(resources, use, "energy"))
    inapplicable = [r for r in resources.get("restricted", []) if use not in r["uses"]]
    general_specific = {d: max(0, a - sum(r["amount"] for r in _restricted_entries(resources, use, "power", d))) for d, a in total["power"].items()}
    short = (resources["energy"] + restricted_energy < total["energy"] or any(resources["power"].get(d, 0) < a for d, a in general_specific.items())
             or sum(resources["power"].values()) - sum(general_specific.values()) < any_amount)
    nonzero = total["energy"] > 0 or any(a > 0 for a in total["power"].values()) or any_amount > 0
    # Core 429.3 (Codex Round B, point A): whenever a resource cost is paid, the
    # controller may use Add reactions first. The engine never assumes they
    # decline — a human confirms the window is closed before any non-zero
    # payment, whether or not the pool already covers it. A zero cost pays
    # nothing and needs no window.
    if nonzero and ctx.get("add_window_closed") is not True:
        raise PlayError("payment", "add_window_confirmation_required",
                        f"a resource cost is due and the Add window (Core 429.3) has not been confirmed closed for {actor}",
                        decision_ids=[f"add_window:{declaration['play_id']}"], decision_controller=actor, rule_locators=["Core 429.3", "Core 357.1.a"])
    if short:
        note = f"; {sum(r['amount'] for r in inapplicable)} restricted resource(s) cannot be spent on {use} ({sorted({u for r in inapplicable for u in r['uses']})})" if inapplicable else ""
        raise PlayError("payment", "cost_unpayable", f"{actor} cannot pay {total} from {resources} with the Add window closed{note}", rule_locators=["Core 357.1"] + (["Core 446.3"] if inapplicable else []),
                        **({"restricted_not_applicable": [r["restriction_id"] for r in inapplicable]} if inapplicable else {}))

    events: list[dict[str, Any]] = []

    def chosen(c):
        return c["mandatory"] or c["intent"] is True

    if total["energy"]:
        energy_events = _pay_resource(resources, "energy", total["energy"], use)
        events.extend(energy_events)
        _allocate(energy_events, [c for c in skeleton["components"] if c["kind"] == "energy" and chosen(c)])
    for domain, amount in sorted(total["power"].items()):
        if not amount:
            continue
        power_events = _pay_resource(resources, "power", amount, use, domain)
        events.extend(power_events)
        _allocate(power_events, [c for c in skeleton["components"] if c["kind"] == "power" and c.get("domain") == domain and chosen(c)])
    if any_amount:
        # Core 809.1.c.1: any-domain Power. The allocation is the player's; the
        # engine spends nothing in an arbitrary order (ADR-0007 §11). One legal
        # allocation proceeds; several need a resource_allocation decision.
        remaining = {d: n for d, n in resources["power"].items()}
        options = _allocations(remaining, any_amount)
        decision_id = f"power_any:{declaration['play_id']}"
        entry = next((e for e in ed.entries(decisions, kind="resource_allocation") if e["decision_id"] == decision_id), None)
        if entry is not None:
            if entry["controller"] != actor:
                raise PlayError("payment", "decision_controller_mismatch", f"the Power allocation was supplied by {entry['controller']!r}, not the paying player", rule_locators=["Core 809.1.c.1"])
            allocation = entry["value"]
            if sum(allocation.values()) != any_amount or any(n < 0 or remaining.get(d, 0) < n for d, n in allocation.items()):
                raise PlayError("payment", "invalid_resource_allocation", f"allocation {allocation} does not pay {any_amount} from {remaining}", invalid=True)
            allocation = {d: n for d, n in allocation.items() if n}
        elif len(options) == 1:
            allocation = options[0]
        else:
            raise PlayError("payment", "resource_allocation_required", f"{actor} must allocate {any_amount} any-domain Power across {sorted(d for d, n in remaining.items() if n)}",
                            decision_ids=[decision_id], decision_controller=actor, rule_locators=["Core 809.1.c.1", "Core 357.1"])
        for domain, amount in sorted(allocation.items()):
            before = resources["power"][domain]; resources["power"][domain] -= amount
            event_id = f"pay:power_any:{domain}"
            events.append({"event_id": event_id, "kind": "pay_power", "domain": domain, "amount": amount, "before": before, "after": resources["power"][domain],
                           "allocation_of": "power_any", "decided_by": entry["decision_id"] if entry else "sole_legal_allocation", "rule_locators": ["Core 809.1.c.1", "Core 357.1"]})
            remaining_share = amount
            for comp in skeleton["components"]:
                if comp["kind"] == "power_any" and chosen(comp) and remaining_share:
                    already = sum(r.get("amount", 0) for r in comp["payment_refs"])
                    share = min(comp["final"] - already, remaining_share)
                    if share > 0:
                        comp["payment_refs"].append({"event_id": event_id, "amount": share})
                        remaining_share -= share
    for comp in skeleton["components"]:
        if comp["kind"] in {"energy", "power", "power_any"} and chosen(comp):
            comp["paid"] = True

    play_stage = {"allow_play_stage": True}
    for comp in skeleton["components"]:
        if comp["kind"] in {"energy", "power", "power_any"} or not chosen(comp):
            continue
        event_id = f"pay:{comp['cost_id']}"
        if comp["kind"] in CHOICE_COSTS:
            # ADR-0011 §4: Discard N (422.1.a, private) / Recycle N from the
            # trash (416.3, public) — the payer's card_selection at play stage;
            # the whole amount must be payable (423.1.b, 416.3).
            amount = comp["requested"]["amount"]
            zone = "hand" if comp["kind"] == "discard" else "trash"
            # Core 354: the card being played moved to the Chain before costs
            # were chosen, so it can never pay its own cost from that zone.
            pool = [c for c in working["players"][actor]["zones"][zone] if c != declaration["card"]]
            if len(pool) < amount:
                raise PlayError("payment", "cost_unpayable", f"cost {comp['cost_id']!r} needs {amount} card(s) in {actor}'s {zone}; there are {len(pool)} (the action must be completable to pay it)",
                                rule_locators=(["Core 423.1.b"] if zone == "hand" else ["Core 416.3"]) + ["Core 354"])
            spec = {"selection_kind": "single" if amount == 1 else "unordered_set", **({"count": {"exactly": amount}} if amount != 1 else {}), "from": zone, "by": actor,
                    "visibility": "private_to_chooser" if zone == "hand" else "public", "identity_binding": True}
            ref = comp["requested"].get("decision_ref") or f"cost:{declaration['play_id']}:{comp['cost_id']}"
            try:
                picked, meta = resolve_choice(working, spec, decision_ref=ref, decisions=decisions, controller=actor, session=play_stage, candidates=pool)
                if not meta["forced"]:
                    supplied = ed.decision_entry(decisions, ref)
                    if supplied is not None and supplied["stage"] != "play_declaration":
                        raise PlayError("payment", "decision_stage_mismatch", f"cost choice {ref!r} was supplied for stage {supplied['stage']!r}, not play_declaration", invalid=True)
                if comp["kind"] == "discard":
                    identities = {}
                    for object_id in picked:
                        working["players"][actor]["zones"]["hand"].remove(object_id)
                        owner = working["objects"][object_id]["owner"]
                        working["players"][owner]["zones"]["trash"].append(object_id)
                        identities[object_id] = _bump_identity(working, object_id)
                    events.append({"event_id": event_id, "kind": "pay_discard", "cost_id": comp["cost_id"], "objects": list(picked), "identities_after": identities,
                                   "decided_by": meta.get("decision_id") or "forced", "rule_locators": ["Core 357.2", "Core 422.1", "Core 422.1.a", "Core 423.1.b", "Core 124"]})
                else:
                    order_ref = comp["requested"].get("order_ref") or f"{ref}:order"
                    working_after, sub = _recycle_batch(working, picked, actor, decisions, order_ref, f"cost:{comp['cost_id']}", choice_session=play_stage)
                    if working_after is not working:  # the batch mutates in place; a copy would strand the payment
                        working.clear(); working.update(working_after)
                    events.append({"event_id": event_id, "kind": "pay_recycle_trash", "cost_id": comp["cost_id"], "objects": list(picked), "identities_after": sub["identities_after"],
                                   "order_decision": sub["order_decision"], "decided_by": meta.get("decision_id") or "forced", "rule_locators": ["Core 357.2", "Core 416.3", "Core 416.5", "Core 124"]})
            except ChoiceRequired as exc:
                raise PlayError("payment", exc.reason_code, f"cost {comp['cost_id']!r}: {exc}", decision_ids=exc.decision_ids, decision_controller=actor, choice=exc.summary,
                                rule_locators=["Core 357.2", "Core 422.1.a"] if zone == "hand" else ["Core 357.2", "Core 416.3"])
            except IllegalDecision as exc:
                raise PlayError("payment", "decision_controller_mismatch", str(exc), rule_locators=["Core 422.1.a"])
            except IllegalOperation as exc:
                raise PlayError("payment", "cost_choice_illegal", f"cost {comp['cost_id']!r}: {exc}", rule_locators=["Core 422.1.a"] if zone == "hand" else ["Core 416.3"])
            except ValueError as exc:
                raise PlayError("payment", "invalid_cost_choice", f"cost {comp['cost_id']!r}: {exc}", invalid=True)
            comp["payment_refs"].append({"event_id": event_id})
            comp["paid"] = True
            continue
        if comp["kind"] in SPEND_COSTS:
            # ADR-0013 §5: XP, a Buff counter, or the source's own Empowered
            # state. Each must be there to be spent (204.3).
            event_id = f"pay:{comp['cost_id']}"
            if comp["kind"] == "spend_xp":
                amount = comp["requested"]["amount"]
                before = int(working["players"][actor].get("xp", 0))
                if before < amount:
                    raise PlayError("payment", "cost_unpayable", f"{actor} has {before} XP and the cost spends {amount} (730.2)", rule_locators=["Core 730.2", "Core 204.3"])
                working["players"][actor]["xp"] = before - amount
                events.append({"event_id": event_id, "kind": "pay_spend_xp", "cost_id": comp["cost_id"], "amount": amount,
                               "before": before, "after": before - amount, "rule_locators": ["Core 357.2", "Core 730.2"]})
            elif comp["kind"] == "spend_buff":
                object_id = comp["object_id"]
                unit = working["objects"].get(object_id, {})
                if not unit.get("buffed"):
                    raise PlayError("payment", "cost_unpayable", f"{object_id!r} has no Buff counter to spend (702.2.b)", rule_locators=["Core 702.2.b", "Core 204.3"])
                if unit.get("controller") != actor:
                    raise PlayError("payment", "cost_unpayable", f"{actor} does not control {object_id!r}; a spender must control the object the counter is on (702.2)", rule_locators=["Core 702.2"])
                del working["objects"][object_id]["buffed"]
                events.append({"event_id": event_id, "kind": "pay_spend_buff", "cost_id": comp["cost_id"], "object_id": object_id,
                               "rule_locators": ["Core 357.2", "Core 702.2.b"]})
            else:
                object_id = comp["object_id"]
                if not working["objects"].get(object_id, {}).get("empowered"):
                    raise PlayError("payment", "cost_unpayable", f"{object_id!r} is not Empowered, so it cannot be Disempowered as a cost (443.2.a)", rule_locators=["Core 443.2.a", "Core 204.3"])
                del working["objects"][object_id]["empowered"]
                events.append({"event_id": event_id, "kind": "pay_disempower_self", "cost_id": comp["cost_id"], "object_id": object_id,
                               "rule_locators": ["Core 357.2", "Core 443.1.b"]})
            comp["payment_refs"].append({"event_id": event_id})
            comp["paid"] = True
            continue
        op = SUPPORTED_NON_STANDARD[comp["kind"]]
        object_id = comp["object_id"]
        selector = {"object_id": object_id, "chosen_zone_class": "board", "controller_relation": "friendly",
                    "bound_identity": object_identity(working, object_id) or f"{object_id}@0"}
        program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "program_id": f"cost:{declaration['play_id']}:{comp['cost_id']}", "controller": actor,
                   "effects": [{"op": op, "effect_id": comp["cost_id"], "object_id": object_id, "target": selector}]}
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
        events.append({"event_id": event_id, "kind": f"pay_{comp['kind']}", "cost_id": comp["cost_id"], "object_id": object_id, "outcome": outcome,
                       "trace": copy.deepcopy(result["trace"]), "rule_locators": ["Core 357.2"] + (["Core 357.2.a"] if outcome != "applied" else []) + (["Core 204.2"] if comp["kind"] in SELF_COSTS else [])})
        comp["payment_refs"].append({"event_id": event_id})
        comp["paid"] = True
        if outcome != "applied":
            comp["rule_locators"] = list(dict.fromkeys(comp["rule_locators"] + ["Core 357.2.a"]))
    return events


# ------------------------------------------------------------------- choices --

def _play_mode(actor: str, program: dict[str, Any], decisions: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """ADR-0011 §2 / Core 402.2: a spell's mode is chosen while playing, by
    stable option id, and only the chosen option's targets are checked."""
    modal = program.get("modal")
    if not modal:
        return list(program.get("effects", [])), None
    if modal["timing"] != "play_declaration":
        raise PlayError("choices", "mode_timing_mismatch", f"program {program.get('program_id')!r} chooses its mode at {modal['timing']}; a played card chooses it while playing (Core 402.2)", invalid=True)
    ref = modal["decision_ref"]
    entry = ed.mode_selection(decisions, ref)
    if entry is None:
        raise PlayError("choices", "mode_selection_required", f"mode {ref!r} is chosen while playing (Core 402.2) and was not supplied", decision_ids=[ref], decision_controller=actor,
                        rule_locators=["Core 402.2"], mode_options=[o["option_id"] for o in modal["options"]])
    if entry["stage"] != "play_declaration":
        raise PlayError("choices", "decision_stage_mismatch", f"mode {ref!r} was supplied for stage {entry['stage']!r}, not play_declaration", invalid=True)
    if entry["controller"] != actor:
        raise PlayError("choices", "decision_controller_mismatch", f"mode {ref!r} was chosen by {entry['controller']!r}, not the card's controller", rule_locators=["Core 402.2"])
    option = next((o for o in modal["options"] if o["option_id"] == entry["value"]), None)
    if option is None:
        raise PlayError("choices", "unknown_mode_option", f"mode {ref!r} names {entry['value']!r}; the options are {[o['option_id'] for o in modal['options']]}", invalid=True)
    return list(option["effects"]), {"decision_id": ref, "option_id": option["option_id"]}


def _check_play_targets(effect_state: dict[str, Any], actor: str, program: dict[str, Any], decisions: dict[str, Any] | None, effects: list[dict[str, Any]] | None = None) -> list[str]:
    """Core 355.5 / 355.9: every selector that targets is chosen and legal at
    play — concrete selectors and decision-supplied ones alike. A supplied
    decision must be for this stage, owned by the actor, and bound to the
    objects' current identities."""
    chosen_objects: list[str] = []  # every time an object is chosen as a target (Deflect counts each, 809.1.c)
    for index, effect in enumerate(program.get("effects", []) if effects is None else effects):
        candidates: list[tuple[dict[str, Any], str | None]] = []
        if isinstance(effect.get("target"), dict):
            candidates.append((effect["target"], effect["target"].get("decision_ref")))
        if isinstance(effect.get("targets"), dict):
            for sel in effect["targets"].get("selectors", []) or []:
                candidates.append((sel, None))
            if "decision_ref" in effect["targets"]:
                candidates.append((dict(effect["targets"].get("restrictions", {}), chosen_zone_class=effect["targets"].get("restrictions", {}).get("chosen_zone_class", "board")), effect["targets"]["decision_ref"]))
        if isinstance(effect.get("units"), list):
            # ADR-0008 s7: a composite instruction's Units are chosen at play like any target (355.5)
            for sel in effect["units"]:
                if isinstance(sel, dict):
                    candidates.append((sel, sel.get("decision_ref")))
        for template, ref in candidates:
            if ref is None:
                if derive_targeted(template):
                    ok, reason = evaluate_target(effect_state, template, actor)
                    if not ok:
                        raise PlayError("choices", "target_illegal_at_play", f"effects[{index}] target {template.get('object_id')!r}: {reason}", rule_locators=["Core 355.9"])
                    if template.get("kind") != "battlefield" and template.get("object_id") in effect_state["objects"]:
                        chosen_objects.append(template["object_id"])
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
                current_identity = entity_identity(effect_state, object_id)
                if object_id in identities and current_identity is not None and identities[object_id] != current_identity:
                    raise PlayError("choices", "selection_identity_mismatch", f"target selection {ref!r} was bound to {identities[object_id]!r}; the entity is now {entity_identity(effect_state, object_id)!r}", invalid=True)
                selector = {k: v for k, v in template.items() if k not in {"decision_ref", "object_id"}}
                selector["object_id"] = object_id
                selector.setdefault("chosen_zone_class", "board" if template.get("kind") == "battlefield" else (zone_class(find_location(effect_state, object_id)) or "non_board"))
                if derive_targeted(selector):
                    ok, reason = evaluate_target(effect_state, selector, actor)
                    if not ok:
                        raise PlayError("choices", "target_illegal_at_play", f"effects[{index}] target {object_id!r}: {reason}", rule_locators=["Core 355.9"])
                    if selector.get("kind") != "battlefield" and object_id in effect_state["objects"]:
                        chosen_objects.append(object_id)
    return chosen_objects


def _same_team(state: dict[str, Any], left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    if left == right:
        return True
    lt, rt = state["players"].get(left, {}).get("team_id"), state["players"].get(right, {}).get("team_id")
    return lt is not None and lt == rt


def deflect_costs(state: dict[str, Any], actor: str, chosen_objects: list[str]) -> list[dict[str, Any]]:
    """Core 809.1.c–d: each time an opposing-team spell or ability chooses an
    object with Deflect, it costs [Deflect Value] more Power of any domain as
    a mandatory additional cost (356.2.a.2); values are summed (809.2).
    Objects merely affected by criteria are never chosen and add nothing."""
    costs: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for object_id in chosen_objects:
        obj = state["objects"].get(object_id, {})
        if "deflect" not in (obj.get("keywords") or []) or _same_team(state, actor, obj.get("controller")):
            continue
        value = obj.get("deflect_value", 1)
        seen[object_id] = seen.get(object_id, 0) + 1
        costs.append({"cost_id": f"deflect:{object_id}:{seen[object_id]}", "mandatory": True, "payment": {"kind": "power_any", "amount": value}, "source": object_id})
    return costs


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
    if isinstance(timing_state, dict) and is_terminal(timing_state):  # ADR-0010 §3
        return {**base, "valid": True, "committed": False, "unsupported": False, "rolled_back": False, "stage": "legality",
                "reason_code": "game_over", "reason": "the game ended; the snapshot is frozen (196)", "errors": [], "trace": [], "rule_locators": ["Core 196"]}

    trace: list[dict[str, Any]] = []
    locators: list[str] = []
    try:
        actor, card = declaration["actor"], declaration["card"]
        item_id = declaration["chain_item"]["id"]
        if actor not in effect_state["players"]:
            raise PlayError("declaration", "unknown_actor", f"{actor!r} is not a player in the effect state", invalid=True)
        if item_id in (effect_state.get("chain_items") or {}) or any(i.get("id") == item_id for i in timing_state.get("chain", {}).get("items", [])):
            raise PlayError("declaration", "chain_item_id_collision", f"chain item {item_id!r} already exists", invalid=True)
        source_kind = (declaration.get("source") or {}).get("kind", "hand")
        is_ability = declaration["chain_item"]["object_kind"] == "ability"
        if is_ability:
            # ADR-0011 §4 / Core 377: the source is a permanent the actor
            # controls on the Board; a Legend's ability is a P3 source.
            source = effect_state["objects"].get(card)
            if source is None:
                raise PlayError("declaration", "unknown_activation_source", f"activation source {card!r} is not in the state", invalid=True)
            where = find_location(effect_state, card)
            on_board = where is not None and (where[0] == "battlefield" or (where[0] == "player" and where[2] == "base"))
            if not on_board:
                raise PlayError("choices", "activation_source_not_on_board", f"{card!r} is at {where}; activated abilities are activated from the Board (Core 377.4)", rule_locators=["Core 377.4", "Core 377"])
            if source.get("controller") != actor:
                raise PlayError("choices", "activation_source_not_controlled", f"{card!r} is controlled by {source.get('controller')!r}, not {actor}", rule_locators=["Core 377.3", "Core 377.4"])
            # ADR-0013 §3 / Core 377.2.b: the activation's own condition is a
            # typed condition.v1 the engine evaluates against this state.
            for index, condition in enumerate(declaration.get("activation_conditions") or []):
                problems = validate_condition(condition, f"activation_conditions[{index}]")
                if problems:
                    raise PlayError("choices", "invalid_activation_condition", "; ".join(problems), invalid=True)
                try:
                    holds = evaluate_condition(effect_state, condition, controller=actor, object_id=card)
                except ConditionUnsupported as exc:
                    raise PlayError("choices", "activation_condition_unsupported", str(exc), unsupported=True, rule_locators=["Core 377.2.b"])
                if not holds:
                    raise PlayError("choices", "activation_condition_not_met",
                                    f"{card!r} may be activated only while {condition['kind']} holds (377.2.b)", rule_locators=["Core 377.2.b", "Core 404"])
        else:
            zone_of = find_location(effect_state, card)
            if source_kind == "hand" and zone_of != ("player", actor, "hand"):
                raise PlayError("choices", "card_not_in_hand", f"{card!r} is not in {actor}'s hand", rule_locators=["Core 354"])
            if source_kind == "facedown":
                # ADR-0012 §3 / Core 811: playable from the turn after it was
                # hidden, at the Battlefield it was hidden at, ignoring its base
                # cost — the declaration states the override, this checks the
                # facts the state carries.
                from hidden import hidden_card
                battlefield_id = declaration["source"]["battlefield"]
                if battlefield_id not in effect_state["battlefields"]:
                    raise PlayError("declaration", "unknown_battlefield", f"the facedown source names battlefield {battlefield_id!r}, which is not in the state", invalid=True)
                entry_facedown = hidden_card(effect_state, battlefield_id, card)
                if entry_facedown is None or zone_of != ("facedown", battlefield_id, actor):
                    raise PlayError("choices", "card_not_in_source", f"{card!r} is not hidden at {battlefield_id!r} for {actor}", rule_locators=["Core 811.1"])
                if entry_facedown["hidden_on_turn"] == effect_state.get("turn_id", "turn-0"):
                    raise PlayError("choices", "hidden_same_turn", f"{card!r} was hidden this turn; a hidden card may be played beginning on the next turn (811.1)", rule_locators=["Core 811.1"])
            elif source_kind != "hand":
                # ADR-0012 §1: the declared source must hold the card, and a
                # source other than the ordinary ones needs a granted permission.
                if zone_of != ("player", actor, source_kind):
                    raise PlayError("choices", "card_not_in_source", f"{card!r} is not in {actor}'s {source_kind}; it is at {zone_of}", rule_locators=["Core 354", "Core 108.3.e"])
                if source_kind in PERMISSION_REQUIRED_SOURCES and not (declaration.get("source_permission") or {}).get("granted_by"):
                    raise PlayError("choices", "play_source_not_permitted", f"playing from {source_kind} needs a permission an effect granted (Core 349)", rule_locators=["Core 349"])
            if effect_state["objects"][card]["kind"] != declaration["chain_item"]["object_kind"]:
                raise PlayError("choices", "object_kind_mismatch", f"{card!r} is a {effect_state['objects'][card]['kind']}; the chain item says {declaration['chain_item']['object_kind']}", invalid=True)

        # --- 355.2: the Unit's location is chosen now. Own Base, a Battlefield
        # the controller controls, or — with the compiled permission — an open
        # Battlefield (170.11.c). A missing Battlefield is malformed input; an
        # existing one the rules refuse is illegal (ADR-0007 §1, §3).
        location = declaration.get("entry_location")
        ambush_record = None
        if source_kind == "facedown" and declaration["chain_item"]["object_kind"] in {"unit", "gear"}:
            # Core 811.4: a hidden permanent is played to that Battlefield —
            # Gear included, which overrides the Base-only restriction.
            expected = declaration["source"]["battlefield"]
            if location is None or location.get("kind") != "battlefield" or location.get("battlefield") != expected:
                raise PlayError("choices", "hidden_entry_location", f"a permanent played from Hidden enters {expected!r}, the Battlefield it was hidden at (811.4)", rule_locators=["Core 811.4"])
        if location is not None and location["kind"] == "battlefield":
            battlefield = effect_state["battlefields"].get(location["battlefield"])
            if battlefield is None:
                raise PlayError("choices", "unknown_battlefield", f"entry_location names battlefield {location['battlefield']!r}, which is not in the state", invalid=True)
            controlled = battlefield.get("controller") == actor
            is_open = battlefield.get("controller") is None and not battlefield.get("objects")
            permissions = effect_state["objects"][card].get("play_permissions", [])
            permitted = "open_battlefield" in permissions
            # ADR-0012 §2 / Core 822.1: Ambush opens a Battlefield where the
            # actor already has Units, and grants Reaction while playing there.
            friendly_units = [o for o in battlefield.get("objects", [])
                              if effect_state["objects"][o]["kind"] == "unit" and effect_state["objects"][o].get("controller") == actor]
            ambush = "ambush" in permissions and bool(friendly_units)
            if declaration.get("timing_source") == "ambush" and not ambush:
                raise PlayError("choices", "ambush_location_invalid",
                                f"{card!r} claims Ambush timing at {location['battlefield']!r}, where {actor} has no Units (822.1, 822.3)",
                                rule_locators=["Core 822.1", "Core 822.3"])
            if not (controlled or (is_open and permitted) or ambush):
                raise PlayError("choices", "entry_location_illegal",
                                f"{card!r} may enter its controller's Base or a Battlefield {actor} controls (355.2.a); {location['battlefield']!r} is "
                                + ("open but the card has no permission to enter open Battlefields (355.2.b)" if is_open else "neither controlled nor open"),
                                rule_locators=["Core 355.2.a", "Core 355.2.b", "Core 170.11.c"])
            ambush_record = {"battlefield": location["battlefield"], "friendly_units": friendly_units} if ambush else None
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
        chosen_objects: list[str] = []
        mode = None
        hidden_battlefield = declaration["source"]["battlefield"] if source_kind == "facedown" else None
        hidden_targeting = declaration.get("hidden_targeting", "restricted")
        # ADR-0011 §4 / Core 820: each paid Repeat is one more execution with its
        # own choices, made now like the first (820.2).
        repeat_paid = [add["cost_id"] for add in declaration["cost"].get("additional", []) or [] if add.get("repeat") and intents.get(add["cost_id"])]
        repeat_record = None
        if effect_program is not None:
            effects, mode = _play_mode(actor, effect_program, engine_decisions)
            chosen_objects = _check_play_targets(effect_state, actor, effect_program, engine_decisions, effects)
            repeat_modes = [mode] if mode else []
            for k, _ in enumerate(repeat_paid, start=1):
                program_k = effect_program
                if effect_program.get("modal"):
                    program_k = {**effect_program, "modal": {**effect_program["modal"], "decision_ref": effect_program["modal"]["decision_ref"] + f"#{k}"}}
                effects_k, mode_k = _play_mode(actor, program_k, engine_decisions)
                chosen_objects += _check_play_targets(effect_state, actor, effect_program, engine_decisions, suffix_decision_refs(effects_k, f"#{k}"))
                if mode_k:
                    repeat_modes.append(mode_k)
            if repeat_paid:
                repeat_record = {"executions": 1 + len(repeat_paid), **({"modes": repeat_modes} if effect_program.get("modal") else {})}
            if hidden_battlefield is not None and hidden_targeting == "restricted":
                # Core 811.4: the choices of a card played from Hidden come from
                # that Battlefield, unless the clause's own restriction makes
                # that impossible — which the compiled clause states.
                outside = [o for o in chosen_objects if find_location(effect_state, o) != ("battlefield", hidden_battlefield, None)]
                if outside:
                    raise PlayError("choices", "hidden_target_outside_battlefield",
                                    f"a card played from Hidden chooses at {hidden_battlefield!r}; {outside} are elsewhere (811.4)",
                                    rule_locators=["Core 811.4", "Core 811.4.a"])
        elif repeat_paid:
            repeat_record = {"executions": 1 + len(repeat_paid)}
        # ADR-0007 §11: Deflect is scanned once targets are fixed and before the
        # cost is determined; it lands on the declared cost as mandatory
        # any-domain Power.
        deflect = deflect_costs(effect_state, actor, chosen_objects)
        cost = copy.deepcopy(declaration["cost"])
        override = declaration.get("cost_override")
        if override is not None:
            # ADR-0012 §1: an override replaces the base cost before 356 runs
            # (811: "ignoring its base cost"); the receipt shows it as a base
            # modification, so the arithmetic stays one implementation.
            modification = {"kind": "ignore_all", "source": override["source"]} if override["kind"] == "ignore_base_cost" else {"kind": "for_cost", "cost": copy.deepcopy(override["cost"]), "source": override["source"]}
            cost["base_modifications"] = [modification] + list(cost.get("base_modifications", []) or [])
        if deflect:
            cost["additional"] = list(cost.get("additional", []) or []) + deflect
        trace.append({"stage": "choices", "outcome": "applied", "optional_cost_intents": intents, "chosen_objects": chosen_objects, "deflect_costs": deflect, **({"mode_selection": mode} if mode else {}), **({"repeat": repeat_record} if repeat_record else {}),
                      "source": source_kind, **({"hidden": {"battlefield": hidden_battlefield, "targeting": hidden_targeting}} if hidden_battlefield else {}), **({"source_permission": dict(declaration["source_permission"])} if declaration.get("source_permission") else {}),
                      **({"cost_override": dict(override)} if override else {}), **({"ambush": ambush_record} if ambush_record else {}),
                      "rule_locators": RULES["choices"] + (["Core 402.2"] if mode else []) + (["Core 809.1.c", "Core 809.1.d", "Core 809.2"] if deflect else [])})
        locators += RULES["choices"] + (["Core 809.1.c", "Core 809.1.d"] if deflect else [])

        # --- 356: total cost.
        for add in cost.get("additional", []) or []:
            kind = add["payment"]["kind"]
            if kind not in {"energy", "power", "power_any"} and kind not in SUPPORTED_NON_STANDARD and kind not in CHOICE_COSTS and kind not in SPEND_COSTS and (add["mandatory"] or intents.get(add["cost_id"])):
                note = " (XP / Buff / Empower costs wait for the P4 catalogue: xp_buff_costs)" if kind in DEFERRED_COST_KINDS else ""
                raise PlayError("cost_determination", "unsupported_cost_kind", f"cost {add['cost_id']!r} uses {kind!r}, which the engine does not type{note}", unsupported=True, rule_locators=["Core 356.7"])
            if kind == "disempower_self" and "object_id" not in add["payment"]:
                add["payment"] = {**add["payment"], "object_id": declaration["activation"]["source_object"] if declaration.get("activation") else declaration["card"]}
            if kind in SELF_COSTS and "object_id" not in add["payment"]:
                add["payment"] = {**add["payment"], "object_id": declaration["activation"]["source_object"]}
        # ADR-0013 §6: P4 evaluates a modification's condition and per-each
        # count here; P2 consumes the evaluated result and never a source.
        evaluated: list[dict[str, Any]] = []
        for key in ("increases", "discounts"):
            kept = []
            for modification in cost.get(key, []) or []:
                if "condition" not in modification and "per_each" not in modification:
                    kept.append(modification)
                    continue
                try:
                    outcome = evaluate_cost_modification(effect_state, modification, actor)
                except ConditionUnsupported as exc:
                    raise PlayError("cost_determination", "cost_modification_sources_unsupported", str(exc), unsupported=True, rule_locators=["Core 356.3", "Core 356.4"])
                except ValueError as exc:
                    raise PlayError("cost_determination", "invalid_cost_modification", str(exc), invalid=True)
                evaluated.append({**outcome, "applies_to": key})
                if outcome["applies"] and outcome["amount"] > 0:
                    kept.append({k: v for k, v in modification.items() if k not in {"condition", "per_each"}}
                                | {"amount": outcome["amount"], "provenance": {"evaluated_by": "p4_condition_layer", **({"source": modification.get("source")} if modification.get("source") else {})}})
            if kept or (cost.get(key) is not None):
                cost[key] = kept
        if evaluated:
            trace.append({"stage": "cost_determination", "outcome": "applied", "evaluated_cost_modifications": evaluated,
                          "rule_locators": ["Core 356.3", "Core 356.4"]})
        skeleton = determine_total_cost(cost, intents, actor=actor)
        trace.append({"stage": "cost_determination", "outcome": "applied", "total": copy.deepcopy(skeleton["total"]), "rule_locators": RULES["cost"]})
        locators += RULES["cost"]

        # --- 357: payment on a working copy.
        working = copy.deepcopy(effect_state)
        before_pay = hash_value(working)
        pay_events = _pay(working, declaration, skeleton, engine_decisions)
        trace.append({"stage": "payment", "outcome": "applied", "event_ids": [e["event_id"] for e in pay_events], "before_state_hash": before_pay, "after_state_hash": hash_value(working), "rule_locators": RULES["payment"]})
        locators += RULES["payment"]

        # The card leaves the hand for the shared chain: a zone change, so a
        # new object (Core 124). The chain entry binds card, controller, and
        # program to the timing item.
        if is_ability:
            entry = {"source_object": card, "ability_id": declaration["activation"]["ability_id"], "controller": actor}
        elif source_kind == "facedown":
            zone = working["battlefields"][declaration["source"]["battlefield"]]["facedown"]
            zone["cards"] = [c for c in zone["cards"] if c["object_id"] != card]
            entry = {"card": card, "controller": actor}
        else:
            working["players"][actor]["zones"][source_kind].remove(card)
            entry = {"card": card, "controller": actor}
        if declaration.get("effect_program_id"):
            entry["effect_program_id"] = declaration["effect_program_id"]
        if declaration.get("entry_location") is not None:
            entry["entry_location"] = dict(declaration["entry_location"])
        if mode is not None:
            entry["mode_selection"] = dict(mode)  # ADR-0011 §2: the mode rides with the chain entry to resolution
        if repeat_record is not None:
            entry["repeat"] = copy.deepcopy(repeat_record)  # ADR-0011 §4: paid Repeats ride to resolution
        working.setdefault("chain_items", {})[item_id] = entry
        identity_after = _bump_identity(working, card) if not is_ability else object_identity(working, card)
        state_errors = validate_state(working)
        if state_errors:
            raise PlayError("payment", "invalid_working_state", "; ".join(state_errors), invalid=True)

        # --- 358: legality and chain insertion through the timing kernel.
        item = {**declaration["chain_item"], "ability_kind": declaration["chain_item"].get("ability_kind")}
        if declaration.get("effect_program_id"):
            item["effect_program_id"] = declaration["effect_program_id"]
        insertion = add_pending_item(timing_state, {"actor": actor, "kind": "activate_ability" if is_ability else "play_card", "item": item,
                                                    "initiated_by": ("add_ability" if item.get("ability_kind") == "add" else "activated_ability") if is_ability else "played_card"})
        if insertion.get("valid") is False:
            raise PlayError("legality", "invalid_timing_state", "; ".join(insertion.get("errors", [])), invalid=True)
        if insertion.get("applied") is not True:
            raise PlayError("legality", insertion.get("reason_code") or "play_illegal", f"the timing kernel refused the play: {insertion.get('reason_code')}", legality=insertion.get("legality"), rule_locators=RULES["legality"])
        trace.append({"stage": "legality", "outcome": "applied", "chain_item_id": item_id, "card_identity_after": identity_after, **({"activation": dict(declaration["activation"])} if is_ability else {}),
                      "rule_locators": RULES["legality"] + (["Core 377", "Core 402"] if is_ability else RULES["identity"])})
        locators += RULES["legality"] + (["Core 377", "Core 402"] if is_ability else RULES["identity"])
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
