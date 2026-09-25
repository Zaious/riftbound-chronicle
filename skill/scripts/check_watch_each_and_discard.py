#!/usr/bin/env python3
"""
Gate for two watched triggers (2026-09-26), each through resolve_with_program, each with the
watch the clause grammar itself lowers from the golden sentence (not a hand-written copy):

  - "When you stun an enemy unit": one trigger PER stunned enemy unit (Core 383.3.a) - a
    resolution of p1's that stuns two enemy units schedules two; the same resolution under
    "When you stun one or more enemy units" schedules one; stunning a friendly unit, or p2
    stunning p1's enemies, schedules none;
  - "When you discard one or more cards": p1 discarding two cards in one instruction schedules
    one; p2 discarding schedules none; p1 with an empty hand discards nothing (Core 422.4) and
    schedules none; the watcher's card in a hand (not on the board) schedules none.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_watch_wiring import resolve, scheduled_from, watcher  # noqa: E402


def watch_of(sentence: str) -> dict:
    out = cg.compile_clause(sentence, cg.load_grammar())
    return copy.deepcopy(out["passive"]["object_fields"]["event_triggers"][0]["watch"])


def main() -> int:
    errors: list[str] = []
    each = watch_of("When you stun an enemy unit, draw 1.")
    batch = watch_of("When you stun one or more enemy units, draw 1.")
    if each.get("grouping") is not None or batch.get("grouping") != "one_or_more":
        errors.append(f"the two stun watches are not 'each' and 'one or more': {each} / {batch}")

    def two_enemies():
        state = base_state()
        state["objects"]["e2"] = copy.deepcopy(state["objects"]["u2"])
        state["players"]["p2"]["zones"]["base"].append("e2")
        return state

    stun_two = [{"op": "stun", "effect_id": "s1", "object_id": "u2"}, {"op": "stun", "effect_id": "s2", "object_id": "e2"}]
    # one per stunned enemy: two abilities of p1's triggered together, so the engine first asks
    # p1 to order them (Core 383.3.d.1) - naming exactly two - and, ordered, schedules both
    board = watcher(two_enemies(), each)
    ask = resolve(board, stun_two)
    if ask.get("committed") or ask.get("reason_code") != "trigger_order_required" or len(ask.get("trigger_ids") or []) != 2:
        errors.append(f"two stunned enemies did not raise two triggers to order: {ask.get('reason_code')} {ask.get('trigger_ids')}")
    else:
        from effect_ir import hash_value
        from check_rules_core import fixture, item
        from check_effect_ir import program
        from resolution_bridge import resolve_with_program
        timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
        ordered = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(board), "chain_item_id": "spell-1",
                   "decisions": [{"decision_id": ask["decision_ids"][0], "stage": "resolution", "kind": "trigger_order",
                                  "controller": "p1", "value": list(ask["trigger_ids"])}]}
        got = resolve_with_program(timing, "spell-1", board, program("resolving", *stun_two), engine_decisions=ordered)
        if not got.get("committed") or len(scheduled_from(got)) != 2:
            errors.append(f"'When you stun an enemy unit', ordered, scheduled {len(scheduled_from(got))}, wanted 2 "
                          f"({got.get('reason')})")
    got = resolve(watcher(two_enemies(), batch), stun_two)
    if not got.get("committed") or len(scheduled_from(got)) != 1:
        errors.append(f"'When you stun one or more enemy units' scheduled {len(scheduled_from(got))} for two stunned "
                      f"enemies, wanted 1 ({got.get('reason')})")
    friendly = resolve(watcher(base_state(), each), [{"op": "stun", "effect_id": "s", "object_id": "u1"}])
    theirs = resolve(watcher(base_state(), each), [{"op": "stun", "effect_id": "s", "object_id": "u1"}], controller="p2")
    for label, result in (("stunning a friendly unit", friendly), ("p2 stunning p1's unit", theirs)):
        if not result.get("committed") or scheduled_from(result):
            errors.append(f"{label} scheduled 'When you stun an enemy unit' (or failed: {result.get('reason')})")

    discard = watch_of("When you discard one or more cards, draw 1.")
    if discard.get("kinds") != ["discarded"] or discard.get("scope") != "actor" or discard.get("grouping") != "one_or_more":
        errors.append(f"the discard watch is not 'discarded, by you, one per batch': {discard}")

    def with_hand(owner: str, n: int):
        state = watcher(base_state(), discard)
        hand = state["players"][owner]["zones"]["hand"]
        for i in range(n):
            card = f"{owner}-h{i}"
            state["objects"][card] = {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0,
                                      "might_modifiers": [], "damage": 0, "exhausted": False}
            hand.append(card)
        return state

    mine = resolve(with_hand("p1", 2), [{"op": "discard", "effect_id": "d", "player": "p1", "count": 2}])
    if not mine.get("committed") or len(scheduled_from(mine)) != 1:
        errors.append(f"p1 discarding two cards scheduled {len(scheduled_from(mine))}, wanted 1 ({mine.get('reason')})")
    theirs = resolve(with_hand("p2", 2), [{"op": "discard", "effect_id": "d", "player": "p2", "count": 2}], controller="p2")
    empty = resolve(watcher(base_state(), discard), [{"op": "discard", "effect_id": "d", "player": "p1", "count": 2}])
    in_hand = watcher(base_state(), discard, where="hand")
    for i in range(2):
        in_hand["objects"][f"p1-h{i}"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                          "might_modifiers": [], "damage": 0, "exhausted": False}
        in_hand["players"]["p1"]["zones"]["hand"].append(f"p1-h{i}")
    away = resolve(in_hand, [{"op": "discard", "effect_id": "d", "player": "p1", "count": 3}])
    for label, result in (("p2 discarding", theirs), ("p1 discarding from an empty hand", empty),
                          ("the watcher's card in a hand", away)):
        if not result.get("committed") or scheduled_from(result):
            errors.append(f"{label} scheduled 'When you discard one or more cards' (or failed: {result.get('reason')})")

    if errors:
        print("FAILED: watch each / discard checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'When you stun an enemy unit' schedules one trigger per stunned enemy (two for two) where 'one or "
          "more' schedules one; a friendly stun or p2's stun schedules none; 'When you discard one or more cards' "
          "schedules one for p1's two-card discard and none for p2's discard or an empty-handed discard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
