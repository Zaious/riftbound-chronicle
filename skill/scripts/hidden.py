#!/usr/bin/env python3
"""
Hide: the Discretionary Action behind the Hidden keyword (ADR-0012 §3, Core
811, 107.3.b, 108.2.b).

Hiding is not playing (811.2): it opens no chain, it is taken on the actor's
own turn in an Open State, and it puts one card from their hand or Champion
Zone facedown into the Facedown Zone of a Battlefield they control. Each
Battlefield has exactly one such zone with a capacity (107.3.b); the zone
itself is public, the cards in it are private to the player who hid them
(108.2.b, 128.4). The card becomes a new object (124), and from the next turn
it may be played from there with Reaction, ignoring its base cost — that path
is the ordinary play transaction with a `facedown` source.

The cost is paid through the same receipt as a play, but its use is `hide`,
so a resource restricted to playing spells or units cannot pay for it.

Failure vocabulary matches the other procedures: `invalid_input` for a
malformed declaration or state, `decision_required` while a cost decision is
outstanding, `illegal` when the rules refuse the action, `unsupported` for a
cost mechanic this slice does not type.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from cost_receipt import RECEIPT_VERSION  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, DEFAULT_TURN_ID, _bump_identity, find_location, hash_value, validate_state  # noqa: E402
from play_transaction import PlayError, _pay, determine_total_cost  # noqa: E402
from rules_core import is_terminal, state_hash, validate_state as validate_timing_state, validate_timing  # noqa: E402

HIDE_VERSION = "riftbound-hide-result.v1"
HIDE_DECLARATION_VERSION = "riftbound-hide-declaration.v1"
HIDE_SOURCES = {"hand", "champion_zone"}
RULES = ["Core 811", "Core 811.2", "Core 107.3.b", "Core 108.2.b", "Core 124"]


def facedown_zone(effect_state: dict[str, Any], battlefield_id: str) -> dict[str, Any]:
    """The Battlefield's Facedown Zone with its defaults filled in (107.3.b)."""
    zone = (effect_state["battlefields"].get(battlefield_id) or {}).get("facedown") or {}
    return {"capacity": zone.get("capacity", 1), "cards": list(zone.get("cards", []))}


def hidden_card(effect_state: dict[str, Any], battlefield_id: str, object_id: str) -> dict[str, Any] | None:
    return next((c for c in facedown_zone(effect_state, battlefield_id)["cards"] if c["object_id"] == object_id), None)


def validate_declaration(value: Any, effect_state: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return ["declaration must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != HIDE_DECLARATION_VERSION:
        errors.append(f"declaration.schema_version must be {HIDE_DECLARATION_VERSION}")
    if set(value) - {"schema_version", "ruleset", "hide_id", "actor", "card", "source", "battlefield", "cost", "payment_context"}:
        errors.append("declaration carries unsupported fields")
    if value.get("ruleset") != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("declaration.ruleset must match the engine ruleset")
    for key in ("hide_id", "actor", "card", "battlefield"):
        if not isinstance(value.get(key), str) or not value.get(key):
            errors.append(f"declaration.{key} must be a non-empty string")
    if value.get("source", "hand") not in HIDE_SOURCES:
        errors.append(f"declaration.source must be one of {sorted(HIDE_SOURCES)} (Core 811.1)")
    if isinstance(value.get("actor"), str) and value["actor"] not in effect_state["players"]:
        errors.append("declaration.actor is not a player")
    if isinstance(value.get("battlefield"), str) and value["battlefield"] not in effect_state["battlefields"]:
        errors.append("declaration.battlefield is not a battlefield in this state")
    cost = value.get("cost")
    if not isinstance(cost, dict) or "base" not in cost or set(cost) - {"base", "base_modifications", "additional", "increases", "discounts", "total_modifications"}:
        errors.append("declaration.cost must carry base and only the typed modification lists")
    ctx = value.get("payment_context")
    if ctx is not None and (not isinstance(ctx, dict) or set(ctx) != {"add_window_closed", "confirmed_by"} or not isinstance(ctx["add_window_closed"], bool) or not isinstance(ctx["confirmed_by"], str) or not ctx["confirmed_by"]):
        errors.append("declaration.payment_context must be {add_window_closed: bool, confirmed_by: non-empty string}")
    return errors


def hide_card(timing_state: dict[str, Any], effect_state: dict[str, Any], declaration: dict[str, Any],
              engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {
        "schema_version": HIDE_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "hide_id": declaration.get("hide_id") if isinstance(declaration, dict) else None,
        "input_timing_state_hash": state_hash(timing_state) if isinstance(timing_state, dict) else hash_value(timing_state),
        "input_effect_state_hash": hash_value(effect_state),
    }

    def invalid(errors: list[str]) -> dict[str, Any]:
        return {**base, "valid": False, "committed": False, "unsupported": False, "rolled_back": False,
                "reason_code": "invalid_input", "reason": "; ".join(errors), "errors": errors, "trace": [], "rule_locators": [],
                "next_timing_state_hash": base["input_timing_state_hash"], "next_effect_state_hash": base["input_effect_state_hash"]}

    errors = [f"timing state: {e}" for e in validate_timing_state(timing_state)] if isinstance(timing_state, dict) else ["timing state must be an object"]
    errors += [f"effect state: {e}" for e in validate_state(effect_state)]
    if errors:
        return invalid(errors)
    errors = validate_declaration(declaration, effect_state)
    errors += [f"engine_decisions: {e}" for e in ed.validate_engine_decisions(engine_decisions)]
    if engine_decisions is not None and not errors and engine_decisions.get("input_hash") != hash_value(effect_state):
        errors.append("engine_decisions.input_hash does not match the effect state")
    if errors:
        return invalid(errors)
    if is_terminal(timing_state):
        return {**base, "valid": True, "committed": False, "unsupported": False, "rolled_back": False,
                "reason_code": "game_over", "reason": "the game ended; the snapshot is frozen (196)", "trace": [], "rule_locators": ["Core 196"],
                "next_timing_state_hash": base["input_timing_state_hash"], "next_effect_state_hash": base["input_effect_state_hash"]}

    actor, card = declaration["actor"], declaration["card"]
    battlefield_id, source = declaration["battlefield"], declaration.get("source", "hand")
    trace: list[dict[str, Any]] = []

    def refuse(reason_code: str, reason: str, locators: list[str], **extra: Any) -> dict[str, Any]:
        return {**base, "valid": True, "committed": False, "unsupported": bool(extra.pop("unsupported", False)), "rolled_back": True,
                "reason_code": reason_code, "reason": reason, "trace": trace + [{"stage": reason_code, "outcome": "rolled_back", "rule_locators": ["Core 358.5"]}],
                "rule_locators": list(dict.fromkeys(locators + RULES)),
                "next_timing_state_hash": base["input_timing_state_hash"], "next_effect_state_hash": base["input_effect_state_hash"], **extra}

    # Core 811.1: the actor's own turn, in an Open State. Hide is a
    # Discretionary Action, so the kernel's discretionary window applies; it is
    # not a play, so nothing goes on the chain.
    verdict = validate_timing(timing_state, {"actor": actor, "kind": "standard_move", "timing": "default"})
    if verdict.get("legal") is not True:
        return refuse("hide_timing_illegal", f"Hide needs {actor}'s own Main Phase in an Open State (811.1); the kernel refused: {verdict.get('reason_code')}",
                      verdict.get("rule_locators", []), timing_verdict=verdict)
    if card not in effect_state["objects"]:
        return refuse("unknown_card", f"{card!r} is not an object in this state", [])
    if find_location(effect_state, card) != ("player", actor, source):
        return refuse("card_not_in_source", f"{card!r} is not in {actor}'s {source} (811.1)", ["Core 811.1"])
    if not effect_state["objects"][card].get("hidden"):
        return refuse("card_has_no_hidden", f"{card!r} does not have the Hidden keyword; Hide is its prerequisite (811)", ["Core 811"])
    battlefield = effect_state["battlefields"][battlefield_id]
    if battlefield.get("controller") != actor:
        return refuse("battlefield_not_controlled", f"{actor} does not control {battlefield_id!r}; a card is hidden at a Battlefield you control (811.1)", ["Core 811.1"])
    zone = facedown_zone(effect_state, battlefield_id)
    if len(zone["cards"]) >= zone["capacity"]:
        return refuse("facedown_zone_full", f"{battlefield_id!r} already holds {len(zone['cards'])} facedown card(s); its capacity is {zone['capacity']} (107.3.b, 811.1)",
                      ["Core 107.3.b", "Core 811.1"])

    working = copy.deepcopy(effect_state)
    try:
        skeleton = determine_total_cost(declaration["cost"], {}, actor=actor)
        # 811.1: the Hide cost is paid like any other, but Hide is not a Play
        # (811.2), so a resource restricted to playing cannot pay for it.
        events = _pay(working, {**declaration, "play_id": declaration["hide_id"], "chain_item": {"object_kind": "spell"}}, skeleton, engine_decisions, use="hide")
    except PlayError as exc:
        extra = dict(exc.extra)
        locators = extra.pop("rule_locators", [])
        if extra.pop("invalid", False):
            return invalid([str(exc)])
        return refuse(exc.reason_code, str(exc), locators, unsupported=bool(extra.pop("unsupported", False)), **extra)
    trace.append({"stage": "payment", "outcome": "applied", "event_ids": [e["event_id"] for e in events], "use": "hide", "rule_locators": ["Core 357.1", "Core 811.1"]})

    working["players"][actor]["zones"][source].remove(card)
    turn_id = working.get("turn_id", DEFAULT_TURN_ID)
    facedown = working["battlefields"][battlefield_id].setdefault("facedown", {"capacity": zone["capacity"], "cards": []})
    facedown.setdefault("capacity", zone["capacity"])
    facedown.setdefault("cards", [])
    facedown["cards"].append({"object_id": card, "controller": actor, "hidden_on_turn": turn_id})
    identity = _bump_identity(working, card)
    if found := validate_state(working):
        return invalid(found)
    trace.append({"stage": "hide", "outcome": "applied", "card_visible_to": [actor], "battlefield": battlefield_id, "identity_after": identity,
                  "hidden_on_turn": turn_id, "opens_chain": False, "not_a_play": True, "rule_locators": RULES})
    receipt = {
        "schema_version": RECEIPT_VERSION, "play_id": declaration["hide_id"], "actor": actor, "card": card,
        "base": skeleton["base"], "after_base_modifications": skeleton["after_base_modifications"],
        "components": skeleton["components"], "aggregate": skeleton["aggregate"],
        "discount_order": skeleton["discount_order"], "order_provenance": skeleton["order_provenance"],
        "payment_events": events, "total": skeleton["total"],
        "paid": all(c["paid"] for c in skeleton["components"] if c["mandatory"] or c["intent"] is True),
        "rule_locators": ["Core 357.1", "Core 811.1"],
    }
    return {
        **base, "valid": True, "committed": True, "unsupported": False, "rolled_back": False, "reason_code": "ok",
        "cost_receipt": receipt, "battlefield": battlefield_id,
        "next_timing_state": copy.deepcopy(timing_state), "next_timing_state_hash": state_hash(timing_state),
        "next_effect_state": working, "next_effect_state_hash": hash_value(working),
        "trace": trace, "rule_locators": RULES + ["Core 357.1"],
    }
