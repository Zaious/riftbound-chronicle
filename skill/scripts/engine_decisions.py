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
import hashlib
import json
import re
from typing import Any

DECISIONS_VERSION = "engine-decisions.v1"
# "procedure": a choice a two-state procedure asks for (ADR-0008 §2: the Turn
# Player's Combat location), bound to combat.combined_input_hash.
STAGES = ("play_declaration", "trigger_finalization", "resolution", "procedure")
# ADR-0010 §2: player_selection names another player (the Burn Out beneficiary).
# ADR-0011 §2–3: mode_selection names a modal option by its stable id;
# card_ordering is the player's permutation of the looked-at / revealed cards
# that remain: complete whenever any card is left, empty when none is.
KINDS = ("target_selection", "replacement_order", "replacement_choice", "optional_choice", "trigger_order", "card_selection", "resource_allocation", "location_selection", "damage_assignment", "player_selection", "mode_selection", "card_ordering")
LEGACY_CLEANUP_VERSION = "riftbound-cleanup-decisions.v1"


# The full form of a board location, used where a decision may name either
# kind. Core 355.4.a: the Board's Locations are the Battlefields and the Bases.
_LOCATION_TOKEN = re.compile(r"^(battlefield|base):(.+)$")


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
    if set(value) - {"schema_version", "input_hash", "chain_item_id", "decisions", "randomization_receipts"}:
        errors.append("engine_decisions contains unsupported fields")
    # ADR-0010 §2: external randomization rides in the same envelope, bound to
    # the same input hash, but it is not a decision — nobody chose it.
    receipts = value.get("randomization_receipts", [])
    if not isinstance(receipts, list):
        errors.append("engine_decisions.randomization_receipts must be a list")
    else:
        from randomization_receipt import validate_randomization_receipt
        seen_ops: set[str] = set()
        for index, receipt in enumerate(receipts):
            for problem in validate_randomization_receipt(receipt):
                errors.append(f"randomization_receipts[{index}]: {problem}")
            if isinstance(receipt, dict) and isinstance(receipt.get("operation_id"), str):
                if receipt["operation_id"] in seen_ops:
                    errors.append(f"randomization_receipts[{index}]: operation_id {receipt['operation_id']!r} appears twice")
                seen_ops.add(receipt["operation_id"])
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
        if not isinstance(item, dict) or not {"decision_id", "stage", "kind", "controller", "value"} <= set(item) or set(item) - {"decision_id", "stage", "kind", "controller", "value", "selection_identities", "options", "provenance", "binding"}:
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
        if kind in {"target_selection", "card_selection", "card_ordering"}:
            # ADR-0011 §1: an empty card_selection is the "none" answer of an
            # any_number / up_to choice; instructions that need a count refuse it.
            # Codex G-1 §11.7: an empty ordering is the answer when nothing is
            # left to put back (Predict that Recycles everything). Completeness
            # is checked against the candidates in `check_choice_entry`, where
            # the candidate set is known — not here, where it is not.
            if not isinstance(val, list) or any(not isinstance(v, str) or not v for v in val) or len(val) != len(set(val)):
                errors.append(f"{label}.value must be a unique array of object ids")
            identities = item.get("selection_identities")
            if not isinstance(identities, dict) or set(identities) != set(val if isinstance(val, list) else []):
                errors.append(f"{label}.selection_identities must map every selected object id exactly once")
            elif any(not isinstance(identity, str) or "@" not in identity or not identity.rsplit("@", 1)[1].isdigit() for identity in identities.values()):
                errors.append(f"{label}.selection_identities values must be identity tokens")
        elif kind == "damage_assignment":
            # ADR-0008 §8: the complete raw assignment — every opposing Unit
            # identity to a non-negative amount — plus, when a Unit's requirements
            # are mutually exclusive, which one applies (465.2.c.8).
            amounts = val.get("amounts") if isinstance(val, dict) and "amounts" in val else val
            choices = val.get("requirement_choices", {}) if isinstance(val, dict) and "amounts" in val else {}
            if not isinstance(amounts, dict) or not amounts or any(not isinstance(k, str) or not k or isinstance(n, bool) or not isinstance(n, int) or n < 0 for k, n in amounts.items()):
                errors.append(f"{label}.value must map every opposing unit id to a non-negative raw amount (or carry amounts + requirement_choices)")
            if not isinstance(choices, dict) or any(k not in (amounts or {}) or c not in {"tank", "backline"} for k, c in choices.items()):
                errors.append(f"{label}.value.requirement_choices must map assigned units to tank or backline")
            identities = item.get("selection_identities")
            if not isinstance(identities, dict) or set(identities) != set(amounts if isinstance(amounts, dict) else []):
                errors.append(f"{label}.selection_identities must bind every assigned unit id exactly once")
            elif any(not isinstance(identity, str) or "@" not in identity for identity in identities.values()):
                errors.append(f"{label}.selection_identities values must be identity tokens")
            if item["stage"] != "procedure":
                errors.append(f"{label}: damage_assignment is a procedure-stage decision")
        elif "selection_identities" in item:
            errors.append(f"{label}.selection_identities is only valid for target_selection, card_selection, card_ordering or damage_assignment")
        # selection-binding.v1: a decision that ESTABLISHES a selection later
        # instructions refer to carries the binding it was made under, so a
        # changed candidate set, rule, visibility or origin is refused by name
        # instead of being silently reused.
        if "binding" in item:
            from selection_binding import validate_binding_claim
            if kind != "target_selection":
                errors.append(f"{label}.binding is only valid for target_selection in selection-binding.v1")
            errors.extend(f"{label}.{problem}" for problem in validate_binding_claim(item["binding"]))
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
        if kind == "card_ordering" and item["stage"] not in ("resolution", "play_declaration"):
            errors.append(f"{label}: card_ordering is decided at resolution, or while paying a cost at play (Core 357.2)")
        if kind == "mode_selection" and (not isinstance(val, str) or not val):
            errors.append(f"{label}.value must be the stable option id of the chosen mode (not an index)")
        if kind == "mode_selection" and item["stage"] not in ("play_declaration", "trigger_finalization"):
            errors.append(f"{label}: mode_selection is chosen while playing or at trigger finalization (Core 402.2)")
        if kind == "card_selection" and item["stage"] not in ("resolution", "play_declaration"):
            errors.append(f"{label}: card_selection is decided at resolution, or while paying a cost at play (Core 357.2)")
        if kind in ("replacement_order", "replacement_choice", "trigger_order") and item["stage"] != "resolution":
            errors.append(f"{label}: {kind} is a resolution-stage decision")
        if kind == "player_selection" and (not isinstance(val, str) or not val):
            errors.append(f"{label}.value must be a player id")
        if kind == "player_selection" and item["stage"] not in ("resolution", "procedure"):
            errors.append(f"{label}: player_selection is a resolution- or procedure-stage decision")
        if kind == "location_selection" and (not isinstance(val, str) or not val):
            errors.append(f"{label}.value must be a battlefield id, or a board location token at resolution")
        if kind == "location_selection" and item["stage"] not in ("procedure", "resolution"):
            errors.append(f"{label}: location_selection is a procedure- or resolution-stage decision")
        # A procedure names a Battlefield by id (opening a Combat, staging a
        # Showdown). A Move at resolution may also name a Base, so it names the
        # location in full - "battlefield:<id>" or "base:<player>" - and the
        # bare-id form stays where it already means something.
        if kind == "location_selection" and item["stage"] == "resolution" and isinstance(val, str) \
                and not _LOCATION_TOKEN.match(val):
            errors.append(f"{label}.value must be 'battlefield:<id>' or 'base:<player>' at resolution")
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


def randomization_receipt(decisions: dict[str, Any] | None, operation_id: str) -> dict[str, Any] | None:
    if not decisions:
        return None
    return next((r for r in decisions.get("randomization_receipts", []) if isinstance(r, dict) and r.get("operation_id") == operation_id), None)


def player_selection(decisions: dict[str, Any] | None, decision_id: str) -> dict[str, Any] | None:
    return next((item for item in entries(decisions, kind="player_selection") if item["decision_id"] == decision_id), None)


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


# ---------------------------------------------------------------- choice grammar (ADR-0011 §1) --
# A choice is a typed specification the instruction carries; the engine
# enumerates candidates, asks for the decision kind the specification maps
# to, and validates the supplied value against the candidates. Private
# sources are never listed in an engine result.
SELECTION_KINDS = ("single", "unordered_set", "ordered_permutation")
# `battlefields` is its own universe, not a filter over `board`: the board
# source walks the objects standing AT a Battlefield, so it can never enumerate
# the Battlefields themselves (Core 355.4.a). Codex's 2026-09-10 ruling on the
# eff_010 split required this path before "Choose a battlefield." could be
# mapped, rather than letting it be disguised as a board choice.
CHOICE_SOURCES = ("hand", "trash", "main_deck_top", "revealed", "board", "battlefields", "players")
# Sabotage: "a non-unit card". Stated as an exclusion from a closed list rather
# than as a negation, so a card kind nobody has thought about is *included* by
# default and never silently filtered out.
EXCLUDABLE_KINDS = ("unit", "gear", "spell", "rune", "legend")
CHOICE_VISIBILITY = ("public", "private_to_chooser")
CHOICE_BY = ("controller", "opponent", "each_player")
COUNT_FORMS = ("exactly", "up_to", "any_number", "one")
PRIVATE_SOURCES = {"hand", "main_deck_top", "revealed"}
DEFAULT_ENUMERABLE_CAP = 64
CHOICE_FIELDS = {"selection_kind", "count", "from", "by", "visibility", "identity_binding", "enumerable_cap", "criteria", "players", "top"}


def validate_choice_spec(spec: Any) -> list[str]:
    if not isinstance(spec, dict):
        return ["choice must be an object"]
    errors: list[str] = []
    if set(spec) - CHOICE_FIELDS or not {"selection_kind", "from"} <= set(spec):
        errors.append(f"choice must carry selection_kind and from, and only {sorted(CHOICE_FIELDS)}")
        return errors
    if spec["selection_kind"] not in SELECTION_KINDS:
        errors.append(f"choice.selection_kind must be one of {SELECTION_KINDS}")
    count = spec.get("count", {"one": True} if spec["selection_kind"] == "single" else None)
    if not isinstance(count, dict) or len(count) != 1 or next(iter(count)) not in COUNT_FORMS:
        errors.append("choice.count must be one of {exactly: n}, {up_to: n}, {any_number: true}, {one: true}")
    else:
        form, value = next(iter(count.items()))
        if form in {"exactly", "up_to"} and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            errors.append(f"choice.count.{form} must be a positive integer")
        if form in {"any_number", "one"} and value is not True:
            errors.append(f"choice.count.{form} must be true")
        if spec["selection_kind"] == "single" and form != "one":
            errors.append("a single choice counts one")
        if spec["selection_kind"] == "ordered_permutation" and form != "any_number":
            errors.append("an ordered_permutation orders every candidate (count any_number)")
    if spec["from"] not in CHOICE_SOURCES:
        errors.append(f"choice.from must be one of {CHOICE_SOURCES}")
    criteria = spec.get("criteria")
    if isinstance(criteria, dict) and "excluded_kinds" in criteria:
        excluded = criteria["excluded_kinds"]
        if spec["from"] != "revealed":
            errors.append("choice.criteria.excluded_kinds applies to a revealed choice")
        elif (not isinstance(excluded, list) or not excluded or len(excluded) != len(set(excluded))
                or any(kind not in EXCLUDABLE_KINDS for kind in excluded)):
            errors.append(f"choice.criteria.excluded_kinds must be a non-empty unique subset of "
                          f"{list(EXCLUDABLE_KINDS)}")
    by = spec.get("by", "controller")
    if not (by in CHOICE_BY or (isinstance(by, str) and by)):
        errors.append("choice.by must be controller, opponent, each_player or a player id")
    if spec.get("visibility", "public") not in CHOICE_VISIBILITY:
        errors.append(f"choice.visibility must be one of {CHOICE_VISIBILITY}")
    if spec["from"] in PRIVATE_SOURCES and spec.get("visibility") == "public":
        errors.append(f"choice.from {spec['from']} is private information (Core 128.4); visibility cannot be public")
    if not isinstance(spec.get("identity_binding", True), bool):
        errors.append("choice.identity_binding must be boolean")
    cap = spec.get("enumerable_cap", DEFAULT_ENUMERABLE_CAP)
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        errors.append("choice.enumerable_cap must be a positive integer")
    if "criteria" in spec and spec["from"] not in {"board", "revealed"}:
        errors.append("choice.criteria applies to a board or revealed source")
    if "criteria" in spec and spec["from"] == "revealed" and set(spec["criteria"]) - {"excluded_kinds"}:
        errors.append("a revealed choice's criteria carries excluded_kinds and nothing else")
    if spec["from"] == "board" and (not isinstance(spec.get("criteria"), dict) or set(spec["criteria"]) - {"kind", "controller_relation", "location"}):
        errors.append("choice.from board needs criteria {kind?, controller_relation?, location?}")
    if spec["from"] == "battlefields" and "criteria" in spec:
        errors.append("choice.from battlefields takes no criteria; the Locations themselves are "
                      "the candidates (Core 355.4.a)")
    if "players" in spec and spec["from"] != "players":
        errors.append("choice.players only applies to a players source")
    if spec["from"] == "players" and spec.get("players", "opponents") not in {"opponents", "any"}:
        errors.append("choice.players must be opponents or any")
    if spec["from"] == "players" and spec["selection_kind"] != "single":
        errors.append("a players choice names one player")
    if "top" in spec and spec["from"] != "main_deck_top":
        errors.append("choice.top only applies to main_deck_top")
    if spec["from"] == "main_deck_top" and (not isinstance(spec.get("top"), int) or isinstance(spec.get("top"), bool) or spec.get("top", 0) < 1):
        errors.append("choice.from main_deck_top needs a positive top count")
    return errors


def choice_visibility(spec: dict[str, Any]) -> str:
    return spec.get("visibility") or ("private_to_chooser" if spec["from"] in PRIVATE_SOURCES else "public")


def choice_decision_kind(spec: dict[str, Any]) -> str:
    if spec["from"] == "players":
        return "player_selection"
    if spec["selection_kind"] == "ordered_permutation":
        return "card_ordering"
    # A Battlefield is a target on the board with a bindable identity
    # (ADR-0007 §4), so choosing one is a target_selection like any other board
    # choice; what differs is the candidate universe, not the decision kind.
    if spec["from"] in {"board", "battlefields"}:
        return "target_selection"
    return "card_selection"


def choice_count(spec: dict[str, Any]) -> tuple[str, int | None]:
    count = spec.get("count", {"one": True} if spec["selection_kind"] == "single" else {"any_number": True})
    form, value = next(iter(count.items()))
    return form, (value if isinstance(value, int) and not isinstance(value, bool) else None)


def forced_choice(spec: dict[str, Any], candidates: list[str]) -> list[str] | None:
    """The set the rules force without asking: nothing to choose from, or
    every candidate must be taken (359.3.e: do as much as possible)."""
    form, n = choice_count(spec)
    if not candidates:
        return []
    if spec["selection_kind"] == "single" and len(candidates) == 1:
        return list(candidates)
    if spec["selection_kind"] == "ordered_permutation" and len(candidates) == 1:
        return list(candidates)
    if form == "exactly" and len(candidates) <= (n or 0):
        return list(candidates)
    return None


def choice_summary(spec: dict[str, Any], chooser: str, candidates: list[str], identities: dict[str, str | None]) -> dict[str, Any]:
    """What an engine result may say about a pending choice. A private source
    is described by count and hash only (Core 128.4, 355.10.a); a public one
    lists its options up to the enumerable cap."""
    visibility = choice_visibility(spec)
    form, n = choice_count(spec)
    listing = [{"object_id": c, "identity": identities.get(c)} for c in candidates]
    digest = hashlib.sha256(json.dumps([[c, identities.get(c)] for c in candidates], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    cap = spec.get("enumerable_cap", DEFAULT_ENUMERABLE_CAP)
    summary = {"decision_kind": choice_decision_kind(spec), "selection_kind": spec["selection_kind"], "count": {form: n if n is not None else True},
               "from": spec["from"], "chooser": chooser, "visibility": visibility, "identity_binding": spec.get("identity_binding", True),
               "options_count": len(candidates), "options_hash": f"sha256:{digest}", "options_enumerated": len(candidates) <= cap}
    if visibility == "public" and len(candidates) <= cap:
        summary["options"] = listing
    else:
        summary["options_visible_to"] = [chooser]
    return summary


def check_choice_entry(spec: dict[str, Any], entry: dict[str, Any], chooser: str, candidates: list[str], identities: dict[str, str | None]) -> tuple[list[str], str | None, str]:
    """Validate a supplied decision against the specification and the
    candidates. Returns (chosen, failure, message); failure is None, or
    'controller' (another player chose), 'invalid' (malformed, wrong count
    or stale identity) or 'illegal' (a value that is not a candidate)."""
    kind = choice_decision_kind(spec)
    if entry.get("kind") != kind:
        return [], "invalid", f"decision {entry.get('decision_id')!r} is a {entry.get('kind')}; this choice is a {kind}"
    if entry.get("controller") != chooser:
        return [], "controller", f"decision {entry.get('decision_id')!r} was made by {entry.get('controller')!r}, not the choosing player {chooser!r}"
    value = entry.get("value")
    chosen = [value] if isinstance(value, str) else list(value) if isinstance(value, list) else None
    if chosen is None:
        return [], "invalid", f"decision {entry.get('decision_id')!r} carries no usable value"
    if len(chosen) != len(set(chosen)):
        return [], "invalid", f"decision {entry.get('decision_id')!r} repeats a candidate"
    outside = [c for c in chosen if c not in candidates]
    if outside:
        return [], "illegal", f"decision {entry.get('decision_id')!r} names {outside}, which cannot be chosen here"
    form, n = choice_count(spec)
    if spec["selection_kind"] == "ordered_permutation":
        if set(chosen) != set(candidates):
            return [], "invalid", f"decision {entry.get('decision_id')!r} must order every candidate exactly once ({len(candidates)} cards)"
    elif spec["selection_kind"] == "single" or form == "one":
        if len(chosen) != 1:
            return [], "invalid", f"decision {entry.get('decision_id')!r} must name exactly one"
    elif form == "exactly":
        expected = min(n or 0, len(candidates))
        if len(chosen) != expected:
            return [], "invalid", f"decision {entry.get('decision_id')!r} names {len(chosen)}; {expected} required"
    elif form == "up_to" and len(chosen) > (n or 0):
        return [], "invalid", f"decision {entry.get('decision_id')!r} names {len(chosen)}; at most {n}"
    if spec.get("identity_binding", True) and kind != "player_selection":
        bound = entry.get("selection_identities") or {}
        for c in chosen:
            if c in bound and identities.get(c) is not None and bound[c] != identities[c]:
                return [], "invalid", f"decision {entry.get('decision_id')!r} was bound to {bound[c]!r}; {c} is now {identities[c]!r}"
    return chosen, None, ""


def mode_selection(decisions: dict[str, Any] | None, decision_id: str) -> dict[str, Any] | None:
    return next((item for item in entries(decisions, kind="mode_selection") if item["decision_id"] == decision_id), None)


def card_ordering(decisions: dict[str, Any] | None, decision_id: str) -> dict[str, Any] | None:
    return next((item for item in entries(decisions, kind="card_ordering") if item["decision_id"] == decision_id), None)


def card_selection(decisions: dict[str, Any] | None, decision_id: str) -> dict[str, Any] | None:
    return next((item for item in entries(decisions, kind="card_selection") if item["decision_id"] == decision_id), None)


def decision_entry(decisions: dict[str, Any] | None, decision_id: str) -> dict[str, Any] | None:
    return next((item for item in entries(decisions) if item["decision_id"] == decision_id), None)
