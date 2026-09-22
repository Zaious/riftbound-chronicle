#!/usr/bin/env python3
"""Regression gate for Might and cost read off the board (Core 477.3; 356.4, 356.6).

Draven - Showboat, "My Might is increased by your points.":
  - a passive arithmetic increase (477.3.a) by its controller's points, computed each
    time Might is read - a passive source is not snapshotted (477.3.b);
  - 0 points adds nothing; more points later add more, also after the state has been
    moved to the canonical effect list by a program; the opponent's points do not count;
  - "per" is refused on an effect that is not passive.

Rhasa the Sunderer, "I cost [1] less for each card in your trash.":
  - through the real play transaction: with 4 cards in its controller's trash a
    10-Energy card is paid with 6; with 5 Energy it is not payable;
  - 356.6: with 12 cards in the trash its Energy cost is 0, not below;
  - the opponent's trash does not count; a per-each over a private zone is refused;
  - mutation: without the per-each count the reduction is 1, and 6 Energy cannot pay.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, effective_might, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def lowered(text):
    return (CG.compile_clause(text, CG.load_grammar()).get("passive") or {}).get("object_fields") or {}


def draven(points=0, their_points=0):
    state = base_state()
    state["objects"]["u1"].update(copy.deepcopy(lowered("My Might is increased by your points.")))
    state["players"]["p1"]["points"] = points
    state["players"]["p2"]["points"] = their_points
    return state


def rhasa(trash=0, energy=6, *, their_trash=0, fields=None):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 6})
    state["objects"]["c1"].update(copy.deepcopy(fields if fields is not None else lowered("I cost :rb_energy_1: less for each card in your trash.")))
    for owner in ("p1", "p2"):  # the fixture's own trash cards go to the deck, so the count is ours
        zones = state["players"][owner]["zones"]
        zones["main_deck"].extend(zones["trash"]); zones["trash"] = []
    for owner, count in (("p1", trash), ("p2", their_trash)):
        for i in range(count):
            oid = f"{owner}t{i}"
            state["objects"][oid] = {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0,
                                     "might_modifiers": [], "damage": 0, "exhausted": False}
            state["players"][owner]["zones"]["trash"].append(oid)
    state["players"]["p1"]["resources"] = {"energy": energy, "power": {}}
    return state


def play(state):
    return PT.play_card(fixture(), state, {
        "schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": "play-1", "actor": "p1", "card": "c1",
        "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
        "cost": {"base": {"energy": 10, "power": {}}}, "entry_location": {"kind": "base"},
        "payment_context": {"add_window_closed": True, "confirmed_by": "human"}})


def main() -> int:
    errors: list[str] = []

    # --- Draven ----------------------------------------------------------------------------------
    printed = base_state()["objects"]["u1"]["base_might"]
    zero = draven(0)
    if validate_state(zero):
        errors.append(f"the Draven board is invalid: {validate_state(zero)}")
    if effective_might(zero, "u1") != printed:
        errors.append("0 points added Might")
    three = draven(3, their_points=5)
    if effective_might(three, "u1") != printed + 3:
        errors.append(f"3 points did not add 3 (the opponent's 5 must not count): {effective_might(three, 'u1')}")
    moved = apply_program(draven(1), program("nudge", {"op": "modify_might", "effect_id": "m", "object_id": "u2", "amount": 1, "duration": "this_turn", "source": "u2"}))
    if not moved.get("committed"):
        errors.append(f"a program on the Draven board did not commit: {moved.get('reason') or moved.get('errors')}")
    else:
        later = copy.deepcopy(moved["next_state"])
        before = effective_might(later, "u1")
        later["players"]["p1"]["points"] = 4
        if before != printed + 1 or effective_might(later, "u1") != printed + 4:
            errors.append(f"the increase was snapshotted, not read off the board (477.3.b): {before} then {effective_might(later, 'u1')}")
    if moved.get("committed"):
        forged = copy.deepcopy(moved["next_state"])
        effect = next(e for e in forged["continuous_effects"] if e["effect_id"].startswith("legacy:dynamic:"))
        effect["passive"] = False
        if not validate_state(forged):
            errors.append("a non-passive effect reading points was accepted; only a passive ability is read fresh (477.3.b)")

    # --- Rhasa -----------------------------------------------------------------------------------
    paid = play(rhasa(trash=4, energy=6))
    if not paid.get("committed") or paid["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
        errors.append(f"4 cards in the trash did not take 4 off a 10-Energy cost: {paid.get('reason_code')} {paid.get('reason')}")
    short = play(rhasa(trash=4, energy=5))
    if short.get("committed") or short.get("reason_code") != "cost_unpayable":
        errors.append(f"5 Energy paid a cost of 6: {short.get('reason_code')}")
    free = play(rhasa(trash=12, energy=0))
    if not free.get("committed"):
        errors.append(f"12 cards in the trash did not bring the Energy cost to 0 (356.6): {free.get('reason_code')} {free.get('reason')}")
    theirs = play(rhasa(trash=0, energy=6, their_trash=8))
    if theirs.get("committed"):
        errors.append("the opponent's trash reduced the cost")
    private = rhasa(trash=4)
    private["objects"]["c1"]["printed_cost_modifications"][0]["per_each"]["zone"] = "hand"
    if not validate_state(private):
        errors.append("a per-each over a private zone (the hand) was accepted")
    flat = rhasa(trash=4, energy=6, fields={"printed_cost_modifications": [{"modification_id": "own-text", "kind": "energy_reduction", "amount": 1}]})
    if play(flat).get("committed"):
        errors.append("mutation not caught: without the per-each count 6 Energy still paid")

    if errors:
        print("FAILED: dynamic Might / cost checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Draven's Might is its printed Might plus its controller's points, read fresh each time (477.3.b), the "
          "opponent's points excluded; Rhasa's Energy cost falls by 1 per card in its controller's trash through the real "
          "play transaction, never below 0 (356.6); a private zone, a non-passive reader and a flat reduction are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
