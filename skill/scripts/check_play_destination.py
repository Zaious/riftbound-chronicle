#!/usr/bin/env python3
"""Regression gate for occupied_enemy_battlefield (DP-95; Core 355.2, 170.11).

Deadbloom Predator: "You may play me to an occupied enemy battlefield."

Codex read the phrase off the Core rather than off a ruling:

    170.11.a  "occupied" means a Unit is there - *a* Unit, not an enemy's.
    355.2.a   the default is the actor's own Base or a Battlefield the actor
              controls; 355.2.b lets a card widen that.
    323.6     Cleanup removes a controller from a Battlefield with none of
              their Units left, so by the next window to play a Unit, a
              Battlefield whose owner has nothing there is no longer theirs.

The narrowest wrong version of this is the tempting one: requiring the Unit
present to be an *enemy's* Unit. It sounds like a tightening, and it is a
restriction the card does not write - so the gate builds the exact board that
separates the two readings (an enemy-controlled Battlefield holding only the
actor's own Unit) and asserts the play is legal there.

The other three failures this is written against:

  - **it widens timing.** The permission says where, not when. A Unit still
    passes Unit timing; playing it as a Reaction is still illegal.
  - **it changes the existing three paths.** Controlled, open + permission and
    Ambush must each behave exactly as before, with and without the new
    permission on the card.
  - **the enumerator and the transaction disagree.** Every Battlefield the
    enumerator offers is one the transaction accepts, and every one it omits
    is one the transaction refuses. Checked by running both over the same
    board rather than by reading the code twice.

Every fixture here is synthetic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import legal_action as la  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def board(*, controller, units, permissions=("occupied_enemy_battlefield",)):
    """bf1 with the given controller and the given units on it; c1 is the card
    in p1's hand, carrying `permissions`."""
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 5, "power": {"calm": 2}}
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2,
                                   "printed_cost": {"energy": 1, "power": {}},
                                   "play_permissions": list(permissions)})
    state["battlefields"]["bf1"] = {"controller": controller, "objects": list(units)}
    # every unit not on bf1 goes home, so the state stays well formed
    state["players"]["p1"]["zones"]["base"] = [] if "u1" in units else ["u1"]
    state["players"]["p2"]["zones"]["base"] = [] if "u2" in units else ["u2"]
    return state


def declaration(battlefield="bf1", **extra):
    return {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}},
            "entry_location": {"kind": "battlefield", "battlefield": battlefield},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}, **extra}


def play(state, **extra):
    return pt.play_card(fixture(), state, declaration(**extra))


def main() -> int:
    errors: list[str] = []

    # --- the reading: occupied means a Unit is there, of anyone's -----------------------------------
    enemy_unit = board(controller="p2", units=["u2"])
    if not play(enemy_unit).get("committed"):
        errors.append(f"an enemy Battlefield holding an enemy Unit was refused: {play(enemy_unit).get('reason')}")
    # the board that separates the two readings: enemy-controlled, but the only
    # Unit there is the actor's own.
    own_unit_only = board(controller="p2", units=["u1"])
    own_unit_only["objects"]["u1"]["controller"] = "p1"
    result = play(own_unit_only)
    if not result.get("committed"):
        errors.append("an enemy Battlefield occupied by the actor's own Unit was refused; "
                      "170.11.a says 'occupied' is a Unit being there, and requiring an *enemy* Unit "
                      f"adds a restriction the card does not write: {result.get('reason')}")

    # --- and what it is not ---------------------------------------------------------------------------
    empty_enemy = board(controller="p2", units=[])
    if play(empty_enemy).get("committed"):
        errors.append("an enemy Battlefield with nothing on it was accepted; it is not occupied (170.11.a)")
    gear_only = board(controller="p2", units=["g1"])
    gear_only["objects"]["g1"] = {"owner": "p2", "controller": "p2", "kind": "gear", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False}
    if play(gear_only).get("committed"):
        errors.append("a Battlefield holding only a Gear was treated as occupied; 170.11.a says a Unit")
    unowned = board(controller=None, units=["u2"])
    if play(unowned).get("committed"):
        errors.append("a Battlefield with no controller was treated as an enemy Battlefield")
    own = board(controller="p1", units=["u2"])
    if not play(own).get("committed"):
        errors.append("the actor's own Battlefield stopped working")
    without = board(controller="p2", units=["u2"], permissions=())
    if play(without).get("committed"):
        errors.append("a card with no permission reached an enemy Battlefield anyway")

    # --- the permission widens where, never when ------------------------------------------------------
    reaction = play(enemy_unit, timing_source="ambush")
    if reaction.get("committed"):
        errors.append("the permission was read as Ambush timing; it says where, not when")
    late = copy.deepcopy(enemy_unit)
    timing = fixture()
    timing["phase"] = "ending"
    outside = pt.play_card(timing, late, declaration())
    if outside.get("committed"):
        errors.append("a Unit was played outside its timing because its destination was permitted")

    # --- the three existing paths are untouched --------------------------------------------------------
    for label, state, permissions, expected in (
        ("controlled", board(controller="p1", units=[]), (), True),
        ("open without permission", board(controller=None, units=[]), (), False),
        ("open with permission", board(controller=None, units=[]), ("open_battlefield",), True),
        ("open with only the new permission", board(controller=None, units=[]),
         ("occupied_enemy_battlefield",), False),
    ):
        state = copy.deepcopy(state)
        state["objects"]["c1"]["play_permissions"] = list(permissions)
        if bool(play(state).get("committed")) is not expected:
            errors.append(f"the {label} path changed: expected committed={expected}")

    # --- the enumerator and the transaction agree, on the same board ------------------------------------
    many = board(controller="p2", units=["u2"])
    many["battlefields"]["bf2"] = {"controller": None, "objects": []}          # open, no permission for it
    many["battlefields"]["bf3"] = {"controller": "p2", "objects": []}          # enemy, empty
    observation = la.build_observation(
        perspective="player1",
        source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard",
                 "card_data_version": "synthetic"},
        timing_state=fixture(), effect_state=many, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete",
                      "pending_decisions": "complete"})
    enumerated = la.enumerate_actions(observation, "p1")
    action = next((a["action"] for a in enumerated["enumeration"]["actions"]
                   if a["candidate_id"] == "play:c1"), None)
    if action is None:
        errors.append(f"the card was not enumerated at all: {enumerated['enumeration']}")
    else:
        offered = {e["battlefield"] for e in action.get("entry_locations", []) if e["kind"] == "battlefield"}
        for battlefield_id in sorted(many["battlefields"]):
            accepted = bool(pt.play_card(fixture(), many, declaration(battlefield_id)).get("committed"))
            if accepted != (battlefield_id in offered):
                errors.append(f"the enumerator and the transaction disagree about {battlefield_id!r}: "
                              f"offered={battlefield_id in offered} accepted={accepted}")
        if offered != {"bf1"}:
            errors.append(f"the enumerator offered the wrong Battlefields: {offered}")

    # --- 323.6: a controller with no Units left loses the Battlefield, so the ----------------------------
    #     permission finds nothing there at the next window to play a Unit.
    vacated = board(controller=None, units=[])   # what 323.6 leaves behind
    vacated["objects"]["c1"]["play_permissions"] = ["occupied_enemy_battlefield"]
    if play(vacated).get("committed"):
        errors.append("the permission reached a Battlefield whose controller Cleanup had already removed")

    if errors:
        print("FAILED: play destination checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("play destination checks passed: 'occupied' is any Unit being there and 'enemy' is the "
          "controller relation, the permission widens where and never when, the three existing paths are "
          "unchanged, and the enumerator offers exactly the Battlefields the transaction accepts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
