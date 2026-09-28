#!/usr/bin/env python3
"""Regression gate for "Friendly units may be played to open battlefields." (Miss Fortune -
Buccaneer): a play permission a permanent grants, while it is on the board, to the unit cards its
side plays (Core 355.2.a, 355.2.b, 170.11.c).

Must hold, through the real play transaction:
  - with the granting permanent (p1's) on the board, p1's unit card may be played to an open
    Battlefield (no controller, nothing on it) - the play commits;
  - the same play with the permanent in the trash (not on the board) is refused
    (entry_location_illegal), and so is the same play with no grant at all;
  - the grant is p1's: p2's unit card is refused the open Battlefield, and a grant on a p2
    permanent does not reach p1's unit;
  - a gear card of p1's is not a unit: refused; a Battlefield p2 controls is not open: refused;
  - the legal-action enumerator offers the open Battlefield by the path open_battlefield
    exactly when the play commits;
  - any other granted shape is refused by the validator.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import legal_action as LA  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "Friendly units may be played to open battlefields."


def grant_fields():
    return (CG.compile_clause(SENTENCE, CG.load_grammar()).get("passive") or {}).get("object_fields") or {}


def board(*, granter="p1", granter_where="base", grant=True):
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}          # open (170.11.c)
    state["battlefields"]["bf1"] = {"controller": "p2", "objects": ["u2"]}      # p2's, occupied
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["objects"]["mf"] = {"owner": granter, "controller": granter, "kind": "unit", "base_might": 4,
                              "might_modifiers": [], "damage": 0, "exhausted": False,
                              **(copy.deepcopy(grant_fields()) if grant else {})}
    state["players"][granter]["zones"]["base" if granter_where == "base" else "trash"].append("mf")
    for oid, owner, kind in (("n1", "p1", "unit"), ("g1", "p1", "gear"), ("n2", "p2", "unit")):
        state["objects"][oid] = {"owner": owner, "controller": owner, "kind": kind, "base_might": 2 if kind == "unit" else 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": False,
                                 "printed_cost": {"energy": 1, "power": {}}}
        state["players"][owner]["zones"]["hand"].append(oid)
    for player in ("p1", "p2"):
        state["players"][player]["resources"] = {"energy": 3, "power": {}}
    return state


def play(state, actor, card, kind, battlefield):
    timing = fixture() if actor == "p1" else {**fixture(priority=actor), "turn_player": actor}
    got = PT.play_card(timing, state, {
        "schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": f"play-{card}", "actor": actor, "card": card,
        "chain_item": {"id": f"item-{card}", "object_kind": kind, "timing": "default"},
        "cost": {"base": {"energy": 1, "power": {}}},
        "entry_location": {"kind": "battlefield", "battlefield": battlefield},
        "payment_context": {"add_window_closed": True, "confirmed_by": "human"}})
    return "committed" if got.get("committed") else got.get("reason_code")


def main() -> int:
    errors: list[str] = []
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    if lowered.get("production_id") != "friendly_units_may_be_played_to_open_battlefields" or not grant_fields():
        errors.append(f"the sentence did not lower to the grant: {lowered.get('production_id')} {lowered.get('reason_code')}")
    cases = [
        ("p1's unit to the open Battlefield, the grant on the board", board(), "p1", "n1", "unit", "bf2", "committed"),
        ("the same, the granting permanent in the trash", board(granter_where="trash"), "p1", "n1", "unit", "bf2",
         "entry_location_illegal"),
        ("the same, no grant", board(grant=False), "p1", "n1", "unit", "bf2", "entry_location_illegal"),
        ("p2's unit to the open Battlefield under p1's grant", board(), "p2", "n2", "unit", "bf2", "entry_location_illegal"),
        ("p1's unit under a grant on p2's permanent", board(granter="p2"), "p1", "n1", "unit", "bf2",
         "entry_location_illegal"),
        ("p1's gear to the open Battlefield", board(), "p1", "g1", "gear", "bf2", None),
        ("p1's unit to p2's occupied Battlefield", board(), "p1", "n1", "unit", "bf1", "entry_location_illegal"),
    ]
    for label, state, actor, card, kind, bf, want in cases:
        if validate_state(state):
            errors.append(f"{label}: the board is invalid: {validate_state(state)[:2]}")
            continue
        got = play(state, actor, card, kind, bf)
        if (want is None and got == "committed") or (want is not None and got != want):
            errors.append(f"{label}: {got}, wanted {want or 'a refusal'}")
    for label, state, want in (("with the grant", board(), True), ("without it", board(grant=False), False)):
        _, candidates = LA._enumerate_play_card(None, fixture(), state, "p1")
        offered = [loc for c in candidates if c["action"]["card"] == "n1"
                   for loc in c["action"].get("entry_locations", []) if loc.get("battlefield") == "bf2"]
        if bool(offered) != want or (want and offered[0].get("paths") != ["open_battlefield"]):
            errors.append(f"the enumerator, {label}: offered {offered}")
    forged = board()
    forged["objects"]["mf"]["granted_play_permissions"] = [{"permission": "open_battlefield", "kind": "unit",
                                                             "controller_relation": "enemy"}]
    if not validate_state(forged):
        errors.append("a grant to enemy units was accepted; the shape is closed")

    if errors:
        print("FAILED: granted play permission" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'Friendly units may be played to open battlefields.' lets its side's unit cards enter an open "
          "Battlefield while the permanent is on the board, and nothing else: not off the board, not an enemy's "
          "unit, not under an enemy's grant, not a gear, not a controlled Battlefield; the enumerator agrees.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
