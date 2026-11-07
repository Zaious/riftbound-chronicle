#!/usr/bin/env python3
"""Regression gate: a card with two or more Domains prints Power payable with Power of ANY of its Domains (Core
135.2.e.6.c - each of the split-colour runes every dual-Domain card prints is paid with either of its Domains; found
2026-11-05 answering GPT A2 ruling 14). printed_cost carries it as
power_of_domains {domains, amount}; a play declares one concrete split as its base cost.

  O1 options      2 Power of Calm/Chaos: three splits (2 Calm; 1 Calm 1 Chaos; 2 Chaos); 1 Power: two
  O2 match        a declared base matches only a split of the printed cost (another Domain, or a wrong total, does not)
  P1 split        a catalogued dual-Domain card with only Chaos in the pool, declared paying Chaos: committed, Chaos spent
  P2 other split  declared paying Calm with no Calm: refused as unpayable (the split is the payer's, and binding)
  P3 not printed  declared paying Fury: refused (not a split of its printed cost)
  R1 repeat asked a granted [Repeat] (Temporal Portal) on a 2-Power dual-Domain spell, paid: waits for the split
                  (power_split_required), naming the three splits
  R2 repeat split declared 1 Calm 1 Chaos: committed, the Repeat's Power paid as split
  R3 declined     the Repeat declined: no split asked
  E1 enumerator   play_space offers one declaration per split
  C1 counts       "Power cost N or more" counts the card's Power; cost_comparison's printed total includes it, under the
                  unspecified Domain
  U1 effect play  an effect-driven play's unobtainability: not certain to fail while one split is obtainable
  V  validation   power_of_domains with one Domain, an unknown Domain, or amount 0 does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_comparison as CCMP  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_space as PS  # noqa: E402
import play_transaction as PT  # noqa: E402
import watchers as W  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_next_spell_repeat import scene  # noqa: E402
from check_rules_core import fixture  # noqa: E402

OWN2 = {"energy": 1, "power": {}, "power_of_domains": {"domains": ["calm", "chaos"], "amount": 2}}
OWN1 = {"energy": 1, "power": {}, "power_of_domains": {"domains": ["calm", "chaos"], "amount": 1}}
BODY = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
        "program_id": "c1-effects", "controller": "p1", "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]}


def board(pool, printed=OWN1, catalogued=True):
    s = base_state()
    s["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s["players"]["p1"]["zones"]["hand"].append("c1")
    s["objects"]["c1"].update({"kind": "spell", "printed_cost": copy.deepcopy(printed), "domains": ["calm", "chaos"],
                               **({"card_ref": "probe-dual"} if catalogued else {})})
    s["players"]["p1"]["resources"] = {"energy": 3, "power": dict(pool)}
    return s


def declare(base, **cost):
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": base, **cost}, "effect_program_id": "c1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def main() -> int:
    errors: list[str] = []
    two = PT.printed_base_options(OWN2)
    if sorted(map(lambda b: sorted(b["power"].items()), two)) != sorted([[("calm", 2)], [("calm", 1), ("chaos", 1)],
                                                                         [("chaos", 2)]]) \
            or len(PT.printed_base_options(OWN1)) != 2:
        errors.append(f"O1 options: {two}")
    if not PT.matches_printed_base(OWN2, {"energy": 1, "power": {"calm": 1, "chaos": 1}}) \
            or PT.matches_printed_base(OWN2, {"energy": 1, "power": {"fury": 2}}) \
            or PT.matches_printed_base(OWN2, {"energy": 1, "power": {"calm": 1}}):
        errors.append("O2 match: a declared base was matched wrongly")
    s = board({"chaos": 1})
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    got = PT.play_card(fixture(), s, declare({"energy": 1, "power": {"chaos": 1}}), effect_program=copy.deepcopy(BODY))
    if not got.get("committed") or got["next_effect_state"]["players"]["p1"]["resources"]["power"].get("chaos") != 0:
        errors.append(f"P1 split: {got.get('reason_code')} {got.get('reason')}")
    calm = PT.play_card(fixture(), s, declare({"energy": 1, "power": {"calm": 1}}), effect_program=copy.deepcopy(BODY))
    if calm.get("committed"):
        errors.append("P2 other split: paying Calm with no Calm committed")
    fury = PT.play_card(fixture(), s, declare({"energy": 1, "power": {"fury": 1}}), effect_program=copy.deepcopy(BODY))
    if fury.get("committed") or "printed" not in str(fury.get("reason") or fury.get("errors")):
        errors.append(f"P3 not printed: {fury.get('committed')} {fury.get('reason_code')} {fury.get('reason')}")

    granted = scene()          # p1 has the Temporal Portal grant for its next spell
    granted["objects"]["c1"].update({"printed_cost": copy.deepcopy(OWN2), "domains": ["calm", "chaos"]})
    granted["players"]["p1"]["resources"] = {"energy": 4, "power": {"calm": 2, "chaos": 2}}
    offer = next(e["effect_id"] for e in granted["turn_effects"] if e.get("kind") == "next_spell_repeat")
    offer_id = f"granted_repeat:{offer}"

    def repeat(paid, splits=None):
        env = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(granted), "decisions": [
            {"decision_id": f"self_offer:{offer_id}", "kind": "optional_choice", "stage": "play_declaration",
             "controller": "p1", "value": paid}]}
        decl = declare({"energy": 1, "power": {"calm": 1, "chaos": 1}}, **({"offer_power_splits": splits} if splits else {}))
        return PT.play_card(fixture(), granted, decl, engine_decisions=env, effect_program=copy.deepcopy(BODY))
    asked = repeat(True)
    if asked.get("committed") or asked.get("reason_code") != "power_split_required" \
            or len((asked.get("power_split_options") or {}).get(offer_id) or []) != 3:
        errors.append(f"R1 repeat asked: {asked.get('reason_code')} {asked.get('reason')} {asked.get('power_split_options')}")
    paid = repeat(True, {offer_id: {"calm": 1, "chaos": 1}})
    pool = (paid.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources", {}).get("power")
    if not paid.get("committed") or pool != {"calm": 0, "chaos": 0}:
        errors.append(f"R2 repeat split: {paid.get('reason_code')} {paid.get('reason')} pool {pool}")
    declined = repeat(False)
    if not declined.get("committed"):
        errors.append(f"R3 declined: {declined.get('reason_code')} {declined.get('reason')}")

    plays = [d for d, _p in PS.play_skeletons(board({"chaos": 2}, OWN2), None, "p1") if d["card"] == "c1"]
    bases = {tuple(sorted(d["cost"]["base"]["power"].items())) for d in plays}
    if bases != {(("calm", 2),), (("calm", 1), ("chaos", 1)), (("chaos", 2),)}:
        errors.append(f"E1 enumerator: {bases}")

    st = board({}, OWN2)
    if not W.watch_matches(st, {"kinds": ["played"], "scope": "actor", "filter": {"printed_power_at_least": 2}},
                           {"kind": "played", "object": "c1", "actor": "p1", "controller": "p1"},
                           source_object="c1", controller="p1"):
        errors.append("C1 counts: 'Power cost 2 or more' did not count the card's own-Domain Power")
    if CCMP.read_cost(st, "c1", "printed_cost") != {"energy": 1, "power": {CCMP.UNSPECIFIED_DOMAIN: 2}}:
        errors.append(f"C1 counts: cost_comparison read {CCMP.read_cost(st, 'c1', 'printed_cost')}")

    trash = board({"chaos": 1})
    trash["players"]["p1"]["zones"]["hand"].remove("c1")
    trash["players"]["p1"]["zones"]["trash"].append("c1")
    if PT.limited_play_unobtainable(trash, "p1", "c1", {"kind": "printed"}) is not None:
        errors.append(f"U1 effect play: {PT.limited_play_unobtainable(trash, 'p1', 'c1', {'kind': 'printed'})}")

    for label, own in (("one Domain", {"domains": ["calm"], "amount": 1}),
                       ("an unknown Domain", {"domains": ["calm", "void"], "amount": 1}),
                       ("amount 0", {"domains": ["calm", "chaos"], "amount": 0})):
        bad = board({}, {**OWN1, "power_of_domains": own})
        if not any("power_of_domains" in p for p in IR.validate_state(bad)):
            errors.append(f"V: {label} validated")
    if errors:
        print("power-of-domains checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("power-of-domains checks passed: a dual-Domain card's Power is paid with any of its Domains - one declared "
          "split, binding; a granted [Repeat] equal to its cost waits for its split once chosen; the enumerator offers "
          "each split; counts and comparisons read its total; an effect play fails only if every split does; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
