#!/usr/bin/env python3
"""Per-player iteration and each-player choices (package 6, 2026-09-27).

"Each player kills one of their units." (Core 411.1's own example), "Each player discards their
hand, then draws 4.", "Starting with the next player, each player may return a unit to its owner's
hand.", "Starting with the next player, each other player chooses a unit you don't control that
hasn't been chosen for this spell. Kill those units.", "Each player chooses 2 units, 2 gear, 2
runes, and 2 cards in their hands. Recycle the rest.", "Each other player chooses Cards or Runes.
For each player that chooses Cards, you and that player each draw 1."

One instruction, each_player {players, order, effects[, only_chose]}, runs its instructions once
per player; each copy names the player of the iteration where the IR says $each_player. Every rule
it claims has a failing case here:

  order        Turn Order from the Turn Player (Core 303.2.a); "Starting with the next player":
               from the player after the controller; "each other player": the controller left out;
               no Turn Order known: refused (turn_order_unknown), never guessed
  choices      each player makes their own choice as the instruction resolves, not a target
               (Core 355.10.e): another player's decision is refused, a decision made at play is
               refused, "one of their units" offers only the chooser's units, nothing to choose
               from does nothing for that player and the rest runs
  responsibility  each copy's game actions are its player's (Core 411.1): a unit killed in p2's
               iteration died with p2 as the actor
  may          "each player may": the iteration's player decides (optional.by)
  hand         "discards their hand": every card in it; an empty hand discards nothing (422.4)
  groups       choose_objects fills a group; "hasn't been chosen for this spell" keeps a chosen
               object out of the next player's candidates; "a unit you don't control" keeps the
               controller's units out; "Kill those units" kills every chosen object still on the
               board; "Recycle the rest" recycles what was offered and not chosen, each to its
               owner's deck (Core 416.1.c), each deck's order its owner's (416.5.a)
  options      "Each other player chooses Cards or Runes": recorded per player; "for each player
               that chooses Cards" iterates exactly those; an option not offered, or made by
               another player, is refused
  bridge       the resolution bridge hands the Turn Order to a program that iterates, from the
               timing state
  shapes       the sentinel outside each_player, each_player inside each_player, an op that is not
               run per player, stray fields, whole_hand with a count, rest_of with a player,
               group_ref on another op and an unknown relation are refused by the validator

Every fixture is synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (apply_program, find_location, hash_value, object_identity, validate_program,  # noqa: E402
                       validate_state)
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
TURN_P1 = {"turn": {"turn_player": "p1", "turn_order": ["p1", "p2"]}}
TURN_P2 = {"turn": {"turn_player": "p2", "turn_order": ["p1", "p2"]}}

CULL = [{"op": "each_player", "effect_id": "ep", "players": "all", "order": "turn_order",
         "effects": [{"op": "kill", "effect_id": "k", "decision_ref": "k",
                      "choice": {"selection_kind": "single", "from": "board", "by": "$each_player", "visibility": "public",
                                 "criteria": {"kind": "unit", "controller_relation": "own"}}}]}]
WHIRL = [{"op": "each_player", "effect_id": "ep", "players": "all", "order": "after_controller",
          "effects": [{"op": "return_to_hand", "effect_id": "rt", "decision_ref": "rt",
                       "optional": {"decision_ref": "may", "by": "$each_player"},
                       "choice": {"selection_kind": "single", "from": "board", "by": "$each_player", "visibility": "public",
                                  "criteria": {"kind": "unit"}}}]}]
INVERT = [{"op": "each_player", "effect_id": "ep", "players": "all", "order": "turn_order",
           "effects": [{"op": "discard", "effect_id": "d", "player": "$each_player", "whole_hand": True}]},
          {"op": "each_player", "effect_id": "ep2", "players": "all", "order": "turn_order",
           "effects": [{"op": "draw", "effect_id": "dr", "player": "$each_player", "count": 4}]}]
EDICT = [{"op": "each_player", "effect_id": "ep", "players": "others", "order": "after_controller",
          "effects": [{"op": "choose_objects", "effect_id": "ch", "decision_ref": "ch", "group": "ke", "distinct_in_group": True,
                       "choice": {"selection_kind": "single", "from": "board", "by": "$each_player", "visibility": "public",
                                  "criteria": {"kind": "unit", "not_controlled_by": "p1"}}}]},
         {"op": "kill", "effect_id": "kl", "group_ref": "ke"}]
JUDGE = [{"op": "each_player", "effect_id": "ep", "players": "all", "order": "turn_order",
          "effects": [{"op": "choose_objects", "effect_id": "cu", "decision_ref": "cu", "group": "kept",
                       "choice": {"selection_kind": "unordered_set", "count": {"exactly": 2}, "from": "board", "by": "$each_player",
                                  "visibility": "public", "criteria": {"kind": "unit", "controller_relation": "own"}}},
                      {"op": "choose_objects", "effect_id": "cg", "decision_ref": "cg", "group": "kept",
                       "choice": {"selection_kind": "unordered_set", "count": {"exactly": 2}, "from": "board", "by": "$each_player",
                                  "visibility": "public", "criteria": {"kind": "gear", "controller_relation": "own"}}},
                      {"op": "choose_objects", "effect_id": "cr", "decision_ref": "cr", "group": "kept",
                       "choice": {"selection_kind": "unordered_set", "count": {"exactly": 2}, "from": "board", "by": "$each_player",
                                  "visibility": "public", "criteria": {"kind": "rune", "controller_relation": "own"}}},
                      {"op": "choose_objects", "effect_id": "ch", "decision_ref": "ch", "group": "kept",
                       "choice": {"selection_kind": "unordered_set", "count": {"exactly": 2}, "from": "hand", "by": "$each_player",
                                  "visibility": "private_to_chooser"}}]},
         {"op": "recycle", "effect_id": "rc", "rest_of": "kept"}]
FAVORS = [{"op": "each_player", "effect_id": "ep", "players": "others", "order": "turn_order",
           "effects": [{"op": "choose_option", "effect_id": "co", "decision_ref": "co", "record": "pf",
                        "options": ["cards", "runes"], "by": "$each_player"}]},
          {"op": "each_player", "effect_id": "epc", "players": "others", "order": "turn_order",
           "only_chose": {"record": "pf", "option": "cards"},
           "effects": [{"op": "draw", "effect_id": "dy", "player": "p1", "count": 1},
                       {"op": "draw", "effect_id": "dt", "player": "$each_player", "count": 1}]},
          {"op": "each_player", "effect_id": "epr", "players": "others", "order": "turn_order",
           "only_chose": {"record": "pf", "option": "runes"},
           "effects": [{"op": "channel_rune", "effect_id": "cy", "player": "p1", "count": 1, "entry_state": "exhausted"},
                       {"op": "channel_rune", "effect_id": "ct", "player": "$each_player", "count": 1, "entry_state": "exhausted"}]}]


def unit(state, object_id, owner, might=3, controller=None, where="base"):
    state["objects"][object_id] = {"owner": owner, "controller": controller or owner, "kind": "unit", "base_might": might,
                                   "might_modifiers": [], "damage": 0, "exhausted": False}
    if where == "base":
        state["players"][controller or owner]["zones"]["base"].append(object_id)
    else:
        state["battlefields"][where]["objects"].append(object_id)


def card(state, object_id, owner, zone, kind="spell"):
    state["objects"][object_id] = {"owner": owner, "controller": owner, "kind": kind, "base_might": 0,
                                   "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"][owner]["zones"][zone].append(object_id)


def board() -> dict:
    """p1: u1 (base), a1 (bf1), a2 (base); p2: u2 (base), b1 (bf1). Both hands hold cards, both decks
    are deep, both rune decks hold runes."""
    state = base_state()
    unit(state, "a1", "p1", where="bf1")
    unit(state, "a2", "p1")
    unit(state, "b1", "p2", where="bf1")
    for i in range(6):
        card(state, f"d1-{i}", "p1", "main_deck")
        card(state, f"d2-{i}", "p2", "main_deck")
    card(state, "h1a", "p1", "hand")
    card(state, "h1b", "p1", "hand")
    card(state, "h2a", "p2", "hand")
    card(state, "rd2", "p2", "rune_deck", kind="rune")
    return settle_contested(state)


def three_players(state: dict) -> dict:
    """A third player p3 with one unit c1u in its Base (King's Edict's 'each other player')."""
    state = copy.deepcopy(state)
    state["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [],
                                        "rune_deck": []}, "resources": {"energy": 0, "power": {}}}
    unit(state, "c1u", "p3")
    return state


def program(effects) -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": "spell-effects",
            "controller": "p1", "source_object": "c1", "effects": copy.deepcopy(effects)}


def pick(state, ref, controller, value, kind="target_selection", stage="resolution"):
    value = list(value) if isinstance(value, list) else value
    entry = {"decision_id": ref, "stage": stage, "kind": kind, "controller": controller, "value": value}
    if kind in {"target_selection", "card_selection", "card_ordering"}:
        entry["selection_identities"] = {o: object_identity(state, o) for o in value}
    return entry


def run(state, effects, decisions=(), context=TURN_P1):
    envelope = ({"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": list(decisions)}
                if decisions else None)
    return apply_program(state, program(effects), decisions=envelope, context=context)


def at(state, object_id):
    return find_location(state, object_id)


def main() -> int:
    errors: list[str] = []
    state = board()
    if validate_state(state):
        errors.append(f"the fixture board does not validate: {validate_state(state)[:2]}")

    # ---------------------------------------------------------------- order (303.2.a)
    cull = [pick(state, "k@p1", "p1", ["a1"]), pick(state, "k@p2", "p2", ["b1"])]
    done = run(state, CULL, cull)
    if not done.get("committed"):
        errors.append(f"Cull the Weak refused: {done.get('reason') or done.get('errors')}")
    else:
        after = done["next_state"]
        if at(after, "a1") != ("player", "p1", "trash") or at(after, "b1") != ("player", "p2", "trash"):
            errors.append(f"Cull the Weak: a1 at {at(after, 'a1')}, b1 at {at(after, 'b1')}")
        if at(after, "u1") != ("player", "p1", "base") or at(after, "u2") != ("player", "p2", "base") \
                or at(after, "a2") != ("player", "p1", "base"):
            errors.append("Cull the Weak killed a unit nobody chose")
        order = done["trace"][0].get("players")
        if order != ["p1", "p2"]:
            errors.append(f"turn_order on p1's turn ran {order}, not p1 then p2 (Core 303.2.a)")
        died = [e for e in done.get("events") or [] if e.get("kind") == "died"]
        actors = {e["object"]: e.get("actor") for e in died}
        if actors != {"a1": "p1", "b1": "p2"}:
            errors.append(f"Core 411.1: each player's kill is theirs; died events name {actors}")
    on_p2 = run(state, CULL, cull, context=TURN_P2)
    if not on_p2.get("committed") or on_p2["trace"][0].get("players") != ["p2", "p1"]:
        errors.append(f"turn_order on p2's turn must run p2 first: {on_p2.get('trace', [{}])[0].get('players')}")
    elif [e.get("effect_id") for e in on_p2["trace"][1:]] != ["k@p2", "k@p1"]:
        errors.append(f"p2's turn: the copies ran {[e.get('effect_id') for e in on_p2['trace'][1:]]}")
    blind = run(state, CULL, cull, context=None)
    if blind.get("committed") or blind.get("reason_code") != "turn_order_unknown":
        errors.append(f"no Turn Order: must be refused as turn_order_unknown, got {blind.get('reason_code')}")

    # ---------------------------------------------------------------- choices (355.10.e)
    missing = run(state, CULL, [pick(state, "k@p1", "p1", ["a1"])])
    if missing.get("committed") or missing.get("decision_ids") != ["k@p2"] or missing.get("decision_controller") != "p2":
        errors.append(f"p2's own choice missing: {missing.get('decision_ids')} {missing.get('decision_controller')}")
    options = [o["object_id"] for o in (missing.get("choice") or {}).get("options") or []]
    if sorted(options) != ["b1", "u2"]:
        errors.append(f"'one of their units' offered p2 {options}, not only p2's units")
    theirs = run(state, CULL, [pick(state, "k@p1", "p1", ["a1"]), pick(state, "k@p2", "p1", ["b1"])])
    if theirs.get("committed") or theirs.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"p1 deciding p2's choice was not refused: {theirs.get('reason_code')}")
    foreign = run(state, CULL, [pick(state, "k@p1", "p1", ["a1"]), pick(state, "k@p2", "p2", ["a2"])])
    if foreign.get("committed") or foreign.get("reason_code") != "illegal_operation":
        errors.append(f"p2 choosing p1's unit was not refused: {foreign.get('reason_code')}")
    at_play = run(state, CULL, [pick(state, "k@p1", "p1", ["a1"], stage="play_declaration"), pick(state, "k@p2", "p2", ["b1"])])
    if at_play.get("committed") or at_play.get("valid") is not False:
        errors.append(f"a choice made at play was accepted for a choice made as it resolves: {at_play.get('committed')}")
    lonely = copy.deepcopy(state)
    for object_id in ("u2", "b1"):
        where = at(lonely, object_id)
        (lonely["players"][where[1]]["zones"][where[2]] if where[0] == "player" else lonely["battlefields"][where[1]]["objects"]).remove(object_id)
        del lonely["objects"][object_id]
    lonely["battlefields"]["bf1"].update({"contested": True, "contested_by": "p1"})
    alone = run(lonely, CULL, [pick(lonely, "k@p1", "p1", ["a1"])])
    if not alone.get("committed") or at(alone["next_state"], "a1") != ("player", "p1", "trash") \
            or alone["trace"][-1].get("outcome") != "no_op":
        errors.append(f"p2 with no unit: p1's kill must still happen and p2's be a no_op: "
                      f"{alone.get('reason') or [e.get('outcome') for e in alone.get('trace', [])]}")

    # ---------------------------------------------------------------- may (optional.by)
    whirl = [pick(state, "may@p2", "p2", False, kind="optional_choice"), pick(state, "may@p1", "p1", True, kind="optional_choice"),
             pick(state, "rt@p1", "p1", ["b1"])]
    done = run(state, WHIRL, whirl)
    if not done.get("committed"):
        errors.append(f"Whirlwind refused: {done.get('reason') or done.get('errors')}")
    else:
        after = done["next_state"]
        if done["trace"][0].get("players") != ["p2", "p1"]:
            errors.append(f"'Starting with the next player' ran {done['trace'][0].get('players')}, not p2 then p1")
        if at(after, "b1") != ("player", "p2", "hand"):
            errors.append(f"p1 returned p2's b1: it must go to its owner's hand, is at {at(after, 'b1')}")
        if [e.get("outcome") for e in done["trace"][1:]] != ["declined", "applied"]:
            errors.append(f"Whirlwind outcomes {[e.get('outcome') for e in done['trace'][1:]]}")
    ask = run(state, WHIRL, [])
    if ask.get("committed") or ask.get("decision_ids") != ["may@p2"] or ask.get("decision_controller") != "p2":
        errors.append(f"'each player may': p2 decides first: {ask.get('decision_ids')} {ask.get('decision_controller')}")
    usurp = run(state, WHIRL, [pick(state, "may@p2", "p1", False, kind="optional_choice")])
    if usurp.get("committed") or usurp.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"p1 deciding p2's 'may' was not refused: {usurp.get('reason_code')}")

    # ---------------------------------------------------------------- the whole hand (422.4)
    done = run(state, INVERT)
    if not done.get("committed"):
        errors.append(f"Invert Timelines refused: {done.get('reason') or done.get('errors')}")
    else:
        after = done["next_state"]
        for player, hand in (("p1", ["h1a", "h1b"]), ("p2", ["h2a"])):
            if any(at(after, c) != ("player", player, "trash") for c in hand):
                errors.append(f"{player}'s hand was not all discarded: {[at(after, c) for c in hand]}")
            if len(after["players"][player]["zones"]["hand"]) != 4:
                errors.append(f"{player} holds {len(after['players'][player]['zones']['hand'])}, not the 4 drawn")
    empty = copy.deepcopy(state)
    for c in list(empty["players"]["p2"]["zones"]["hand"]):
        empty["players"]["p2"]["zones"]["hand"].remove(c)
        empty["players"]["p2"]["zones"]["trash"].append(c)
    done = run(empty, INVERT)
    discards = [e for e in done.get("trace") or [] if e.get("op") == "discard"]
    if not done.get("committed") or [e.get("outcome") for e in discards] != ["applied", "no_op"] \
            or len(done["next_state"]["players"]["p2"]["zones"]["hand"]) != 4:
        errors.append(f"an empty hand discards nothing and still draws 4: {[e.get('outcome') for e in discards]}")

    # ---------------------------------------------------------------- groups: King's Edict
    three = settle_contested(three_players(state))
    edict = [pick(three, "ch@p2", "p2", ["b1"]), pick(three, "ch@p3", "p3", ["c1u"])]
    ctx3 = {"turn": {"turn_player": "p1", "turn_order": ["p1", "p2", "p3"]}}
    done = run(three, EDICT, edict, context=ctx3)
    if not done.get("committed"):
        errors.append(f"King's Edict refused: {done.get('reason') or done.get('errors')}")
    else:
        after = done["next_state"]
        if at(after, "b1") != ("player", "p2", "trash") or at(after, "c1u") != ("player", "p3", "trash"):
            errors.append(f"King's Edict: b1 at {at(after, 'b1')}, c1u at {at(after, 'c1u')}")
        if done["trace"][0].get("players") != ["p2", "p3"]:
            errors.append(f"'each other player', starting with the next: {done['trace'][0].get('players')}")
        if any(at(after, o) != at(three, o) for o in ("u1", "a1", "a2", "u2")):
            errors.append("King's Edict killed a unit no player chose")
    twice = run(three, EDICT, [pick(three, "ch@p2", "p2", ["b1"]), pick(three, "ch@p3", "p3", ["b1"])], context=ctx3)
    if twice.get("committed") or twice.get("reason_code") != "illegal_operation":
        errors.append(f"p3 choosing the unit p2 chose was not refused: {twice.get('reason_code')}")
    mine = run(three, EDICT, [pick(three, "ch@p2", "p2", ["a1"]), pick(three, "ch@p3", "p3", ["c1u"])], context=ctx3)
    if mine.get("committed") or mine.get("reason_code") != "illegal_operation":
        errors.append(f"p2 choosing a unit the caster controls was not refused: {mine.get('reason_code')}")
    # a chosen unit gone before the kill (a unit p3 chose, returned by an instruction in between)
    gone = copy.deepcopy(EDICT)
    gone.insert(1, {"op": "return_to_hand", "effect_id": "rt", "object_id": "c1u"})
    done = run(three, gone, edict, context=ctx3)
    if not done.get("committed") or at(done["next_state"], "c1u") != ("player", "p3", "hand") \
            or at(done["next_state"], "b1") != ("player", "p2", "trash") \
            or [g["object_id"] for g in done["trace"][-1].get("not_in_play") or []] != ["c1u"]:
        errors.append(f"a chosen unit that left the board is not killed, the others are: "
                      f"{done.get('reason') or done['trace'][-1] if done.get('trace') else None}")
    unbound = run(three, [{"op": "kill", "effect_id": "kl", "group_ref": "ke"}], [], context=ctx3)
    if unbound.get("committed") or unbound.get("reason_code") != "group_unbound":
        errors.append(f"'those units' with nothing chosen was not refused: {unbound.get('reason_code')}")

    # ---------------------------------------------------------------- groups: the rest
    judge = copy.deepcopy(state)
    unit(judge, "a3", "p1")
    for rune, owner in (("rn1", "p1"), ("rn2", "p1"), ("rn3", "p1"), ("rn4", "p2")):
        card(judge, rune, owner, "base", kind="rune")
    card(judge, "h1c", "p1", "hand")
    for gear in ("g1a", "g1b", "g1c"):
        card(judge, gear, "p1", "base", kind="gear")
    chosen = [pick(judge, "cu@p1", "p1", ["u1", "a1"]), pick(judge, "cg@p1", "p1", ["g1a", "g1b"]),
              pick(judge, "cr@p1", "p1", ["rn1", "rn2"]),
              pick(judge, "ch@p1", "p1", ["h1a", "h1b"], kind="card_selection"),
              pick(judge, "cu@p2", "p2", ["u2", "b1"]),
              pick(judge, "rc:order:p1.main_deck", "p1", ["h1c", "g1c", "a3", "a2"], kind="card_ordering")]
    done = run(judge, JUDGE, chosen)
    if not done.get("committed"):
        errors.append(f"Divine Judgment refused: {done.get('reason') or done.get('errors')}")
    else:
        after = done["next_state"]
        for kept in ("u1", "a1", "g1a", "g1b", "rn1", "rn2", "h1a", "h1b", "u2", "b1", "h2a", "rn4"):
            if at(after, kept) != at(judge, kept):
                errors.append(f"Divine Judgment: {kept} was kept and moved to {at(after, kept)}")
        deck1 = after["players"]["p1"]["zones"]["main_deck"]
        if deck1[-4:] != ["h1c", "g1c", "a3", "a2"]:
            errors.append(f"the rest of p1's units, gear and hand, in p1's order, at the bottom of p1's deck: {deck1[-4:]}")
        if after["players"]["p1"]["zones"]["rune_deck"][-1:] != ["rn3"]:
            errors.append(f"p1's unchosen rune goes to p1's rune deck: {after['players']['p1']['zones']['rune_deck']}")
    wrong_order = [c for c in chosen if c["kind"] != "card_ordering"] + [pick(judge, "rc:order", "p1", ["h1c", "g1c", "a3", "a2"], kind="card_ordering")]
    done = run(judge, JUDGE, wrong_order)
    if done.get("committed") or "rc:order:p1.main_deck" not in (done.get("decision_ids") or []):
        errors.append(f"each deck's order is its own decision (rc:order:<owner>.<deck>): {done.get('decision_ids')}")
    private = next((e for e in (run(judge, JUDGE, chosen).get("trace") or []) if e.get("effect_id") == "ch@p1"), {})
    if "chosen_objects" in private or private.get("objects_visible_to") != ["p1"]:
        errors.append("a choice of cards in hand is not named in the public trace (Core 128.4)")

    # ---------------------------------------------------------------- options
    for option, drawn, channeled in (("cards", 1, 0), ("runes", 0, 1)):
        done = run(state, FAVORS, [pick(state, "co@p2", "p2", option, kind="option_selection")])
        if not done.get("committed"):
            errors.append(f"Party Favors ({option}) refused: {done.get('reason') or done.get('errors')}")
            continue
        after = done["next_state"]
        for player in ("p1", "p2"):
            got_hand = len(after["players"][player]["zones"]["hand"]) - len(state["players"][player]["zones"]["hand"])
            got_runes = len([o for o in after["players"][player]["zones"]["base"] if after["objects"][o]["kind"] == "rune"]) \
                - len([o for o in state["players"][player]["zones"]["base"] if state["objects"][o]["kind"] == "rune"])
            if (got_hand, got_runes) != (drawn, channeled):
                errors.append(f"Party Favors ({option}): {player} drew {got_hand} and channeled {got_runes}")
        if option == "runes" and not all(after["objects"][r].get("exhausted") for r in ("r1", "rd2")):
            errors.append("Party Favors (runes): the channeled runes enter exhausted")
    for label, entry, code in (("an option not offered", pick(state, "co@p2", "p2", "gold", kind="option_selection"), "illegal_operation"),
                               ("p1 choosing for p2", pick(state, "co@p2", "p1", "cards", kind="option_selection"), "decision_controller_mismatch")):
        done = run(state, FAVORS, [entry])
        if done.get("committed") or done.get("reason_code") != code:
            errors.append(f"Party Favors, {label}: {done.get('reason_code')}")
    ask = run(state, FAVORS, [])
    if ask.get("reason_code") != "option_selection_required" or ask.get("decision_controller") != "p2":
        errors.append(f"'each other player chooses': p2 is asked, p1 is not: {ask.get('reason_code')} {ask.get('decision_controller')}")
    no_record = run(state, FAVORS[1:], [])
    if no_record.get("committed") or no_record.get("reason_code") != "option_record_unbound":
        errors.append(f"'for each player that chooses Cards' with nothing chosen was not refused: {no_record.get('reason_code')}")

    # ---------------------------------------------------------------- the bridge supplies Turn Order
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    timing.update({"turn_player": "p2"})
    envelope = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": cull}
    bridged = resolve_with_program(timing, "spell-1", state, program(CULL), engine_decisions=envelope)
    first = ((bridged.get("trace") or {}).get("effect") or [{}])[0]
    if not bridged.get("committed") or first.get("players") != ["p2", "p1"]:
        errors.append(f"the bridge did not hand the timing state's Turn Order to the program: "
                      f"{bridged.get('reason') or first.get('players')}")

    # ---------------------------------------------------------------- shapes
    def refused(effects, label):
        if not validate_program(program(effects)):
            errors.append(f"validate_program accepted {label}")

    refused([{"op": "draw", "effect_id": "dr", "player": "$each_player", "count": 1}], "the sentinel outside each_player")
    refused([{**CULL[0], "effects": [copy.deepcopy(CULL[0])]}], "each_player inside each_player")
    refused([{**CULL[0], "effects": [{"op": "deal_damage", "effect_id": "x", "amount": 1,
                                      "target": {"object_id": "u2", "chosen_zone_class": "board"}, "player": "$each_player"}]}],
            "an op that is not run per player")
    refused([{**CULL[0], "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]}],
            "an each_player whose instructions never name the player")
    refused([{**CULL[0], "count": 2}], "a stray count on each_player")
    refused([{**CULL[0], "order": "clockwise"}], "an unknown order")
    refused([{**INVERT[0], "effects": [{"op": "discard", "effect_id": "d", "player": "$each_player", "whole_hand": True, "count": 2}]}],
            "whole_hand with a count")
    refused([{"op": "recycle", "effect_id": "rc", "rest_of": "kept", "player": "p1"}], "rest_of with a player")
    refused([{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1, "group_ref": "ke"}], "group_ref on draw")
    bad = copy.deepcopy(CULL)
    bad[0]["effects"][0]["choice"]["criteria"]["controller_relation"] = "mine"
    refused(bad, "an unknown controller relation")
    for effects, label in ((CULL, "Cull"), (WHIRL, "Whirlwind"), (INVERT, "Invert"), (EDICT, "Edict"), (JUDGE, "Judgment"),
                           (FAVORS, "Favors")):
        problems = validate_program(program(effects))
        if problems:
            errors.append(f"{label}'s program does not validate: {problems[:2]}")
    import json
    schemas = SCRIPT_DIR.parent / "schemas"
    program_schema = json.loads((schemas / "effect-program.schema.json").read_text(encoding="utf-8"))
    item_schema = program_schema["properties"]["effects"]["items"]
    if not {"each_player", "choose_objects", "choose_option"} <= set(item_schema["properties"]["op"]["enum"]) \
            or not {"players", "order", "only_chose", "group", "group_ref", "rest_of", "whole_hand", "options", "record"} <= set(item_schema["properties"]):
        errors.append("effect-program schema lacks the per-player ops or their fields")
    decisions_schema = json.loads((schemas / "engine-decisions.schema.json").read_text(encoding="utf-8"))
    if "option_selection" not in decisions_schema["properties"]["decisions"]["items"]["properties"]["kind"]["enum"]:
        errors.append("engine-decisions schema lacks option_selection")

    if errors:
        print("FAILED: per-player iteration")
        for error in errors:
            print("  - " + error)
        return 1
    print("per-player iteration: order (303.2.a, next player, others, unknown refused), each player's own choice "
          "(355.10.e: another's, at play, not theirs refused; none is a no_op), responsibility (411.1), 'may' by "
          "the player, the whole hand (422.4), groups (distinct, not yours, gone, unbound; the rest to each owner's "
          "deck in its owner's order), options (recorded, filtered, refused), the bridge's Turn Order, and shapes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
