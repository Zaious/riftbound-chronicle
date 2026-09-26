#!/usr/bin/env python3
"""
Gate for two watched triggers (2026-09-26), each through the engine's own resolution and play
paths, each with the watch the clause grammar itself lowers from the golden sentence:

  - "When you stun an enemy unit": one trigger PER stunned enemy unit - a resolution of p1's that
    stuns two enemy units asks p1 to order two triggers (Core 383.3.d) and, ordered, schedules two;
    the same resolution under "When you stun one or more enemy units" schedules one; p1 stunning a
    friendly unit, p2 stunning p2's own unit (enemy to p1, but not stunned by p1), and p1 stunning
    an enemy that is already stunned (Core 423.1.a.1: it cannot be stunned again) schedule none;
  - "When you discard one or more cards" is about the player whose card is discarded, not about
    whose effect it is: p1 discarding two cards in one instruction schedules one; p2's effect
    making p1 discard schedules one; p1's effect making p2 discard schedules none; p2 discarding
    schedules none; p1 with an empty hand discards nothing (Core 422.4) and schedules none; the
    watcher's card in a hand schedules none; a card played by p1 with a discard as its COST
    schedules one (Core 422.1.b: a discard paid as a cost is a discard).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from check_watch_wiring import resolve, scheduled_from, watcher  # noqa: E402
from effect_ir import hash_value  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402


def watch_of(sentence: str) -> dict:
    out = cg.compile_clause(sentence, cg.load_grammar())
    return copy.deepcopy(out["passive"]["object_fields"]["event_triggers"][0]["watch"])


def with_hand(state: dict, owner: str, n: int) -> dict:
    hand = state["players"][owner]["zones"]["hand"]
    for i in range(n):
        card = f"{owner}-h{i}"
        state["objects"][card] = {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False}
        hand.append(card)
    return state


def main() -> int:
    errors: list[str] = []
    each = watch_of("When you stun an enemy unit, draw 1.")
    batch = watch_of("When you stun one or more enemy units, draw 1.")
    if each.get("grouping") is not None or batch.get("grouping") != "one_or_more" or each.get("scope") != "actor":
        errors.append(f"the two stun watches are not 'each, by you' and 'one or more': {each} / {batch}")

    def two_enemies():
        state = base_state()
        state["objects"]["e2"] = copy.deepcopy(state["objects"]["u2"])
        state["players"]["p2"]["zones"]["base"].append("e2")
        return state

    stun_two = [{"op": "stun", "effect_id": "s1", "object_id": "u2"}, {"op": "stun", "effect_id": "s2", "object_id": "e2"}]
    board = watcher(two_enemies(), each)
    ask = resolve(board, stun_two)
    if ask.get("committed") or ask.get("reason_code") != "trigger_order_required" or len(ask.get("trigger_ids") or []) != 2:
        errors.append(f"two stunned enemies did not raise two triggers to order: {ask.get('reason_code')} {ask.get('trigger_ids')}")
    else:
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
    theirs = resolve(watcher(base_state(), each), [{"op": "stun", "effect_id": "s", "object_id": "u2"}], controller="p2")
    first = resolve(watcher(base_state(), each), [{"op": "stun", "effect_id": "s", "object_id": "u2"}])
    if first.get("committed"):
        again = resolve(first["next_effect_state"], [{"op": "stun", "effect_id": "s2", "object_id": "u2"}])
    else:
        again = first
    for label, result in (("p1 stunning a friendly unit", friendly), ("p2 stunning its own unit", theirs),
                          ("p1 stunning an enemy already stunned (Core 423.1.a.1)", again)):
        if not result.get("committed") or scheduled_from(result):
            errors.append(f"{label} scheduled 'When you stun an enemy unit' (or failed: {result.get('reason')})")

    discard = watch_of("When you discard one or more cards, draw 1.")
    if discard.get("kinds") != ["discarded"] or discard.get("scope") != "controller" or discard.get("grouping") != "one_or_more":
        errors.append(f"the discard watch is not 'discarded, the discarding player, one per batch': {discard}")

    def run(owner_hand: str, n: int, player: str, controller: str, where: str = "base"):
        state = with_hand(watcher(base_state(), discard, where=where), owner_hand, n)
        count = len(state["players"][player]["zones"]["hand"]) or 2      # the whole hand: no choice to make
        return resolve(state, [{"op": "discard", "effect_id": "d", "player": player, "count": count}], controller=controller)

    for label, result, wanted in (
            ("p1 discarding two cards by its own effect", run("p1", 2, "p1", "p1"), 1),
            ("p2's effect making p1 discard", run("p1", 2, "p1", "p2"), 1),
            ("p1's effect making p2 discard", run("p2", 2, "p2", "p1"), 0),
            ("p2 discarding by its own effect", run("p2", 2, "p2", "p2"), 0),
            ("p1 discarding from an empty hand", run("p1", 0, "p1", "p1"), 0),
            ("the watcher's card in a hand", run("p1", 2, "p1", "p1", where="hand"), 0)):
        if not result.get("committed") or len(scheduled_from(result)) != wanted:
            errors.append(f"{label}: scheduled {len(scheduled_from(result))}, wanted {wanted} ({result.get('reason')})")

    # a discard paid as a COST (Core 422.1.b): p1 plays a spell whose additional cost is 'discard 1'
    from check_costs_and_activation import declaration, hand_state
    from play_transaction import play_card
    paid = watcher(hand_state("c1", "c2"), discard)
    cost = {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "d", "mandatory": True,
                                                                "payment": {"kind": "discard", "amount": 1}}]}
    played = play_card(fixture(), paid, declaration(cost=cost))
    if not played.get("committed") or len(scheduled_from(played)) != 1:
        errors.append(f"a discard paid as a cost scheduled {len(scheduled_from(played))}, wanted 1 "
                      f"({played.get('reason_code')} {played.get('reason')})")
    plain = watcher(hand_state("c1"), discard)
    no_cost = play_card(fixture(), plain, declaration())
    if not no_cost.get("committed") or scheduled_from(no_cost):
        errors.append(f"a play with no discard in its cost scheduled the discard watcher ({no_cost.get('reason')})")

    if errors:
        print("FAILED: watch each / discard checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'When you stun an enemy unit' schedules one trigger per enemy p1 stuns (two for two, ordered) where "
          "'one or more' schedules one; a friendly stun, p2's stun and a re-stun schedule none; 'When you discard one "
          "or more cards' follows the discarding player - p1's own discard, p2 making p1 discard and a discard paid as "
          "a cost schedule one; p1 making p2 discard, p2's discard, an empty hand and a watcher in hand schedule none.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
