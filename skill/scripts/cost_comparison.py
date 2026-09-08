#!/usr/bin/env python3
"""`cost-comparison.v1`: what "a spell that costs no more than X" reads.

A card that compares a cost has to say *which* cost. A spell on the chain has
three of them and they routinely disagree:

  printed_cost     what is printed on the card. Ignores every reduction,
                   increase, cost-ignoring effect and optional extra.
  modified_cost    what Core 356 arrives at after base modifications,
                   increases, discounts, total modifications and the floor -
                   the amount that had to be paid.
  payment_receipt  what was actually paid, including a Repeat cost paid N
                   times and an optional cost declined.

The Core Rules 2026-07-16 define all three quantities (356, 357) but never
define which one the phrase "costs no more than" reads. Nothing in this module
picks for a card. A limit that does not name its basis is refused, and a card
mapping - which is service data, not engine data - supplies it along with the
authority that mapping rests on.

**Authority travels with the answer.** A limit carries `authority_status` and
`official_status`, and every comparison returns them in its evidence, so an
answer produced under a community reading can never be presented as a Riot
ruling. `official` is for a reading with an official source; anything else says
so in the output.

Power is measured one of two ways, and the choice changes real cards:

  total_*       every Power added up across Domains. A spell costing one Calm
                and one Mind costs two Power.
  per_domain_*  the largest Power in any one Domain. That same spell costs one.

The measure names differ per basis on purpose: `total_printed_power` cannot be
combined with `modified_cost`, because a measure that says "printed" while the
basis says "modified" is two different claims in one field.
"""

from __future__ import annotations

from typing import Any

COMPARISON_VERSION = "cost-comparison.v1"

# The three quantities, and where each is read from.
COST_BASES = ("printed_cost", "modified_cost", "payment_receipt")

# Power measures, keyed by the basis they may be used with.
POWER_MEASURES: dict[str, tuple[str, ...]] = {
    "printed_cost": ("total_printed_power", "per_domain_printed_power"),
    "modified_cost": ("total_power", "per_domain_power"),
    "payment_receipt": ("total_power", "per_domain_power"),
}

# How much weight the reading carries. Never inferred - always stated.
AUTHORITY_STATUS = ("official", "community_interpretation", "house_ruling")
OFFICIAL_STATUS = ("verified", "unverified")

LIMIT_FIELDS = {"energy", "power", "cost_basis", "power_measure",
                "authority_status", "official_status", "source"}
SOURCE_FIELDS = {"platform", "recorded_on", "url", "quote", "recorded_by"}


def validate_limit(limit: Any) -> list[str]:
    """A limit is well formed only if it says what it reads and on whose
    authority. Both omissions are the same mistake: an answer that looks
    definitive and is not."""
    if not isinstance(limit, dict):
        return ["cost limit must be an object"]
    errors: list[str] = []
    if set(limit) - LIMIT_FIELDS:
        errors.append(f"cost limit has unsupported fields {sorted(set(limit) - LIMIT_FIELDS)}")
    if not any(limit.get(key) is not None for key in ("energy", "power")):
        errors.append("cost limit must bound energy, power, or both")
    for key in ("energy", "power"):
        value = limit.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            errors.append(f"cost limit {key} must be a non-negative integer when supplied")
    basis = limit.get("cost_basis")
    if basis not in COST_BASES:
        errors.append(f"cost_basis must be one of {list(COST_BASES)}; a limit that does not say which "
                      "cost it reads cannot be evaluated")
        return errors
    measure = limit.get("power_measure")
    if limit.get("power") is not None and measure not in POWER_MEASURES[basis]:
        errors.append(f"power_measure for {basis} must be one of {list(POWER_MEASURES[basis])}")
    if limit.get("power") is None and measure is not None:
        errors.append("power_measure without a power bound measures nothing")
    if limit.get("authority_status") not in AUTHORITY_STATUS:
        errors.append(f"authority_status must be one of {list(AUTHORITY_STATUS)}")
    if limit.get("official_status") not in OFFICIAL_STATUS:
        errors.append(f"official_status must be one of {list(OFFICIAL_STATUS)}")
    if limit.get("authority_status") == "official" and limit.get("official_status") != "verified":
        errors.append("an official reading must be verified; an unverified one is not official")
    if limit.get("authority_status") in {"community_interpretation", "house_ruling"}:
        source = limit.get("source")
        if not isinstance(source, dict) or set(source) - SOURCE_FIELDS:
            errors.append("a non-official reading must carry a source object")
        else:
            for key in ("platform", "recorded_on"):
                if not isinstance(source.get(key), str) or not source[key]:
                    errors.append(f"source.{key} is required for a non-official reading")
    return errors


def _printed(state: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    printed = (state.get("objects") or {}).get(object_id, {}).get("printed_cost")
    if not isinstance(printed, dict):
        return None
    return {"energy": printed.get("energy", 0), "power": dict(printed.get("power") or {})}


def _from_receipt(state: dict[str, Any], object_id: str, basis: str) -> dict[str, Any] | None:
    """`modified_cost` and `payment_receipt` are facts about a play, so they
    live on the chain item that play created. A card sitting somewhere with no
    chain item has neither, and the comparison abstains rather than falling
    back to the printed cost - a silent fallback would make the basis field a
    decoration."""
    for entry in (state.get("chain_items") or {}).values():
        if entry.get("card") != object_id:
            continue
        receipt = entry.get("cost_receipt")
        if not isinstance(receipt, dict):
            return None
        if basis == "modified_cost":
            total = receipt.get("total") or {}
            power = dict(total.get("power") or {})
            if total.get("power_any"):
                power["$any"] = total["power_any"]
            return {"energy": total.get("energy", 0), "power": power}
        paid_energy = 0
        power: dict[str, int] = {}
        for component in receipt.get("components", []) or []:
            if not component.get("paid"):
                continue
            amount = component.get("final")
            if not isinstance(amount, int):
                continue
            if component.get("kind") == "energy":
                paid_energy += amount
            elif component.get("kind") == "power":
                power[component.get("domain", "$any")] = power.get(component.get("domain", "$any"), 0) + amount
            elif component.get("kind") == "power_any":
                power["$any"] = power.get("$any", 0) + amount
        return {"energy": paid_energy, "power": power}
    return None


def read_cost(state: dict[str, Any], object_id: str, basis: str) -> dict[str, Any] | None:
    """The cost `basis` names, or None when this state does not carry it."""
    if basis == "printed_cost":
        return _printed(state, object_id)
    return _from_receipt(state, object_id, basis)


# A card corpus that records a printed Power *total* without saying how it
# splits across Domains carries it under this key. Summing it is exact; asking
# which Domain holds the most is not answerable from it.
UNSPECIFIED_DOMAIN = "$unspecified"


def measure_power(power: dict[str, int], measure: str) -> int | None:
    """The measured Power, or None when this data cannot answer this measure."""
    if measure in {"total_printed_power", "total_power"}:
        return sum(power.values())
    if UNSPECIFIED_DOMAIN in power:
        return None
    return max(power.values(), default=0)


def compare(state: dict[str, Any], object_id: str, limit: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one cost comparison.

    Returns {"holds": True|False|None, "reason": str, "evidence": {...}}.
    `holds` is None when the basis is not observable here - not False. "This
    spell does not qualify" and "we cannot see what this spell cost" are
    different answers, and only the first may be acted on.
    """
    errors = validate_limit(limit)
    if errors:
        return {"holds": None, "reason": "cost_limit_invalid",
                "evidence": {"schema_version": COMPARISON_VERSION, "errors": errors}}
    basis = limit["cost_basis"]
    cost = read_cost(state, object_id, basis)
    evidence: dict[str, Any] = {
        "schema_version": COMPARISON_VERSION,
        "object": object_id,
        "cost_basis": basis,
        "power_measure": limit.get("power_measure"),
        "authority_status": limit["authority_status"],
        "official_status": limit["official_status"],
        **({"source": limit["source"]} if limit.get("source") else {}),
    }
    if cost is None:
        return {"holds": None, "reason": f"{basis}_not_observed", "evidence": evidence}
    evidence["observed"] = cost
    if limit.get("energy") is not None:
        evidence["energy_limit"] = limit["energy"]
        if cost["energy"] > limit["energy"]:
            return {"holds": False, "reason": "energy_over_limit", "evidence": evidence}
    if limit.get("power") is not None:
        measured = measure_power(cost["power"], limit["power_measure"])
        if measured is None:
            # The data gives a Power total and this measure needs the split.
            # Guessing a split would decide real cards on invented data.
            evidence["power_limit"] = limit["power"]
            return {"holds": None, "reason": "power_split_not_observed", "evidence": evidence}
        evidence.update({"power_limit": limit["power"], "power_measured": measured})
        if measured > limit["power"]:
            return {"holds": False, "reason": "power_over_limit", "evidence": evidence}
    return {"holds": True, "reason": "within_limit", "evidence": evidence}
