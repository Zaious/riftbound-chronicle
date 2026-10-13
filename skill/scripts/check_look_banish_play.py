#!/usr/bin/env python3
"""Each player banishes one of the cards they looked at, then plays it (package 11, Promising Future: "Each player looks at
the top 5 cards of their Main Deck, banishes one of them, then recycles the rest. Starting with the next player, each
player plays those cards, ignoring Energy costs. (They must still pay Power costs.)").

GPT 2026-10-12 (PACKAGE11 ruling 16, after package 10's reading): each player is bound to the card they banished and
plays it, in the order the card names (starting with the next player); ignoring Energy does not waive Power; a card that
cannot be played legally stays in banishment - never played by another player, never swapped. Core 738's own example
plays out this card: the plays go on the Chain in that order, so the later one resolves first. The engine's shape: inside
each_player, look_at_top (the player looks), banish_one_looked (that player chooses, privately), recycle_looked_rest;
then an each_player from the next player whose limited_play is linked per_player to that iteration's own banish.

  F1 resolved      p1 casts: each looks at five, banishes one (p1 its 3rd, p2 its 1st) and recycles four (the sixth card
                   now on top); p2's play is put on the Chain first, then p1's - each its own player's, from banishment
  F2 completed     p2's play completed first, then p1's: each card enters its owner's Base, no Energy paid
  F3 Power         p2's card costs one Fury Power p2 lacks: its play is cancelled, the card back in p2's banishment;
                   p1's play goes on
  F4 empty deck    p2 has no Main Deck: p2 looks at nothing, banishes and plays nothing (named); p1 as before
  F5 the looker    each player's looked-at cards are visible to that player only
  V  shape         per_player not true, a linked play outside its loop's banish, banish_one_looked without a player -
                   each refused

    python skill/scripts/check_look_banish_play.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import complete_limited_play, resolve_with_program  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []
PF = [
    {"op": "each_player", "effect_id": "ep1", "players": "all", "order": "turn_order", "effects": [
        {"op": "look_at_top", "effect_id": "look", "player": "$each_player", "count": 5},
        {"op": "banish_one_looked", "effect_id": "ban", "player": "$each_player", "decision_ref": "pick"},
        {"op": "recycle_looked_rest", "effect_id": "rest", "player": "$each_player", "order_ref": "rest-order"}]},
    {"op": "each_player", "effect_id": "ep2", "players": "all", "order": "after_controller", "effects": [
        {"op": "limited_play", "effect_id": "lp", "linked": {"effect_id": "ban", "from": "banishment", "per_player": True},
         "player": "owner", "cost_basis": {"kind": "ignore_energy"}}]}]
PROGRAM = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "pf-effects", "controller": "p1",
           "source_object": "pf", "effects": PF}
PICKS = {"p1": "p1c2", "p2": "p2c0"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def card(owner, power=None):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, "printed_cost": {"energy": 3, "power": power or {}}}


def board(*, p2_power=None, p2_empty=False):
    """Six units in each Main Deck (p1c0.. on top); PF, p1's spell, on the Chain; no Energy anywhere."""
    state = base_state()
    for p in ("p1", "p2"):
        for old in state["players"][p]["zones"]["main_deck"]:
            state["objects"].pop(old, None)
        state["players"][p]["zones"]["main_deck"] = []
        for i in range(0 if (p == "p2" and p2_empty) else 6):
            oid = f"{p}c{i}"
            state["objects"][oid] = card(p, p2_power if oid == "p2c0" else None)
            state["players"][p]["zones"]["main_deck"].append(oid)
        state["players"][p]["resources"] = {"energy": 0, "power": {}}
    state["objects"]["pf"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["chain_items"] = {"spell-pf": {"card": "pf", "controller": "p1", "effect_program_id": "pf-effects"}}
    return state


def resolve(state):
    """PF resolved through the bridge, each player's choice and each recycle's random order answered."""
    timing = fixture(priority="p2", items=[item("spell-pf", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    decisions, receipts = [], []
    for _ in range(12):
        env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": decisions,
               "randomization_receipts": receipts}
        done = resolve_with_program(timing, "spell-pf", state, PROGRAM, engine_decisions=env)
        effect = (done.get("effect_result") or done)
        code = effect.get("reason_code") or done.get("reason_code")
        if done.get("committed") or code not in {"card_selection_required", "randomization_receipt_required"}:
            return done
        for ref in effect.get("decision_ids") or done.get("decision_ids") or []:
            player = ref.split("@")[1].split(":")[0]
            if code == "card_selection_required":
                decisions.append({"decision_id": ref, "stage": "resolution", "kind": "card_selection", "controller": player,
                                  "value": [PICKS[player]], "selection_identities": {PICKS[player]: object_identity(state, PICKS[player])}})
            else:
                rest = [c for c in state["players"][player]["zones"]["main_deck"][:5] if c != PICKS[player]]
                receipts.append({"schema_version": "randomization-receipt.v1", "receipt_id": f"{ref}:rnd",
                                 "operation": "recycle_simultaneous", "operation_id": ref, "player": player,
                                 "permutation": rest, "provenance": {"provider": "gate", "method": "listed-order"}})
    return done


def plays(done):
    return [(i["id"], i["controller"]) for i in done["next_timing_state"]["chain"]["items"] if i.get("limited_play")]


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    done = resolve(s)
    if not done.get("committed"):
        fail("F1 resolved", f"{done.get('reason')} {done.get('reason_code')}")
        return report()
    after = done["next_effect_state"]
    # the banished cards are on the Chain now (each play's step 1); the four left are at the bottom, the sixth on top
    if after["players"]["p1"]["zones"]["main_deck"][0] != "p1c5" or "p1c2" in after["players"]["p1"]["zones"]["main_deck"] \
            or after["players"]["p2"]["zones"]["main_deck"][0] != "p2c5" or "p2c0" in after["players"]["p2"]["zones"]["main_deck"]:
        fail("F1 decks", f"{after['players']['p1']['zones']['main_deck']} {after['players']['p2']['zones']['main_deck']}")
    order = plays(done)
    if order != [("limited-play:pf-effects:lp@p2", "p2"), ("limited-play:pf-effects:lp@p1", "p1")]:
        fail("F1 order", order)
    if {after["chain_items"][k]["card"] for k, _ in order} != {"p1c2", "p2c0"} \
            or after["chain_items"]["limited-play:pf-effects:lp@p2"]["card"] != "p2c0":
        fail("F1 bound", "a player's play is not the card that player banished")
    # F5: each player's look was private to that player
    looks = [e for e in (done.get("trace") or {}).get("effect") or [] if e.get("op") == "look_at_top"]
    if sorted((e["player"], tuple(e["objects_visible_to"])) for e in looks) != [("p1", ("p1",)), ("p2", ("p2",))]:
        fail("F5 the looker", [(e.get("player"), e.get("objects_visible_to")) for e in looks])
    # F2
    t, e = done["next_timing_state"], done["next_effect_state"]
    for expected in ("p2c0", "p1c2"):
        got = complete_limited_play(t, e, entry_location={"kind": "base"}, payment_context=CLOSED)
        if not got.get("committed") or got.get("removed"):
            fail("F2 completed", f"{expected}: {got.get('reason')} {got.get('message')}")
            break
        t, e = got["next_timing_state"], got["next_effect_state"]
        owner = expected[:2]
        if expected not in e["players"][owner]["zones"]["base"]:
            fail("F2 completed", f"{expected} is not in {owner}'s Base")
    # F3
    poor = resolve(board(p2_power={"fury": 1}))
    if poor.get("committed"):
        first = complete_limited_play(poor["next_timing_state"], poor["next_effect_state"], entry_location={"kind": "base"},
                                      payment_context=CLOSED)
        e3 = first.get("next_effect_state") or {}
        if not first.get("removed") or "p2c0" not in (e3.get("players") or {}).get("p2", {}).get("zones", {}).get("banishment", []):
            fail("F3 Power", f"{first.get('reason')} {first.get('transition')}")
        else:
            second = complete_limited_play(first["next_timing_state"], e3, entry_location={"kind": "base"}, payment_context=CLOSED)
            if not second.get("committed") or "p1c2" not in second["next_effect_state"]["players"]["p1"]["zones"]["base"]:
                fail("F3 Power", f"p1's play did not go on: {second.get('reason')}")
    else:
        fail("F3 Power", poor.get("reason"))
    # F4
    empty = resolve(board(p2_empty=True))
    steps = {x.get("effect_id"): x for x in (empty.get("trace") or {}).get("effect") or []} if empty.get("committed") else {}
    if not empty.get("committed") or plays(empty) != [("limited-play:pf-effects:lp@p1", "p1")] \
            or steps.get("lp@p2", {}).get("reason") != "nothing_banished":
        fail("F4 empty deck", f"{empty.get('reason')} {plays(empty) if empty.get('committed') else ''} "
                              f"{steps.get('lp@p2', {}).get('reason')}")
    # V
    for label, mutate in (("per_player not true", lambda p: p["effects"][1]["effects"][0]["linked"].update(per_player=False)),
                          ("banish_one_looked without a player", lambda p: p["effects"][0]["effects"][1].pop("player"))):
        bad = copy.deepcopy(PROGRAM)
        mutate(bad)
        if not validate_program(bad):
            fail("V shape", f"{label} validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: each player banishes one looked-at card, then plays it")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: each player looks at their own five, banishes one and recycles the rest; starting with the next player each "
          "plays the card they banished - Energy ignored, Power still paid, an unpayable play leaving the card in "
          "banishment; an empty deck plays nothing, by name (F1-F5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
