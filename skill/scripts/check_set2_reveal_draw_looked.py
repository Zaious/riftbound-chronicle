#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "... look at the top 4 cards of your Main Deck. You may reveal a gear from among them
and draw it. Then recycle the rest." (Ornn - Blacksmith) - draw_it with a choice (up to one of the looked-at cards, of a
kind) and reveal (the card shown to every player before it is drawn, Core 425).

  L1 a gear revealed and drawn   p1 picks the gear: it is drawn (a draw event, Core 414), seen by both players; the
                                 other three looked-at cards recycled
  L2 declined                    p1 picks none ("you may"): nothing drawn; all four recycled
  L3 not a gear                  the unit among them cannot be picked
  L4 no gear                     no gear among the four: nothing to pick, nothing asked
  V                              a choice of another zone, of two, or a reveal other than true does not validate

    python skill/scripts/check_set2_reveal_draw_looked.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program  # noqa: E402

errors: list[str] = []
TAKE = {"op": "draw_it", "effect_id": "take", "player": "p1", "decision_ref": "pick", "reveal": True,
        "choice": {"from": "revealed", "selection_kind": "unordered_set", "count": {"up_to": 1}, "by": "controller",
                   "visibility": "private_to_chooser", "criteria": {"kind": "gear"}}}
REST = {"op": "recycle", "effect_id": "rest", "player": "p1", "decision_ref": "rest", "order_ref": "rest-order",
        "choice": {"from": "revealed", "selection_kind": "unordered_set", "by": "controller",
                   "visibility": "private_to_chooser", "count": {"all": True}}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(kinds=("unit", "gear", "spell", "unit")):
    state = base_state()
    names = [f"top{i + 1}" for i in range(len(kinds))]
    for name, kind in zip(names, kinds):
        state["objects"][name] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": 1 if kind == "unit" else 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["main_deck"][:0] = names
    return state


def run(state, pick, rest_order):
    prog = program("ornn", {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 4}, TAKE, REST)
    decisions = [{"decision_id": "pick", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": pick,
                  "selection_identities": {c: object_identity(state, c) or f"{c}@0" for c in pick}}]
    receipts = [{"schema_version": "randomization-receipt.v1", "receipt_id": "rnd-1", "operation": "recycle_simultaneous",
                 "operation_id": "rest-order", "player": "p1", "permutation": list(rest_order),
                 "provenance": {"provider": "chronicle-harness", "method": "fisher-yates", "seed": "7"}}]
    value = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": decisions,
             "randomization_receipts": receipts}
    return apply_program(state, prog, decisions=value)


def main() -> int:
    state = board()
    done = run(state, ["top2"], ["top1", "top3", "top4"])
    if not done.get("committed"):
        fail("L1", f"refused: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    else:
        z = done["next_state"]["players"]["p1"]["zones"]
        take = next((t for t in done["trace"] if t.get("effect_id") == "take"), {})
        drawn = [e for e in done.get("events") or [] if e.get("kind") == "drawn"]
        if "top2" not in z["hand"] or sorted(z["main_deck"][-3:]) != ["top1", "top3", "top4"]:
            fail("L1", f"hand {z['hand']}, deck {z['main_deck']}")
        if take.get("objects_visible_to") != ["p1", "p2"] or not take.get("revealed_to_all") or len(drawn) != 1 \
                or (drawn[0].get("visibility") or {}).get("identity") != ["p1", "p2"]:
            fail("L1 shown", f"{take.get('objects_visible_to')} {take.get('revealed_to_all')} {drawn}")
    done = run(state, [], ["top1", "top2", "top3", "top4"])
    if not done.get("committed") or "top2" in done["next_state"]["players"]["p1"]["zones"]["hand"] \
            or len(done["next_state"]["players"]["p1"]["zones"]["main_deck"]) != len(state["players"]["p1"]["zones"]["main_deck"]):
        fail("L2", f"{done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    done = run(state, ["top1"], ["top2", "top3", "top4"])
    if done.get("committed"):
        fail("L3", "the unit among the looked-at cards was picked as a gear")
    nogear = board(("unit", "spell", "unit", "spell"))
    prog = program("ornn", {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 4}, TAKE)
    done = apply_program(nogear, prog)
    take = next((t for t in done.get("trace") or [] if t.get("effect_id") == "take"), {})
    if not done.get("committed") or take.get("outcome") != "no_op":
        fail("L4", f"{done.get('reason_code')} {take.get('outcome')}")
    for label, change in (("another zone", {"choice": {**TAKE["choice"], "from": "hand"}}),
                          ("two", {"choice": {**TAKE["choice"], "count": {"up_to": 2}}}),
                          ("a rune kind", {"choice": {**TAKE["choice"], "criteria": {"kind": "rune"}}}),
                          ("reveal false", {"reveal": False})):
        if not validate_program(program("bad", {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 4},
                                        {**TAKE, **change})):
            fail("V " + label, "validated")
    if errors:
        print("FAILED: set 2 reveal a looked-at card of a kind and draw it")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: of the looked-at cards up to one of the kind is revealed to every player and drawn (425, 414), the rest "
          "recycled; declined, nothing drawn; another kind cannot be picked; none of the kind, nothing asked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
