#!/usr/bin/env python3
"""
engine-decisions.v1 — one envelope for every choice a transition needs (ADR-0005 §2).

Before this, choices lived in three places with three shapes: replacement
order and optional-replacement choices embedded in an effect, and a separate
cleanup-decisions object for lethal cleanup. Target selection had no home at
all. This module gives them one shape with an explicit `stage`, keyed to the
input hash the choice was made against, so a decision supplied for a different
state or a different stage is refused as `invalid_input` rather than applied
to something it was not about.

Kinds and the values they carry:

  target_selection   value: [object_id, ...] plus a matching
                     selection_identities map          stage play_declaration
                     (or trigger_finalization for triggered abilities)
  replacement_order  value: {event_id: [replacement_id...]}   stage resolution
  replacement_choice value: {replacement_id: {event_id: bool}} stage resolution
  optional_choice    value: bool                       any stage (C-15 uses it)
  trigger_order      value: [trigger_id, ...]           stage resolution — the
                     complete order of one controller's simultaneously
                     triggered abilities in one chronological batch
                     (Core 383.3.d.1); decision_id is
                     trigger_order:<batch_id>:<controller>

The legacy `riftbound-cleanup-decisions.v1` object is still *read* — the
adapter below turns it into resolution-stage entries — but writers emit only
this form, per ADR-0002's migration policy.
"""

from __future__ import annotations

import copy
from typing import Any

DECISIONS_VERSION = "engine-decisions.v1"
STAGES = ("play_declaration", "trigger_finalization", "resolution")
KINDS = ("target_selection", "replacement_order", "replacement_choice", "optional_choice", "trigger_order", "card_selection", "resource_allocation")
LEGACY_CLEANUP_VERSION = "riftbound-cleanup-decisions.v1"


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71


def validate_engine_decisions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["engine_decisions must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != DECISIONS_VERSION:
        errors.append(f"engine_decisions.schema_version must be {DECISIONS_VERSION}")
    if set(value) - {"schema_version", "input_hash", "chain_item_id", "decisions"}:
        errors.append("engine_decisions contains unsupported fields")
    if not _is_hash(value.get("input_hash")):
        errors.append("engine_decisions.input_hash must be a sha256 hash")
    if "chain_item_id" in value and (not isinstance(value["chain_item_id"], str) or not value["chain_item_id"]):
        errors.append("engine_decisions.chain_item_id must be a non-empty string when supplied")
    items = value.get("decisions")
    if not isinstance(items, list):
        return errors + ["engine_decisions.decisions must be an array"]
    seen: set[str] = set()
    for index, item in enumerate(items):
        label = f"decisions[{index}]"
        if not isinstance(item, dict) or not {"decision_id", "stage", "kind", "controller", "value"} <= set(item) or set(item) - {"decision_id", "stage", "kind", "controller", "value", "selection_identities", "options", "provenance"}:
            errors.append(f"{label} has invalid fields")
            continue
        if not isinstance(item["decision_id"], str) or not item["decision_id"] or item["decision_id"] in seen:
            errors.append(f"{label}.decision_id is invalid or duplicated")
        seen.add(item.get("decision_id", ""))
        if item["stage"] not in STAGES:
            errors.append(f"{label}.stage is invalid")
        if item["kind"] not in KINDS:
            errors.append(f"{label}.kind is invalid")
        if not isinstance(item["controller"], str) or not item["controller"]:
            errors.append(f"{label}.controller is required")
        kind, val = item["kind"], item["value"]
        if kind in {"target_selection", "card_selection"}:
            if not isinstance(val, list) or (kind == "card_selection" and not val) or any(not isinstance(v, str) or not v for v in val) or len(val) != len(set(val)):
                errors.append(f"{label}.value must be a {'non-empty ' if kind == 'card_selection' else ''}unique array of object ids")
            identities = item.get("selection_identities")
            if not isinstance(identities, dict) or set(identities) != set(val if isinstance(val, list) else []):
                errors.append(f"{label}.selection_identities must map every selected object id exactly once")
            elif any(not isinstance(identity, str) or "@" not in identity or not identity.rsplit("@", 1)[1].isdigit() for identity in identities.values()):
                errors.append(f"{label}.selection_identities values must be identity tokens")
        elif "selection_identities" in item:
            errors.append(f"{label}.selection_identities is only valid for target_selection or card_selection")
        if kind == "replacement_order" and (not isinstance(val, dict) or any(not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) for ids in val.values())):
            errors.append(f"{label}.value must map event ids to non-empty unique replacement-id arrays")
        if kind == "replacement_choice" and (not isinstance(val, dict) or any(not isinstance(by_event, dict) or any(not isinstance(c, bool) for c in by_event.values()) for by_event in val.values())):
            errors.append(f"{label}.value must map replacement ids to {{event_id: bool}}")
        if kind == "optional_choice" and not isinstance(val, bool):
            errors.append(f"{label}.value must be a boolean")
        if kind == "trigger_order" and (not isinstance(val, list) or not val or any(not isinstance(v, str) or not v for v in val) or len(val) != len(set(val))):
            errors.append(f"{label}.value must be a non-empty unique array of trigger ids")
        if kind == "resource_allocation" and (not isinstance(val, dict) or not val or any(not isinstance(k, str) or not k or isinstance(n, bool) or not isinstance(n, int) or n < 0 for k, n in val.items())):
            errors.append(f"{label}.value must map domains to non-negative integers (the complete allocation)")
        if kind == "resource_allocation" and item["stage"] != "play_declaration":
            errors.append(f"{label}: resource_allocation is decided while paying at play")
        if kind in ("replacement_order", "replacement_choice", "trigger_order", "card_selection") and item["stage"] != "resolution":
            errors.append(f"{label}: {kind} is a resolution-stage decision")
    return errors


def from_cleanup_decisions(legacy: dict[str, Any] | None, *, input_hash: str, controller: str) -> dict[str, Any] | None:
    """Read-side adapter for riftbound-cleanup-decisions.v1. Writers do not emit this form."""
    if legacy is None:
        return None
    decisions: list[dict[str, Any]] = []
    if legacy.get("replacement_event_order"):
        decisions.append({"decision_id": "legacy:replacement_event_order", "stage": "resolution", "kind": "replacement_order",
                          "controller": controller, "value": copy.deepcopy(legacy["replacement_event_order"]), "provenance": LEGACY_CLEANUP_VERSION})
    if legacy.get("replacement_choices"):
        decisions.append({"decision_id": "legacy:replacement_choices", "stage": "resolution", "kind": "replacement_choice",
                          "controller": controller, "value": copy.deepcopy(legacy["replacement_choices"]), "provenance": LEGACY_CLEANUP_VERSION})
    return {"schema_version": DECISIONS_VERSION, "input_hash": input_hash, "decisions": decisions}


def entries(decisions: dict[str, Any] | None, *, kind: str | None = None, stage: str | None = None) -> list[dict[str, Any]]:
    if not decisions:
        return []
    out = []
    for item in decisions.get("decisions", []):
        if kind is not None and item.get("kind") != kind:
            continue
        if stage is not None and item.get("stage") != stage:
            continue
        out.append(item)
    return out


def replacement_maps(decisions: dict[str, Any] | None) -> tuple[dict[str, list[str]] | None, dict[str, dict[str, bool]] | None]:
    """Collapse resolution-stage replacement decisions into the maps the cleanup batch consumes."""
    order: dict[str, list[str]] = {}
    choices: dict[str, dict[str, bool]] = {}
    for item in entries(decisions, kind="replacement_order", stage="resolution"):
        order.update(copy.deepcopy(item["value"]))
    for item in entries(decisions, kind="replacement_choice", stage="resolution"):
        for replacement_id, by_event in item["value"].items():
            choices.setdefault(replacement_id, {}).update(by_event)
    return (order or None), (choices or None)


def trigger_order(decisions: dict[str, Any] | None, batch_id: str, controller: str) -> dict[str, Any] | None:
    wanted = f"trigger_order:{batch_id}:{controller}"
    for item in entries(decisions, kind="trigger_order", stage="resolution"):
        if item["decision_id"] == wanted:
            return item
    return None


def target_selection(decisions: dict[str, Any] | None, decision_id: str) -> dict[str, Any] | None:
    for item in entries(decisions, kind="target_selection"):
        if item["decision_id"] == decision_id:
            return item
    return None
