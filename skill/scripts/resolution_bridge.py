#!/usr/bin/env python3
"""Atomic bridge between Chronicle timing state and typed effect programs."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from effect_ir import DEFAULT_TURN_ID, TURN_EFFECT_KINDS, _bump_identity, action_performed, apply_program, contains_each_player, drop_play_bound_replacements, find_location, hash_value, migrate_legacy_effects, object_triggers, perform_lethal_cleanup, validate_state, zone_class
from rules_core import add_limited_play_items, apply_terminal_event, complete_resolution, is_terminal, remove_chain_item, schedule_triggered_items, state_hash
from rules_core import validate_state as validate_timing_state

CLEANUP_DECISION_VERSION = "riftbound-cleanup-decisions.v1"

import engine_decisions as _ed  # noqa: E402


def validate_cleanup_decisions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["cleanup_decisions must be an object"]
    if value.get("schema_version") != CLEANUP_DECISION_VERSION:
        return [f"cleanup_decisions.schema_version must be {CLEANUP_DECISION_VERSION}"]
    if set(value) - {"schema_version", "replacement_event_order", "replacement_choices"}:
        return ["cleanup_decisions contains unsupported fields"]
    event_order = value.get("replacement_event_order", {})
    if not isinstance(event_order, dict) or any(
        not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or any(not isinstance(item, str) or not item for item in ids)
        for ids in event_order.values()
    ):
        return ["cleanup_decisions.replacement_event_order must map ids to non-empty unique string arrays"]
    choices = value.get("replacement_choices", {})
    if not isinstance(choices, dict) or any(
        not isinstance(by_event, dict) or any(not isinstance(event_id, str) or not isinstance(choice, bool) for event_id, choice in by_event.items())
        for by_event in choices.values()
    ):
        return ["cleanup_decisions.replacement_choices must map replacement and event ids to booleans"]
    return []


def program_hash(program: dict[str, Any]) -> str:
    """The content of a program: its instructions. The ID names a program; this says
    whether what is about to run is still the program that was named."""
    return hash_value(program.get("effects") or [])


def dispatch_program(registry: dict[str, Any], chain_item: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The registered program a chain item is bound to, or why there is none.

    A chain item binds `effect_program_id`, and - when its trigger descriptor carried
    one - `effect_program_hash`. The caller does not get to choose the program: it is
    looked up by the ID the engine put on the Chain, and refused if its content is not
    the content the descriptor named."""
    program_id = chain_item.get("effect_program_id")
    program = (registry or {}).get(program_id) if isinstance(program_id, str) else None
    if not isinstance(program, dict):
        return None, {"reason": "effect_program_not_registered", "expected_program_id": program_id}
    if program.get("program_id") != program_id:
        return None, {"reason": "effect_program_id_mismatch", "expected_program_id": program_id, "received_program_id": program.get("program_id")}
    bound_hash = chain_item.get("effect_program_hash")
    if bound_hash is not None and program_hash(program) != bound_hash:
        return None, {"reason": "effect_program_hash_mismatch", "expected_program_hash": bound_hash, "received_program_hash": program_hash(program)}
    return program, None


def bind_source_identity(program: dict[str, Any], chain_item: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The program as it runs for this chain item: carrying the identity its source had
    when the trigger condition was met, which the chain item recorded.

    A registered program is a template - it cannot know which generation of its source
    will trigger it - so a relational "here" (location_ref, whose identity check is
    mandatory, GPT 2026-09-23) could never resolve on a triggered ability. The engine
    supplies it from its own record. A template that declares a DIFFERENT identity is
    refused rather than silently overridden; with no record, the program is unchanged
    and "here" stays refused by name. Not part of the content hash (program_hash reads
    the instructions only)."""
    recorded = chain_item.get("source_identity")
    if recorded is None:
        return bind_trigger_event(program, chain_item)
    declared = program.get("source_identity")
    if declared is not None and declared != recorded:
        return None, {"reason": "effect_program_source_identity_mismatch",
                      "expected_source_identity": recorded, "received_source_identity": declared}
    return bind_trigger_event({**program, "source_identity": recorded}, chain_item)


def bind_trigger_event(program: dict[str, Any], chain_item: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """2026-09-28: the program as it runs for this chain item, carrying the event that met its
    trigger condition - the object that event is about and the identity it had then - as the chain
    item recorded it (watchers.trigger_event_of, rules_core.schedule_triggered_items). This is what
    `{object_ref: trigger_event_object}` ("give IT +1 Might") resolves against (effect_ir.
    resolve_object_ref, Core 359.3.f.3). Only the engine supplies it: a template that declares
    another (or one where the chain item recorded none) is refused rather than overridden, and with
    no record the program is unchanged, so a referent in it is refused by name as it executes. Not
    part of the content hash."""
    recorded = chain_item.get("trigger_event")
    declared = program.get("trigger_event")
    if declared is not None and declared != recorded:
        return None, {"reason": "effect_program_trigger_event_mismatch",
                      "why": "only the engine binds a triggered ability's event; a program may not bring its own",
                      "received_trigger_event": declared, "expected_trigger_event": recorded}
    if recorded is None:
        return program, None
    return {**program, "trigger_event": dict(recorded)}, None


def _target_refs(program: dict[str, Any]) -> list[str]:
    refs = []
    for effect in program.get("effects") or []:
        for field in ("target", "targets"):
            selector = effect.get(field)
            if isinstance(selector, dict) and isinstance(selector.get("decision_ref"), str):
                refs.append(selector["decision_ref"])
        for unit in effect.get("units") or []:
            if isinstance(unit, dict) and isinstance(unit.get("decision_ref"), str):
                refs.append(unit["decision_ref"])
    return refs


def finalize_trigger(
    timing_state: dict[str, Any],
    effect_state: dict[str, Any],
    registry: dict[str, Any],
    engine_decisions: dict[str, Any] | None = None,
    *,
    perform_optional_trigger: bool | None = None,
    pay_trigger_cost: bool | None = None,
    payment_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Finalize the oldest Pending triggered ability: dispatch its program, bind its targets.

    Core 355.5.b keeps a permanent's triggered-ability choices out of the permanent's
    own play; Core 383.3 puts the ability on the Chain like an activated one; Core
    337.1 has its controller complete the steps of playing it until it is Finalized,
    and Core 355.5 is one of those steps. So this is where a target is chosen, and it
    is the only place: the selection is recorded on the chain item, and resolution
    uses the record (Core 359.3.e - a target illegal by then is mistargeted, never
    re-chosen).

    2026-09-27: a program that opens with a `trigger_base_cost` (Core 204.3.a, 383.3.b,
    403.1.b.1) has that cost paid here, after its targets are bound (402 before 404), and
    only here (383.3.b.1, 740.4.a.2). Its controller says whether to pay
    (`pay_trigger_cost`; `payment_context` confirms the Add window for a resource cost, Core
    429.3). Declined, or not payable (Core 203.3), the ability leaves the Chain and never
    becomes a Finalized Chain Item (404.2) - not a counter (404.2.a) - and nothing is paid.
    Paid, the chain item keeps the cost receipt resolution checks, the effect state after
    payment is returned, and what the costs did wakes the watchers (a recycle as a cost is
    a recycle, 416.2.a) - their triggers go on the Chain after this one."""
    from play_transaction import PlayError, _check_play_targets  # late: play_transaction imports effect_ir too
    from rules_core import finalize_oldest_pending, next_procedure
    base = {"schema_version": "riftbound-trigger-finalization-result.v1",
            "input_timing_state_hash": state_hash(timing_state), "input_effect_state_hash": hash_value(effect_state)}
    locators = ["Core 337.1", "Core 355.5", "Core 355.5.b", "Core 383.3"]
    step = next_procedure(timing_state)
    if step.get("procedure") != "finalize_oldest_pending":
        return {**base, "valid": True, "committed": False, "stage": "timing", "reason": "finalize_not_next", "next_procedure": step}
    item = next(i for i in timing_state["chain"]["items"] if i["status"] == "pending")
    if item.get("timing") != "triggered":
        return {**base, "valid": True, "committed": False, "stage": "timing", "reason": "pending_item_is_not_a_triggered_ability", "item_id": item["id"]}
    program, refusal = dispatch_program(registry, item)
    if refusal is not None:
        return {**base, "valid": True, "committed": False, "stage": "program_dispatch", "item_id": item["id"], **refusal}
    if program.get("controller") is not None and program["controller"] != item.get("controller"):
        return {**base, "valid": True, "committed": False, "stage": "program_dispatch", "item_id": item["id"], "reason": "effect_program_controller_mismatch"}
    if program.get("source_object") is not None and program["source_object"] != item.get("source_object"):
        return {**base, "valid": True, "committed": False, "stage": "program_dispatch", "item_id": item["id"], "reason": "effect_program_source_mismatch"}
    registered = program
    program, refusal = bind_source_identity(program, item)
    if refusal is not None:
        return {**base, "valid": True, "committed": False, "stage": "program_dispatch", "item_id": item["id"], **refusal}
    if decision_errors := _ed.validate_engine_decisions(engine_decisions):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": decision_errors, "reason": "; ".join(decision_errors)}
    if engine_decisions is not None and engine_decisions.get("input_hash") != hash_value(effect_state):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "reason": "stale decision envelope"}
    declining = item.get("optional_at_finalize") is True and perform_optional_trigger is False
    import trigger_cost as TC
    cost = TC.base_cost(program)
    if cost is None and pay_trigger_cost is not None:
        return {**base, "valid": True, "committed": False, "stage": "trigger_cost", "item_id": item["id"],
                "reason": "unexpected_trigger_cost_choice", "rule_locators": ["Core 403.1.b"]}
    if declining and pay_trigger_cost:
        return {**base, "valid": False, "committed": False, "stage": "trigger_cost", "item_id": item["id"],
                "reason": "declined_trigger_cannot_pay_its_cost", "rule_locators": ["Core 383.3.a.2"]}
    recorded: list[dict[str, Any]] = []
    performing = not declining and (item.get("optional_at_finalize") is not True or perform_optional_trigger is True)
    if performing and (lacking := _lacking_choices(effect_state, item["controller"], program)):
        # GPT 2026-09-29, Core 402.4: not enough options to make its legal choices - it leaves the Chain now,
        # never becomes a Finalized Chain Item, and is not countered (402.4.a)
        removal = remove_chain_item(timing_state, item["id"], reason="no_legal_choices")
        if removal.get("applied") is not True:
            return {**base, "valid": removal.get("valid", True), "committed": False, "stage": "target_binding",
                    "item_id": item["id"], "reason": removal.get("reason_code") or "chain_item_removal_failed",
                    "timing_result": removal}
        next_timing = removal["next_state"]
        return {**base, "valid": True, "committed": True, "removed": True, "item_id": item["id"],
                "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
                "next_effect_state": effect_state, "next_effect_state_hash": hash_value(effect_state),
                "finalized_targets": [], "lacking_choices": lacking,
                "transition": {"type": "no_legal_choices", "item_id": item["id"], "never_finalized": True,
                               "countered": False, "why": f"no legal options for {lacking}"},
                "rule_locators": ["Core 402.2", "Core 402.4", "Core 402.4.a"]}
    if not declining:
        try:
            _check_play_targets(effect_state, item["controller"], program, engine_decisions, stage="trigger_finalization")
        except PlayError as error:
            return {**base, "valid": not error.extra.get("invalid", False), "committed": False, "stage": "target_binding",
                    "item_id": item["id"], "reason": error.reason_code, "message": str(error),
                    "decision_ids": error.extra.get("decision_ids"), "rule_locators": locators}
        for ref in _target_refs(program):
            entry = _ed.target_selection(engine_decisions, ref)
            if entry is None:   # the check above already refuses this; never record a hole
                return {**base, "valid": True, "committed": False, "stage": "target_binding", "item_id": item["id"],
                        "reason": "target_selection_required", "decision_ids": [ref], "rule_locators": locators}
            recorded.append({k: copy.deepcopy(entry[k]) for k in ("decision_id", "stage", "kind", "controller", "value", "selection_identities") if k in entry})
        # GPT 2026-09-29 (Core 355.4, 355.15): the Move destination chosen now is recorded with the targets
        from play_transaction import destination_refs
        for ref in dict.fromkeys(destination_refs(program.get("effects") or [])):
            entry = next((e for e in _ed.entries(engine_decisions, kind="location_selection") if e["decision_id"] == ref), None)
            if entry is None:   # _check_play_targets already refuses this
                return {**base, "valid": True, "committed": False, "stage": "target_binding", "item_id": item["id"],
                        "reason": "move_destination_required", "decision_ids": [ref], "rule_locators": locators + ["Core 355.4"]}
            recorded.append({k: copy.deepcopy(entry[k]) for k in ("decision_id", "stage", "kind", "controller", "value") if k in entry})
    paid = None
    choosing_first = item.get("optional_at_finalize") is True and perform_optional_trigger is None
    if cost is not None and not declining and not choosing_first:
        # Core 403.1.b.1 / 404: the ability's base cost, paid now or never (383.3.b.1)
        cost_rules = locators + TC.RULES
        if pay_trigger_cost is None:
            return {**base, "valid": True, "committed": False, "stage": "trigger_cost", "item_id": item["id"],
                    "reason": "trigger_cost_choice_required", "choices": ["pay", "decline"],
                    "decision_controller": item["controller"], "base_cost": copy.deepcopy(cost["payment"]),
                    "rule_locators": cost_rules + ["Core 404.2"]}
        if pay_trigger_cost is False:
            return _trigger_left_unpaid(base, timing_state, effect_state, item, "trigger_cost_declined",
                                        "its controller declined to pay the base cost", TC.DECLINE_RULES)
        try:
            paid = TC.pay_base_cost(effect_state, item, program, engine_decisions, payment_context)
        except TC.TriggerCostError as exc:
            if exc.kind == "unpayable":
                return _trigger_left_unpaid(base, timing_state, effect_state, item, "trigger_cost_unpayable", str(exc),
                                            list(dict.fromkeys(TC.UNPAYABLE_RULES + list(exc.extra.get("rule_locators") or []))))
            extra = {k: v for k, v in exc.extra.items() if k != "rule_locators"}
            return {**base, "valid": exc.kind != "invalid", "committed": False, "stage": "trigger_cost", "item_id": item["id"],
                    "reason": exc.reason_code, "message": str(exc), **extra,
                    "rule_locators": list(dict.fromkeys(cost_rules + list(exc.extra.get("rule_locators") or [])))}
    timing_result = finalize_oldest_pending(timing_state, perform_optional_trigger=perform_optional_trigger)
    if timing_result.get("applied") is not True:
        return {**base, "valid": timing_result.get("valid", True), "committed": False, "stage": "timing",
                "reason": timing_result.get("reason_code", "finalize_failed"), "timing_result": timing_result}
    next_timing = timing_result["next_state"]
    next_effect = effect_state
    for candidate in next_timing["chain"]["items"]:
        if candidate["id"] == item["id"]:
            candidate["finalized_targets"] = recorded
            candidate.setdefault("effect_program_hash", program_hash(registered))
            if paid is not None:
                candidate["trigger_cost_receipt"] = {"cost_hash": paid["cost_hash"], "receipt": copy.deepcopy(paid["receipt"])}
    cost_trace = None
    if paid is not None:
        next_effect = paid["state"]
        scheduled = _schedule_cost_watchers(base, next_timing, next_effect, paid, engine_decisions, item["id"])
        if "failure" in scheduled:
            return scheduled["failure"]
        next_timing, next_effect = scheduled["timing"], scheduled["effect"]
        cost_trace = {"stage": "trigger_cost", "outcome": "paid", "cost_hash": paid["cost_hash"],
                      "payment_events": [e["event_id"] for e in paid["pay_events"]],
                      **({"spend_buff": paid["buff_choice"]} if paid.get("buff_choice") else {}),
                      "events": [e["event_id"] for e in paid["events"]], "scheduled": scheduled["scheduled"],
                      "rule_locators": TC.RULES + ["Core 357.1", "Core 357.2"]}
        locators = list(dict.fromkeys(locators + TC.RULES))
    return {**base, "valid": True, "committed": True, "item_id": item["id"], "next_timing_state": next_timing,
            "next_timing_state_hash": state_hash(next_timing), "finalized_targets": recorded,
            "next_effect_state": next_effect, "next_effect_state_hash": hash_value(next_effect),
            **({"trigger_cost": cost_trace, "cost_receipt": paid["receipt"]} if paid is not None else {}),
            "effect_program_id": item["effect_program_id"], "effect_program_hash": program_hash(program),
            "transition": timing_result.get("transition"), "rule_locators": locators}


def _trigger_left_unpaid(base: dict[str, Any], timing_state: dict[str, Any], effect_state: dict[str, Any],
                         item: dict[str, Any], kind: str, why: str, rule_locators: list[str]) -> dict[str, Any]:
    """Core 404.2: a triggered ability whose base cost is not paid - declined, or not payable
    (203.3) - leaves the Chain and never becomes a Finalized Chain Item; it is not countered
    (404.2.a). Nothing was paid, so the effect state is the one given."""
    removal = remove_chain_item(timing_state, item["id"], reason=kind)
    if removal.get("applied") is not True:
        return {**base, "valid": removal.get("valid", True), "committed": False, "stage": "trigger_cost", "item_id": item["id"],
                "reason": removal.get("reason_code") or "chain_item_removal_failed", "timing_result": removal}
    next_timing = removal["next_state"]
    return {**base, "valid": True, "committed": True, "removed": True, "item_id": item["id"],
            "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
            "next_effect_state": effect_state, "next_effect_state_hash": hash_value(effect_state), "finalized_targets": [],
            "transition": {"type": kind, "item_id": item["id"], "never_finalized": True, "countered": False, "why": why},
            "rule_locators": rule_locators}


def kill_attributed(effect_events: list[dict[str, Any]], cleanup_events: list[dict[str, Any]], *,
                    killer: str | None, responsible: str | None) -> list[dict[str, Any]]:
    """The events of one resolution, its deaths stamped with the kill's attribution (Core 428.5): a
    death by one of its own instructions (428.5.b), or a death in the Cleanup right after it of a unit
    it dealt damage to (428.5.c), is a kill by the resolving card - or, for an ability, by the object
    it originates from, which is attributed with it (428.5.d) - and its controller is the player
    responsible (428.5.c.1). Copies are stamped; the events themselves are not changed. A death the
    resolution did not cause (a Cleanup death of a unit it did not damage) is left unattributed."""
    if killer is None or responsible is None:
        return effect_events + cleanup_events
    damaged = {event.get("object") for event in effect_events if event.get("kind") == "damaged"}

    def stamp(event: dict[str, Any], rules: list[str]) -> dict[str, Any]:
        return {**event, "killed_by": {"objects": [killer], "responsible_player": responsible,
                                       "rule_locators": rules + ["Core 428.5.d"]}}
    return ([stamp(e, ["Core 428.5.b"]) if e.get("kind") == "died" else e for e in effect_events]
            + [stamp(e, ["Core 428.5.c", "Core 428.5.c.1"]) if e.get("kind") == "died" and e.get("object") in damaged else e
               for e in cleanup_events])


def _schedule_cost_watchers(base: dict[str, Any], next_timing: dict[str, Any], next_effect: dict[str, Any],
                            paid: dict[str, Any], engine_decisions: dict[str, Any] | None, item_id: str) -> dict[str, Any]:
    """What the base cost did happened while the ability was finalized: a card recycled as a cost
    (Core 416.2.a), a permanent exhausted as one. The watchers those events wake go on the Chain
    as Pending items after the finalized ability (Core 383.3), one batch, the way the play
    transaction schedules what its costs woke."""
    import watchers
    events = paid["events"]
    if paid["death_batches"]:   # no payment kind of trigger_cost.py kills; a hand-built one is not modelled
        return {"failure": {**base, "valid": True, "committed": False, "unsupported": True, "stage": "trigger_cost",
                            "item_id": item_id, "reason": "trigger_cost_death_triggers_not_modelled"}}
    if not events:
        return {"timing": next_timing, "effect": next_effect, "scheduled": []}
    try:
        woken, next_effect = watchers.schedule_live(next_effect, events, turn_id=next_effect.get("turn_id", "turn-0"),
                                                    batch_label=f"trigger-cost:{item_id}",
                                                    turn_player=next_timing.get("turn_player"))
    except watchers.WatchUnsupported as exc:
        return {"failure": {**base, "valid": True, "committed": False, "unsupported": True, "stage": "trigger_cost",
                            "item_id": item_id, "reason": exc.reason_code, "message": str(exc)}}
    if not woken:
        return {"timing": next_timing, "effect": next_effect, "scheduled": []}
    for trigger in woken:
        trigger.update({"batch_sequence": 0, "batch_id": f"trigger-cost:{item_id}"})
    ordering = _settle_trigger_orders(woken, engine_decisions, base)
    if ordering is not None:
        return {"failure": {**ordering, "stage": "trigger_cost", "item_id": item_id}}
    scheduled = schedule_triggered_items(next_timing, woken)
    if scheduled.get("applied") is not True:
        return {"failure": {**base, "valid": scheduled.get("valid", True), "committed": False, "stage": "trigger_cost",
                            "item_id": item_id, "reason": scheduled.get("reason_code") or "trigger_schedule_failed",
                            "trigger_result": scheduled}}
    return {"timing": scheduled["next_state"], "effect": next_effect, "scheduled": [t["trigger_id"] for t in woken]}


def _lacking_choices(effect_state: dict[str, Any], controller: str, program: dict[str, Any]) -> list[str]:
    """Core 402.4: the choices this triggered ability must make now for which there are not enough legal
    options - a target with no legal object, a set of targets with fewer than its minimum, a pair of slots
    with no two different legal objects. The legality test is the one finalization applies to a choice
    (play_transaction._check_play_targets); only its answer to "is there any" is asked here."""
    from play_transaction import legal_target_options
    lacking = []
    for effect in program.get("effects") or []:
        target = effect.get("target")
        if isinstance(target, dict) and isinstance(target.get("decision_ref"), str) and "selection_ref" not in target:
            if not legal_target_options(effect_state, controller, program, target):
                lacking.append(target["decision_ref"])
        targets = effect.get("targets")
        if isinstance(targets, dict) and isinstance(targets.get("decision_ref"), str):
            restrictions = dict(targets.get("restrictions") or {})
            restrictions.setdefault("chosen_zone_class", "board")
            if len(legal_target_options(effect_state, controller, program, restrictions)) < int(targets.get("min", 0) or 0):
                lacking.append(targets["decision_ref"])
        units = [u for u in effect.get("units") or [] if isinstance(u, dict) and isinstance(u.get("decision_ref"), str)]
        if units:
            options = [legal_target_options(effect_state, controller, program, u) for u in units]
            if any(not o for o in options) or len({x for o in options for x in o}) < len(units):
                lacking += [u["decision_ref"] for u in units]
    return list(dict.fromkeys(lacking))


def _envelope_extras(engine_decisions: dict[str, Any] | None) -> dict[str, Any]:
    """What an engine-decisions envelope carries besides its decisions (randomization receipts, the
    chain item it is for), kept when the bridge rebuilds its decisions around recorded targets."""
    return {k: copy.deepcopy(v) for k, v in (engine_decisions or {}).items()
            if k not in ("schema_version", "input_hash", "decisions")}


def resolve_with_program(
    timing_state: dict[str, Any],
    item_id: str,
    effect_state: dict[str, Any],
    program: dict[str, Any] | None,
    cleanup_decisions: dict[str, Any] | None = None,
    engine_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": "riftbound-resolution-bridge-result.v1",
        "item_id": item_id,
        "input_timing_state_hash": state_hash(timing_state),
        "input_effect_state_hash": hash_value(effect_state),
    }
    if is_terminal(timing_state):
        return {**base, "valid": True, "committed": False, "stage": "terminal", "reason": "game_over", "reason_code": "game_over", "rule_locators": ["Core 196"]}
    chain_item = next((item for item in timing_state.get("chain", {}).get("items", []) if item.get("id") == item_id), None)
    if chain_item is None:
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "chain_item_not_found"}
    # ADR-0007 §1: a permanent with no rules text to execute resolves with no
    # program; its resolution is the entry procedure. A spell always needs one.
    if program is None:
        if chain_item.get("object_kind") not in {"unit", "gear"} or chain_item.get("effect_program_id"):
            return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_required"}
        program = {}
    bound_program = chain_item.get("effect_program_id")
    if bound_program is not None and program.get("program_id") != bound_program:
        return {
            **base,
            "valid": True,
            "committed": False,
            "stage": "program_binding",
            "reason": "effect_program_id_mismatch",
            "expected_program_id": bound_program,
            "received_program_id": program.get("program_id"),
        }
    # The ID names the program; a bound hash says it must still BE that program. A
    # body swapped under a correct ID is refused here rather than run.
    bound_hash = chain_item.get("effect_program_hash")
    if bound_hash is not None and program and program_hash(program) != bound_hash:
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_hash_mismatch",
                "expected_program_hash": bound_hash, "received_program_hash": program_hash(program)}
    if program.get("controller") is not None and program.get("controller") != chain_item.get("controller"):
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_controller_mismatch"}
    if program.get("source_object") is not None and chain_item.get("source_object") is not None and program.get("source_object") != chain_item.get("source_object"):
        return {**base, "valid": True, "committed": False, "stage": "program_binding", "reason": "effect_program_source_mismatch"}
    if program:
        program, refusal = bind_source_identity(program, chain_item)
        if refusal is not None:
            return {**base, "valid": True, "committed": False, "stage": "program_binding", **refusal}
    # Both components are pure. Probe timing first so an effect program is never
    # exposed as committed for an item that is not next to resolve.
    timing_result = complete_resolution(timing_state, item_id, effect_execution_confirmed=True)
    if timing_result.get("applied") is not True:
        return {
            **base,
            "valid": timing_result.get("valid", True),
            "committed": False,
            "stage": "timing",
            "reason": timing_result.get("reason_code", "timing_resolution_failed"),
            "timing_result": timing_result,
        }
    if decision_errors := validate_cleanup_decisions(cleanup_decisions):
        return {**base, "valid": False, "committed": False, "stage": "cleanup_decision", "errors": decision_errors, "reason": "; ".join(decision_errors)}
    # ADR-0005 §2 / ADR-0002 migration: the legacy cleanup-decisions object is
    # still read, converted into resolution-stage entries; writers emit only
    # engine-decisions.v1. Supplying both is ambiguous and refused.
    if engine_decisions is not None and cleanup_decisions is not None:
        return {**base, "valid": False, "committed": False, "stage": "cleanup_decision", "errors": ["supply engine_decisions or cleanup_decisions, not both"], "reason": "ambiguous decision envelopes"}
    if engine_decisions is None and cleanup_decisions is not None:
        engine_decisions = _ed.from_cleanup_decisions(cleanup_decisions, input_hash=hash_value(effect_state), controller=program.get("controller") or chain_item.get("controller") or "unknown")
    if decision_errors := _ed.validate_engine_decisions(engine_decisions):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": decision_errors, "reason": "; ".join(decision_errors)}
    if engine_decisions is not None and engine_decisions.get("input_hash") != hash_value(effect_state):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": ["engine_decisions.input_hash does not match the effect state"], "reason": "stale decision envelope"}
    if engine_decisions is not None and engine_decisions.get("chain_item_id") not in (None, item_id):
        return {**base, "valid": False, "committed": False, "stage": "engine_decision", "errors": ["engine_decisions.chain_item_id does not match the resolving item"], "reason": "decision envelope for another chain item"}
    # Targets bound at trigger finalization are the targets. Core 359.3.e: one that is
    # illegal by now is mistargeted and its instruction ignored - it is never re-chosen.
    # So a target selection supplied at resolution must BE the recorded one, and when
    # none is supplied the record is what the program runs with.
    finalized = chain_item.get("finalized_targets")
    if finalized is not None:
        recorded = {entry["decision_id"]: entry for entry in finalized}
        supplied = [entry for entry in ((engine_decisions or {}).get("decisions") or []) if entry.get("kind") == "target_selection"]
        # package 5 (2026-09-27): a board choice the program makes AS IT RESOLVES is not a target -
        # "You must recycle one of your runes." is chosen then (Core 355.10.f) - so a resolution-stage
        # selection for a choice's own decision_ref, never a target selector's, is not a re-chosen target
        effects = [e for e in (program or {}).get("effects") or [] if isinstance(e, dict)]
        target_refs = {s.get("decision_ref") for e in effects for s in (e.get("target"), e.get("targets"))
                       if isinstance(s, dict) and s.get("decision_ref")}
        choice_refs = {e.get("decision_ref") for e in effects if isinstance(e.get("choice"), dict) and e.get("decision_ref")} - target_refs
        # package 6 (2026-09-27): "Spend any number of buffs." chooses as it resolves by its own decision_ref too -
        # buffs are counters, not targets (Core 704.1, 355.17)
        from effect_ir import DECISION_REF_CHOICE_OPS
        choice_refs |= {e.get("decision_ref") for e in effects if e.get("op") in DECISION_REF_CHOICE_OPS
                        and e.get("decision_ref")} - target_refs
        resolution_choices = [entry for entry in supplied if entry.get("stage") == "resolution"
                              and entry.get("decision_id") in choice_refs and entry.get("decision_id") not in recorded]
        for entry in supplied:
            if entry in resolution_choices:
                continue
            kept = recorded.get(entry.get("decision_id"))
            if kept is None or entry.get("value") != kept.get("value") or (entry.get("selection_identities") or {}) != (kept.get("selection_identities") or {}):
                return {**base, "valid": True, "committed": False, "stage": "engine_decision", "reason": "target_changed_after_finalization",
                        "decision_id": entry.get("decision_id"), "rule_locators": ["Core 355.5", "Core 359.3.e.2", "Core 359.3.e.9"]}
        for entry in ((engine_decisions or {}).get("decisions") or []):
            kept = recorded.get(entry.get("decision_id"))
            if entry.get("kind") == "location_selection" and kept is not None and entry.get("value") != kept.get("value"):
                # GPT 2026-09-29, Core 355.15: the Move destination was chosen as the ability was finalized
                return {**base, "valid": True, "committed": False, "stage": "engine_decision", "reason": "destination_changed_after_finalization",
                        "decision_id": entry.get("decision_id"), "rule_locators": ["Core 355.4", "Core 355.15"]}
        others = [entry for entry in ((engine_decisions or {}).get("decisions") or []) if entry.get("kind") != "target_selection"
                  and entry.get("decision_id") not in recorded] + resolution_choices
        if finalized or others:
            # the rebuilt envelope keeps what else it carried - a randomization receipt (Core 416.5) is
            # not a decision, and dropping it left a trigger that recycles two cards unable to resolve
            engine_decisions = {**_envelope_extras(engine_decisions), "schema_version": "engine-decisions.v1",
                                "input_hash": hash_value(effect_state),
                                "decisions": [copy.deepcopy(entry) for entry in finalized] + others}
    # The same for a card's or an activated ability's own targets, chosen as it was played
    # (Core 355.5) and recorded on its chain entry: they cannot be changed after that step
    # (355.15). A selection supplied now for one of them must BE the recorded one; when none
    # is supplied the record is what the program runs with. Other decisions pass through.
    played = ((effect_state.get("chain_items") or {}).get(item_id) or {}).get("played_targets")
    if finalized is None and played:
        recorded = {entry["decision_id"]: entry for entry in played}
        supplied = list((engine_decisions or {}).get("decisions") or [])
        for entry in supplied:
            kept = recorded.get(entry.get("decision_id"))
            if kept is not None and kept.get("kind") == "location_selection":
                if entry.get("kind") != "location_selection" or entry.get("value") != kept.get("value"):
                    # GPT 2026-09-29, Core 355.15: the Move destination was chosen as the card was played
                    return {**base, "valid": True, "committed": False, "stage": "engine_decision", "reason": "destination_changed_after_play",
                            "decision_id": entry.get("decision_id"), "rule_locators": ["Core 355.4", "Core 355.15"]}
                continue
            if kept is not None and (entry.get("kind") != "target_selection" or entry.get("value") != kept.get("value")
                                     or (entry.get("selection_identities") or {}) != (kept.get("selection_identities") or {})):
                return {**base, "valid": True, "committed": False, "stage": "engine_decision", "reason": "target_changed_after_play",
                        "decision_id": entry.get("decision_id"), "rule_locators": ["Core 355.5", "Core 355.15", "Core 359.3.e.2"]}
        others = [entry for entry in supplied if entry.get("decision_id") not in recorded]
        engine_decisions = {**_envelope_extras(engine_decisions), "schema_version": "engine-decisions.v1",
                            "input_hash": hash_value(effect_state),
                            "decisions": [copy.deepcopy(entry) for entry in played] + others}
    order_map, choice_map = _ed.replacement_maps(engine_decisions)
    # ADR-0008 §5: a 'this combat' grant binds to the Combat in progress, which
    # only the timing state knows.
    combat_in_progress = timing_state.get("combat")
    context = {"combat": {"combat_id": combat_in_progress["combat_id"], "battlefield": combat_in_progress["battlefield"], "battlefield_identity": combat_in_progress["battlefield_identity"]}} if combat_in_progress and combat_in_progress.get("status") in ("open", "damage_assigned", "damage_dealt", "cleanup_done", "result_determined") else None
    # ADR-0011 §2: a mode chosen at play rides on the chain entry.
    entry_before = (effect_state.get("chain_items") or {}).get(item_id) or {}
    recorded_mode = entry_before.get("mode_selection")
    if recorded_mode is not None:
        context = {**(context or {}), "mode_selection": dict(recorded_mode)}
    if entry_before.get("repeat") is not None:
        context = {**(context or {}), "repeat": copy.deepcopy(entry_before["repeat"])}  # ADR-0011 §4: paid Repeats
    if entry_before.get("played_from_hidden"):
        # Core 811.1.d.3 (GPT 2026-09-27): the battlefield this card was played from Hidden at
        context = {**(context or {}), "hidden_battlefield": entry_before["played_from_hidden"]}
    # 2026-09-27: a base cost paid as the ability was finalized (Core 383.3.b.1) - the chain
    # item's receipt is what apply_program checks; resolution pays nothing again
    paid_cost = chain_item.get("trigger_cost_receipt")
    if program and paid_cost is not None:
        context = {**(context or {}), "trigger_base_cost_paid": paid_cost.get("cost_hash")}
    # The target selections the program runs with from the chain item's record were counted where
    # they were chosen (Core 355.14.c: a split's Targets against the damage available then, its
    # Bonus Damage included, 715.3); resolution does not count them again against a changed amount.
    counted = [entry["decision_id"] for entry in (finalized if finalized is not None else (played or []))
               if isinstance(entry, dict) and isinstance(entry.get("decision_id"), str)]
    if program and counted:
        context = {**(context or {}), "targets_counted_when_chosen": counted}
    # 2026-09-27 package 6: "Each player ..." runs in Turn Order from the Turn Player (Core 303.2.a) -
    # facts only the timing state holds. Given to a program that iterates over players, and to no other.
    if program and contains_each_player(program):
        context = {**(context or {}), "turn": {"turn_player": timing_state.get("turn_player"),
                                               "turn_order": list(timing_state.get("turn_order") or [])}}
    # 2026-09-27 package 6 (Core 359.3.e.16): this turn's Ending Step has begun (begin_ending_step
    # moved the turn to the Ending phase) - a delayed trigger "at the end of this turn" made now is
    # not generated
    ending_step = timing_state.get("ending_step") or {}
    if program and timing_state.get("phase") == "ending" and ending_step.get("turn_id") == effect_state.get("turn_id", DEFAULT_TURN_ID):
        context = {**(context or {}), "ending_step_begun": ending_step["turn_id"]}
    # GPT 2026-10-02 (package 6): a delayed trigger made by this resolution is this chain item's - two finalized
    # abilities of one source in one turn (two Conquers of Targon's Peak) make two, never one id twice
    if program and any(isinstance(e, dict) and e.get("op") == "create_delayed_trigger" for e in program.get("effects") or []):
        context = {**(context or {}), "creating_chain_item": item_id}
    if program:
        effect_result = apply_program(effect_state, program, decisions=engine_decisions, context=context)
    else:
        effect_result = {"committed": True, "next_state": copy.deepcopy(effect_state), "trace": [], "pending_triggers": []}
    if effect_result.get("committed") is not True:
        return {
            **base,
            "valid": effect_result.get("valid", True),
            "committed": False,
            "stage": "effect",
            "reason": effect_result.get("reason", "; ".join(effect_result.get("errors", [])) or "effect_program_failed"),
            "effect_result": effect_result,
        }
    # Core 157 / Codex ruling on C-15: after its instructions, a spell goes to
    # its owner's trash as a new object (124) and leaves the chain, and only
    # then does Cleanup run. A Unit or Gear on the chain enters the board at
    # finalization (359.2) by a procedure this bridge does not have.
    after_effect = effect_result["next_state"]
    chain_card_trace = []
    entry_triggers: list[dict[str, Any]] = []
    chain_entry = (after_effect.get("chain_items") or {}).get(item_id)
    # Core 419.4.a (GPT 2026-09-27): the play this item's card was made by is complete only now,
    # by its resolution; the event recorded at Finalize wakes the play watchers below
    played_event = copy.deepcopy((chain_entry or {}).get("played_event"))
    if chain_entry is not None and "card" not in chain_entry:
        # ADR-0011 §4 / Core 402: an activated ability has no card; it just
        # leaves the chain. Its source stays wherever the cost left it.
        after_effect = copy.deepcopy(after_effect)
        del after_effect["chain_items"][item_id]
        if not after_effect["chain_items"]:
            del after_effect["chain_items"]
        chain_card_trace.append({"ability_id": chain_entry["ability_id"], "source_object": chain_entry["source_object"], "chain_item_id": item_id, "no_card": True,
                                 "rule_locators": ["Core 377", "Core 402"]})
        chain_entry = None
    if chain_entry is not None and after_effect["objects"][chain_entry["card"]]["kind"] in {"unit", "gear"}:
        # ADR-0007 §1–2: the permanent entry procedure, then "When you play me".
        after_effect, entry_trace, entry_triggers = complete_permanent_play(after_effect, item_id, engine_decisions)
        if entry_trace.get("replacement_decision_required"):
            return {
                **base, "valid": True, "committed": False, "stage": "permanent_entry",
                "replacement_decision_required": True,
                "reason": entry_trace["reason"],
                "replacement_ids": entry_trace["replacement_ids"],
                "event_ids": entry_trace["event_ids"],
                "decision_controller": entry_trace["decision_controller"],
                "effect_result": effect_result,
            }
        if entry_trace.get("unsupported"):
            return {**base, "valid": True, "committed": False, "unsupported": True, "stage": "permanent_entry",
                    "reason_code": entry_trace["reason_code"], "reason": entry_trace["reason"], "effect_result": effect_result}
        if entry_trace.get("error"):
            return {**base, "valid": False, "committed": False, "stage": "permanent_entry", "errors": [entry_trace["error"]], "reason": entry_trace["error"], "effect_result": effect_result}
        chain_card_trace.append(entry_trace)
        chain_entry = None
    if chain_entry is not None:
        card = chain_entry["card"]
        after_effect = copy.deepcopy(after_effect)
        del after_effect["chain_items"][item_id]
        if not after_effect["chain_items"]:
            del after_effect["chain_items"]
        owner = after_effect["objects"][card]["owner"]
        after_effect["players"][owner]["zones"]["trash"].append(card)
        chain_card_trace.append({"card": card, "chain_item_id": item_id, "destination": f"{owner}.trash",
                                 "identity_after": _bump_identity(after_effect, card), "rule_locators": ["Core 157", "Core 124"]})
    # ADR-0011 §5 / Core 425.1: a countered item leaves the timing chain in the
    # same commit as the effect state that cleared it.
    countered = effect_result.get("countered_chain_items") or []
    countered_trace = []
    next_timing_after_counter = timing_result["next_state"]
    for countered_id in countered:
        removal = remove_chain_item(next_timing_after_counter, countered_id)
        if removal.get("applied") is not True:
            return {**base, "valid": removal.get("valid", True), "committed": False, "stage": "counter",
                    "reason": removal.get("reason_code") or "chain_item_removal_failed", "reason_code": removal.get("reason_code"),
                    "countered_chain_items": countered, "timing_result": removal, "effect_result": effect_result}
        next_timing_after_counter = removal["next_state"]
        countered_trace.append(removal["transition"])
    if countered:
        timing_result = {**timing_result, "next_state": next_timing_after_counter}
    # ADR-0010 §2, §4: a Draw that Burned Out to an immediate victory ends the
    # game inside this resolution. The typed event is written into the timing
    # state here, in the same commit as the effect state that produced it, and
    # the Cleanup and trigger scheduling that would follow are skipped.
    terminal_event = effect_result.get("terminal_event")
    if terminal_event is not None:
        final_timing_state = apply_terminal_event(timing_result["next_state"], after_effect, terminal_event)
        return {
            **base, "valid": True, "committed": True,
            "next_timing_state": final_timing_state, "next_timing_state_hash": state_hash(final_timing_state),
            "next_effect_state": after_effect, "next_effect_state_hash": hash_value(after_effect),
            "trace": {"effect": effect_result["trace"], "chain_card": chain_card_trace, "terminal": terminal_event,
                      "skipped_after_terminal": {"combat_designations": True, "lethal_cleanup": True, "trigger_schedule": True,
                                                 "pending_triggers": [t.get("trigger_id") for t in effect_result.get("pending_triggers", [])] + [t.get("trigger_id") for t in entry_triggers]},
                      "timing": timing_result["transition"]},
            "rule_locators": list(dict.fromkeys([locator for event in effect_result["trace"] for locator in event.get("rule_locators", [])] + ["Core 431.3.c.1", "Core 196"])),
        }
    # ADR-0008 §3 / Core 323.2: the Cleanup's step 2 comes before 3a/3b — while
    # a Combat is in progress, designations follow presence first, so a Unit
    # that just arrived is a Defender (Shield, alone) before lethal damage is
    # judged. Its Attack/Defend triggers batch before the death triggers.
    combat_sync_trace = None
    combat_sync_triggers: list[dict[str, Any]] = []
    next_timing_for_schedule = timing_result["next_state"]
    combat_record = timing_state.get("combat")
    if combat_record is not None and combat_record.get("status") in ("open", "damage_assigned", "damage_dealt", "cleanup_done", "result_determined"):
        from combat import sync_designations
        sync_index = int(combat_record.get("sync_count", 0))
        import watchers
        try:
            after_effect, next_record, combat_sync_trace, combat_sync_triggers = sync_designations(
                combat_record, after_effect, f"combat:{combat_record['combat_id']}:sync:{sync_index}", 0)
        except watchers.WatchUnsupported as exc:
            return {**base, "valid": True, "committed": False, "unsupported": True, "stage": "watchers",
                    "reason": str(exc), "reason_code": exc.reason_code}
        next_record["sync_count"] = sync_index + 1
        next_timing_for_schedule = copy.deepcopy(next_timing_for_schedule)
        next_timing_for_schedule["combat"] = next_record
    cleanup_result = perform_lethal_cleanup(
        after_effect,
        attributed_sources=[program.get("source_object")] if program.get("source_object") else [],
        replacement_event_order=order_map,
        replacement_choices=choice_map,
    )
    if cleanup_result.get("committed") is not True:
        return {
            **base,
            "valid": cleanup_result.get("valid", True),
            "committed": False,
            "stage": "cleanup",
            "reason": cleanup_result.get("reason", "; ".join(cleanup_result.get("errors", [])) or "lethal_cleanup_failed"),
            "effect_result": effect_result,
            "cleanup_result": cleanup_result,
        }
    final_effect_state = cleanup_result["next_state"]
    # 2026-09-27: Core 428.5.c, 428.5.c.1 - a Unit dying in a Cleanup counts as killed by the last spell or
    # ability to resolve before that Cleanup only when that one damaged the Unit; the player responsible for the
    # damage (its controller, 411.1) is responsible for the kill. A Unit this program never damaged died for no one's
    # action here (411.2): its event keeps responsible_player None
    damaged_here = {e.get("object") for e in effect_result.get("events") or [] if e.get("kind") == "damaged"}
    for event in cleanup_result.get("events") or []:
        if event.get("kind") == "died" and event.get("object") in damaged_here:
            event["responsible_player"] = program.get("controller")
            event["rule_locators"] = list(dict.fromkeys(list(event.get("rule_locators") or []) + ["Core 428.5.c", "Core 428.5.c.1"]))
    effect_triggers = [dict(trigger) for trigger in effect_result.get("pending_triggers", [])]
    # Play-completion triggers form one batch after the item's own effect
    # triggers and before anything the board-entry Cleanup raises (419.4.a).
    play_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in entry_triggers:
        trigger["batch_sequence"] = play_batch
        trigger["batch_id"] = f"play:{item_id}"
    effect_triggers += entry_triggers
    # step 2 designation triggers precede the Cleanup's 3a death triggers (323.2, 323.4)
    sync_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in combat_sync_triggers:
        trigger["batch_sequence"] = sync_batch
    effect_triggers += combat_sync_triggers
    cleanup_triggers = [dict(trigger) for trigger in cleanup_result.get("pending_triggers", [])]
    next_batch = max((trigger.get("batch_sequence", -1) for trigger in effect_triggers), default=-1) + 1
    for trigger in cleanup_triggers:
        trigger["batch_sequence"] = trigger.get("batch_sequence", 0) + next_batch
    # ADR-0005 §5 / Codex Q4 (b): "If this kills it" is a conditional reflexive
    # trigger. The spell has left the chain, Cleanup has killed (or not), and
    # 428.5.c attributes a Cleanup kill to the spell that dealt the damage
    # immediately before it. Only then is the Pending reflexive item built
    # (387–388); a death a replacement prevented builds nothing.
    conditional_trace = []
    conditional_triggers = []
    events = {e.get("effect_id"): e for e in effect_result.get("trace", [])}
    # Codex Round B, point 5: a caused-kill reflexive trigger and the death
    # triggers of the same Cleanup kill are simultaneously triggered — one
    # chronological batch, ordered by controller in Turn Order (383.3.d). The
    # batch is the Cleanup iteration that killed the object; for a Kill
    # instruction (428.5.b) it is the instruction's own batch.
    cleanup_kill_iteration = {e.get("object_id"): e.get("cleanup_iteration") for e in cleanup_result.get("trace", []) if e.get("op") == "kill" and e.get("outcome") in {"applied", "augmented_applied"}}
    cleanup_prefix = f"lethal-cleanup:{hash_value(after_effect).split(':', 1)[1][:12]}"
    all_batches = effect_triggers + cleanup_triggers

    def batch_for(killed_ids: list[str], event: dict[str, Any]) -> tuple[int, str]:
        if event.get("op") == "kill":
            return event.get("index", 0), f"{program.get('program_id')}:{event.get('effect_id')}"
        iteration = min(cleanup_kill_iteration.get(o, 0) for o in killed_ids)
        return iteration + next_batch, f"{cleanup_prefix}:{iteration}"

    for ct in program.get("conditional_triggers", []) or []:
        event = events.get(ct["condition"]["effect_id"], {})
        performed = action_performed(event)
        touched = [event["object_id"]] if isinstance(event.get("object_id"), str) else [x.get("object_id") for x in event.get("expansion_trace", []) if action_performed(x)]
        if event.get("op") == "kill":
            killed = [o for o in touched if performed]  # 428.5.b: a Kill instruction kills directly
            locators = ["Core 428.5.b", "Core 387.2", "Core 388.1"]
        else:
            killed = [o for o in touched if performed and o in cleanup_result.get("killed_objects", [])]
            locators = ["Core 428.5.c", "Core 428.5.c.1", "Core 387.2", "Core 388.1"]
        prevented = [o for o in touched if o in cleanup_result.get("stable_prevented_objects", [])]
        held = bool(killed)
        conditional_trace.append({
            "trigger_id": ct["trigger_id"], "condition": dict(ct["condition"]), "held": held,
            "action_performed": performed, "touched_objects": touched, "killed_objects": killed, "prevented_objects": prevented,
            "attributed_to": program.get("source_object"), "responsible_player": program.get("controller"), "rule_locators": locators,
        })
        if held:
            descriptor = {k: ct[k] for k in ("trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize")}
            batch_sequence, batch_id = batch_for(killed, event)
            descriptor.update({"trigger_kind": "reflexive", "batch_sequence": batch_sequence, "batch_id": batch_id,
                               "condition": dict(ct["condition"]), "killed_objects": killed})
            conditional_triggers.append(descriptor)
    # 2026-09-24: watchers ("When you stun one or more enemy units", "When a buffed friendly
    # unit dies", ...) wake on what this resolution actually did - the program's events and
    # its Cleanup's - once Cleanup has run, as the batch after its death triggers.
    import watchers
    # 2026-09-27 (package 6): the deaths this resolution is responsible for name what killed them and
    # who is responsible (Core 428.5) - what "When you kill a unit with a spell" reads (kill_attributed)
    watched_events = kill_attributed(list(effect_result.get("events") or []), list(cleanup_result.get("events") or []),
                                     killer=entry_before.get("card") or chain_item.get("source_object"),
                                     responsible=chain_item.get("controller"))
    if played_event is not None:
        # Core 419.4.a: "abilities that trigger on playing cards" - the card's play, completed by
        # this resolution (a countered card never gets here: 419.4.a.1). It is counted here too - which
        # of its player's plays this turn it is ("your second card in a turn"): a countered card was
        # not played, so it is never counted (GPT 2026-09-27, package 3 section 7 item 1)
        from effect_ir import record_card_played
        played_event["play_ordinal"] = record_card_played(final_effect_state, played_event["actor"])
        watched_events.append({**played_event, "completed_by": f"resolve:{item_id}",
                               "rule_locators": list(dict.fromkeys(list(played_event.get("rule_locators") or [])
                                                                   + ["Core 419.4.a", "Core 419.4.a.1"]))})
    watch_triggers: list[dict[str, Any]] = []
    if watched_events:
        try:
            watch_triggers, final_effect_state = watchers.schedule_live(
                final_effect_state, watched_events, turn_id=final_effect_state.get("turn_id", "turn-0"),
                batch_label=f"resolve:{item_id}", turn_player=timing_state.get("turn_player"))
        except watchers.WatchUnsupported as exc:
            return {**base, "valid": True, "committed": False, "unsupported": True, "stage": "watchers",
                    "reason": str(exc), "reason_code": exc.reason_code}
        watch_batch = max((t.get("batch_sequence", -1) for t in effect_triggers + cleanup_triggers + conditional_triggers),
                          default=-1) + 1
        # Core 383.3.d (GPT 2026-09-27): a watcher on the same action as other triggers joins their batch
        watchers.batch_with_same_action(watch_triggers, watched_events, effect_triggers + cleanup_triggers + conditional_triggers,
                                        own_sequence=watch_batch, own_id=f"watch:{item_id}")
    pending_triggers = effect_triggers + cleanup_triggers + conditional_triggers + watch_triggers
    # 2026-09-28 (package 6): a card this resolution played (Core 419.3) moved to the Chain at the
    # play's step 1 as its instruction executed (354), before anything this resolution triggered was
    # put on the Chain, so its Pending item comes first; its remaining steps wait until this
    # resolution is done (354.3) - finalize_limited_play takes them as the oldest Pending item
    limited_plays = effect_result.get("limited_plays") or []
    if limited_plays:
        added = add_limited_play_items(next_timing_for_schedule, limited_plays)
        if added.get("applied") is not True:
            return {**base, "valid": added.get("valid", True), "committed": False, "stage": "limited_play",
                    "reason": added.get("reason_code") or "; ".join(added.get("errors", [])) or "limited_play_items_refused",
                    "effect_result": effect_result, "limited_play_result": added}
        next_timing_for_schedule = added["next_state"]
    # Core 383.3.d: when one controller has several abilities triggered at
    # once, that controller orders them. The engine never picks: a missing or
    # colliding controller_order inside one batch is a decision_required
    # naming the controller, the batch and the trigger ids; a supplied
    # trigger_order decision (engine-decisions.v1) assigns 0..n-1 and the
    # resolution retries. Different controllers in one batch need no
    # decision — Turn Order settles them.
    ordering_failure = _settle_trigger_orders(pending_triggers, engine_decisions, base)
    if ordering_failure is not None:
        return ordering_failure
    scheduled_result = schedule_triggered_items(next_timing_for_schedule, pending_triggers)
    if scheduled_result.get("applied") is not True:
        return {
            **base,
            "valid": scheduled_result.get("valid", True),
            "committed": False,
            "stage": "trigger_schedule",
            "reason": scheduled_result.get("reason_code", "; ".join(scheduled_result.get("errors", [])) or "trigger_schedule_failed"),
            "effect_result": effect_result,
            "cleanup_result": cleanup_result,
            "trigger_result": scheduled_result,
        }
    final_timing_state = scheduled_result["next_state"]
    return {
        **base,
        "valid": True,
        "committed": True,
        "next_timing_state": final_timing_state,
        "next_timing_state_hash": scheduled_result["next_state_hash"],
        "next_effect_state": final_effect_state,
        "next_effect_state_hash": hash_value(final_effect_state),
        "trace": {
            **({"countered": countered_trace} if countered_trace else {}),
            "effect": effect_result["trace"],
            "chain_card": chain_card_trace,
            "cleanup": cleanup_result["trace"],
            "conditional_triggers": conditional_trace,
            "combat_designations": combat_sync_trace,
            "trigger_schedule": scheduled_result["transition"],
            "timing": timing_result["transition"],
        },
        "rule_locators": list(dict.fromkeys(
            [locator for event in effect_result["trace"] for locator in event.get("rule_locators", [])]
            + [locator for event in cleanup_result["trace"] for locator in event.get("rule_locators", [])]
            + [locator for event in conditional_trace for locator in event.get("rule_locators", [])]
            + scheduled_result.get("rule_locators", [])
            + timing_result.get("rule_locators", [])
        )),
    }


# 2026-09-28 (package 6): the failures of an effect-driven play's own steps that cancel it (Core 358.5)
# - its cost cannot be paid with the Add window closed (357.1), or its player cannot play cards now
# (054.1). Any other refusal is of a choice supplied for it, which its player makes again.
LIMITED_PLAY_CANCEL_REASONS = {"cost_unpayable", "play_prohibited"}
LIMITED_PLAY_RULES = ["Core 419.3", "Core 419.3.a", "Core 419.3.b", "Core 354.3", "Core 337.1"]


def finalize_limited_play(
    timing_state: dict[str, Any],
    effect_state: dict[str, Any],
    engine_decisions: dict[str, Any] | None = None,
    *,
    entry_location: dict[str, Any] | None = None,
    payment_context: dict[str, Any] | None = None,
    effect_program: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """2026-09-28 (package 6): the rest of an effect-driven play (Core 419.3). An effect's resolution
    took step 1 - its card is on the Chain as the oldest Pending item (Core 354, 354.3, 337.1) - and its
    controller now completes steps 2 to 5 through the play transaction, like any play but as the effect
    notes (419.3.b): the source and the permission are the effect's, its base cost is the card's
    printed one with the effect's change (356.1.b), and no timing permission is asked (419.3.a). A Unit
    enters where its controller chooses now (355.2; `entry_location`); Accelerate and every other
    optional cost are offered as usual (356.1.b.3).

    Committed, the item is Finalized; a Unit or Gear then resolves immediately (337.2) -
    complete_limited_play runs both. A decision the play still needs is returned, nothing changed.
    Its cost unpayable with the Add window closed, or its player unable to play cards, the play is
    cancelled (358.5): the card goes back where the effect took it from, as it was, and the item leaves
    the Chain - never Finalized, not countered. What the effect did before it stays (GPT 2026-09-25).
    Any other refusal is of a choice supplied for the play (an entry location the rules refuse), which
    its player makes again: nothing changes."""
    from play_transaction import DECISION_REASONS, DECLARATION_VERSION, LIMITED_PLAY_OVERRIDE, play_card
    from rules_core import finalize_oldest_pending, next_procedure
    from effect_ir import CORE_RULESET, FAQ_AS_OF
    base = {"schema_version": "riftbound-limited-play-result.v1",
            "input_timing_state_hash": state_hash(timing_state), "input_effect_state_hash": hash_value(effect_state)}
    step = next_procedure(timing_state)
    if step.get("procedure") != "finalize_oldest_pending":
        return {**base, "valid": True, "committed": False, "stage": "timing", "reason": "finalize_not_next", "next_procedure": step}
    item = next(i for i in timing_state["chain"]["items"] if i["status"] == "pending")
    if item.get("limited_play") is not True:
        return {**base, "valid": True, "committed": False, "stage": "timing", "reason": "pending_item_is_not_a_limited_play",
                "item_id": item["id"]}
    entry = (effect_state.get("chain_items") or {}).get(item["id"]) or {}
    record = entry.get("limited_play")
    card = entry.get("card")
    if not isinstance(record, dict) or card not in effect_state["objects"]:
        return {**base, "valid": False, "committed": False, "stage": "effect_state", "item_id": item["id"],
                "reason": "limited_play_record_missing", "errors": [f"the effect state has no limited play under {item['id']!r}"]}
    kind = effect_state["objects"][card]["kind"]
    named = record.get("entry_location")
    if named is not None:
        # the effect named the location ("play it here", Core 355.2.b): nothing to choose
        if entry_location is not None and entry_location != named:
            return {**base, "valid": True, "committed": False, "stage": "choices", "item_id": item["id"],
                    "reason": "entry_location_named_by_the_effect", "location": named, "rule_locators": ["Core 355.2.b"]}
        entry_location = named
    if kind == "unit" and entry_location is None:
        # Core 355.2: a Unit's location is chosen in the play's own step 2 - now
        controller = item["controller"]
        candidates = [{"kind": "base"}] + [{"kind": "battlefield", "battlefield": b} for b in sorted(effect_state["battlefields"])
                                           if effect_state["battlefields"][b].get("controller") == controller]
        return {**base, "valid": True, "committed": False, "stage": "choices", "item_id": item["id"],
                "reason": "entry_location_required", "decision_controller": controller,
                "location_candidates": candidates, "rule_locators": ["Core 355.2", "Core 355.2.a"]}
    declaration = {
        "schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": f"limited:{item['id']}", "actor": item["controller"], "card": card,
        "chain_item": {"id": item["id"], "object_kind": kind, "timing": "default"},
        "cost": {"base": copy.deepcopy(effect_state["objects"][card].get("printed_cost"))},
        "source": {"kind": record["source_zone"]}, "source_permission": {"granted_by": record["granted_by"]},
        "cost_override": {"kind": LIMITED_PLAY_OVERRIDE[record["cost_basis"]["kind"]], "source": record["granted_by"]},
        "timing_source": "limited_play",
        **({"payment_context": copy.deepcopy(payment_context)} if payment_context is not None else {}),
        **({"entry_location": copy.deepcopy(entry_location)} if entry_location is not None else {}),
        **({"effect_program_id": effect_program.get("program_id")} if effect_program is not None else {}),
    }
    played = play_card(timing_state, effect_state, declaration, engine_decisions=engine_decisions, effect_program=effect_program)
    if played.get("committed"):
        finalized = finalize_oldest_pending(played["next_timing_state"])
        if finalized.get("applied") is not True or (finalized.get("transition") or {}).get("item_id") != item["id"]:
            return {**base, "valid": finalized.get("valid", True), "committed": False, "stage": "timing", "item_id": item["id"],
                    "reason": finalized.get("reason_code") or "finalize_failed", "timing_result": finalized}
        next_timing = finalized["next_state"]
        return {**base, "valid": True, "committed": True, "item_id": item["id"], "card": card,
                "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
                "next_effect_state": played["next_effect_state"], "next_effect_state_hash": played["next_effect_state_hash"],
                "cost_receipt": played["cost_receipt"], "play_trace": played["trace"],
                "transition": finalized["transition"],
                "immediate_resolution_required": bool(finalized["transition"].get("immediate_resolution_required")),
                "rule_locators": list(dict.fromkeys(LIMITED_PLAY_RULES + played.get("rule_locators", [])))}
    if not played.get("valid"):
        return {**base, "valid": False, "committed": False, "stage": played.get("stage"), "item_id": item["id"],
                "reason": played.get("reason_code"), "errors": played.get("errors") or [played.get("reason")]}
    if played.get("reason_code") in DECISION_REASONS or played.get("reason_code") not in LIMITED_PLAY_CANCEL_REASONS:
        return {**base, "valid": True, "committed": False, "stage": played.get("stage"), "item_id": item["id"],
                "reason": played.get("reason_code"), "message": played.get("reason"),
                "unsupported": bool(played.get("unsupported")),
                **{k: played[k] for k in ("decision_ids", "decision_controller") if k in played},
                "rule_locators": played.get("rule_locators", [])}
    # Core 358.5: the play is cancelled - what its steps did is undone, the card back in the zone the
    # effect took it from, at its place there and as the object it was (a play that never happened)
    cancelled = copy.deepcopy(effect_state)
    del cancelled["chain_items"][item["id"]]
    if not cancelled["chain_items"]:
        del cancelled["chain_items"]
    zone = cancelled["players"][record["zone_owner"]]["zones"][record["source_zone"]]
    zone.insert(min(record["zone_index"], len(zone)), card)
    cancelled["objects"][card]["identity"] = record["identity_before"]
    cancelled["objects"][card]["controller"] = record["controller_before"]
    removal = remove_chain_item(timing_state, item["id"], reason="limited_play_cancelled")
    if removal.get("applied") is not True:
        return {**base, "valid": removal.get("valid", True), "committed": False, "stage": "timing", "item_id": item["id"],
                "reason": removal.get("reason_code") or "chain_item_removal_failed", "timing_result": removal}
    next_timing = removal["next_state"]
    return {**base, "valid": True, "committed": True, "removed": True, "item_id": item["id"], "card": card,
            "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
            "next_effect_state": cancelled, "next_effect_state_hash": hash_value(cancelled),
            "transition": {"type": "limited_play_cancelled", "item_id": item["id"], "reason_code": played.get("reason_code"),
                           "why": played.get("reason"), "never_finalized": True, "countered": False,
                           "card_returned_to": {"player": record["zone_owner"], "zone": record["source_zone"],
                                                "identity": record["identity_before"]}},
            "rule_locators": list(dict.fromkeys(["Core 358.5"] + LIMITED_PLAY_RULES + played.get("rule_locators", [])))}


def complete_limited_play(
    timing_state: dict[str, Any],
    effect_state: dict[str, Any],
    engine_decisions: dict[str, Any] | None = None,
    *,
    entry_location: dict[str, Any] | None = None,
    payment_context: dict[str, Any] | None = None,
    effect_program: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """2026-09-28 (package 6): finalize_limited_play, and - for a Unit or Gear, which resolves as soon as
    it is Finalized (Core 337.2) - its resolution: it enters the Board and "When you play me" triggers
    (359.2, 419.4.a). A Spell stays on the Chain, Finalized, and resolves when the players have passed
    (337.4, 340.1). The result carries both steps."""
    finalized = finalize_limited_play(timing_state, effect_state, engine_decisions, entry_location=entry_location,
                                      payment_context=payment_context, effect_program=effect_program)
    if finalized.get("committed") is not True or finalized.get("removed") or not finalized.get("immediate_resolution_required"):
        return {**finalized, "resolution": None}
    resolved = resolve_with_program(finalized["next_timing_state"], finalized["item_id"], finalized["next_effect_state"], None)
    if resolved.get("committed") is not True:
        return {**finalized, "committed": False, "stage": "resolution", "reason": resolved.get("reason") or resolved.get("reason_code"),
                "resolution": resolved, "next_timing_state": None, "next_effect_state": None}
    return {**finalized, "next_timing_state": resolved["next_timing_state"], "next_timing_state_hash": resolved["next_timing_state_hash"],
            "next_effect_state": resolved["next_effect_state"], "next_effect_state_hash": resolved["next_effect_state_hash"],
            "resolution": {k: resolved[k] for k in ("trace", "rule_locators") if k in resolved},
            "rule_locators": list(dict.fromkeys(finalized["rule_locators"] + ["Core 337.2"] + resolved.get("rule_locators", [])))}


def _settle_trigger_orders(pending_triggers: list[dict[str, Any]], engine_decisions: dict[str, Any] | None, base: dict[str, Any]) -> dict[str, Any] | None:
    """Core 383.3.d: one controller's simultaneously triggered abilities are
    ordered by that controller. Missing or colliding controller_order inside
    one batch is a decision_required; a supplied trigger_order decision
    assigns 0..n-1. Returns a failure result or None."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trigger in pending_triggers:
        groups.setdefault((trigger.get("batch_id"), trigger.get("controller")), []).append(trigger)

    def asked_first(kv):
        # the batches in the order they happened (batch_sequence), then by id and controller -
        # a play's cost batch is asked about before the play's own (fourth review 2026-09-26)
        sequences = [t.get("batch_sequence") for t in kv[1] if isinstance(t.get("batch_sequence"), int)]
        return (min(sequences) if sequences else 0, kv[0][0] or "", kv[0][1] or "")

    for (batch_id, controller), members in sorted(groups.items(), key=asked_first):
        if len(members) < 2:
            continue
        orders = [t.get("controller_order") for t in members]
        if all(isinstance(o, int) for o in orders) and len(set(orders)) == len(orders):
            continue
        trigger_ids = [t["trigger_id"] for t in members]
        decision = _ed.trigger_order(engine_decisions, batch_id, controller)
        decision_id = f"trigger_order:{batch_id}:{controller}"
        if decision is None:
            return {
                **base, "valid": True, "committed": False, "stage": "trigger_order",
                "reason_code": "trigger_order_required",
                "reason": f"{controller} has {len(members)} abilities triggered together in batch {batch_id}; their order is {controller}'s choice (Core 383.3.d)",
                "decision_ids": [decision_id], "decision_controller": controller,
                "batch_id": batch_id, "trigger_ids": trigger_ids,
                "rule_locators": ["Core 383.3.d", "Core 383.3.d.1"],
            }
        if decision["controller"] != controller:
            return {**base, "valid": True, "committed": False, "applied": False, "stage": "trigger_order", "reason_code": "decision_controller_mismatch",
                    "reason": f"trigger order for {controller} was supplied by {decision['controller']!r}", "batch_id": batch_id, "trigger_ids": trigger_ids}
        if sorted(decision["value"]) != sorted(trigger_ids):
            return {**base, "valid": False, "committed": False, "stage": "engine_decision",
                    "errors": [f"trigger_order {decision_id} must list exactly {sorted(trigger_ids)}, once each; got {decision['value']}"],
                    "reason": "trigger order decision does not match the batch"}
        for position, trigger_id in enumerate(decision["value"]):
            next(t for t in members if t["trigger_id"] == trigger_id)["controller_order"] = position
    return None


def entry_state_for(
    state: dict[str, Any], card: str, controller: str, event_id: str,
    engine_decisions: dict[str, Any] | None = None, chain_item: str | None = None,
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
    """Core 143.4 / 359.2.c–d defaults, then entry replacements (369.3): the
    object's own `entry_replacements` and this turn's `turn_effects` that set
    the entry state for units the controller plays (ADR-0007 §6). Returns
    (default, final, applied replacements)."""
    obj = state["objects"][card]
    default = "exhausted" if obj["kind"] == "unit" else "ready"
    candidates: list[dict[str, Any]] = []
    for index, replacement in enumerate(obj.get("entry_replacements", []) or []):
        # Core 805.2.b: a replacement bound to one play belongs to that play.
        # An unbound one (a printed entry replacement) applies as it always did.
        bound = replacement.get("chain_item")
        if bound is not None and bound != chain_item:
            continue
        if replacement.get("card") is not None and replacement["card"] != card:
            continue
        if replacement.get("condition") is not None:
            # 2026-09-27, Core 364.3.a / 369.3: "If an opponent controls a battlefield, I enter
            # ready." - a conditional replacement, read as the unit enters; one that cannot be
            # read is refused by name, never guessed
            from effect_ir import ConditionUnsupported, evaluate_condition
            try:
                if not evaluate_condition(state, replacement["condition"], controller=controller, object_id=card):
                    continue
            except ConditionUnsupported as exc:
                return default, default, [], {"error": f"the entry replacement's condition cannot be read here: {exc}"}
        if replacement.get("mode") == "entry_state" and replacement.get("value") in {"ready", "exhausted"}:
            candidates.append({"replacement_id": replacement.get("replacement_id", f"entry:{card}:{index}"),
                               "source": card, "mode": "entry_state", "value": replacement["value"], "rule_locators": ["Core 369.3"]})
    current_turn = state.get("turn_id", DEFAULT_TURN_ID)
    for effect in state.get("turn_effects", []) or []:
        if (effect.get("kind") == "entry_state_for_played_units" and effect.get("controller") == controller
                and effect.get("turn_id") == current_turn and obj["kind"] == "unit"
                and effect.get("value") in {"ready", "exhausted"}):
            candidates.append({"replacement_id": effect["effect_id"], "source": effect.get("source"),
                               "mode": "entry_state_for_played_units", "value": effect["value"],
                               "turn_id": effect.get("turn_id"), "rule_locators": ["Core 369.3"]})
    # 2026-09-27 package 6: what a permanent on the board grants the other Units its side plays
    # ("Other friendly units enter ready.", Core 369.3, 365.1)
    from effect_ir import granted_entry_states
    candidates.extend(granted_entry_states(state, card, obj["kind"], controller))
    if len({candidate["value"] for candidate in candidates}) > 1:
        order_map, _ = _ed.replacement_maps(engine_decisions)
        replacement_ids = [candidate["replacement_id"] for candidate in candidates]
        supplied = (order_map or {}).get(event_id)
        if supplied is None:
            return default, default, [], {
                "replacement_decision_required": True,
                "reason": f"conflicting entry-state replacements for {card} require {controller} to choose their order",
                "replacement_ids": replacement_ids, "event_ids": [event_id], "decision_controller": controller,
            }
        if len(supplied) != len(replacement_ids) or set(supplied) != set(replacement_ids):
            return default, default, [], {"error": f"replacement order for {event_id} must list exactly {replacement_ids}, once each"}
        by_id = {candidate["replacement_id"]: candidate for candidate in candidates}
        candidates = [by_id[replacement_id] for replacement_id in supplied]
    final = default
    applied: list[dict[str, Any]] = []
    for candidate in candidates:
        final = candidate["value"]
        applied.append(candidate)
    return default, final, applied, None


def complete_permanent_play(
    state: dict[str, Any], item_id: str, engine_decisions: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """ADR-0007 §1 (Core 359.2): the permanent leaves the chain and becomes a
    new object on the board (124); entry replacements apply; a Unit enters the
    location chosen at play, a Non-Unit Gear its controller's Base (359.2.d);
    the play is then complete and "When you play me" triggers are collected
    (419.4.a) for the caller to schedule before the board-entry Cleanup."""
    working = copy.deepcopy(state)
    entry = working["chain_items"][item_id]
    card, controller = entry["card"], entry["controller"]
    obj = working["objects"][card]
    location = entry.get("entry_location")
    if obj["kind"] == "unit" and location is None:
        return state, {"error": f"unit {card!r} on the chain has no entry_location; it is chosen at play (Core 355.2)"}, []
    if obj["kind"] == "gear" and location is not None and location.get("kind") != "base":
        return state, {"error": f"gear {card!r} may only enter its controller's Base (Core 359.2.d)"}, []
    del working["chain_items"][item_id]
    if not working["chain_items"]:
        del working["chain_items"]
    event_id = f"enter_board:{item_id}"
    default, final, replacements, entry_problem = entry_state_for(working, card, controller, event_id, engine_decisions, chain_item=item_id)
    if entry_problem is not None:
        return state, entry_problem, []
    obj["exhausted"] = final == "exhausted"
    # 2026-09-28: a replacement bound to this play (Accelerate, "the next unit you play enters ready")
    # is this play's and is done with once the card has entered; kept on the object, it applied
    # again to the same card played later under a reused chain item id - a new object (Core 124)
    drop_play_bound_replacements(obj, item_id)
    trace: dict[str, Any] = {"card": card, "chain_item_id": item_id, "kind": obj["kind"], "default_entry_state": default,
                             "entry_replacements": replacements, "entry_state": final, "not_a_move": True,
                             "rule_locators": ["Core 359.2", "Core 359.2.a", "Core 143.4", "Core 124", "Core 446.2"]}
    if obj["kind"] == "unit" and location["kind"] == "battlefield":
        battlefield = working["battlefields"][location["battlefield"]]
        battlefield["objects"].append(card)
        trace["destination"] = f"battlefield:{location['battlefield']}"
        trace["rule_locators"].append("Core 359.2.c")
        # Core 190.3.a.1: only if not already Contested - the first applier stays recorded
        from effect_ir import TeamContestUnsupported, apply_arrival_contested
        try:
            applier = apply_arrival_contested(working, location["battlefield"], card)
        except TeamContestUnsupported as exc:
            return state, {"unsupported": True, "reason_code": "team_contest_unsupported", "reason": str(exc)}, []
        if applier:
            trace["contested"] = {"battlefield": location["battlefield"], "contested_by": applier}
            trace["rule_locators"].append("Core 190.3.a.1")
    else:
        working["players"][controller]["zones"]["base"].append(card)
        trace["destination"] = f"{controller}.base"
        trace["rule_locators"].append("Core 359.2.c" if obj["kind"] == "unit" else "Core 359.2.d")
    trace["identity_after"] = _bump_identity(working, card)
    triggers = []
    inactive = []
    for descriptor in object_triggers(working, card, "play_triggers"):
        condition = descriptor.get("condition")
        if condition is not None and condition.get("kind") == "another_card_finalized_this_turn":
            # Core 812.1.c: the Legion text exists only while another card this
            # player Finalized this turn is on record; read as the play completes (419.4.a).
            from effect_ir import evaluate_condition
            if not evaluate_condition(working, condition, controller=controller, object_id=card):
                inactive.append({"trigger_id": descriptor["trigger_id"], "reason": "legion_not_active", "rule_locators": ["Core 812.1.c"]})
                continue
            descriptor = {k: v for k, v in descriptor.items() if k != "condition"}
        elif condition is not None and condition.get("kind") == "controls_units":
            # 2026-09-27 package 6 (Poro Herder): "if you control a Poro" right after the trigger
            # condition is part of it (Core 383.2.a.1) - read as the play completes; not met, the
            # ability does not trigger. Once on the Chain it resolves whatever happens to the Poro.
            from effect_ir import evaluate_condition
            if not evaluate_condition(working, condition, controller=controller, object_id=card):
                inactive.append({"trigger_id": descriptor["trigger_id"], "reason": "trigger_condition_not_met",
                                 "rule_locators": ["Core 383.2.a.1"]})
                continue
            descriptor = {k: v for k, v in descriptor.items() if k != "condition"}
        copied = copy.deepcopy(descriptor)
        copied.setdefault("trigger_kind", "triggered")
        copied["play_completion"] = item_id
        # the entered object's identity, as the attack path records it (combat.py): a program
        # that reads "here" or "me" is bound to THIS object, never to whatever sits at the id
        # later (2026-09-24, "When you play me, play a ... token here.")
        copied["source_identity"] = trace["identity_after"]
        triggers.append(copied)
    # Core 817.1.c: Vision triggers as the permanent enters the Board by being played
    from effect_ir import vision_triggers
    for descriptor in vision_triggers(working, card, controller):
        triggers.append({**descriptor, "trigger_kind": "triggered", "play_completion": item_id})
        trace.setdefault("rule_locators", []).append("Core 817.1.c")
    trace["play_triggers"] = [t["trigger_id"] for t in triggers]
    if inactive:
        trace["play_triggers_inactive"] = inactive
    trace["rule_locators"] += ["Core 419.4.a"] if triggers else []
    return working, trace, triggers


TURN_STEP_VERSION = "riftbound-turn-step-result.v1"


def _turn_base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": TURN_STEP_VERSION, "step": step,
            "input_timing_state_hash": state_hash(timing_state), "input_effect_state_hash": hash_value(effect_state)}


def begin_ending_step(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0007 §8 / Core 317.1: enter the Ending Step, evaluate "At the end of
    your turn" triggers of the turn player's board objects (383.1, with the
    383.2.a.1 condition checked now) and schedule them as one batch. Nothing
    expires here; that is run_expiration_step once the chain has emptied."""
    base = _turn_base("begin_ending_step", timing_state, effect_state)
    errors = [f"timing: {e}" for e in validate_timing_state(timing_state)] + [f"effect: {e}" for e in validate_state(effect_state)]
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "reason": "; ".join(errors)}
    if is_terminal(timing_state):
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "game_over", "reason": "the game ended; the snapshot is frozen (196)", "rule_locators": ["Core 196"]}
    if timing_state.get("phase") != "main":
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "ending_step_requires_main_phase", "reason": f"the Ending Step follows the Main Phase (316.9.b); phase is {timing_state.get('phase')!r}", "rule_locators": ["Core 316.9.b", "Core 317.1"]}
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"] or timing_state["showdown"]["active"]:
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "turn_not_quiet", "reason": "the chain, outstanding tasks and any showdown must be finished before the turn ends (316.9)", "rule_locators": ["Core 316.9", "Core 317.1"]}
    turn_player = timing_state["turn_player"]
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    descriptors: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    for object_id in sorted(effect_state["objects"]):
        obj = effect_state["objects"][object_id]
        for descriptor in object_triggers(effect_state, object_id, "end_of_turn_triggers"):
            record = {"trigger_id": descriptor["trigger_id"], "source_object": object_id, "controller": descriptor["controller"], "scheduled": False}
            # a board object, or (2026-09-27, Annie - Dark Child) a Legend in its controller's
            # Legend Zone, where a Legend's abilities work (Core 107.4, 174.7) - the same test
            # turn_cycle._phase_triggers makes for the Beginning Phase
            location = find_location(effect_state, object_id)
            in_legend_zone = (location is not None and location[0] == "player" and location[2] == "legend_zone"
                              and obj.get("kind") == "legend")
            if obj.get("controller") != turn_player or not (zone_class(location) == "board" or in_legend_zone):
                record["reason"] = "not the turn player's board object or Legend"
                evaluated.append(record); continue
            condition = descriptor.get("condition")
            if condition is not None and condition["kind"] == "at_battlefield":
                location = find_location(effect_state, object_id)
                if location is None or location[0] != "battlefield":
                    record["reason"] = "condition at_battlefield not met (383.2.a.1)"
                    evaluated.append(record); continue
            copied = {k: v for k, v in descriptor.items() if k != "condition"}
            copied.update({"trigger_kind": "triggered", "batch_sequence": 0, "batch_id": f"ending:{turn_id}", "ending_step": turn_id})
            descriptors.append(copied)
            record["scheduled"] = True
            evaluated.append(record)
    # ADR-0014 §2: delayed triggers waiting for the end of this turn fire here,
    # alongside the printed ones; one whose bound identity is gone is dropped
    # with its reason rather than fired on a stranger (Core 124).
    import watchers
    delayed, dropped = watchers.delayed_matches(effect_state, [], turn_id=turn_id, moment="end_of_turn")
    for entry in delayed:
        entry.update({"batch_sequence": 0, "batch_id": f"ending:{turn_id}", "ending_step": turn_id})
    descriptors.extend(delayed)
    ending_effect_state = watchers.settle_delayed(effect_state, delayed, dropped)
    failure = _settle_trigger_orders(descriptors, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    next_timing["phase"] = "ending"
    next_timing["priority"] = None
    next_timing["ending_step"] = {"status": "triggers_scheduled", "turn_id": turn_id, "scheduled_triggers": [d["trigger_id"] for d in descriptors]}
    scheduled = schedule_triggered_items(next_timing, descriptors)
    if scheduled.get("applied") is not True:
        return {**base, "valid": scheduled.get("valid", True), "committed": False, "applied": False, "reason_code": scheduled.get("reason_code", "trigger_schedule_failed"), "reason": "; ".join(scheduled.get("errors", [])) or scheduled.get("reason_code", "trigger_schedule_failed"), "trigger_result": scheduled}
    final_timing = scheduled["next_state"]
    return {**base, "valid": True, "committed": True, "applied": True, "reason_code": "ok",
            "next_timing_state": final_timing, "next_timing_state_hash": state_hash(final_timing),
            "next_effect_state": copy.deepcopy(ending_effect_state), "next_effect_state_hash": hash_value(ending_effect_state),
            "turn_id": turn_id, "trace": {"ending_triggers": evaluated, "trigger_schedule": scheduled.get("transition"),
                                          "delayed_triggers": [d["delayed_id"] for d in delayed], "delayed_dropped": dropped},
            "rule_locators": ["Core 316.9.b", "Core 317.1", "Core 317.1.a", "Core 383.1", "Core 383.2.a.1", "Core 124"]}


def run_expiration_step(timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    """ADR-0007 §8 / Core 317.2: one Ending Special Cleanup, only once the
    Ending Step's triggers are done, the chain is empty and no task is
    outstanding — 3c heal all Units, 3d every "this turn" effect of this
    turn expires at once, 3e every pool empties. Follow-up cleanups are
    normal Cleanups (324.2). The next Beginning Phase is not modelled."""
    base = _turn_base("run_expiration_step", timing_state, effect_state)
    errors = [f"timing: {e}" for e in validate_timing_state(timing_state)] + [f"effect: {e}" for e in validate_state(effect_state)]
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "reason": "; ".join(errors)}
    if is_terminal(timing_state):
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "game_over", "reason": "the game ended; the snapshot is frozen (196)", "rule_locators": ["Core 196"]}
    ending = timing_state.get("ending_step") or {}
    if timing_state.get("phase") != "ending" or ending.get("status") != "triggers_scheduled":
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "expiration_requires_ending_step", "reason": "the Expiration Step follows the Ending Step (317.2); begin_ending_step has not run for this turn", "rule_locators": ["Core 317.1", "Core 317.2"]}
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"]:
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "ending_triggers_unfinished", "reason": "end-of-turn chain items and outstanding tasks must finish before anything expires (317.1, 320)", "rule_locators": ["Core 317.1", "Core 320", "Core 317.2"]}
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    if ending.get("turn_id") not in (None, turn_id):
        return {**base, "valid": False, "committed": False, "errors": [f"ending_step is for turn {ending.get('turn_id')!r}, the effect state is turn {turn_id!r}"], "reason": "turn mismatch"}
    for effect in effect_state.get("turn_effects", []) or []:
        if effect["kind"] not in TURN_EFFECT_KINDS and effect.get("turn_id") == turn_id:
            return {**base, "valid": True, "committed": False, "unsupported": True, "reason": f"turn effect kind {effect['kind']!r} is not modelled; it cannot be expired safely"}
    working = copy.deepcopy(effect_state)
    healed = []
    for object_id, obj in working["objects"].items():
        if obj.get("kind") == "unit" and obj.get("damage", 0) > 0 and zone_class(find_location(working, object_id)) == "board":
            healed.append({"object_id": object_id, "damage": obj["damage"]})
            obj["damage"] = 0
    # ADR-0013 §1 / Core 317.2.c: this turn's continuous effects expire, with
    # the reason recorded; the canonical list is the only place they live.
    working = migrate_legacy_effects(working)
    expired_modifiers = []
    kept_effects = []
    for effect in working.get("continuous_effects", []):
        if effect["duration"]["kind"] == "this_turn" and effect["duration"].get("turn_id") == turn_id:
            expired_modifiers.append({"effect_id": effect["effect_id"], "kind": effect["kind"],
                                      "object_id": effect["affects"].get("object"), "removal": {"reason": "expired_this_turn", "turn_id": turn_id}})
        else:
            kept_effects.append(effect)
    working["continuous_effects"] = kept_effects
    expired_granted = [r["replacement_id"] for r in working["replacement_effects"] if "granted" in r and r["granted"].get("turn_id") == turn_id]
    working["replacement_effects"] = [r for r in working["replacement_effects"] if not ("granted" in r and r["granted"].get("turn_id") == turn_id)]
    expired_effects = [e for e in working.get("turn_effects", []) if e.get("turn_id") == turn_id]
    # Core 317.2.d / 423.2: a Stun is a "this turn" effect, so 3d is where it
    # ends. The status comes off with the entry that owned it, in the same
    # simultaneous step as every other expiry.
    unstunned = []
    for entry in expired_effects:
        if entry.get("kind") != "stunned_unit":
            continue
        obj = working["objects"].get(entry.get("object_id"))
        if isinstance(obj, dict) and obj.get("stunned"):
            obj["stunned"] = False
            unstunned.append(entry["object_id"])
    remaining = [e for e in working.get("turn_effects", []) if e.get("turn_id") != turn_id]
    if remaining:
        working["turn_effects"] = remaining
    else:
        working.pop("turn_effects", None)
    emptied = {}
    for player_id, player in working["players"].items():
        emptied[player_id] = copy.deepcopy(player["resources"])
        player["resources"] = {"energy": 0, "power": {}}
    next_timing = copy.deepcopy(timing_state)
    next_timing["ending_step"] = {**ending, "status": "expired"}
    return {**base, "valid": True, "committed": True, "applied": True, "reason_code": "ok", "turn_id": turn_id,
            "next_timing_state": next_timing, "next_timing_state_hash": state_hash(next_timing),
            "next_effect_state": working, "next_effect_state_hash": hash_value(working),
            "trace": {"heal_all_units": healed, "expire_this_turn": {"might_modifiers": expired_modifiers, "turn_effects": expired_effects, "granted_replacements": expired_granted, "unstunned": unstunned}, "empty_rune_pools": emptied,
                      "simultaneous": True, "follow_up_cleanup": "normal (324.2)"},
            "rule_locators": ["Core 317.2", "Core 317.2.a", "Core 317.2.b", "Core 317.2.c", "Core 317.2.d", "Core 324.2"]}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve one Chronicle Chain Item with a typed effect program")
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("item_id")
    parser.add_argument("effect_state", type=Path)
    parser.add_argument("program", type=Path)
    parser.add_argument("--cleanup-decisions", type=Path)
    args = parser.parse_args()
    try:
        result = resolve_with_program(
            _load(args.timing_state), args.item_id, _load(args.effect_state), _load(args.program),
            _load(args.cleanup_decisions) if args.cleanup_decisions else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("valid") and result.get("committed") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
