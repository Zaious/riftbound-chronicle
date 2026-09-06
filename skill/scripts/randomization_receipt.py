#!/usr/bin/env python3
"""
randomization-receipt.v1 — the record of an external randomization (ADR-0010 §2).

Randomizing is never a player's choice and never the engine's: when a Burn
Out recycles the Trash into the Main Deck (Core 431.2.b) the new order comes
from outside, and this receipt is how it arrives — bound to the operation it
serves, carrying the complete permutation and the provenance of the provider
and method that produced it. Standalone on purpose: engine_decisions reads
it, the effect IR consumes it, neither defines it.
"""

from __future__ import annotations

from typing import Any

RANDOMIZATION_RECEIPT_VERSION = "randomization-receipt.v1"
OPERATIONS = {"recycle_trash"}
_TOP = {"schema_version", "receipt_id", "operation", "operation_id", "player", "permutation", "provenance"}
_PROVENANCE = {"provider", "method"}


def validate_randomization_receipt(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["randomization receipt must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != RANDOMIZATION_RECEIPT_VERSION:
        errors.append(f"schema_version must be {RANDOMIZATION_RECEIPT_VERSION}")
    if set(value) != _TOP:
        errors.append(f"receipt fields must be exactly {sorted(_TOP)}")
        return errors
    for key in ("receipt_id", "operation_id", "player"):
        if not isinstance(value[key], str) or not value[key]:
            errors.append(f"{key} must be a non-empty string")
    if value["operation"] not in OPERATIONS:
        errors.append(f"operation must be one of {sorted(OPERATIONS)}")
    permutation = value["permutation"]
    if not isinstance(permutation, list) or any(not isinstance(x, str) or not x for x in permutation) or len(permutation) != len(set(permutation)):
        errors.append("permutation must be a list of unique non-empty object ids")
    provenance = value["provenance"]
    if not isinstance(provenance, dict) or _PROVENANCE - set(provenance) or set(provenance) - _PROVENANCE - {"seed", "recorded_at"}:
        errors.append("provenance must carry provider and method (optionally seed, recorded_at)")
    elif any(not isinstance(provenance[k], str) or not provenance[k] for k in _PROVENANCE):
        errors.append("provenance.provider and provenance.method must be non-empty strings")
    return errors


def permutation_matches(receipt: dict[str, Any], zone: list[str]) -> str | None:
    """None when the receipt's permutation is exactly the zone's contents; else the error."""
    expected, given = sorted(zone), sorted(receipt["permutation"])
    if expected != given:
        missing = sorted(set(expected) - set(given))
        extra = sorted(set(given) - set(expected))
        return f"receipt {receipt['receipt_id']} does not permute the Trash exactly (missing {missing}, extra {extra})"
    return None
