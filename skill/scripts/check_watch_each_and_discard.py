#!/usr/bin/env python3
"""
Gate for two watched triggers (2026-09-26), each through the engine's own resolution and play
paths, each with the watch the clause grammar itself lowers from the golden sentence:

  - "When you stun an enemy unit": one trigger PER stunned enemy unit - a resolution of p1's that
    stuns two enemy units asks p1 to order two triggers (Core 383.3.d) and, ordered, schedules two;
    the same resolution under "When you stun one or more enemy units" schedules one; p1 stunning a
    friendly unit, p2 stunning p2's own unit (enemy to p1, but not stunned by p1), and p1 stunning
    an enemy that is already stunned (Core 423.1.a.1: it cannot be stunned again) schedule none;
  - "When you discard one or more cards" is about the player whose card is discarded (the
    event's player, scope `player`), not about whose effect it is: p1 discarding two cards in one
    instruction schedules one; p2's effect making p1 discard schedules one; p1's effect making p2
    discard schedules none; p2 discarding schedules none; p1 with an empty hand discards nothing
    (Core 422.4) and schedules none; the watcher's card in a hand schedules none;
  - a discard paid as a COST is a discard (Core 422.2.a, 422.3): a card played by p1 with a
    discard in its cost schedules one, and so does an ability p1 activates with one (no `played`
    event: the discard alone wakes it, and the ability stays the item under the trigger); a play
    or an activation with no discard in its cost schedules none; two cost components give events
    with distinct ids, shaped hand -> trash like an instruction's discard;
  - two of p1's watchers woken by one cost discard ask p1 to order them (Core 383.3.d) instead
    of refusing the play; ordered, both are scheduled;
  - a recycle and a kill paid as costs wake their watchers; a unit killed as a cost puts its own
    death trigger on the Chain as its own earlier batch (Core 428.1.a.1.b), under what the death
    woke, whoever controls the watcher; a kill cost a replacement changed is refused by name
    (Core 357.2.a: it is paid, but its events are not modelled), never called unpayable;
  - every field a result, its receipt and its payment events carry is one the schema allows.
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
    if discard.get("kinds") != ["discarded"] or discard.get("scope") != "player" or discard.get("grouping") != "one_or_more":
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

    # a discard paid as a COST (Core 422.2.a, 422.3): p1 plays a spell whose additional cost is 'discard 1'
    from check_costs_and_activation import ability_declaration, declaration, envelope, hand_state
    from game_events import validate_events
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

    # ... and the same for an ACTIVATED ability of u1 (no `played` event: the discard alone wakes it)
    ability_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "d", "mandatory": True,
                                                                        "payment": {"kind": "discard", "amount": 1}}]}
    activated = play_card(fixture(), watcher(hand_state("c1"), discard), ability_declaration(cost=ability_cost))
    items = (activated.get("next_timing_state") or {}).get("chain", {}).get("items", [])
    if not activated.get("committed") or len(scheduled_from(activated)) != 1:
        errors.append(f"an ability with a discard cost scheduled {len(scheduled_from(activated))}, wanted 1 "
                      f"({activated.get('reason_code')} {activated.get('reason')})")
    elif not items or items[0].get("id") != "ability-1":
        errors.append(f"the ability is not the item under the discard trigger: {[i.get('id') for i in items]}")
    no_discard = play_card(fixture(), watcher(hand_state("c1"), discard), ability_declaration())
    if not no_discard.get("committed") or scheduled_from(no_discard):
        errors.append(f"an ability with no discard in its cost scheduled the discard watcher ({no_discard.get('reason')})")

    # two discard components: two events, distinct ids, each hand -> trash with its identity before and after
    import game_events
    two_parts = {"base": {"energy": 1, "power": {}},
                 "additional": [{"cost_id": "d1", "mandatory": True, "payment": {"kind": "discard", "amount": 1}},
                                {"cost_id": "d2", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]}
    # the payer picks c2 for the first; the second then has only c3 left (forced)
    from check_costs_and_activation import pick
    state3 = hand_state("c1", "c2", "c3")
    both = play_card(fixture(), state3, declaration(cost=two_parts),
                     engine_decisions=envelope(state3, pick("cost:play-1:d1", ["c2"], state3)))
    if not both.get("committed"):
        errors.append(f"a play with two discard components did not commit: {both.get('reason_code')} {both.get('reason')}")
    else:
        events = game_events.cost_zone_events(
            play_id="play-1", actor="p1", source_card="c1", state=both["next_effect_state"],
            pay_events=both["cost_receipt"]["payment_events"])
        ids = [e["event_id"] for e in events]
        shaped = all(e["location_before"] == {"kind": "player_zone", "player": "p1", "zone": "hand"}
                     and e["location_after"] == {"kind": "player_zone", "player": "p1", "zone": "trash"}
                     and e["identity_before"] and e["identity_after"] and e["identity_before"] != e["identity_after"]
                     and e["source"] == {"object": "c1", "kind": "object"} and e["player"] == "p1" for e in events)
        problems = validate_events(events)
        if len(ids) != 2 or len(set(ids)) != 2 or not shaped or problems:
            errors.append(f"two cost discards are not two well-shaped events: {ids} shaped={shaped} {problems}")

    # two of p1's watchers woken by one cost discard: p1 orders them (Core 383.3.d), the play is not refused
    two_watchers = watcher(hand_state("c1", "c2"), discard)
    second = copy.deepcopy(two_watchers["objects"]["w1"])
    second["event_triggers"][0].update({"trigger_id": "w2", "source_object": "w2"})
    two_watchers["objects"]["w2"] = second
    two_watchers["players"]["p1"]["zones"]["base"].append("w2")
    from engine_check import build_engine_check
    from play_transaction import validate_play_result
    ask = play_card(fixture(), two_watchers, declaration(cost=cost))
    if ask.get("committed") or ask.get("reason_code") != "trigger_order_required" or not ask.get("decision_ids") \
            or len(ask.get("trigger_ids") or []) != 2 or ask.get("next_effect_state_hash") != hash_value(two_watchers) \
            or validate_play_result(ask):
        errors.append(f"two watchers woken by a cost discard did not ask p1 for their order: "
                      f"{ask.get('reason_code')} {ask.get('decision_ids')} {ask.get('trigger_ids')} {validate_play_result(ask)}")
    else:
        wrapped = build_engine_check("play", ask, input_hashes={"timing_state": "sha256:" + "1" * 64,
                                                                "effect_state": hash_value(two_watchers),
                                                                "play_declaration": "sha256:" + "2" * 64})
        if wrapped["outcome"] != "decision_required" or wrapped["decision_required"]["kind"] != "trigger_order":
            errors.append(f"the play's trigger order wrapped as {wrapped['outcome']} {wrapped.get('decision_required')}")
        order = {"decision_id": ask["decision_ids"][0], "stage": "resolution", "kind": "trigger_order",
                 "controller": "p1", "value": list(reversed(ask["trigger_ids"]))}
        ordered = play_card(fixture(), two_watchers, declaration(cost=cost), engine_decisions=envelope(two_watchers, order))
        woke = [i for i in (ordered.get("next_timing_state") or {}).get("chain", {}).get("items", [])
                if str(i.get("id", "")).startswith(("w@", "w2@")) or str(i.get("trigger_id", "")).startswith(("w@", "w2@"))]
        if not ordered.get("committed") or len(woke) != 2 or validate_play_result(ordered):
            errors.append(f"ordered, the two cost-discard triggers were not both scheduled: {len(woke)} "
                          f"({ordered.get('reason_code')} {ordered.get('reason')})")
        # the order supplied by the wrong player, and an order naming the wrong triggers
        theirs = play_card(fixture(), two_watchers, declaration(cost=cost),
                           engine_decisions=envelope(two_watchers, {**order, "controller": "p2"}))
        if theirs.get("committed") or theirs.get("reason_code") != "decision_controller_mismatch" or validate_play_result(theirs):
            errors.append(f"an order supplied by p2 for p1's triggers was not refused well-formed: "
                          f"{theirs.get('reason_code')} {validate_play_result(theirs)}")
        wrong = play_card(fixture(), two_watchers, declaration(cost=cost),
                          engine_decisions=envelope(two_watchers, {**order, "value": ["x", "y"]}))
        if wrong.get("valid") is not False or wrong.get("reason_code") != "invalid_input" or validate_play_result(wrong):
            errors.append(f"an order naming other triggers was not invalid_input: {wrong.get('reason_code')} "
                          f"{validate_play_result(wrong)}")

    # a RECYCLE paid as a cost wakes "When you recycle one or more cards to your Main Deck" (Core 416.2.a)
    recycle_watch = watch_of("When you recycle one or more cards to your Main Deck, draw 1.")
    rec_state = watcher(hand_state("c1"), recycle_watch)          # p1's trash holds c3 alone: the choice is forced
    rec_cost = {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "r", "mandatory": True,
                                                                    "payment": {"kind": "recycle_trash", "amount": 1}}]}
    recycled = play_card(fixture(), rec_state, declaration(cost=rec_cost))
    if not recycled.get("committed") or len(scheduled_from(recycled)) != 1 or validate_play_result(recycled):
        errors.append(f"a recycle paid as a cost scheduled {len(scheduled_from(recycled))}, wanted 1 "
                      f"({recycled.get('reason_code')} {recycled.get('reason')})")

    # a KILL paid as a cost (Core 428.1.a.1): "the first time a friendly unit dies each turn" sees it, and the
    # killed unit's own death trigger goes on the Chain too (428.1.a.1.b) - above the ability, under nothing new
    from check_combat_staging import trigger as death_trigger
    first_death = watch_of("The first time a friendly unit dies each turn, draw 1.")
    kill_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "self", "mandatory": True,
                                                                     "payment": {"kind": "kill_this"}}]}
    killed_state = watcher(hand_state("c1"), first_death)
    killed_state["objects"]["u3"] = {**copy.deepcopy(killed_state["objects"]["u1"])}
    killed_state["players"]["p1"]["zones"]["base"].append("u3")
    killed = play_card(fixture(), killed_state, ability_declaration(cost=kill_cost))
    if not killed.get("committed") or len(scheduled_from(killed)) != 1 or validate_play_result(killed):
        errors.append(f"a unit killed as a cost did not wake the first-friendly-death watcher once: "
                      f"{len(scheduled_from(killed))} ({killed.get('reason_code')} {killed.get('reason')})")
    else:
        later = resolve(killed["next_effect_state"], [{"op": "kill", "effect_id": "k", "object_id": "u3"}])
        if not later.get("committed") or scheduled_from(later):
            errors.append(f"an effect death after a cost death was treated as the first friendly death of the turn "
                          f"(or failed: {later.get('reason')})")
        # the same effect death with no cost death before it IS the first
        control = resolve(copy.deepcopy(killed_state), [{"op": "kill", "effect_id": "k", "object_id": "u3"}])
        if not control.get("committed") or len(scheduled_from(control)) != 1:
            errors.append(f"negative mutation failed: the effect death alone did not wake the watcher ({control.get('reason')})")
    knell_state = hand_state("c1")
    knell_state["objects"]["u1"].update({"keywords": ["deathknell"], "death_triggers": [death_trigger("u1-knell", "p1", "u1")]})
    knelled = play_card(fixture(), knell_state, ability_declaration(cost=kill_cost))
    knell_items = [i for i in (knelled.get("next_timing_state") or {}).get("chain", {}).get("items", [])
                   if "u1-knell" in str(i.get("id", "")) + str(i.get("trigger_id", ""))]
    if not knelled.get("committed") or len(knell_items) != 1 or validate_play_result(knelled):
        errors.append(f"a Deathknell unit killed as a cost did not put its death trigger on the Chain: "
                      f"{len(knell_items)} ({knelled.get('reason_code')} {knelled.get('reason')})")

    def chain_ids(result):
        return [str(i.get("id")) for i in (result.get("next_timing_state") or {}).get("chain", {}).get("items", [])]

    # the dying unit's own death trigger is its OWN earlier batch (Core 428.1.a.1.b), as on the
    # resolution path: with p1's "first friendly death" watcher too, no order is asked, and the
    # death trigger is under the watcher's
    both_state = watcher(copy.deepcopy(knell_state), first_death)
    both = play_card(fixture(), both_state, ability_declaration(cost=kill_cost))
    ids = chain_ids(both)
    knell_at = next((k for k, i in enumerate(ids) if "u1-knell" in i), None)
    watch_at = next((k for k, i in enumerate(ids) if i.startswith("w@")), None)
    if not both.get("committed") or knell_at is None or watch_at is None or not knell_at < watch_at:
        errors.append(f"a cost death's own trigger and a watcher it woke were not two batches, death first: "
                      f"{both.get('reason_code')} {ids}")
    # ... and with the watcher p2's ("when a unit dies", any side): still death trigger first, then p2's
    other_state = watcher(copy.deepcopy(knell_state), {"kinds": ["died"], "scope": "any"}, owner="p2")
    other = play_card(fixture(), other_state, ability_declaration(cost=kill_cost))
    ids = chain_ids(other)
    knell_at = next((k for k, i in enumerate(ids) if "u1-knell" in i), None)
    watch_at = next((k for k, i in enumerate(ids) if i.startswith("w@")), None)
    if not other.get("committed") or knell_at is None or watch_at is None or not knell_at < watch_at:
        errors.append(f"p1's cost-death trigger and p2's watcher were not ordered death first: {other.get('reason_code')} {ids}")

    # a kill paid as a cost that a replacement changes is still PAID (Core 357.2.a, 203.2) - the engine
    # does not model the replacement's events during payment, so it refuses by name, never "unpayable"
    from check_replacement_subject import CLAUSES, hourglass_state, install
    zhonya = install(hourglass_state(), cg.compile_card(CLAUSES, cg.load_grammar()))
    zhonya["players"]["p1"]["resources"] = {"energy": 0, "power": {}}
    replaced = play_card(fixture(), zhonya, ability_declaration(cost=kill_cost))
    if replaced.get("committed") or not replaced.get("unsupported") \
            or replaced.get("reason_code") != "payment_replacement_events_not_modelled" or validate_play_result(replaced):
        errors.append(f"a kill cost a replacement changed was not refused by name as unsupported: "
                      f"{replaced.get('reason_code')} unsupported={replaced.get('unsupported')}")

    # every field a result, its receipt and its payment events carry is one the published schema allows
    import json as _json
    schemas = Path(__file__).resolve().parent.parent / "schemas"
    result_schema = _json.loads((schemas / "play-result.schema.json").read_text(encoding="utf-8"))
    receipt_schema = _json.loads((schemas / "cost-receipt.schema.json").read_text(encoding="utf-8"))
    event_props = set(receipt_schema["properties"]["payment_events"]["items"].get("properties") or {})
    for label, result in (("committed play", played), ("cost-discard ask", ask), ("recycle cost", recycled),
                          ("kill cost", killed), ("Deathknell cost", knelled), ("replaced cost", replaced)):
        extra = set(result) - set(result_schema["properties"])
        receipt = result.get("cost_receipt") or {}
        extra |= {f"cost_receipt.{k}" for k in set(receipt) - set(receipt_schema["properties"])}
        for event in receipt.get("payment_events") or []:
            extra |= {f"payment_events.{k}" for k in set(event) - event_props} if event_props else set()
        if extra:
            errors.append(f"the {label} result carries fields its schema does not allow: {sorted(extra)}")

    if errors:
        print("FAILED: watch each / discard checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'When you stun an enemy unit' schedules one trigger per enemy p1 stuns (two for two, ordered) where "
          "'one or more' schedules one; a friendly stun, p2's stun and a re-stun schedule none; 'When you discard one "
          "or more cards' follows the discarding player - p1's own discard, p2 making p1 discard and a discard paid as "
          "a cost (a play's or an ability's) schedule one; p1 making p2 discard, p2's discard, an empty hand, a watcher "
          "in hand and a cost with no discard schedule none; two cost discards are two distinct hand -> trash events; "
          "two watchers woken by one cost discard are p1's to order (a well-formed decision_required, wrapped as "
          "trigger_order; p2's order refused, wrong ids invalid_input), then both scheduled; a recycle and a kill "
          "paid as costs wake their watchers, the cost death counts as the turn's first, a Deathknell unit "
          "killed as a cost puts its own death trigger on the Chain as the earlier batch, a replaced kill cost is "
          "refused by name, and every result field is one its schema allows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
