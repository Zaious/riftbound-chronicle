#!/usr/bin/env python3
"""Regression gate for C-59 (ADR-0015 §3): free-for-all play and the Removal
of a Player.

The rule, in its own words: "A player may concede at any time. When a player
concedes, they are removed from the game in progress. If only one other player
is remaining after a player has conceded, the player remaining Wins. If more
than one player remains after a concession, follow the steps for the Removal
of a Player."

Must hold:
  - three and four players run as free-for-all: the Turn Order cycles through
    everyone, and War's First Turn Process is in the catalogue rather than
    refused as unknown;
  - a concession with one other player left ends the game with that player as
    the winner, recorded and not derived from points;
  - a concession with more than one left removes the player and the game goes
    on: everything they own leaves the game, everything they controlled but
    did not own is Banished to its own owner, the Battlefield they contributed
    becomes a token Battlefield with no abilities while the Units and Hidden
    cards there do not move, their chain items are Countered, and the turn and
    the Focus pass to the next available player in Turn Order;
  - no winner is derived from a three-player concession — the result says so;
  - a team mode is refused by name, and a state that cannot say who
    contributed which Battlefield fails closed rather than guessing;
  - the two-player path is unchanged, and `declare_terminal` now points a
    multi-player concession at this procedure instead of refusing it blankly.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import find_location, validate_state  # noqa: E402
from engine_check import KIND_CONFIG  # noqa: E402
from rules_core import validate_state as validate_timing  # noqa: E402
from terminal import concede, declare_terminal  # noqa: E402
from turn_cycle import MODE_CATALOGUE, first_turn_process  # noqa: E402

PLAYERS = ("p1", "p2", "p3")


def timing(players=PLAYERS, **over):
    state = copy.deepcopy(fixture())
    state["players"] = list(players)
    state["turn_order"] = list(players)
    state["turn_player"] = players[0]
    state["priority"] = players[0]
    state.update(over)
    return state


def effects(players=PLAYERS):
    """Three players, each with a Battlefield they contributed, one Unit p1
    controls but p3 owns, and a Hidden card at p3's Battlefield."""
    state = base_state()
    state["mode"] = {"id": "skirmish", "victory_score": 8}
    state["turn_id"] = "turn-2"
    state["players"]["p3"] = copy.deepcopy(state["players"]["p2"])
    state["players"]["p3"]["zones"] = {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [],
                                       "rune_deck": []}
    state["battlefields"] = {}
    for index, player in enumerate(players, start=1):
        state["battlefields"][f"bf{index}"] = {"controller": None, "objects": [], "contributed_by": player}
    # p2 owns u9 but p3 controls it: Banished to its own owner, and it stays
    # in the game because it is not the conceding player's card (652.3, 652.4)
    state["objects"]["u9"] = {"owner": "p2", "controller": "p3", "kind": "unit", "base_might": 2,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["battlefields"]["bf1"]["objects"].append("u9")
    # p3's own Unit at their own Battlefield, and p2's Unit standing there too
    state["objects"]["u7"] = {"owner": "p3", "controller": "p3", "kind": "unit", "base_might": 3,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["battlefields"]["bf3"]["objects"].append("u7")
    state["objects"]["u8"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 1,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["battlefields"]["bf3"]["objects"].append("u8")
    state["battlefields"]["bf3"]["controller"] = "p3"
    for card, owner in (("s3", "p3"), ("s2", "p2")):
        state["objects"][card] = {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False}
    state["chain_items"] = {"spell-p3": {"controller": "p3", "card": "s3"},
                            "spell-p2": {"controller": "p2", "card": "s2"}}
    return state


def main() -> int:
    errors: list[str] = []

    # --- the modes ----------------------------------------------------------------------------
    war = MODE_CATALOGUE["war"]
    if war["first_turn"] != {"extra_channel": ["last"], "skip_draw": ["first"]}:
        errors.append(f"War's First Turn Process is not in the catalogue: {war['first_turn']}")
    four = timing(("p1", "p2", "p3", "p4"))
    four_effect = effects()
    four_effect["mode"] = {"id": "war", "victory_score": 8}
    four_effect["players"]["p4"] = copy.deepcopy(four_effect["players"]["p3"])
    for player, expected in (("p1", (False, True)), ("p4", (True, False)), ("p2", (False, False))):
        facts, problem = first_turn_process(four, four_effect, player)
        if problem is not None:
            errors.append(f"War's First Turn Process refused {player}: {problem}")
        elif (facts["extra_channel"], facts["skip_draw"]) != expected:
            errors.append(f"War's First Turn Process is wrong for {player}: {facts}")

    # --- three players: the game continues -----------------------------------------------------
    t, e = timing(), effects()
    if found := validate_timing(t):
        errors.append(f"the three-player timing fixture is invalid: {found}")
    if found := validate_state(e):
        errors.append(f"the three-player effect fixture is invalid: {found}")
    result = concede(t, e, player="p3")
    if not result.get("committed"):
        print("FAILED: free-for-all checks")
        print(f"  - the three-player concession did not commit: {result.get('reason_code')} {result.get('reason')}")
        return 1
    next_t, next_e = result["next_timing_state"], result["next_effect_state"]
    if next_t.get("terminal") is not None or result["trace"]["winner"] is not None:
        errors.append("a three-player concession derived a winner instead of continuing (651.4)")
    if next_t["players"] != ["p1", "p2"] or next_t["turn_order"] != ["p1", "p2"]:
        errors.append(f"the conceding player was not removed from the game: {next_t['players']}")
    if "p3" in next_e["players"]:
        errors.append("the conceding player still has a seat in the effect state")
    if "u7" in next_e["objects"] or "u7" in result["trace"]["banished"]:
        errors.append("a card the conceding player owned was Banished instead of leaving the game (652.4)")
    if find_location(next_e, "u9") != ("player", "p2", "banishment"):
        errors.append(f"a card they controlled but did not own was not Banished to its owner (652.3): {find_location(next_e, 'u9')}")
    if result["trace"]["banished"] != ["u9"] or sorted(result["trace"]["cards_removed_from_game"]) != ["s3", "u7"]:
        errors.append(f"the removal did not separate Banish from leaving the game: {result['trace']['banished']} "
                      f"{result['trace']['cards_removed_from_game']}")
    if result["trace"]["countered_chain_items"] != ["spell-p3"] or "spell-p2" not in next_e["chain_items"]:
        errors.append(f"the wrong chain items were Countered: {result['trace']['countered_chain_items']}")

    # the Battlefield they contributed becomes a token with no abilities, and
    # what stands there does not move
    replaced = next_e["battlefields"]["bf3"]
    if replaced.get("is_token") is not True:
        errors.append("the contributed Battlefield was not replaced with a token Battlefield (652.5.a.1)")
    if "u8" not in replaced["objects"]:
        errors.append("a Unit at the removed Battlefield moved; it should be unaffected (652.5.b.1)")
    if replaced.get("controller") != "p3" and "controller" not in replaced:
        errors.append("the replaced Battlefield lost its controller field entirely")

    # --- two players left after a three-player concession, then one ------------------------------
    second = concede(next_t, next_e, player="p2")
    if not second.get("committed"):
        errors.append(f"the second concession did not commit: {second.get('reason_code')} {second.get('reason')}")
    else:
        record = second["next_timing_state"].get("terminal") or {}
        if record.get("reason") != "concession" or record.get("winner") != "p1" or record.get("derived") is not False:
            errors.append(f"the last remaining player did not win, recorded rather than derived: {record}")

    # --- the boundaries ---------------------------------------------------------------------------
    teamed = copy.deepcopy(e)
    teamed["mode"] = {"id": "magma_chamber", "victory_score": 11, "teams": True}
    if concede(t, teamed, player="p3").get("reason_code") != "team_scoring":
        errors.append("a team-mode concession was resolved instead of refused by name (652.2.a)")
    anonymous = copy.deepcopy(e)
    for battlefield in anonymous["battlefields"].values():
        battlefield.pop("contributed_by", None)
    blind = concede(t, anonymous, player="p3")
    if blind.get("committed") or blind.get("reason_code") != "contributed_battlefield_unknown":
        errors.append(f"a state that cannot say who contributed a Battlefield did not fail closed: {blind.get('reason_code')}")
    if concede(t, e, player="p9").get("valid") is not False:
        errors.append("a concession by an unknown player was accepted")

    # --- the turn and the focus move on --------------------------------------------------------
    turn_of_p3 = timing(over={} if False else {"turn_player": "p3", "priority": "p3"})
    moved = concede(turn_of_p3, e, player="p3")
    if not moved.get("committed"):
        errors.append(f"conceding on one's own turn did not commit: {moved.get('reason')}")
    elif moved["next_timing_state"]["turn_player"] != "p1":
        errors.append(f"play did not proceed to the next available player in Turn Order: {moved['next_timing_state']['turn_player']}")
    focused = timing()
    focused["showdown"] = {"active": True, "focus": "p3", "battlefield": "bf3", "origin": None}
    focused["priority"] = "p3"
    with_focus = concede(focused, e, player="p3")
    if with_focus.get("committed") and with_focus["next_timing_state"]["showdown"]["focus"] != "p1":
        errors.append(f"the Focus did not pass to the next player in order: {with_focus['next_timing_state']['showdown']['focus']}")

    # --- the two-player path is unchanged --------------------------------------------------------
    duo_t, duo_e = fixture(), base_state()
    duo_e["mode"] = {"id": "duel", "victory_score": 8}
    duo = declare_terminal(duo_t, duo_e, declaration={"reason": "concession", "player": "p1"})
    if not duo.get("committed") or (duo["next_timing_state"].get("terminal") or {}).get("winner") != "p2":
        errors.append("the two-player concession path changed")
    pointed = declare_terminal(t, e, declaration={"reason": "concession", "player": "p3"})
    if pointed.get("reason_code") != "multi_player_concession" or "concede" not in pointed.get("reason", ""):
        errors.append(f"declare_terminal does not point a multi-player concession at the procedure: {pointed.get('reason')}")
    if "multi_player_concession" in KIND_CONFIG["turn_step"]["unsupported"]:
        errors.append("multi_player_concession is still declared unsupported")
    if concede(t, e, player="p3") != result:
        errors.append("the Removal of a Player is not deterministic")

    if errors:
        print("FAILED: free-for-all checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("free-for-all checks passed: Skirmish and War first turns, the Removal of a Player, and no winner derived "
          "from a concession while more than one player remains")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
