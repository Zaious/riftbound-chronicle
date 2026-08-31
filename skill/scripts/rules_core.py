#!/usr/bin/env python3
"""Chronicle-owned Riftbound timing and permission kernel.

This module deliberately implements a bounded rules layer, not a complete card
simulator.  It derives the four turn states, the next HOT/FEPR procedure, and
whether a proposed timing action is permitted by the supplied public state.
Official rules and scoped FAQs remain the authority; disagreements are kernel
conformance failures, never rule overrides.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "riftbound-rules-core-state.v1"
CORE_RULESET = "2026-07-16"
FAQ_AS_OF = "2026-08-14"

TIMINGS = {"default", "action", "reaction", "triggered"}
OBJECT_KINDS = {"spell", "unit", "gear", "ability"}
ITEM_STATUSES = {"pending", "finalized"}
ABILITY_KINDS = {"standard", "add", None}
CHAIN_ORIGINS = {"played_card", "activated_ability", "triggered_ability", "add_ability", None}

RULES = {
    "four_states": ["Core 308–310"],
    "priority": ["Core 312"],
    "focus": ["Core 313"],
    "cleanup_lock": ["Core 320–321"],
    "chain_exists": ["Core 328–331"],
    "hot_fepr": ["Core 333–340"],
    "showdown": ["Core 341–348"],
    "timing_check": ["Core 358.4"],
    "action": ["Core 806"],
    "reaction": ["Core 807"],
}


def state_hash(state: dict[str, Any]) -> str:
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _result(state: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {
        "schema_version": "riftbound-rules-core-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "state_label": state_label(state),
        "input_state_hash": state_hash(state),
        **values,
    }


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("valid") is not True:
        outcome = "unsupported"
    elif result.get("legal") is True:
        outcome = "supported_legal_timing"
    elif result.get("legal") is False:
        outcome = "supported_illegal_timing"
    else:
        outcome = "supported_procedure"
    digest = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "core_version": SCHEMA_VERSION,
        "coverage": "timing_permission_v1",
        "ruleset": result.get("ruleset", {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}),
        "input_state_hash": result.get("input_state_hash", ""),
        "state_label": result.get("state_label", "unknown"),
        "outcome": outcome,
        "reason_code": result.get("reason_code", result.get("procedure", "ok")),
        "rule_locators": result.get("rule_locators", []),
        "result_hash": f"sha256:{digest}",
    }


def _next_player(state: dict[str, Any], player: str) -> str:
    order = state["turn_order"]
    return order[(order.index(player) + 1) % len(order)]


def _open_after_empty_chain(state: dict[str, Any], origin: str | None) -> dict[str, Any]:
    state["chain"]["initiated_by"] = None
    state["chain"]["consecutive_passes"] = []
    if state["showdown"]["active"]:
        focus = state["showdown"]["focus"]
        if origin not in {"triggered_ability", "add_ability"}:
            focus = _next_player(state, focus)
            state["showdown"]["focus"] = focus
        state["priority"] = focus
    else:
        state["showdown"]["focus"] = None
        state["priority"] = state["turn_player"] if state.get("phase") == "main" else None
    return state


def validate_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if state.get("ruleset") != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("ruleset must match this v1 kernel baseline")
    players = state.get("players")
    if not isinstance(players, list) or len(players) < 2 or len(players) != len(set(players)):
        errors.append("players must contain at least two unique player ids")
        players = []
    turn_order = state.get("turn_order")
    if not isinstance(turn_order, list) or set(turn_order) != set(players):
        errors.append("turn_order must contain every player exactly once")
    if state.get("turn_player") not in players:
        errors.append("turn_player must be a player id")
    priority = state.get("priority")
    if priority is not None and priority not in players:
        errors.append("priority must be null or a player id")

    showdown = state.get("showdown")
    if not isinstance(showdown, dict) or not isinstance(showdown.get("active"), bool):
        errors.append("showdown.active must be boolean")
        showdown = {"active": False, "focus": None}
    focus = showdown.get("focus")
    if showdown.get("active") and focus not in players:
        errors.append("an active showdown must name a focus player")
    if not showdown.get("active") and focus is not None:
        errors.append("a neutral state cannot retain focus")

    tasks = state.get("outstanding_tasks")
    if not isinstance(tasks, list) or not all(isinstance(item, str) and item for item in tasks):
        errors.append("outstanding_tasks must be a list of non-empty strings")

    chain = state.get("chain")
    if not isinstance(chain, dict) or not isinstance(chain.get("items"), list):
        errors.append("chain.items must be a list")
        return errors
    if chain.get("initiated_by") not in CHAIN_ORIGINS:
        errors.append("chain.initiated_by is invalid")
    seen: set[str] = set()
    for index, item in enumerate(chain["items"]):
        label = f"chain.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{label}.id must be non-empty")
        elif item_id in seen:
            errors.append(f"{label}.id is duplicated")
        else:
            seen.add(item_id)
        if item.get("controller") not in players:
            errors.append(f"{label}.controller must be a player id")
        if item.get("object_kind") not in OBJECT_KINDS:
            errors.append(f"{label}.object_kind is invalid")
        if item.get("timing") not in TIMINGS:
            errors.append(f"{label}.timing is invalid")
        if item.get("status") not in ITEM_STATUSES:
            errors.append(f"{label}.status is invalid")
        if item.get("ability_kind") not in ABILITY_KINDS:
            errors.append(f"{label}.ability_kind is invalid")
        if item.get("timing") == "triggered":
            if not isinstance(item.get("source_object"), str) or not item.get("source_object"):
                errors.append(f"{label}.source_object is required for triggered items")
            if not isinstance(item.get("effect_program_id"), str) or not item.get("effect_program_id"):
                errors.append(f"{label}.effect_program_id is required for triggered items")
            if not isinstance(item.get("optional_at_finalize"), bool):
                errors.append(f"{label}.optional_at_finalize is required for triggered items")
            if item.get("trigger_kind") not in {"triggered", "self_death", "reflexive"}:
                errors.append(f"{label}.trigger_kind is invalid")
            if not isinstance(item.get("batch_sequence"), int) or item.get("batch_sequence", -1) < 0:
                errors.append(f"{label}.batch_sequence is invalid")
            if not isinstance(item.get("batch_id"), str) or not item.get("batch_id"):
                errors.append(f"{label}.batch_id is invalid")
    passes = chain.get("consecutive_passes", [])
    if not isinstance(passes, list) or any(player not in players for player in passes):
        errors.append("chain.consecutive_passes must contain only player ids")
    elif len(passes) != len(set(passes)) or len(passes) > len(players):
        errors.append("chain.consecutive_passes cannot duplicate or exceed players")
    if showdown.get("active") and not chain["items"] and not tasks and focus in players and priority != focus:
        errors.append("Showdown Open without Outstanding Tasks must give Priority to the Focus holder")
    return errors


def state_label(state: dict[str, Any]) -> str:
    showdown = bool(state.get("showdown", {}).get("active"))
    closed = bool(state.get("chain", {}).get("items"))
    return f"{'showdown' if showdown else 'neutral'}_{'closed' if closed else 'open'}"


def next_procedure(state: dict[str, Any]) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, errors=errors)
    tasks = state["outstanding_tasks"]
    items = state["chain"]["items"]
    pending = [item for item in items if item["status"] == "pending"]
    if tasks:
        return _result(
            state,
            valid=True,
            procedure="handle_outstanding_tasks",
            subject=tasks[0],
            discretionary_actions_allowed=False,
            rule_locators=RULES["hot_fepr"],
        )
    if pending:
        return _result(
            state,
            valid=True,
            procedure="finalize_oldest_pending",
            subject=pending[0]["id"],
            discretionary_actions_allowed=False,
            rule_locators=RULES["hot_fepr"],
        )
    if items:
        passes = state["chain"].get("consecutive_passes", [])
        if len(passes) >= len(state["players"]):
            return _result(
                state,
                valid=True,
                procedure="resolve_newest_finalized",
                subject=items[-1]["id"],
                discretionary_actions_allowed=False,
                rule_locators=["Core 339.1", "Core 340.1–340.4"],
            )
        return _result(
            state,
            valid=True,
            procedure="execute_or_pass_priority",
            subject=state["priority"],
            discretionary_actions_allowed=True,
            rule_locators=["Core 338–339"],
        )
    if state["showdown"]["active"]:
        return _result(
            state,
            valid=True,
            procedure="showdown_focus_window",
            subject=state["showdown"]["focus"],
            discretionary_actions_allowed=True,
            rule_locators=RULES["showdown"],
        )
    return _result(
        state,
        valid=True,
        procedure="neutral_turn_window",
        subject=state["turn_player"],
        discretionary_actions_allowed=state.get("phase") == "main",
        rule_locators=["Core 310.1.a", "Core 312.2.a", "Core 316"],
    )


def derive_permissions(state: dict[str, Any]) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, errors=errors)
    procedure = next_procedure(state)
    permissions = {
        player: {"play_timings": [], "activate_timings": [], "may_pass_priority": False, "may_pass_focus": False}
        for player in state["players"]
    }
    if not procedure.get("discretionary_actions_allowed"):
        return _result(
            state,
            valid=True,
            procedure=procedure["procedure"],
            permissions=permissions,
            rule_locators=procedure.get("rule_locators", []),
        )
    label = state_label(state)
    actor = state["priority"]
    if actor not in permissions:
        return _result(state, valid=True, procedure=procedure["procedure"], permissions=permissions, rule_locators=RULES["priority"])
    if label.endswith("closed"):
        permissions[actor]["play_timings"] = ["reaction"]
        permissions[actor]["activate_timings"] = ["reaction"]
        permissions[actor]["may_pass_priority"] = True
        locators = ["Core 309.1.a", "Core 338–339", "Core 358.4", "Core 807"]
    elif label == "showdown_open":
        permissions[actor]["play_timings"] = ["action", "reaction"]
        permissions[actor]["activate_timings"] = ["action", "reaction"]
        permissions[actor]["may_pass_focus"] = True
        locators = ["Core 308.1.a", "Core 313", "Core 347", "Core 806–807"]
    elif state.get("phase") == "main" and actor == state["turn_player"]:
        permissions[actor]["play_timings"] = ["default", "action", "reaction"]
        permissions[actor]["activate_timings"] = ["default", "action", "reaction"]
        locators = ["Core 310.1.a", "Core 312.2.a", "Core 316"]
    else:
        locators = ["Core 310.1.a", "Core 312"]
    return _result(
        state,
        valid=True,
        procedure=procedure["procedure"],
        permissions=permissions,
        rule_locators=locators,
    )


def validate_timing(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, legal=None, errors=errors)
    actor = action.get("actor")
    kind = action.get("kind")
    timing = action.get("timing", "default")
    if actor not in state["players"]:
        return _result(state, valid=True, legal=False, reason_code="unknown_actor", explanation="Actor is not a player in this state.", rule_locators=[])
    if timing not in TIMINGS:
        return _result(state, valid=True, legal=False, reason_code="unknown_timing", explanation="Timing must be default, action, or reaction.", rule_locators=[])

    procedure = next_procedure(state)
    if not procedure.get("discretionary_actions_allowed"):
        return _result(
            state,
            valid=True,
            legal=False,
            reason_code="procedure_blocks_discretionary_action",
            explanation=f"The next required procedure is {procedure.get('procedure')}; discretionary play is not available yet.",
            rule_locators=RULES["hot_fepr"] + RULES["cleanup_lock"],
        )

    label = state_label(state)
    priority = state["priority"]
    focus = state["showdown"]["focus"]
    if kind == "pass_priority":
        legal = label.endswith("closed") and actor == priority
        return _result(
            state,
            valid=True,
            legal=legal,
            reason_code="ok" if legal else "priority_required",
            explanation="The player with Priority may pass during a Closed state." if legal else "Only the current Priority holder may pass Priority during a Chain.",
            rule_locators=["Core 338.1.b", "Core 339"],
        )
    if kind == "pass_focus":
        legal = label == "showdown_open" and actor == focus and actor == priority
        return _result(
            state,
            valid=True,
            legal=legal,
            reason_code="ok" if legal else "focus_and_priority_required",
            explanation="The Focus holder may pass in a Showdown Open state." if legal else "Passing Focus requires both Focus and Priority in a Showdown Open state.",
            rule_locators=["Core 313", "Core 347.2"],
        )
    if kind not in {"play_card", "activate_ability"}:
        return _result(state, valid=True, legal=False, reason_code="unsupported_action_kind", explanation="This v1 kernel only validates play, activation, and pass timing.", rule_locators=[])

    if actor != priority:
        return _result(
            state,
            valid=True,
            legal=False,
            reason_code="priority_required",
            explanation="The proposed actor does not currently have Priority.",
            rule_locators=RULES["priority"],
        )
    if label.endswith("closed"):
        legal = timing == "reaction"
        return _result(
            state,
            valid=True,
            legal=legal,
            reason_code="ok" if legal else "reaction_required_in_closed_state",
            explanation="Only Reaction cards or abilities may be added while a Chain exists.",
            rule_locators=["Core 309.1.a", "Core 338.1.a", "Core 358.4", "Core 807"],
        )
    if label == "showdown_open":
        if actor != focus:
            return _result(
                state,
                valid=True,
                legal=False,
                reason_code="focus_required",
                explanation="Only the player with Focus may start the next Chain in a Showdown Open state.",
                rule_locators=RULES["focus"] + RULES["showdown"],
            )
        legal = timing in {"action", "reaction"}
        return _result(
            state,
            valid=True,
            legal=legal,
            reason_code="ok" if legal else "action_or_reaction_required_in_showdown",
            explanation="A Showdown Open state permits cards and abilities with Action or Reaction.",
            rule_locators=["Core 308.1.a", "Core 313.1", "Core 347.1", "Core 806–807"],
        )
    legal = state.get("phase") == "main" and actor == state["turn_player"]
    return _result(
        state,
        valid=True,
        legal=legal,
        reason_code="ok" if legal else "neutral_open_turn_window_required",
        explanation="By default, the Turn Player with Priority may play cards or activate abilities during the Main Phase in Neutral Open.",
        rule_locators=["Core 310.1.a", "Core 312.2.a", "Core 316"],
    )


def finalize_oldest_pending(state: dict[str, Any], *, perform_optional_trigger: bool | None = None) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, errors=errors)
    next_step = next_procedure(state)
    if next_step.get("procedure") != "finalize_oldest_pending":
        return _result(state, valid=True, applied=False, reason_code="finalize_not_next", next_procedure=next_step)
    original_item = next(item for item in state["chain"]["items"] if item["status"] == "pending")
    optional_trigger = original_item.get("timing") == "triggered" and original_item.get("optional_at_finalize") is True
    if optional_trigger and perform_optional_trigger is None:
        return _result(
            state,
            valid=True,
            applied=False,
            reason_code="trigger_finalize_choice_required",
            choices=["perform", "decline"],
            subject=original_item["id"],
            rule_locators=["Core 383.3.a–383.3.a.3"],
        )
    if not optional_trigger and perform_optional_trigger is not None:
        return _result(
            state,
            valid=True,
            applied=False,
            reason_code="unexpected_trigger_finalize_choice",
            subject=original_item["id"],
        )
    if optional_trigger and perform_optional_trigger is False:
        new_state = copy.deepcopy(state)
        origin = new_state["chain"].get("initiated_by")
        new_state["chain"]["items"] = [item for item in new_state["chain"]["items"] if item["id"] != original_item["id"]]
        new_state["chain"]["consecutive_passes"] = []
        if not new_state["chain"]["items"]:
            _open_after_empty_chain(new_state, origin)
        elif not any(item["status"] == "pending" for item in new_state["chain"]["items"]):
            new_state["priority"] = new_state["chain"]["items"][-1]["controller"]
        return _result(
            state,
            valid=True,
            applied=True,
            next_state=new_state,
            next_state_hash=state_hash(new_state),
            transition={"type": "optional_trigger_declined", "item_id": original_item["id"], "considered_triggered": False},
            next_procedure=next_procedure(new_state),
            rule_locators=["Core 383.3.a–383.3.a.3"],
        )
    new_state = copy.deepcopy(state)
    item = next(item for item in new_state["chain"]["items"] if item["status"] == "pending")
    item["status"] = "finalized"
    immediate = item["object_kind"] in {"unit", "gear"} or item.get("ability_kind") == "add"
    if not immediate and not any(candidate["status"] == "pending" for candidate in new_state["chain"]["items"]):
        new_state["priority"] = new_state["chain"]["items"][-1]["controller"]
    return _result(
        new_state,
        valid=True,
        applied=True,
        next_state=new_state,
        transition={
            "type": "chain_item_finalized",
            "item_id": item["id"],
            "optional_trigger_performed": True if optional_trigger else None,
            "immediate_resolution_required": immediate,
            "effect_execution_owned": False,
        },
        rule_locators=["Core 337.1–337.4", "Core 429.2.a"] if immediate else ["Core 337.1–337.4"],
    )


def add_pending_item(state: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, errors=errors)
    item = proposal.get("item")
    if not isinstance(item, dict):
        return _result(state, valid=True, applied=False, reason_code="missing_chain_item")
    action = {
        "actor": proposal.get("actor"),
        "kind": proposal.get("kind"),
        "timing": item.get("timing"),
        "object_kind": item.get("object_kind"),
    }
    verdict = validate_timing(state, action)
    if verdict.get("legal") is not True:
        return _result(state, valid=True, applied=False, reason_code=verdict.get("reason_code"), legality=verdict)
    candidate = copy.deepcopy(item)
    candidate["controller"] = proposal.get("actor")
    candidate["status"] = "pending"
    probe = copy.deepcopy(state)
    probe["chain"]["items"].append(candidate)
    if state["chain"]["items"] == []:
        origin = proposal.get("initiated_by") or ("activated_ability" if proposal.get("kind") == "activate_ability" else "played_card")
        probe["chain"]["initiated_by"] = origin
    probe["chain"]["consecutive_passes"] = []
    if found := validate_state(probe):
        return _result(state, valid=True, applied=False, reason_code="invalid_chain_item", errors=found)
    return _result(
        state,
        valid=True,
        applied=True,
        next_state=probe,
        next_state_hash=state_hash(probe),
        transition={"type": "pending_chain_item_added", "item_id": candidate["id"], "controller": candidate["controller"]},
        next_procedure=next_procedure(probe),
        rule_locators=["Core 328–330", "Core 334–337", "Core 358.4"],
    )


def pass_priority(state: dict[str, Any], actor: str) -> dict[str, Any]:
    verdict = validate_timing(state, {"actor": actor, "kind": "pass_priority", "timing": "default"})
    if verdict.get("legal") is not True:
        return _result(state, valid=verdict.get("valid", True), applied=False, reason_code=verdict.get("reason_code"), legality=verdict)
    new_state = copy.deepcopy(state)
    passes = new_state["chain"]["consecutive_passes"]
    if actor in passes:
        return _result(state, valid=True, applied=False, reason_code="non_consecutive_duplicate_pass")
    passes.append(actor)
    all_passed = len(passes) == len(new_state["players"])
    if not all_passed:
        new_state["priority"] = _next_player(new_state, actor)
    transition = {
        "type": "priority_passed",
        "actor": actor,
        "next_priority": None if all_passed else new_state["priority"],
        "all_players_passed": all_passed,
    }
    return _result(
        state,
        valid=True,
        applied=True,
        next_state=new_state,
        next_state_hash=state_hash(new_state),
        transition=transition,
        next_procedure=next_procedure(new_state),
        rule_locators=["Core 338.1.b", "Core 339"],
    )


def complete_resolution(state: dict[str, Any], item_id: str, *, effect_execution_confirmed: bool) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, errors=errors)
    items = state["chain"]["items"]
    match = next((item for item in items if item["id"] == item_id), None)
    if match is None or match["status"] != "finalized":
        return _result(state, valid=True, applied=False, reason_code="finalized_item_required")
    immediate = match["object_kind"] in {"unit", "gear"} or match.get("ability_kind") == "add"
    expected = next_procedure(state)
    ordinary_ready = expected.get("procedure") == "resolve_newest_finalized" and items[-1]["id"] == item_id
    if not immediate and not ordinary_ready:
        return _result(state, valid=True, applied=False, reason_code="resolution_not_next", next_procedure=expected)
    if not effect_execution_confirmed:
        return _result(
            state,
            valid=True,
            applied=False,
            reason_code="effect_execution_confirmation_required",
            explanation="The timing core never invents a card-effect result; the caller must supply or confirm effect execution.",
        )
    if immediate:
        earlier_pending = any(item["status"] == "pending" for item in items[: items.index(match)])
        if earlier_pending:
            return _result(state, valid=True, applied=False, reason_code="older_pending_item_must_finalize_first")
    origin = state["chain"].get("initiated_by")
    new_state = copy.deepcopy(state)
    new_state["chain"]["items"] = [item for item in new_state["chain"]["items"] if item["id"] != item_id]
    new_state["chain"]["consecutive_passes"] = []
    if not new_state["chain"]["items"]:
        _open_after_empty_chain(new_state, origin)
    elif not any(item["status"] == "pending" for item in new_state["chain"]["items"]):
        new_state["priority"] = new_state["chain"]["items"][-1]["controller"]
    transition = {
        "type": "immediate_item_resolution_completed" if immediate else "chain_item_resolution_completed",
        "item_id": item_id,
        "effect_execution_confirmed": True,
        "chain_empty": not bool(new_state["chain"]["items"]),
        "focus_before": state["showdown"].get("focus"),
        "focus_after": new_state["showdown"].get("focus"),
    }
    return _result(
        state,
        valid=True,
        applied=True,
        next_state=new_state,
        next_state_hash=state_hash(new_state),
        transition=transition,
        next_procedure=next_procedure(new_state),
        rule_locators=["Core 337.2", "Core 340", "Core 346", "Core 429.2.a"] if immediate else ["Core 339.1", "Core 340", "Core 346"],
    )


def schedule_triggered_items(state: dict[str, Any], descriptors: list[dict[str, Any]]) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        return _result(state, valid=False, applied=False, errors=errors)
    if not descriptors:
        return _result(state, valid=True, applied=True, next_state=copy.deepcopy(state), next_state_hash=state_hash(state), transition={"type": "no_triggers"})
    seen: set[str] = set()
    batches: dict[tuple[int, str], dict[str, list[dict[str, Any]]]] = {}
    descriptor_errors = []
    for index, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, dict):
            descriptor_errors.append(f"descriptor {index} must be an object")
            continue
        trigger_id = descriptor.get("trigger_id")
        controller = descriptor.get("controller")
        if not isinstance(trigger_id, str) or not trigger_id or trigger_id in seen:
            descriptor_errors.append(f"descriptor {index} has invalid or duplicate trigger_id")
        else:
            seen.add(trigger_id)
        if controller not in state["players"]:
            descriptor_errors.append(f"descriptor {index} has unknown controller")
            continue
        if not isinstance(descriptor.get("source_object"), str) or not descriptor.get("source_object"):
            descriptor_errors.append(f"descriptor {index} must preserve source_object")
        if not isinstance(descriptor.get("effect_program_id"), str) or not descriptor.get("effect_program_id"):
            descriptor_errors.append(f"descriptor {index} must bind effect_program_id")
        if not isinstance(descriptor.get("optional_at_finalize", False), bool):
            descriptor_errors.append(f"descriptor {index}.optional_at_finalize must be boolean")
        batch_sequence = descriptor.get("batch_sequence", 0)
        batch_id = descriptor.get("batch_id", f"batch-{batch_sequence}")
        if not isinstance(batch_sequence, int) or batch_sequence < 0 or not isinstance(batch_id, str) or not batch_id:
            descriptor_errors.append(f"descriptor {index} has invalid trigger batch")
            continue
        descriptor["batch_sequence"] = batch_sequence
        descriptor["batch_id"] = batch_id
        batches.setdefault((batch_sequence, batch_id), {}).setdefault(controller, []).append(descriptor)
    for (batch_sequence, batch_id), groups in batches.items():
        for controller, values in groups.items():
            if len(values) > 1:
                orders = [value.get("controller_order") for value in values]
                if any(not isinstance(order, int) or order < 0 for order in orders) or len(orders) != len(set(orders)):
                    descriptor_errors.append(f"batch {batch_id} controller {controller} must provide unique non-negative controller_order values")
            else:
                values[0].setdefault("controller_order", 0)
    if descriptor_errors:
        return _result(state, valid=True, applied=False, reason_code="trigger_order_required", errors=descriptor_errors)

    order = state["turn_order"]
    start = order.index(state["turn_player"])
    rotated = order[start:] + order[:start]
    ordered = []
    batch_trace = []
    for (batch_sequence, batch_id), groups in sorted(batches.items(), key=lambda entry: (entry[0][0], entry[0][1])):
        batch_ordered = []
        for controller in rotated:
            batch_ordered.extend(sorted(groups.get(controller, []), key=lambda value: value["controller_order"]))
        ordered.extend(batch_ordered)
        batch_trace.append({
            "batch_sequence": batch_sequence,
            "batch_id": batch_id,
            "ordered_trigger_ids": [descriptor["trigger_id"] for descriptor in batch_ordered],
            "controller_blocks": [controller for controller in rotated if controller in groups],
        })

    new_state = copy.deepcopy(state)
    was_empty = not new_state["chain"]["items"]
    for descriptor in ordered:
        new_state["chain"]["items"].append({
            "id": descriptor["trigger_id"],
            "controller": descriptor["controller"],
            "object_kind": "ability",
            "timing": "triggered",
            "status": "pending",
            "ability_kind": "standard",
            "source_object": descriptor["source_object"],
            "effect_program_id": descriptor.get("effect_program_id"),
            "optional_at_finalize": descriptor.get("optional_at_finalize", False),
            "trigger_kind": descriptor.get("trigger_kind", "triggered"),
            "batch_sequence": descriptor["batch_sequence"],
            "batch_id": descriptor["batch_id"],
        })
    if was_empty:
        new_state["chain"]["initiated_by"] = "triggered_ability"
    new_state["chain"]["consecutive_passes"] = []
    if found := validate_state(new_state):
        return _result(state, valid=True, applied=False, reason_code="scheduled_trigger_state_invalid", errors=found)
    return _result(
        state,
        valid=True,
        applied=True,
        next_state=new_state,
        next_state_hash=state_hash(new_state),
        transition={
            "type": "triggered_items_scheduled",
            "ordered_trigger_ids": [descriptor["trigger_id"] for descriptor in ordered],
            "batches": batch_trace,
        },
        next_procedure=next_procedure(new_state),
        rule_locators=["Core 383.3", "Core 383.3.c–383.3.d.1", "Core 428.1.a.1.b"],
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Chronicle sovereign Riftbound timing/permission kernel")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "next", "permissions"):
        item = sub.add_parser(name)
        item.add_argument("state", type=Path)
    finalized = sub.add_parser("finalize")
    finalized.add_argument("state", type=Path)
    trigger_choice = finalized.add_mutually_exclusive_group()
    trigger_choice.add_argument("--perform-trigger", action="store_true")
    trigger_choice.add_argument("--decline-trigger", action="store_true")
    timing = sub.add_parser("validate-timing")
    timing.add_argument("state", type=Path)
    timing.add_argument("action", type=Path)
    add = sub.add_parser("add")
    add.add_argument("state", type=Path)
    add.add_argument("proposal", type=Path)
    passed = sub.add_parser("pass-priority")
    passed.add_argument("state", type=Path)
    passed.add_argument("actor")
    resolved = sub.add_parser("complete-resolution")
    resolved.add_argument("state", type=Path)
    resolved.add_argument("item_id")
    resolved.add_argument("--effect-executed", action="store_true")
    args = parser.parse_args()
    try:
        state = _load(args.state)
        if args.command == "inspect":
            output = _result(state, valid=not bool(validate_state(state)), errors=validate_state(state))
        elif args.command == "next":
            output = next_procedure(state)
        elif args.command == "permissions":
            output = derive_permissions(state)
        elif args.command == "finalize":
            choice = True if args.perform_trigger else False if args.decline_trigger else None
            output = finalize_oldest_pending(state, perform_optional_trigger=choice)
        elif args.command == "add":
            output = add_pending_item(state, _load(args.proposal))
        elif args.command == "pass-priority":
            output = pass_priority(state, args.actor)
        elif args.command == "complete-resolution":
            output = complete_resolution(state, args.item_id, effect_execution_confirmed=args.effect_executed)
        else:
            output = validate_timing(state, _load(args.action))
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
