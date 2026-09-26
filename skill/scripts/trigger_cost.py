#!/usr/bin/env python3
"""A triggered ability's base cost, paid as the ability is finalized (Core 204.3.a, 383.3.b).

"[do X] to [do Y]" at the start of a triggered ability's effect - or right after the "you may"
that opens it - is a cost within instructions that is taken as the ability's BASE cost (Core
204.3.a, 383.3.b, 403.1.b.1). It is paid while the ability is finalized to the Chain (383.3.b.1,
740.4.a.2), not as it resolves. A player may decline to pay it, and a cost a player cannot pay
is not paid (Core 203.3); either way the ability leaves the Chain and never becomes a Finalized
Chain Item (Core 404.2), which is not the ability being countered (404.2.a).

The program carries the cost as its first instruction, `trigger_base_cost` (effect_ir: its
content hash covers the cost like any instruction). This module pays it with the play
transaction's own machinery - determine_total_cost and _pay: Energy and Power (Core 357.1, with
the Add window the payer confirms, 429.3), exhausting the ability's own source (a Legend from
its Legend Zone, Core 174.8, or a permanent on the board), spending a buff from a unit its
controller controls (Core 702.2.b, 702.2.b.1, 702.2.b.2) - plus recycling the ability's own
source from its owner's trash (Core 416.1, 416.3; Ekko, Recurrent is 383.3.b's own example). It
writes the cost receipt the chain item keeps (cost_receipt.py) and returns the events the costs
caused, for the watchers (a recycle as a cost is a recycle, Core 416.2.a).

Nothing here decides whether to pay: finalize_trigger asks, and calls this only when the
controller pays.
"""
from __future__ import annotations

import copy
from typing import Any

import engine_decisions as ed
from cost_receipt import RECEIPT_VERSION, validate_cost_receipt
from effect_ir import (_recycle_batch, find_location, hash_value, object_identity, validate_state,
                       zone_class)

BASE_COST_OP = "trigger_base_cost"
RULES = ["Core 204.3.a", "Core 383.3.b", "Core 383.3.b.1", "Core 403.1.b.1", "Core 740.4.a.2"]
DECLINE_RULES = ["Core 404.2", "Core 404.2.a", "Core 383.3.b.1"]
UNPAYABLE_RULES = ["Core 203.3", "Core 404.2", "Core 404.2.a", "Core 383.3.b.1"]
# play_transaction.PlayError reason codes that are a decision the payer still owes, not a refusal
DECISION_CODES = {"add_window_confirmation_required", "resource_allocation_required", "card_selection_required",
                  "card_ordering_required"}


class TriggerCostError(Exception):
    """The cost was not paid. `kind`: unpayable (the ability leaves the Chain, 203.3 / 404.2),
    decision_required (the payer owes a choice first), invalid (malformed input) or refused."""

    def __init__(self, kind: str, reason_code: str, message: str, **extra: Any):
        super().__init__(message)
        self.kind, self.reason_code, self.extra = kind, reason_code, extra


def base_cost(program: dict[str, Any] | None) -> dict[str, Any] | None:
    """The program's base cost instruction, or None. validate_program keeps it first."""
    effects = (program or {}).get("effects") or []
    first = effects[0] if effects else None
    return first if isinstance(first, dict) and first.get("op") == BASE_COST_OP else None


def cost_hash(marker: dict[str, Any]) -> str:
    return hash_value(marker)


def spend_buff_decision_id(item_id: str) -> str:
    return f"trigger_cost:{item_id}:spend_buff"


def buff_candidates(state: dict[str, Any], controller: str) -> list[str]:
    """Core 702.2.b.1 / 702.2.b.2: a buff is spent from a Unit its spender controls that has one."""
    return sorted(o for o, obj in (state.get("objects") or {}).items()
                  if obj.get("kind") == "unit" and obj.get("controller") == controller and obj.get("buffed")
                  and zone_class(find_location(state, o)) == "board")


def _chosen_buff(state: dict[str, Any], item: dict[str, Any], decisions: dict[str, Any] | None) -> tuple[str, str]:
    controller = item["controller"]
    candidates = buff_candidates(state, controller)
    if not candidates:
        raise TriggerCostError("unpayable", "cost_unpayable",
                               f"no unit {controller} controls has a buff to spend (Core 702.2.b.1, 702.2.b.2, 203.3)",
                               rule_locators=["Core 702.2.b.1", "Core 702.2.b.2", "Core 203.3"])
    decision_id = spend_buff_decision_id(item["id"])
    entry = next((e for e in ed.entries(decisions, kind="card_selection") if e["decision_id"] == decision_id), None)
    if entry is None:
        if len(candidates) == 1:
            return candidates[0], "sole_candidate"
        raise TriggerCostError("decision_required", "cost_selection_required",
                               f"{controller} chooses which of {candidates} spends its buff to pay the cost",
                               decision_ids=[decision_id], decision_controller=controller, candidates=candidates,
                               rule_locators=["Core 702.2.b", "Core 404.1"])
    if entry["stage"] != "trigger_finalization":
        raise TriggerCostError("invalid", "decision_stage_mismatch",
                               f"{decision_id!r} was supplied for stage {entry['stage']!r}, not trigger_finalization")
    if entry["controller"] != controller:
        raise TriggerCostError("refused", "decision_controller_mismatch",
                               f"{decision_id!r} was made by {entry['controller']!r}, not the paying player {controller!r}",
                               rule_locators=["Core 702.2.b.2"])
    if len(entry["value"]) != 1 or entry["value"][0] not in candidates:
        raise TriggerCostError("refused", "cost_choice_illegal",
                               f"{decision_id!r} names {entry['value']}; one of {candidates} spends the buff",
                               rule_locators=["Core 702.2.b.1", "Core 702.2.b.2"])
    chosen = entry["value"][0]
    if (entry.get("selection_identities") or {}).get(chosen) != object_identity(state, chosen):
        raise TriggerCostError("invalid", "selection_identity_mismatch",
                               f"{decision_id!r} was bound to another object than {chosen!r} is now (Core 124)")
    return chosen, decision_id


def _source_is_me(state: dict[str, Any], item: dict[str, Any], *, where: str) -> str:
    """The ability's own source, as the payment needs it: `board` (a permanent, or a Legend in its
    Legend Zone) for an exhaust, `trash` (its owner's) for a recycle. A source that is not there, or
    is a new object since it triggered (Core 124), cannot pay (203.3)."""
    source = item.get("source_object")
    obj = (state.get("objects") or {}).get(source or "")
    if obj is None:
        raise TriggerCostError("unpayable", "cost_unpayable",
                               f"the ability's source {source!r} is not an object; 'me' cannot pay (Core 203.3)",
                               rule_locators=["Core 203.3"])
    location = find_location(state, source)
    if where == "board":
        in_legend_zone = obj.get("kind") == "legend" and location == ("player", item["controller"], "legend_zone")
        if zone_class(location) != "board" and not in_legend_zone:
            raise TriggerCostError("unpayable", "cost_unpayable",
                                   f"{source!r} is at {location}, not on the board, so it cannot exhaust itself (Core 203.3)",
                                   rule_locators=["Core 203.3", "Core 414.1"])
        recorded = item.get("source_identity")
        if recorded is not None and object_identity(state, source) != recorded:
            raise TriggerCostError("unpayable", "cost_unpayable",
                                   f"{source!r} is {object_identity(state, source)!r}, a new object since the ability "
                                   f"triggered from {recorded!r} (Core 124)", rule_locators=["Core 124", "Core 203.3"])
    else:
        owner = obj.get("owner")
        if location != ("player", owner, "trash"):
            raise TriggerCostError("unpayable", "cost_unpayable",
                                   f"{source!r} is at {location}, not in its owner's trash, so 'recycle me' cannot be "
                                   f"completed (Core 416.3, 203.3)", rule_locators=["Core 416.3", "Core 203.3"])
    return source


def pay_base_cost(effect_state: dict[str, Any], item: dict[str, Any], program: dict[str, Any],
                  decisions: dict[str, Any] | None, payment_context: dict[str, Any] | None) -> dict[str, Any]:
    """Pay the program's base cost for this pending chain item on a copy of the effect state.

    Returns {state, receipt, pay_events, events, death_batches}; raises TriggerCostError. The
    input state is never touched: a cost that fails part-way leaves nothing paid (the same
    all-or-nothing rule the play transaction keeps, Core 358.5)."""
    import play_transaction as PT
    import game_events

    marker = base_cost(program)
    if marker is None:
        raise TriggerCostError("invalid", "no_base_cost", "the program has no trigger_base_cost to pay")
    actor = item["controller"]
    item_id = item["id"]
    play_id = f"trigger:{item_id}"
    working = copy.deepcopy(effect_state)
    base = {"energy": 0, "power": {}}
    additional: list[dict[str, Any]] = []
    recycle_source = None
    buff_choice = None
    for part in marker["payment"]:
        kind = part["kind"]
        if kind == "energy":
            base["energy"] += part["amount"]
        elif kind == "power":
            base["power"][part["domain"]] = base["power"].get(part["domain"], 0) + part["amount"]
        elif kind == "exhaust":
            source = _source_is_me(working, item, where="board")
            additional.append({"cost_id": "trigger:exhaust-self", "mandatory": True,
                               "payment": {"kind": "exhaust", "object_id": source}})
        elif kind == "spend_buff":
            chosen, decided_by = _chosen_buff(working, item, decisions)
            buff_choice = {"object_id": chosen, "decided_by": decided_by}
            additional.append({"cost_id": "trigger:spend-buff", "mandatory": True,
                               "payment": {"kind": "spend_buff", "object_id": chosen}})
        elif kind == "recycle":
            recycle_source = _source_is_me(working, item, where="trash")
        else:   # validate_program admits nothing else; a hand-built program is refused by name
            raise TriggerCostError("invalid", "unsupported_trigger_cost", f"payment kind {kind!r} is not modelled")
    skeleton = PT.determine_total_cost({"base": base, "additional": additional}, {}, actor=actor)
    declaration = {"actor": actor, "play_id": play_id, "card": item.get("source_object"),
                   "payment_context": payment_context or {},
                   "chain_item": {"id": item_id, "object_kind": "ability", "timing": "default", "ability_kind": "standard"},
                   "activation": {"source_object": item.get("source_object"), "ability_id": item_id}}
    semantic: dict[str, list[Any]] = {"events": [], "death_batches": []}
    try:
        pay_events = PT._pay(working, declaration, skeleton, decisions, use="trigger_ability", semantic=semantic)
    except PT.PlayError as exc:
        extra = dict(exc.extra)
        locators = extra.pop("rule_locators", [])
        if extra.pop("invalid", False):
            raise TriggerCostError("invalid", exc.reason_code, str(exc), rule_locators=locators)
        if exc.reason_code == "cost_unpayable":
            raise TriggerCostError("unpayable", exc.reason_code, str(exc), rule_locators=locators + ["Core 203.3"])
        if exc.reason_code in DECISION_CODES:
            raise TriggerCostError("decision_required", exc.reason_code, str(exc), rule_locators=locators, **extra)
        raise TriggerCostError("refused", exc.reason_code, str(exc), rule_locators=locators, **extra)
    components = skeleton["components"]
    if recycle_source is not None:
        before = object_identity(working, recycle_source)
        working, sub = _recycle_batch(working, [recycle_source], actor, decisions, f"{play_id}:recycle:order",
                                      "cost:trigger:recycle-self")
        event_id = "pay:trigger:recycle-self"
        pay_events.append({"event_id": event_id, "kind": "pay_recycle_trash", "cost_id": "trigger:recycle-self",
                           "objects": [recycle_source], "identities_before": {recycle_source: before},
                           "identities_after": sub["identities_after"], "order_decision": None,
                           "decided_by": "the ability's own source",
                           "rule_locators": ["Core 357.2", "Core 416.1", "Core 416.3", "Core 124"]})
        components.append({"cost_id": "trigger:recycle-self", "kind": "recycle_self", "mandatory": True, "intent": None,
                           "requested": {"object_id": recycle_source}, "increases": [], "reductions": [],
                           "final": {"object_id": recycle_source}, "payment_refs": [{"event_id": event_id}],
                           "paid": True, "rule_locators": ["Core 204.3.a", "Core 383.3.b", "Core 416.3"]})
    receipt = {
        "schema_version": RECEIPT_VERSION, "play_id": play_id, "actor": actor, "card": item.get("source_object"),
        "chain_item": item_id, "base": skeleton["base"], "after_base_modifications": skeleton["after_base_modifications"],
        "components": components, "aggregate": skeleton["aggregate"], "discount_order": skeleton["discount_order"],
        "order_provenance": skeleton["order_provenance"], "payment_events": pay_events, "total": skeleton["total"],
        "paid": all(c["paid"] for c in components if c["mandatory"] or c["intent"] is True),
        "rule_locators": list(dict.fromkeys(RULES + ["Core 357.1", "Core 357.2"])),
    }
    problems = validate_cost_receipt(receipt) + [f"state: {e}" for e in validate_state(working)]
    if problems or not receipt["paid"]:
        raise TriggerCostError("invalid", "trigger_cost_receipt_invalid", "; ".join(problems) or "a component is unpaid")
    events = game_events.cost_zone_events(play_id=play_id, actor=actor, source_card=item.get("source_object"),
                                          pay_events=pay_events, state=working) + semantic["events"]
    return {"state": working, "receipt": receipt, "pay_events": pay_events, "events": events,
            "death_batches": semantic["death_batches"], "buff_choice": buff_choice,
            "cost_hash": cost_hash(marker)}
