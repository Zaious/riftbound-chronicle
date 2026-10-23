#!/usr/bin/env python3
"""A count of the cards a reveal showed, and recycling them (package 11, Teemo - Strategist: "When I defend, choose an
enemy unit here and reveal the top 5 cards of your Main Deck. Deal 1 to that unit for each card with [Hidden] revealed
this way, then recycle the revealed cards.").

Both read an EARLIER reveal of the same program (a linked instruction, Core 359.3.e.14): count_per {kind:
linked_revealed_with_keyword, effect_id, keyword: hidden} multiplies a Deal's printed amount by how many of the revealed
cards carry [Hidden]; recycle {revealed_by} recycles the revealed cards. Each card is counted, and recycled, only while it
is still the object it was when revealed (Core 124). Neither chooses anything (355.10.a).

  R1 two of five     the top five hold two [Hidden] cards: the unit is dealt 2; the five go to the bottom, the sixth is
                     now on top
  R2 none            no [Hidden] card among them: nothing is dealt (linked_count_zero); the five are still recycled
  R3 short deck      three cards in the deck, one [Hidden]: 1 dealt, the three recycled
  R4 moved meanwhile one revealed [Hidden] card drawn before the Deal (a new object in the hand): it is not counted, not
                     recycled
  V  validation      the count names an earlier top reveal and is read by a Deal only; revealed_by names no objects
  D  defend          "When I defend, ..." lowers to one defend trigger (the card's own trigger)

    python skill/scripts/check_revealed_count.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
COUNT = {"kind": "linked_revealed_with_keyword", "effect_id": "rv", "keyword": "hidden"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects, pid="teemo-fx"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "tm", "effects": effects}


def body(between=None):
    effects = [{"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 5}]
    effects += between or []
    effects += [{"op": "deal_damage", "effect_id": "dmg", "object_id": "e1", "amount": 1, "count_per": dict(COUNT)},
                {"op": "recycle", "effect_id": "rc", "player": "p1", "revealed_by": "rv"}]
    return program(effects)


def card(hidden):
    return {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, **({"hidden": True} if hidden else {})}


def board(deck):
    """deck: [(id, hidden)] top first; e1 (p2, 6 Might) and tm (p1) at bf1."""
    state = base_state()
    for old in state["players"]["p1"]["zones"]["main_deck"]:
        state["objects"].pop(old, None)
    state["players"]["p1"]["zones"]["main_deck"] = []
    for oid, hidden in deck:
        state["objects"][oid] = card(hidden)
        state["players"]["p1"]["zones"]["main_deck"].append(oid)
    state["objects"]["e1"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 6, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["objects"]["tm"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["battlefields"]["bf1"]["objects"] += ["e1", "tm"]
    return settle_contested(state)


def run(state, prog):
    """apply_program, answering the random order of a simultaneous recycle (Core 417.5) with a receipt that keeps the
    revealed order (ADR-0010 section 2)."""
    receipts = []
    for _ in range(3):
        env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [],
               "randomization_receipts": receipts} if receipts else None
        got = apply_program(state, prog, decisions=env)
        if got.get("committed") or got.get("reason_code") != "randomization_receipt_required":
            return got
        shown = next((e for e in got.get("trace") or [] if e.get("effect_id") == "rv"), {})
        # a draw between the reveal and the recycle takes the deck's top cards first (R4)
        draws = sum(e.get("count", 0) for e in prog["effects"] if e.get("op") == "draw")
        drawn = state["players"]["p1"]["zones"]["main_deck"][:draws]
        order = [r["object_id"] for r in shown.get("revealed") or [] if r["object_id"] not in drawn]
        for ref in got["decision_ids"]:
            receipts.append({"schema_version": "randomization-receipt.v1", "receipt_id": f"{ref}:rnd",
                             "operation": "recycle_simultaneous", "operation_id": ref, "player": "p1",
                             "permutation": order, "provenance": {"provider": "gate", "method": "listed-order"}})
    return got


def step(got, effect_id):
    return next((e for e in got.get("trace") or [] if e.get("effect_id") == effect_id), {})


def main() -> int:
    five = [("h1", True), ("x1", False), ("h2", True), ("x2", False), ("x3", False), ("x4", False)]
    got = run(board(five), body())
    deck = (got.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("main_deck", [])
    if not got.get("committed") or got["next_state"]["objects"]["e1"]["damage"] != 2 or deck[:1] != ["x4"] \
            or sorted(deck[1:]) != sorted(["h1", "x1", "h2", "x2", "x3"]):
        fail("R1 two of five", f"{got.get('reason_code')} {got.get('reason') or got.get('errors')} deck {deck} "
                               f"damage {(got.get('next_state') or {}).get('objects', {}).get('e1', {}).get('damage')}")
    none = run(board([(o, False) for o, _ in five]), body())
    if not none.get("committed") or none["next_state"]["objects"]["e1"]["damage"] != 0 \
            or step(none, "dmg").get("reason") != "linked_count_zero" or step(none, "rc").get("outcome") != "applied":
        fail("R2 none", f"{none.get('reason')} {step(none, 'dmg')} {step(none, 'rc').get('outcome')}")
    short = run(board([("h1", True), ("x1", False), ("x2", False)]), body())
    if not short.get("committed") or short["next_state"]["objects"]["e1"]["damage"] != 1 \
            or sorted(short["next_state"]["players"]["p1"]["zones"]["main_deck"]) != ["h1", "x1", "x2"]:
        fail("R3 short deck", f"{short.get('reason')} {step(short, 'dmg')}")
    drawn = run(board(five), body([{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]))
    hand = (drawn.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("hand", [])
    if not drawn.get("committed") or drawn["next_state"]["objects"]["e1"]["damage"] != 1 or "h1" not in hand \
            or "h1" in (step(drawn, "rc").get("objects") or step(drawn, "rc").get("recycled") or []):
        fail("R4 moved meanwhile", f"{drawn.get('reason')} damage {(drawn.get('next_state') or {}).get('objects', {}).get('e1', {}).get('damage')} hand {hand}")
    for label, effects in (
            ("a count naming no reveal", [{"op": "deal_damage", "effect_id": "dmg", "object_id": "e1", "amount": 1,
                                           "count_per": dict(COUNT)}]),
            ("a count read by a draw", [{"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 5},
                                        {"op": "draw", "effect_id": "d", "player": "p1", "count": 1, "count_per": dict(COUNT)}]),
            ("another keyword", [{"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 5},
                                 {"op": "deal_damage", "effect_id": "dmg", "object_id": "e1", "amount": 1,
                                  "count_per": {**COUNT, "keyword": "deflect"}}]),
            ("revealed_by with objects", [{"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 5},
                                          {"op": "recycle", "effect_id": "rc", "player": "p1", "revealed_by": "rv",
                                           "objects": ["x1"]}])):
        if not validate_program(program(effects)):
            fail("V validation", f"{label} validated")
    if validate_program(body()):
        fail("V validation", f"the card's program did not validate: {validate_program(body())}")
    # the card's trigger: a Unit's own Defend trigger, filed where the attack-or-defend row files its Defend half
    import clause_grammar as cg
    lowered = cg.compile_card([{"text": "When I defend, draw 1."}], cg.load_grammar())
    fields = (lowered.get("passive") or {}).get("object_fields") or {}
    if lowered.get("unsupported_clauses") or len(fields.get("defend_triggers") or []) != 1 or fields.get("attack_triggers"):
        fail("D defend", f"'When I defend' did not lower to one defend trigger: {lowered.get('unsupported_clauses')} {fields}")
    if errors:
        print("FAILED: a count of the revealed cards")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'for each card with [Hidden] revealed this way' counts the cards that reveal showed and are still those "
          "cards; 'recycle the revealed cards' recycles exactly them; none counted - nothing dealt, still recycled; a short "
          "deck counts what it showed; 'When I defend' is a defend trigger (R1-R4, V, D)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
