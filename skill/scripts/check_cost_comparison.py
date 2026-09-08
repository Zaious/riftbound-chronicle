#!/usr/bin/env python3
"""Regression gate for `cost-comparison.v1` (DP-93).

"A spell that costs no more than X" has three possible referents and the Core
Rules 2026-07-16 define none of them as *the* one. So this module's job is not
to be right about the phrase - it is to make sure no answer is produced
without saying which cost it read and on whose authority.

What the gate holds to:

  - **the three bases really differ.** One synthetic spell is set up so that
    its printed cost, its modified cost and what was actually paid are three
    different numbers, and a limit that qualifies it under one basis
    disqualifies it under another. If they ever agree, this gate stops testing
    anything and says so.
  - **a limit that does not name its basis is refused**, and so is one whose
    power measure belongs to a different basis. `total_printed_power` with
    `modified_cost` is two claims in one field.
  - **authority is mandatory and cannot be inflated.** A non-official reading
    must carry a source with a platform and a date; an `official` reading may
    not be `unverified`. Every verdict carries both statuses in its evidence,
    so a community reading cannot be rendered as a ruling.
  - **an unobservable basis abstains, and abstention refuses the target.**
    A spell with no chain item has no modified cost and no payment; the
    comparison returns None and `evaluate_target` refuses. Reading None as
    "qualifies" would counter a spell on no evidence at all.
  - **the grammar leaves the hole open.** The clause compiles to
    mapping_not_supplied until a card mapping supplies a basis, and to
    mapping_invalid if the mapping does not satisfy the contract.

Every fixture here is synthetic: no Wave B card text, no card mapping. Which
reading a real card takes is service data and lives with the card corpus.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import cost_comparison as cc  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import evaluate_target, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SOURCE = {"platform": "synthetic fixture", "recorded_on": "2026-09-08"}


def limit(energy=None, power=None, basis="printed_cost", measure=None,
          authority="community_interpretation", official="unverified", source=SOURCE):
    out = {"cost_basis": basis, "authority_status": authority, "official_status": official}
    if energy is not None:
        out["energy"] = energy
    if power is not None:
        out["power"] = power
        out["power_measure"] = measure or ("total_printed_power" if basis == "printed_cost" else "total_power")
    if source is not None and authority != "official":
        out["source"] = source
    return out


def mapping(basis="printed_cost", measure=None, authority="community_interpretation",
            official="unverified", source=SOURCE):
    """What a *card mapping* supplies: the reading and its authority, never the
    numbers - those are printed on the card and come from the clause."""
    out = {"cost_basis": basis, "authority_status": authority, "official_status": official,
           "power_measure": measure or ("total_printed_power" if basis == "printed_cost" else "total_power")}
    if source is not None and authority != "official":
        out["source"] = source
    return out


def receipt(components, total):
    return {
        "schema_version": "riftbound-cost-receipt.v1", "play_id": "play-1", "actor": "p1", "card": "s1",
        "chain_item": "spell-1", "base": {"energy": 0, "power": {}},
        "after_base_modifications": {"energy": 0, "power": {}}, "components": components,
        "aggregate": {"energy": {"before_total_discounts": total["energy"], "reductions": [],
                                 "final": total["energy"]}},
        "discount_order": [], "order_provenance": "synthetic", "payment_events": [],
        "total": total, "paid": True, "rule_locators": ["Core 356.1"],
    }


def divergent_state():
    """One spell, three different costs.

      printed        6 Energy, 2 Power (one Calm, one Mind)
      modified       3 Energy, 1 Power   (a discount applied)
      actually paid  3 Energy, 1 Power, plus a declined optional cost that is
                     on the receipt unpaid - so the paid figure and the
                     modified figure differ from printed, and the *component*
                     set differs between them.
    """
    state = base_state()
    state["objects"]["s1"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False,
                              "printed_cost": {"energy": 6, "power": {"calm": 1, "mind": 1}}}
    state["chain_items"] = {"spell-1": {
        "card": "s1", "controller": "p1",
        "cost_receipt": receipt(
            components=[
                {"cost_id": "base:energy", "kind": "energy", "mandatory": True, "intent": None,
                 "requested": 6, "increases": [], "reductions": [], "final": 3,
                 "payment_refs": [], "paid": True, "rule_locators": ["Core 356.1"]},
                {"cost_id": "base:power:calm", "kind": "power", "mandatory": True, "intent": None,
                 "requested": 1, "increases": [], "reductions": [], "final": 1,
                 "payment_refs": [], "paid": True, "rule_locators": ["Core 356.1"], "domain": "calm"},
                {"cost_id": "extra", "kind": "power", "mandatory": False, "intent": False,
                 "requested": 1, "increases": [], "reductions": [], "final": 1,
                 "payment_refs": [], "paid": False, "rule_locators": ["Core 356.2.b"], "domain": "mind"},
            ],
            total={"energy": 3, "power": {"calm": 1, "mind": 1}}),
    }}
    return state


def main() -> int:
    errors: list[str] = []
    state = divergent_state()
    if validate_state(state):
        errors.append(f"the divergent fixture is not a valid state: {validate_state(state)}")

    # --- the three bases really are three different numbers ---------------------------------------
    seen = {}
    for basis in cc.COST_BASES:
        cost = cc.read_cost(state, "s1", basis)
        if cost is None:
            errors.append(f"the fixture does not carry {basis}, so this gate cannot test it")
            continue
        seen[basis] = (cost["energy"], sum(cost["power"].values()))
    if len(set(seen.values())) < 3:
        errors.append(f"the fixture's three bases are not three different costs ({seen}); "
                      "this gate would pass whatever the implementation read")

    # --- and a limit that qualifies under one disqualifies under another ---------------------------
    printed = cc.compare(state, "s1", limit(energy=4, basis="printed_cost"))
    modified = cc.compare(state, "s1", limit(energy=4, basis="modified_cost"))
    if printed["holds"] is not False or modified["holds"] is not True:
        errors.append(f"the basis did not decide the answer: printed={printed['holds']} "
                      f"modified={modified['holds']}")
    if printed["evidence"]["cost_basis"] != "printed_cost" or modified["evidence"]["cost_basis"] != "modified_cost":
        errors.append("the evidence does not say which cost it read")

    # --- power measure: total across Domains vs the largest in one ---------------------------------
    total = cc.compare(state, "s1", limit(power=1, basis="printed_cost", measure="total_printed_power"))
    per_domain = cc.compare(state, "s1", limit(power=1, basis="printed_cost", measure="per_domain_printed_power"))
    if total["holds"] is not False or per_domain["holds"] is not True:
        errors.append(f"the power measure did not decide a two-Domain spell: total={total['holds']} "
                      f"per_domain={per_domain['holds']}")

    # --- what a limit may not be --------------------------------------------------------------------
    for label, bad in (
        ("no basis", {"energy": 4, "authority_status": "community_interpretation",
                      "official_status": "unverified", "source": SOURCE}),
        ("a measure from another basis", limit(power=1, basis="modified_cost", measure="total_printed_power")),
        ("an official reading that is unverified", limit(energy=4, authority="official", official="unverified")),
        ("a community reading with no source", limit(energy=4, source=None)),
        ("no bound at all", {"cost_basis": "printed_cost", "authority_status": "official",
                             "official_status": "verified"}),
    ):
        if not cc.validate_limit(bad):
            errors.append(f"a limit with {label} was accepted")
        verdict = cc.compare(state, "s1", bad)
        if verdict["holds"] is not None or verdict["reason"] != "cost_limit_invalid":
            errors.append(f"an invalid limit ({label}) produced a verdict anyway: {verdict}")

    # --- an unobservable basis abstains, and abstention refuses -------------------------------------
    loose = copy.deepcopy(state)
    loose["chain_items"] = {}
    loose["players"]["p1"]["zones"]["trash"].append("s1")   # off the chain, in a public non-board zone
    for basis in ("modified_cost", "payment_receipt"):
        verdict = cc.compare(loose, "s1", limit(energy=99, basis=basis))
        if verdict["holds"] is not None or verdict["reason"] != f"{basis}_not_observed":
            errors.append(f"a spell with no chain item still produced a {basis} verdict: {verdict}")
    target = {"object_id": "s1", "chosen_zone_class": "non_board",
              "max_cost": limit(energy=99, basis="modified_cost")}
    legal, reason = evaluate_target(loose, target, "p1")
    if legal or not reason.startswith("target_cost_not_observed"):
        errors.append(f"an unobservable cost was treated as within the limit: {legal} {reason}")
    # the printed basis is observable there, and the same spell qualifies
    legal, reason = evaluate_target(loose, {**target, "max_cost": limit(energy=99, basis="printed_cost")}, "p1")
    if not legal:
        errors.append(f"a printed-cost limit the spell satisfies was refused: {reason}")
    legal, reason = evaluate_target(loose, {**target, "max_cost": limit(energy=1, basis="printed_cost")}, "p1")
    if legal or not reason.startswith("target_cost_over_limit"):
        errors.append(f"a spell over the printed limit was a legal target: {legal} {reason}")

    # --- authority travels with the answer ----------------------------------------------------------
    verdict = cc.compare(state, "s1", limit(energy=99, authority="community_interpretation"))
    evidence = verdict["evidence"]
    if evidence.get("authority_status") != "community_interpretation" or evidence.get("official_status") != "unverified":
        errors.append(f"the verdict does not carry the authority it rests on: {evidence}")
    if evidence.get("source") != SOURCE:
        errors.append("the verdict dropped the source of a non-official reading")

    # --- the grammar leaves the hole open ------------------------------------------------------------
    grammar = cg.load_grammar()
    text = "Counter a spell that costs no more than :rb_energy_4: and no more than :rb_rune_rainbow:."
    unmapped = cg.compile_clause(text, grammar)
    if not unmapped.get("unsupported") or unmapped.get("reason_code") != "mapping_not_supplied":
        errors.append(f"the clause compiled without a cost basis: {unmapped}")
    mapped = cg.compile_clause(text, grammar, mappings={"cost_comparison": mapping()})
    if mapped.get("unsupported"):
        errors.append(f"a valid mapping did not complete the clause: {mapped}")
    else:
        written = mapped["program_effects"][0]["target"]["max_cost"]
        if written.get("energy") != 4 or written.get("power") != 1:
            errors.append(f"the clause's own numbers were lost or changed by the mapping: {written}")
        if written.get("cost_basis") != "printed_cost":
            errors.append(f"the mapping's basis did not reach the program: {written}")
        if cc.validate_limit(written):
            errors.append(f"the completed limit is not valid: {cc.validate_limit(written)}")
    broken = cg.compile_clause(text, grammar, mappings={"cost_comparison": {"cost_basis": "printed_cost"}})
    if broken.get("reason_code") != "mapping_invalid":
        errors.append(f"a mapping missing its authority was accepted: {broken}")

    if errors:
        print("FAILED: cost comparison checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"cost comparison checks passed: {len(cc.COST_BASES)} bases that differ on the same spell, a limit "
          "without a basis or an authority is refused, an unobservable basis abstains and the target is "
          "refused with it, and the clause stays open until a card mapping supplies the reading")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
