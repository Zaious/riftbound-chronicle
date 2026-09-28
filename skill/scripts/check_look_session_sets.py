#!/usr/bin/env python3
"""
Regression gate for the look-at session's own sets (package 5, 2026-09-27): a later
instruction of the same program acting on what an earlier look left.

  choice.count {all: true}  - "recycle the rest" (Core 416.4, 424.4.a): every card the
      session still marks, with no choice made; only an unordered set from `revealed`
      may say it (a single, a board, a hand or an ordered choice with `all` is refused).
  Look, take one, recycle the rest (look_at_top 3, put_in_hand 1, recycle all):
      - the taken card is in the hand; the other two are at the bottom of the deck, in
        the randomization receipt's order (416.5), the rest of the deck unchanged above them; the
        recycle asks for no card_selection (and the card in hand is never a candidate);
      - a deck of two looks at two, takes one and recycles the other; a deck of one takes
        it and recycles nothing, without Burn Out (431.1.c, 431.1.c.1);
      - counterexample: the same body with {exactly: 1} leaves a looked card on top.
  Look at two, recycle up to both, put the others back (look_at_top 2, recycle up_to 2,
  put_back top) - the Predict composition (436.1.a):
      - recycling none, one or both leaves the deck exactly as the engine's own predict 2
        with the same choices;
      - recycling three is refused (at most two).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402

PRIVATE = {"by": "controller", "visibility": "private_to_chooser"}


def deck_of(n):
    state = base_state()
    for card in ("c1", "c2"):
        state["players"]["p1"]["zones"]["main_deck"].remove(card)
        del state["objects"][card]
    for k in range(1, n + 1):
        state["objects"][f"d{k}"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                     "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["main_deck"] = [f"d{k}" for k in range(1, n + 1)]
    return state


def envelope(state, *entries, receipts=()):
    value = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": list(entries)}
    if receipts:
        value["randomization_receipts"] = list(receipts)
    return value


def receipt(operation_id, permutation):
    """Core 416.5: the random bottom order of a simultaneous recycle, from outside (ADR-0010 §2)."""
    return {"schema_version": "randomization-receipt.v1", "receipt_id": f"rnd-{operation_id}", "operation": "recycle_simultaneous",
            "operation_id": operation_id, "player": "p1", "permutation": list(permutation),
            "provenance": {"provider": "chronicle-harness", "method": "fisher-yates", "seed": "7"}}


def pick(decision_id, ids, state, kind="card_selection"):
    return {"decision_id": decision_id, "stage": "resolution", "kind": kind, "controller": "p1", "value": list(ids),
            "selection_identities": {i: object_identity(state, i) or f"{i}@0" for i in ids}}


def take_one_recycle_rest(count_form):
    return program("take-rest",
                   {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 3},
                   {"op": "put_in_hand", "effect_id": "pick", "player": "p1", "count": 1, "decision_ref": "pick"},
                   {"op": "recycle", "effect_id": "rest", "player": "p1", "decision_ref": "rest", "order_ref": "rest-order",
                    "choice": {"selection_kind": "unordered_set", "count": count_form, "from": "revealed", **PRIVATE}})


def look_recycle_put_back():
    return program("look-recycle-back",
                   {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 2},
                   {"op": "recycle", "effect_id": "rc", "player": "p1", "decision_ref": "recycle-pick", "order_ref": "recycle-order",
                    "choice": {"selection_kind": "unordered_set", "count": {"up_to": 2}, "from": "revealed", **PRIVATE}},
                   {"op": "put_back", "effect_id": "back", "player": "p1", "position": "top", "decision_ref": "put-back-order"})


def main() -> int:
    errors: list[str] = []

    # --- the count form ---------------------------------------------------------------------------------
    ok = {"selection_kind": "unordered_set", "count": {"all": True}, "from": "revealed", **PRIVATE}
    if ed.validate_choice_spec(ok):
        errors.append(f"{{all: true}} over revealed was refused: {ed.validate_choice_spec(ok)}")
    for label, bad in (("single", {**ok, "selection_kind": "single"}),
                       ("ordered", {**ok, "selection_kind": "ordered_permutation"}),
                       ("from hand", {**ok, "from": "hand"}),
                       ("from board", {"selection_kind": "unordered_set", "count": {"all": True}, "from": "board",
                                       "criteria": {"kind": "unit"}}),
                       ("all: 2", {**ok, "count": {"all": 2}})):
        if not ed.validate_choice_spec(bad):
            errors.append(f"{{all}} accepted on a {label} choice")

    # --- look at 3, take 1, recycle the rest ------------------------------------------------------------
    state = deck_of(5)
    prog = take_one_recycle_rest({"all": True})
    if validate_program(prog) or validate_state(state):
        errors.append(f"the take-one-recycle-rest body is not valid: {validate_program(prog)} {validate_state(state)}")
    asked = apply_program(state, prog, decisions=envelope(state, pick("pick", ["d2"], state)))
    if asked.get("committed") or asked.get("reason_code") != "randomization_receipt_required" or asked.get("decision_ids") != ["rest-order"]:
        errors.append(f"recycling the rest waited for something other than its random bottom order (416.5): {asked.get('reason_code')} "
                      f"{asked.get('decision_ids')}")
    done = apply_program(state, prog, decisions=envelope(state, pick("pick", ["d2"], state),
                                                         receipts=[receipt("rest-order", ["d3", "d1"])]))
    zones = (done.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
    if not done.get("committed") or zones.get("hand") != ["d2"] or zones.get("main_deck") != ["d4", "d5", "d3", "d1"]:
        errors.append(f"look 3 / take d2 / recycle the rest did not leave hand [d2] and deck [d4, d5, d3, d1]: "
                      f"{done.get('reason') or done.get('errors')} {zones}")
    recycle = next((t for t in done.get("trace") or [] if t.get("op") == "recycle"), {})
    if not (recycle.get("selection") or {}).get("forced"):
        errors.append(f"the rest was chosen, not forced: {recycle.get('selection')}")
    short = deck_of(2)
    two = apply_program(short, prog, decisions=envelope(short, pick("pick", ["d1"], short)))
    z2 = (two.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
    if not two.get("committed") or z2.get("hand") != ["d1"] or z2.get("main_deck") != ["d2"]:
        errors.append(f"a deck of two: {two.get('reason_code') or two.get('errors')} {z2}")
    single = deck_of(1)
    one = apply_program(single, prog)
    z1 = (one.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
    if not one.get("committed") or z1.get("hand") != ["d1"] or z1.get("main_deck") != [] \
            or any(t.get("burn_out") for t in one.get("trace") or []):
        errors.append(f"a deck of one: {one.get('reason_code') or one.get('errors')} {z1}")
    wrong = apply_program(state, take_one_recycle_rest({"exactly": 1}),
                          decisions=envelope(state, pick("pick", ["d2"], state), pick("rest", ["d3"], state)))
    zw = (wrong.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
    if wrong.get("committed") and zw.get("main_deck") == ["d4", "d5", "d3", "d1"]:
        errors.append("counterexample: {exactly: 1} recycled the whole rest too, so {all} is not what bites")

    # --- look at 2, recycle up to both, put the rest back: predict 2 --------------------------------------
    body = look_recycle_put_back()
    predict = program("predict", {"op": "predict", "effect_id": "p", "player": "p1", "count": 2,
                                  "recycle_ref": "rc", "order_ref": "ro", "put_back_ref": "pb"})
    for chosen, order in (([], ["d2", "d1"]), (["d1"], ["d2"]), (["d1", "d2"], [])):
        board = deck_of(4)
        mine = [pick("recycle-pick", chosen, board)] + ([pick("put-back-order", order, board, "card_ordering")] if len(order) > 1 else [])
        theirs = [pick("rc", chosen, board)] + ([pick("pb", order, board, "card_ordering")] if len(order) > 1 else [])
        # 416.5: two or more recycled at once go in a random order - a receipt, not a player's ordering
        mine_r = [receipt("recycle-order", chosen)] if len(chosen) > 1 else []
        theirs_r = [receipt("ro", chosen)] if len(chosen) > 1 else []
        got = apply_program(board, body, decisions=envelope(board, *mine, receipts=mine_r))
        want = apply_program(board, predict, decisions=envelope(board, *theirs, receipts=theirs_r))
        deck = lambda r: ((r.get("next_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("main_deck"))
        if not got.get("committed") or not want.get("committed") or deck(got) != deck(want):
            errors.append(f"recycling {chosen}: the three instructions left {deck(got)} "
                          f"({got.get('reason_code') or got.get('errors')}), predict 2 left {deck(want)}")
    board = deck_of(4)
    too_many = apply_program(board, body, decisions=envelope(board, pick("recycle-pick", ["d1", "d2", "d3"], board)))
    if too_many.get("committed"):
        errors.append("recycling three of two looked cards was accepted")

    if errors:
        print("FAILED\n  - " + "\n  - ".join(errors))
        return 1
    print("OK: {all: true} takes every card the look still marks, forced, and only over revealed; look 3 / take 1 / "
          "recycle the rest leaves the taken card in hand and the other two at the bottom (a deck of two or one as "
          "far as it goes, no Burn Out), and {exactly: 1} does not; look 2 / recycle up to both / put the others back "
          "leaves the deck exactly as predict 2 with the same choices, and three is refused.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
