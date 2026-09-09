#!/usr/bin/env python3
"""
selection-binding.v1 - what makes a reference to an earlier choice legal.

A clause such as "Choose a friendly unit." establishes a selection; later
clauses ("Buff it.", "Kill it.") refer to it. Before this module the engine
resolved a `decision_ref` by NAME alone: any instruction could read any
decision id, from any program, with no check that the candidates or the
selection rule were still the ones the choice was made under. That is the hole
the Selection Binding Contract closes.

Four refusals, each named. A refusal means the instruction does not run; the
engine never re-chooses, back-fills or guesses a substitute:

  selection_origin_unbound        the reference names no selection this program
                                  (or an ancestor of it) established earlier
  selection_candidates_changed    the candidates, or the rule that selected
                                  them, are not the ones recorded
  selection_visibility_mismatch   a private selection referenced publicly, or
                                  the reverse
  selection_already_consumed      the selection is being made a SECOND time as
                                  a new selection

The hash covers the RULE, not only who was eligible. Same candidates with
`count` changed from {one} to {exactly 2}, or `visibility` flipped, or `from`
changed, is a different selection; hashing the candidate list alone would let a
result taken under one rule be reused under another.

A selection used by several effects fans OUT from one immutable result: the
second effect references that result rather than re-resolving the reference.
`consumed` therefore forbids only re-establishing the selection as a NEW one.
Conflating the two would fail the perfectly legal
"Choose a unit. Buff it. Kill it."
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

BINDING_VERSION = "selection-binding.v1"

ORIGIN_UNBOUND = "selection_origin_unbound"
CANDIDATES_CHANGED = "selection_candidates_changed"
VISIBILITY_MISMATCH = "selection_visibility_mismatch"
ALREADY_CONSUMED = "selection_already_consumed"
REFUSAL_CODES = (ORIGIN_UNBOUND, CANDIDATES_CHANGED, VISIBILITY_MISMATCH, ALREADY_CONSUMED)

VISIBILITIES = ("public", "private_to_chooser")

# The rule fields a binding claim echoes, so a tampered one is refused by the
# field that changed rather than by a bare hash mismatch.
ECHOED_RULE_FIELDS = ("source", "selection_kind", "count")
BINDING_FIELDS = {"selection_id", "candidate_set_hash", "visibility", "origin", *ECHOED_RULE_FIELDS}
ORIGIN_FIELDS = {"program_id", "effect_id", "chain_item_id"}


def candidate_set_hash(spec: dict[str, Any], candidates, identities: dict[str, Any] | None = None) -> str:
    """sha256 over the whole rule: who was eligible AND the rule that selected.

    `candidates` are the eligible object ids in the engine's enumeration order,
    which is sorted here so a re-enumeration in another order still matches;
    `identities` maps each to its `<id>@<generation>` token.
    """
    payload = {
        "candidates": sorted([[c, (identities or {}).get(c)] for c in candidates], key=lambda row: row[0]),
        "selection_kind": spec.get("selection_kind"),
        "count": spec.get("count"),
        "ordering": spec.get("ordering") if spec.get("selection_kind") == "ordered_permutation" else None,
        "source": spec.get("from", spec.get("source")),
        "visibility": spec.get("visibility"),
        "criteria": spec.get("criteria"),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# How apply_program names a nested program, and how many segments sit between
# the prefix and the parent program id. `replacement:` and the two
# `augmentation-` forms carry the replacement id first.
#
# `simultaneous:` is deliberately NOT here: apply_program builds it as
# `simultaneous:{effect_id}` with no parent id in the name at all, so an
# ancestor cannot be read out of it. Listing it would invent a parent out of an
# effect id that happened to contain a colon.
NEST_FORMS = (("affected:", 0), ("expand:", 0),
              ("augmentation-original:", 1), ("augmentation-extra:", 1),
              ("replacement:", 1))


def program_ancestry(program_id: str) -> list[str]:
    """The program ids `program_id` descends from, itself first, innermost next.

    The parent sits BETWEEN a known prefix and a trailing effect id, never at
    the end: `affected:{parent}:{effect_id}`, `expand:{parent}:{effect_id}`,
    `replacement:{replacement_id}:{parent}:{effect_id}`. Stripping from the
    right yields `expand:p1` and `expand`, and the real parent `p1` never
    appears - a nested program could then not read its parent's selection.

    Fails CLOSED: an id whose nesting form is not recognised yields only
    itself, so an ancestry that cannot be proven is refused, not assumed.
    """
    seen, current = [program_id], program_id
    while True:
        for prefix, extra in NEST_FORMS:
            if not current.startswith(prefix):
                continue
            rest = current[len(prefix):].split(":")
            if len(rest) < extra + 2:
                return seen
            parent = ":".join(rest[extra:-1])
            if not parent or parent in seen:
                return seen
            seen.append(parent)
            current = parent
            break
        else:
            return seen


def validate_binding_claim(claim: Any) -> list[str]:
    """Shape of the binding a decision artifact carries. Content is checked
    against the engine's own computation by `check_claim`, not here."""
    if not isinstance(claim, dict):
        return ["binding must be an object"]
    errors: list[str] = []
    unknown = set(claim) - BINDING_FIELDS
    if unknown:
        errors.append(f"binding has unsupported fields {sorted(unknown)}")
    if not {"selection_id", "candidate_set_hash", "visibility", "origin"} <= set(claim):
        errors.append("binding must carry selection_id, candidate_set_hash, visibility and origin")
        return errors
    if not isinstance(claim["selection_id"], str) or not claim["selection_id"]:
        errors.append("binding.selection_id must be a non-empty string")
    digest = claim["candidate_set_hash"]
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        errors.append("binding.candidate_set_hash must be a sha256 hash")
    if claim["visibility"] not in VISIBILITIES:
        errors.append(f"binding.visibility must be one of {VISIBILITIES}")
    origin = claim["origin"]
    if not isinstance(origin, dict) or set(origin) - ORIGIN_FIELDS or not {"program_id", "effect_id"} <= set(origin):
        errors.append("binding.origin must be {program_id, effect_id, chain_item_id?}")
    elif any(not isinstance(origin[key], str) or not origin[key] for key in origin):
        errors.append("binding.origin values must be non-empty strings")
    return errors


def check_claim(claim: dict[str, Any], *, spec: dict[str, Any], candidates, identities,
                visibility: str, program_id: str, effect_id: str, selection_id: str,
                established) -> tuple[str | None, str]:
    """The artifact's binding against what the engine independently computes.

    Returns (refusal_code, message); a refusal_code of None means the claim
    holds. Every tamper vector the ruling names gets its own refusal:
    candidates, the rule (source / kind / count / criteria), visibility, origin.
    """
    if claim.get("selection_id") != selection_id:
        return ORIGIN_UNBOUND, (
            f"the decision's binding names selection {claim.get('selection_id')!r}; this "
            f"instruction establishes {selection_id!r}")

    origin = claim.get("origin") or {}
    if origin.get("program_id") != program_id:
        return ORIGIN_UNBOUND, (
            f"the decision's binding was made in program {origin.get('program_id')!r}, not in "
            f"{program_id!r}, which is establishing it")
    if origin.get("effect_id") != effect_id:
        return ORIGIN_UNBOUND, (
            f"the decision's binding names effect {origin.get('effect_id')!r}, not {effect_id!r}")

    if selection_id in established:
        return ALREADY_CONSUMED, (
            f"selection {selection_id!r} is already established; a later instruction must "
            f"reference its result, not make the selection a second time")

    if claim.get("visibility") != visibility:
        return VISIBILITY_MISMATCH, (
            f"the decision's binding claims {claim.get('visibility')!r}; this choice is "
            f"{visibility!r}")

    for field in ECHOED_RULE_FIELDS:
        if field not in claim:
            continue
        mine = spec.get("from") if field == "source" else spec.get(field)
        if field == "count" and mine is None:
            mine = {"one": True} if spec.get("selection_kind") == "single" else None
        if claim[field] != mine:
            return CANDIDATES_CHANGED, (
                f"the decision's binding claims {field}={claim[field]!r}; this choice is "
                f"{field}={mine!r}")

    mine_hash = candidate_set_hash(spec, candidates, identities)
    if claim.get("candidate_set_hash") != mine_hash:
        return CANDIDATES_CHANGED, (
            f"the decision's binding was taken over a different candidate set or selection "
            f"rule ({claim.get('candidate_set_hash')} != {mine_hash})")
    return None, ""


def check_reference(selection_id: str, bindings: dict[str, Any], *, program_id: str,
                    order_index: int,
                    referencing_visibility: str = "public") -> tuple[dict[str, Any] | None, str | None, str]:
    """Resolve one later reference to an established selection.

    Returns (bound_result, refusal_code, message). A read is NOT a
    consumption: any number of later effects may reference the same result,
    which is what keeps "Choose a unit. Buff it. Kill it." legal.
    """
    bound = bindings.get(selection_id)
    if bound is None:
        return None, ORIGIN_UNBOUND, f"no selection named {selection_id!r} has been established"

    origin = bound.get("origin") or {}
    if origin.get("program_id") not in program_ancestry(program_id):
        return None, ORIGIN_UNBOUND, (
            f"selection {selection_id!r} was established in program {origin.get('program_id')!r}, "
            f"which is neither {program_id!r} nor one of its ancestors")
    if bound.get("order_index") is None or bound["order_index"] >= order_index:
        return None, ORIGIN_UNBOUND, (
            f"selection {selection_id!r} is not established before the instruction referencing it")
    if bound.get("visibility") != referencing_visibility:
        return None, VISIBILITY_MISMATCH, (
            f"selection {selection_id!r} is {bound.get('visibility')!r}; the referencing "
            f"instruction is {referencing_visibility!r}")
    return bound, None, ""


def result_ref(selection_id: str) -> str:
    """The immutable handle later effects fan out from."""
    return f"result:{selection_id}"


__all__ = ["BINDING_VERSION", "REFUSAL_CODES", "ORIGIN_UNBOUND", "CANDIDATES_CHANGED",
           "VISIBILITY_MISMATCH", "ALREADY_CONSUMED", "VISIBILITIES", "NEST_FORMS",
           "BINDING_FIELDS", "ORIGIN_FIELDS", "ECHOED_RULE_FIELDS",
           "candidate_set_hash", "program_ancestry", "validate_binding_claim",
           "check_claim", "check_reference", "result_ref"]
