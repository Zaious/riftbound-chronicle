#!/usr/bin/env python3
"""
Gate: Universal Power - "[Add] [A]" (2026-09-27; Kai'Sa - Daughter of the Void, Malzahar - Fanatic).

[A] is Power of any Domain (Core 135.2.e.5). Added to a Rune Pool it can be spent to pay a Power
cost of any Domain (135.2.e.5.b; 163.2.b: some Power is Universal), and it pays an any-Domain cost
too (135.2.e.5.a). The engine keeps it apart from the Domains' own Power: `universal_power` in the
general pool, `universal: true` on a restricted entry (ADR-0011 §4). add_resource writes it with
`{resource: power, universal: true}` and names no Domain.

Must hold:
  - shape: add_resource `universal: true` on power with no domain validates; with a domain, on
    Energy, or `universal: false` it is refused; a state's universal_power must be a non-negative
    integer, a restricted universal entry names no domain;
  - adding: unrestricted it goes to universal_power; "Use only to play spells" makes a restricted
    universal entry (uses play_spell), and nothing reaches the general pool;
  - paying (play_card, the payment path every play uses):
      one Universal Power pays a spell's [fury] and, as well, a spell's [calm] (any Domain); it does
      not pay [fury][fury] nor an Energy cost; it pays an any-Domain additional cost;
      with the Domain's own Power in the pool too there are two legal ways - the engine asks
      (resource_allocation_required), then follows the payer's answer both ways; a wrong answer is
      invalid, an answer from the other player is refused; where only one way is legal ([fury][calm]
      from a fury and one Universal) it proceeds unasked;
      restricted to spells: it pays a spell, it does not pay a unit (cost_unpayable, the entry named);
      the receipt validates, its events are `pay_power` of domain `universal` with `paid_for`;
  - a pool with no Universal Power: the affordability verdict equals the pre-2026-09-27 formula on a
    grid of pools and costs (no play that paid before pays differently now).
Negative mutations (each must break a case above): Universal Power ignored; Universal Power paying
Energy; a restricted Universal entry spent on any use; the engine choosing the allocation itself.
"""
from __future__ import annotations

import copy
import itertools
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_costs_and_activation import declaration, envelope, hand_state  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from cost_receipt import validate_cost_receipt  # noqa: E402
from effect_ir import apply_program, hash_value, validate_program, validate_state  # noqa: E402
from play_transaction import play_card  # noqa: E402


def add(**fields) -> dict:
    return {"op": "add_resource", "effect_id": "add", "player": "p1", "resource": "power", "amount": 1, **fields}


def pool(state: dict, *, energy: int = 0, power: dict | None = None, universal: int = 0,
         restricted: list | None = None) -> dict:
    state["players"]["p1"]["resources"] = {"energy": energy, "power": dict(power or {}),
                                           **({"universal_power": universal} if universal else {}),
                                           **({"restricted": copy.deepcopy(restricted)} if restricted else {})}
    return state


SPELLS_ONLY = [{"restriction_id": "kaisa", "kind": "power", "universal": True, "amount": 1, "uses": ["play_spell"]}]


def spell(power: dict, *, energy: int = 0, additional: list | None = None, **kw) -> dict:
    cost = {"base": {"energy": energy, "power": dict(power)}}
    if additional:
        cost["additional"] = additional
    return declaration(cost=cost, **kw)


def unit_decl(power: dict) -> dict:
    return declaration(card="c1", chain_item={"id": "unit-1", "object_kind": "unit", "timing": "default"},
                       cost={"base": {"energy": 0, "power": dict(power)}}, entry_location={"kind": "base"})


def as_unit(state: dict) -> dict:
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2})
    return state


def allocation(state: dict, value: dict, controller: str = "p1") -> dict:
    return envelope(state, {"decision_id": "universal_power:play-1", "stage": "play_declaration", "kind": "resource_allocation",
                            "controller": controller, "value": value})


def left(result: dict) -> dict:
    return (result.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources")


def legacy_short(resources: dict, total: dict, use: str) -> bool:
    """play_transaction.affordability's `short` before 2026-09-27, verbatim, for the comparison only."""
    any_amount = total.get("power_any", 0)
    restricted_energy = sum(r["amount"] for r in PT._restricted_entries(resources, use, "energy"))
    general_specific = {d: max(0, a - sum(r["amount"] for r in PT._restricted_entries(resources, use, "power", d)))
                        for d, a in total["power"].items()}
    return (resources["energy"] + restricted_energy < total["energy"]
            or any(resources["power"].get(d, 0) < a for d, a in general_specific.items())
            or sum(resources["power"].values()) - sum(general_specific.values()) < any_amount)


def payments(errors: list[str]) -> dict[str, bool]:
    """Each payment case: its label -> whether it held. Errors are appended for the real engine."""
    held: dict[str, bool] = {}

    def check(label: str, ok: bool, why: str = "") -> None:
        held[label] = ok
        if not ok:
            errors.append(f"{label}: {why}")

    one = lambda: pool(hand_state("c1", energy=0), universal=1)  # noqa: E731
    got = play_card(fixture(), one(), spell({"fury": 1}))
    ev = [e for e in (got.get("cost_receipt") or {}).get("payment_events", []) if e["kind"] == "pay_power"]
    check("one Universal pays [fury]", bool(got.get("committed")) and left(got) == {"energy": 0, "power": {}}
          and [(e["domain"], e.get("paid_for"), e["amount"]) for e in ev] == [("universal", "fury", 1)]
          and not validate_cost_receipt(got["cost_receipt"]),
          f"{got.get('reason_code')} {got.get('reason')} {left(got)} {ev}")
    got = play_card(fixture(), one(), spell({"calm": 1}))
    check("one Universal pays [calm] (any Domain)", bool(got.get("committed")), f"{got.get('reason_code')} {got.get('reason')}")
    got = play_card(fixture(), one(), spell({"fury": 2}))
    check("one Universal does not pay [fury][fury]", got.get("reason_code") == "cost_unpayable", f"{got.get('reason_code')}")
    got = play_card(fixture(), one(), spell({}, energy=1))
    check("Universal Power does not pay Energy", got.get("reason_code") == "cost_unpayable", f"{got.get('reason_code')}")
    got = play_card(fixture(), one(), spell({}, additional=[{"cost_id": "a", "mandatory": True,
                                                             "payment": {"kind": "power_any", "amount": 1}}]))
    check("one Universal pays an any-Domain cost (Core 135.2.e.5.a)", bool(got.get("committed")) and left(got) == {"energy": 0, "power": {}},
          f"{got.get('reason_code')} {got.get('reason')} {left(got)}")

    both = lambda: pool(hand_state("c1", energy=0), power={"fury": 1}, universal=1)  # noqa: E731
    ask = play_card(fixture(), both(), spell({"fury": 1}))
    check("fury and a Universal for [fury]: the payer is asked", ask.get("reason_code") == "resource_allocation_required"
          and ask.get("decision_ids") == ["universal_power:play-1"], f"{ask.get('reason_code')} {ask.get('decision_ids')}")
    state = both()
    got = play_card(fixture(), state, spell({"fury": 1}), engine_decisions=allocation(state, {"fury": 1}))
    check("answered 'the Universal pays': the fury stays", left(got) == {"energy": 0, "power": {"fury": 1}},
          f"{got.get('reason_code')} {got.get('reason')} {left(got)}")
    state = both()
    got = play_card(fixture(), state, spell({"fury": 1}), engine_decisions=allocation(state, {"fury": 0}))
    check("answered 'the fury pays': the Universal stays", left(got) == {"energy": 0, "power": {"fury": 0}, "universal_power": 1},
          f"{got.get('reason_code')} {got.get('reason')} {left(got)}")
    state = both()
    got = play_card(fixture(), state, spell({"fury": 1}), engine_decisions=allocation(state, {"fury": 2}))
    check("an allocation that is no legal way is invalid", got.get("valid") is False and not got.get("committed")
          and "Universal Power allocation" in str(got.get("reason") or got.get("errors")), f"{got.get('reason_code')} {got.get('reason')}")
    state = both()
    got = play_card(fixture(), state, spell({"fury": 1}), engine_decisions=allocation(state, {"fury": 1}, controller="p2"))
    check("an allocation from the other player is refused", got.get("reason_code") == "decision_controller_mismatch", f"{got.get('reason_code')}")
    got = play_card(fixture(), both(), spell({"fury": 1, "calm": 1}))
    check("[fury][calm] from a fury and a Universal: one way, unasked", bool(got.get("committed"))
          and left(got) == {"energy": 0, "power": {"fury": 0}}, f"{got.get('reason_code')} {got.get('reason')} {left(got)}")

    restricted = lambda: pool(hand_state("c1", energy=0), restricted=SPELLS_ONLY)  # noqa: E731
    got = play_card(fixture(), restricted(), spell({"order": 1}))
    ev = [e for e in (got.get("cost_receipt") or {}).get("payment_events", []) if e["kind"] == "pay_power"]
    check("a spells-only Universal pays a spell's [order]", bool(got.get("committed")) and left(got) == {"energy": 0, "power": {}}
          and [e.get("restricted_from") for e in ev] == ["kaisa"], f"{got.get('reason_code')} {got.get('reason')} {left(got)} {ev}")
    got = play_card(fixture(), as_unit(restricted()), unit_decl({"order": 1}))
    check("a spells-only Universal does not pay a unit", got.get("reason_code") == "cost_unpayable"
          and got.get("restricted_not_applicable") == ["kaisa"], f"{got.get('reason_code')} {got.get('restricted_not_applicable')}")
    return held


def main() -> int:
    errors: list[str] = []

    # shape
    for label, effect, ok in (("universal power", add(universal=True), True),
                              ("universal with a domain", add(universal=True, domain="fury"), False),
                              ("universal Energy", add(universal=True, resource="energy"), False),
                              ("universal false", add(universal=False), False),
                              ("restricted universal", add(universal=True, restriction={"uses": ["play_spell"]}), True)):
        problems = validate_program(program("add", effect))
        if bool(problems) == ok:
            errors.append(f"validate_program on {label}: {problems or 'accepted'}")
    for label, resources in (("universal_power -1", {"energy": 0, "power": {}, "universal_power": -1}),
                             ("universal_power true", {"energy": 0, "power": {}, "universal_power": True}),
                             ("a restricted universal entry with a domain",
                              {"energy": 0, "power": {}, "restricted": [{**SPELLS_ONLY[0], "domain": "fury"}]}),
                             ("a restricted universal Energy entry",
                              {"energy": 0, "power": {}, "restricted": [{**SPELLS_ONLY[0], "kind": "energy"}]})):
        state = base_state()
        state["players"]["p1"]["resources"] = resources
        if not validate_state(state):
            errors.append(f"validate_state accepted {label}")
    state = base_state()
    state["players"]["p1"]["resources"] = {"energy": 0, "power": {}, "universal_power": 2, "restricted": copy.deepcopy(SPELLS_ONLY)}
    if validate_state(state):
        errors.append(f"validate_state refused a well-formed Universal pool: {validate_state(state)}")

    # adding
    got = apply_program(base_state(), program("add", add(universal=True, amount=2)))
    if not got.get("committed") or got["next_state"]["players"]["p1"]["resources"] != {"energy": 0, "power": {}, "universal_power": 2}:
        errors.append(f"an unrestricted [A][A] did not reach universal_power: {got.get('reason')} "
                      f"{(got.get('next_state') or {}).get('players', {}).get('p1', {}).get('resources')}")
    got = apply_program(base_state(), program("add", add(universal=True, restriction={"uses": ["play_spell"]})))
    resources = (got.get("next_state") or {}).get("players", {}).get("p1", {}).get("resources") or {}
    entries = resources.get("restricted") or []
    if not got.get("committed") or resources.get("universal_power") or resources.get("power") \
            or [(e.get("kind"), e.get("universal"), e.get("domain"), e.get("amount"), e.get("uses")) for e in entries] \
            != [("power", True, None, 1, ["play_spell"])]:
        errors.append(f"a spells-only [A] is not one restricted universal entry: {resources}")

    held = payments(errors)

    # a pool with no Universal Power: the same verdict as before
    uses = ("play_spell", "play_unit")
    compared = 0
    for energy, fury, calm, r_energy, r_fury in itertools.product(range(3), range(3), range(2), range(2), range(2)):
        resources = {"energy": energy, "power": {"fury": fury, "calm": calm},
                     **({"restricted": [e for e in (
                         {"restriction_id": "re", "kind": "energy", "amount": r_energy, "uses": ["play_spell"]},
                         {"restriction_id": "rf", "kind": "power", "domain": "fury", "amount": r_fury, "uses": ["play_spell"]})
                         if e["amount"]]} if r_energy or r_fury else {})}
        for c_energy, c_fury, c_calm, c_any in itertools.product(range(3), range(3), range(2), range(2)):
            total = {"energy": c_energy, "power": {d: n for d, n in (("fury", c_fury), ("calm", c_calm)) if n},
                     **({"power_any": c_any} if c_any else {})}
            for use in uses:
                compared += 1
                verdict = PT.affordability(resources, total, use)
                if verdict["short"] != legacy_short(resources, total, use) or "universal" in verdict:
                    errors.append(f"with no Universal Power the verdict changed: {resources} {total} {use}")
                    break

    # negative mutations: each must break a case above
    real = {name: getattr(PT, name) for name in ("universal_available", "_universal_entries", "_universal_allocations",
                                                 "affordability")}
    mutants = {
        "Universal Power ignored": {"universal_available": lambda resources, use: 0},
        "a restricted Universal entry spent on any use": {
            "_universal_entries": lambda resources, use: [r for r in resources.get("restricted", [])
                                                          if r["kind"] == "power" and r.get("universal") is True]},
        "the engine chooses the allocation itself": {
            "_universal_allocations": lambda *a, **k: real["_universal_allocations"](*a, **k)[:1]},
    }

    def pays_energy(resources, total, use):
        verdict = real["affordability"](resources, total, use)
        if verdict.get("universal") and total["energy"] and resources["energy"] + verdict["restricted_energy"] < total["energy"]:
            verdict = {**verdict, "short": False}
        return verdict

    mutants["Universal Power paying Energy"] = {"affordability": pays_energy}
    for label, patch in mutants.items():
        for name, fn in patch.items():
            setattr(PT, name, fn)
        try:
            broken = [k for k, ok in payments([]).items() if not ok]
        except Exception as crash:  # noqa: BLE001 - a crash is a caught mutant too
            broken = [f"crash: {type(crash).__name__}"]
        finally:
            for name, fn in real.items():
                setattr(PT, name, fn)
        if not broken:
            errors.append(f"negative mutation not caught: {label}")

    if not all(held.values()) and not errors:
        errors.append("a payment case failed without a message")
    if errors:
        print("FAILED: Universal Power checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print(f"OK: add_resource `universal: true` adds Universal Power ([A], Core 135.2.e.5.b, 163.2.b) to universal_power, or to "
          f"a restricted entry for 'Use only to play spells'; it pays [fury] and [calm] and an any-Domain cost, not [fury][fury] "
          f"nor Energy; beside the Domain's own Power the payer is asked and followed both ways (a wrong or foreign answer "
          f"refused), a single legal way proceeds unasked; spells-only pays a spell and not a unit; receipts validate; with "
          f"no Universal Power the verdict equals the old formula on {compared} pool/cost/use cases; four mutants caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
