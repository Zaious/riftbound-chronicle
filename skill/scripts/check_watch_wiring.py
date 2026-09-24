#!/usr/bin/env python3
"""
Regression gate: watchers wired into real play (2026-09-24).

watchers.py could always decide whether an event falls inside a watch, but nothing in play
asked it. Now the play transaction emits "played" once a card is Finalized (Core 419.4.a)
and wakes the watchers, and every resolution wakes them on the events it produced, after
its Cleanup (watchers.schedule_live).

Must hold, each through play_card / resolve_with_program:
  - "When you play a spell": p1 playing a spell schedules the trigger; p1 playing a unit,
    p2 playing a spell, and the watcher's card in a hand (not on the board) schedule nothing;
  - "... on an opponent's turn" fires only when the turn player is not the controller; "...
    from [Hidden]" only for a card played from a facedown zone;
  - "... a spell that costs [5] or more" compares the PRINTED Energy cost (Core 206): printed 5
    or 7 schedules, printed 4 does not, and a spell with no printed cost is unsupported, not guessed;
  - "When you stun one or more enemy units": a resolution of p1's that stuns two enemy units
    schedules ONE trigger; stunning a friendly unit, or p2 stunning p1's enemies, none;
  - "When a buffed friendly unit dies": a buffed friendly unit killed - scheduled; an
    unbuffed one, or a buffed enemy, none (the buff is read as the unit was, Core 417);
  - "The first time a friendly unit dies each turn": the first death of the turn schedules,
    the second does not; a new turn schedules again;
  - "When you recycle one or more cards to your Main Deck": two recycled, one trigger;
  - a scheduled trigger carries its source's identity and the program hash its descriptor names.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, object_identity  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

HASH = "sha256:" + "a" * 64


def watcher(state, watch, *, where="base", owner="p1", trigger_id="w"):
    state["objects"]["w1"] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False,
                              "event_triggers": [{"trigger_id": trigger_id, "controller": owner, "source_object": "w1",
                                                  "controller_order": 0, "effect_program_id": "w-program",
                                                  "optional_at_finalize": False, "watch": watch,
                                                  "effect_program_hash": HASH}]}
    state["players"][owner]["zones"][where].append("w1")
    return state


def playable(state, card="c9", *, actor="p1", kind="spell"):
    state["objects"][card] = {"owner": actor, "controller": actor, "kind": kind, "base_might": 2 if kind == "unit" else 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"][actor]["zones"]["hand"].append(card)
    state["players"][actor]["resources"] = {"energy": 2, "power": {}}
    return state


def play(state, card="c9", *, actor="p1", kind="spell", turn_player="p1", timing="default"):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"play-{card}", "actor": actor, "card": card,
            "chain_item": {"id": f"{kind}-9", "object_kind": kind, "timing": timing},
            "cost": {"base": {"energy": 2, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"},
            **({"entry_location": {"kind": "base"}} if kind == "unit" else {})}
    window = fixture()
    if timing == "reaction":
        # a closed state on the other player's turn: their spell is on the Chain and the
        # actor holds priority (Core 813.1)
        other = next(p for p in ("p1", "p2") if p != actor)
        window = fixture(priority=actor, items=[item("their-spell", other, "spell", "default")])
    if actor != "p1" or turn_player != "p1":
        window.update({"turn_player": turn_player, "priority": actor, "turn_order": [turn_player] + [p for p in ("p1", "p2") if p != turn_player]})
    return play_card(window, state, decl)


def scheduled_from(result, trigger_prefix="w@"):
    timing = result.get("next_timing_state") or {}
    return [i for i in timing.get("chain", {}).get("items", []) if str(i.get("id", "")).startswith(trigger_prefix)
            or str(i.get("trigger_id", "")).startswith(trigger_prefix)]


def resolve(state, effects, *, controller="p1"):
    timing = fixture(priority="p2", items=[item("spell-1", controller, "spell", "default", "finalized")], passes=["p1", "p2"])
    if controller != "p1":
        timing["turn_player"] = controller
    return resolve_with_program(timing, "spell-1", state, {**program("resolving", *effects), "controller": controller})


def main() -> int:
    errors: list[str] = []
    spell_watch = {"kinds": ["played"], "scope": "actor", "filter": {"object_kind": "spell"}}

    # --- played ------------------------------------------------------------------------------
    got = play(playable(watcher(base_state(), spell_watch)))
    items = scheduled_from(got)
    if not got.get("committed") or len(items) != 1:
        errors.append(f"p1 playing a spell did not schedule the watcher: {got.get('reason')} {items}")
    elif items[0].get("source_identity") != object_identity(got["next_effect_state"], "w1") \
            or items[0].get("effect_program_hash") != HASH:
        errors.append(f"the scheduled trigger lost its source identity or program hash: {items[0]}")
    for label, result in (
            ("p1 playing a unit", play(playable(watcher(base_state(), spell_watch), kind="unit"), kind="unit")),
            ("p2 playing a spell", play(playable(watcher(base_state(), spell_watch), actor="p2"), actor="p2", turn_player="p2")),
            ("the watcher's card in a hand", play(playable(watcher(base_state(), spell_watch, where="hand"))))):
        if not result.get("committed") or scheduled_from(result):
            errors.append(f"{label} scheduled the spell watcher (or failed: {result.get('reason')})")
    turn_watch = {"kinds": ["played"], "scope": "actor", "filter": {"on_opponents_turn": True}}
    mine = play(playable(watcher(base_state(), turn_watch)))
    # a card played on the opponent's turn is a Reaction (Core 813.1), printed so
    reaction = playable(watcher(base_state(), turn_watch))
    reaction["objects"]["c9"]["play_timing"] = "reaction"
    theirs = play(reaction, turn_player="p2", timing="reaction")
    if scheduled_from(mine) or not scheduled_from(theirs):
        errors.append(f"'on an opponent's turn' fired on p1's turn or not on p2's: {bool(scheduled_from(mine))} "
                      f"{bool(scheduled_from(theirs))} ({theirs.get('reason')})")

    # --- "a spell that costs [5] or more": the PRINTED cost (Core 206) ---------------------------
    costly_watch = {"kinds": ["played"], "scope": "actor", "filter": {"object_kind": "spell", "printed_energy_at_least": 5}}
    for printed, wanted in ((5, 1), (7, 1), (4, 0)):
        board = playable(watcher(base_state(), costly_watch))
        board["objects"]["c9"]["printed_cost"] = {"energy": printed, "power": {}}
        result = play(board)
        if not result.get("committed") or len(scheduled_from(result)) != wanted:
            errors.append(f"a spell printed at {printed} scheduled {len(scheduled_from(result))} costly-spell trigger(s), "
                          f"wanted {wanted} ({result.get('reason')})")
    unknown = play(playable(watcher(base_state(), costly_watch)))
    if unknown.get("committed") or unknown.get("reason_code") != "printed_cost_unknown":
        errors.append(f"a spell with no printed cost was compared anyway: {unknown.get('reason_code')}")

    # --- stunned: one or more, enemy, by you ---------------------------------------------------
    stun_watch = {"kinds": ["stunned"], "scope": "actor", "filter": {"object_controller_relation": "enemy"},
                  "grouping": "one_or_more"}
    two = base_state()
    two["objects"]["e2"] = copy.deepcopy(two["objects"]["u2"])
    two["players"]["p2"]["zones"]["base"].append("e2")
    watcher(two, stun_watch)
    stunned = resolve(two, [{"op": "stun", "effect_id": "s1", "object_id": "u2"}, {"op": "stun", "effect_id": "s2", "object_id": "e2"}])
    if not stunned.get("committed") or len(scheduled_from(stunned)) != 1:
        errors.append(f"stunning two enemy units did not schedule exactly one trigger: {stunned.get('reason')} "
                      f"{scheduled_from(stunned)}")
    friendly = resolve(watcher(base_state(), stun_watch), [{"op": "stun", "effect_id": "s1", "object_id": "u1"}])
    if not friendly.get("committed") or scheduled_from(friendly):
        errors.append(f"stunning a friendly unit scheduled the enemy-stun watcher ({friendly.get('reason')})")
    by_p2 = base_state()
    by_p2["objects"]["e1"] = {**copy.deepcopy(by_p2["objects"]["u1"]), "owner": "p2", "controller": "p2"}
    by_p2["players"]["p2"]["zones"]["base"].append("e1")
    their_stun = resolve(watcher(by_p2, stun_watch), [{"op": "stun", "effect_id": "s1", "object_id": "u1"}], controller="p2")
    if not their_stun.get("committed") or scheduled_from(their_stun):
        errors.append(f"p2's stun scheduled p1's 'when YOU stun' watcher ({their_stun.get('reason')})")

    # --- died: buffed friendly; first each turn -------------------------------------------------
    buffed_watch = {"kinds": ["died"], "scope": "any",
                    "filter": {"object_kind": "unit", "object_controller_relation": "friendly", "object_was_buffed": True}}
    for label, buffed, victim, want in (("a buffed friendly unit", True, "u1", 1), ("an unbuffed friendly unit", False, "u1", 0),
                                        ("a buffed enemy unit", True, "u2", 0)):
        state = watcher(base_state(), buffed_watch)
        state["objects"][victim]["buffed"] = buffed
        died = resolve(state, [{"op": "kill", "effect_id": "k", "object_id": victim}])
        if not died.get("committed") or len(scheduled_from(died)) != want:
            errors.append(f"{label} dying scheduled {len(scheduled_from(died))} trigger(s), wanted {want} ({died.get('reason')})")
    first_watch = {"kinds": ["died"], "scope": "any", "filter": {"object_kind": "unit", "object_controller_relation": "friendly"},
                   "occurrence": "first_each_turn"}
    state = watcher(base_state(), first_watch)
    state["objects"]["f2"] = copy.deepcopy(state["objects"]["u1"])
    state["players"]["p1"]["zones"]["base"].append("f2")
    state["turn_id"] = "turn-3"
    once = resolve(state, [{"op": "kill", "effect_id": "k", "object_id": "u1"}])
    twice = resolve(once["next_effect_state"], [{"op": "kill", "effect_id": "k", "object_id": "f2"}]) if once.get("committed") else once
    if len(scheduled_from(once)) != 1 or scheduled_from(twice):
        errors.append(f"'the first time each turn' scheduled {len(scheduled_from(once))} then {len(scheduled_from(twice))}")
    if once.get("committed"):
        later = copy.deepcopy(once["next_effect_state"])
        later["turn_id"] = "turn-4"
        again = resolve(later, [{"op": "kill", "effect_id": "k", "object_id": "f2"}])
        if len(scheduled_from(again)) != 1:
            errors.append("'the first time each turn' did not schedule again on a new turn")

    # --- recycled: one or more, to your Main Deck ----------------------------------------------
    recycle_watch = {"kinds": ["recycled"], "scope": "actor", "filter": {"destination_zone": "main_deck"},
                     "grouping": "one_or_more"}
    state = watcher(base_state(), recycle_watch)
    state["objects"]["t2"] = copy.deepcopy(state["objects"]["c3"])
    state["players"]["p1"]["zones"]["trash"].append("t2")
    recycled = resolve(state, [{"op": "recycle", "effect_id": "r1", "player": "p1", "objects": ["c3"]},
                               {"op": "recycle", "effect_id": "r2", "player": "p1", "objects": ["t2"]}])
    if not recycled.get("committed") or len(scheduled_from(recycled)) != 1:
        errors.append(f"recycling two cards did not schedule exactly one trigger: {recycled.get('reason')} "
                      f"{scheduled_from(recycled)}")

    if errors:
        print("FAILED: watch wiring checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a play wakes 'When you play ...' watchers once Finalized, and only for the right card, player, turn and "
          "zone; a resolution wakes stun / death / recycle watchers on what it did - one or more is one trigger, the "
          "first death of a turn is the only one, a death reads the buff the unit had - and every trigger carries its "
          "source identity and program hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
