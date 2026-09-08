#!/usr/bin/env python3
"""Regression gate for move_restriction.v1 (DP-96; Core 144, 359.3.e.6).

Vilemaw's Lair: "Units can't move from here to base."

The tempting implementation is one rule - refuse the move - and Core
359.3.e.6 says that is wrong. It gives the case directly: a player uses Ride
the Wind and chooses to move a Unit at Vilemaw's Lair to a Base. The Base is
a *legal destination* for that choice. The restriction makes the move
instruction impossible when the effect resolves, so that instruction is
ignored - and only that instruction.

So one predicate, two behaviours:

  Standard Move        the player's own action. A destination the board
                       forbids is not an action they have: the enumerator does
                       not list it, and submitting it anyway is refused by
                       name (move_restricted_by_location). Never silently
                       dropped, never treated as an invalid target.
  effect-induced Move  the destination may be chosen. At resolution the
                       instruction is skipped_restricted_move and everything
                       else in the program still runs. The spell is not
                       invalid and the earlier choice is not retroactively
                       illegal.

Two predicates would eventually disagree about which moves are restricted at
all, which is a different bug from either behaviour - so both paths read
`move_restricted`.

Every fixture here is synthetic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import combat  # noqa: E402
import effect_ir  # noqa: E402
import legal_action as la  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, hash_value, move_restricted, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

LAIR = [{"source_location": "here", "destination_kind": "base", "affected_kind": "unit"}]


def board():
    """u1 (p1) at the restricted bf1; u2 (p1) at the ordinary bf2."""
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["u2"].update({"owner": "p1", "controller": "p1", "exhausted": False})
    state["objects"]["u1"]["exhausted"] = False
    state["players"]["p1"]["zones"]["base"] = []
    state["players"]["p2"]["zones"]["base"] = []
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"], "move_restrictions": copy.deepcopy(LAIR)}
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": ["u2"]}
    return state


def move_declaration(state, units, destination):
    return {"schema_version": combat.STANDARD_MOVE_DECLARATION_VERSION,
            "actor": "p1", "units": list(units),
            "unit_identities": {u: effect_ir.object_identity(state, u) for u in units},
            "destination": destination,
            "cost_confirmation": {"exhaust_confirmed": True}}


def ride_the_wind(object_id="u1", destination=None):
    """An effect that moves a Unit and then draws - so the gate can see whether
    an ignored move takes the rest of the spell down with it."""
    prog = program("ride-the-wind",
                   {"op": "move_board_object", "effect_id": "mv", "object_id": object_id,
                    "destination": destination or {"kind": "base", "player": "p1"}},
                   {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1})
    prog["source_object"] = "u2"
    return prog


def observe(state):
    return la.build_observation(
        perspective="player1", source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard",
                 "card_data_version": "synthetic"},
        timing_state=fixture(), effect_state=state, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete",
                      "pending_decisions": "complete"})


def main() -> int:
    errors: list[str] = []
    state = board()
    if validate_state(state):
        errors.append(f"the restricted board is not a valid state: {validate_state(state)}")

    # --- 1. a Standard Move to a Base is neither listed nor accepted ---------------------------------
    enumerated = la.enumerate_actions(observe(state), "p1")
    moves = [a for a in enumerated["enumeration"]["actions"] if a["family"] == "standard_move"]
    offered = {(a["action"]["object_id"], a["action"]["destination"].get("player")
                or a["action"]["destination"].get("battlefield")) for a in moves}
    if ("u1", "p1") in offered:
        errors.append("the enumerator offered a Standard Move the Battlefield forbids")
    if ("u2", "p1") not in offered:
        errors.append(f"a Unit elsewhere lost its ordinary Move to Base: {sorted(offered)}")
    if ("u1", "bf2") not in offered:
        errors.append("moving off the restricted Battlefield to another Battlefield was refused")
    family = next(f for f in enumerated["enumeration"]["families"] if f["family"] == "standard_move")
    if not any(item.get("reason_code") == "move_restricted_by_location" for item in family["excluded"]):
        errors.append(f"the restricted destination was dropped without saying why: {family['excluded']}")

    refused = combat.standard_move(fixture(), state, move_declaration(state, ["u1"], {"kind": "base"}))
    if refused.get("committed") or refused.get("reason_code") != "move_restricted_by_location":
        errors.append(f"a Standard Move to the forbidden Base was not refused by name: "
                      f"{refused.get('reason_code')}")

    # --- 4. and what is not restricted still works -----------------------------------------------------
    state["objects"]["u1"]["keywords"] = ["ganking"]
    away = combat.standard_move(fixture(), state, move_declaration(state, ["u1"], {"kind": "battlefield", "battlefield": "bf2"}))
    if not away.get("committed"):
        errors.append(f"moving off the restricted Battlefield was refused: {away.get('reason_code')}")
    elsewhere = combat.standard_move(fixture(), state, move_declaration(state, ["u2"], {"kind": "base"}))
    if not elsewhere.get("committed"):
        errors.append(f"a Unit at an ordinary Battlefield could not move to its Base: "
                      f"{elsewhere.get('reason_code')}")

    # --- 2 and 3. Core 359.3.e.6: the choice stands, the instruction is ignored, ------------------------
    #     and the rest of the spell runs.
    ridden = apply_program(state, ride_the_wind())
    if not ridden.get("committed"):
        errors.append(f"a spell moving a restricted Unit was made invalid: "
                      f"{ridden.get('reason') or ridden.get('errors')}; 359.3.e.6 ignores the instruction, "
                      "not the spell")
    else:
        steps = {step["effect_id"]: step for step in ridden["trace"]}
        move = steps.get("mv", {})
        if move.get("outcome") != "skipped_restricted_move" or move.get("reason") != "move_restricted_by_location":
            errors.append(f"the restricted move instruction was not ignored by name: {move}")
        if "Core 359.3.e.6" not in move.get("rule_locators", []):
            errors.append(f"the ignored instruction does not cite the rule that ignores it: {move}")
        after = ridden["next_state"]
        if "u1" not in after["battlefields"]["bf1"]["objects"]:
            errors.append("the restricted Unit moved anyway")
        if steps.get("dr", {}).get("outcome") != "applied":
            errors.append(f"an independent instruction of the same effect was abandoned: {steps.get('dr')}")
        if len(after["players"]["p1"]["zones"]["hand"]) != 1:
            errors.append("the draw that shares the spell with the restricted move did not happen")
    # the same effect, unrestricted, does move - so the fixture proves the restriction and not a no-op
    free = apply_program(state, ride_the_wind("u2"))
    if "u2" not in free["next_state"]["players"]["p1"]["zones"]["base"]:
        errors.append("the same effect did not move an unrestricted Unit; the fixture is not testing "
                      "the restriction")

    # --- both paths read the same predicate --------------------------------------------------------------
    if move_restricted(state, "u1", {"kind": "base", "player": "p1"}) is None:
        errors.append("the predicate does not see the restriction the two paths act on")
    if move_restricted(state, "u1", {"kind": "battlefield", "battlefield": "bf2"}) is not None:
        errors.append("the predicate restricts a destination the card does not name")
    if move_restricted(state, "u2", {"kind": "base", "player": "p1"}) is not None:
        errors.append("the predicate restricts a Unit that is not at the restricted Battlefield")

    # --- the state validator holds the restriction to its vocabulary ---------------------------------------
    for bad, why in (
        ([{"source_location": "anywhere", "destination_kind": "base", "affected_kind": "unit"}], "a source it cannot express"),
        ([{"source_location": "here", "destination_kind": "battlefield", "affected_kind": "unit"}], "a destination kind it cannot express"),
        ([{"source_location": "here", "destination_kind": "base"}], "a missing field"),
    ):
        broken = copy.deepcopy(state)
        broken["battlefields"]["bf1"]["move_restrictions"] = bad
        if not validate_state(broken):
            errors.append(f"a restriction with {why} was accepted; it should stay unparsed instead")

    # --- 5. the four shapes this wave does not read ---------------------------------------------------------
    grammar = cg.load_grammar()
    compiled = cg.compile_card([{"text": "Units can't move from here to base."}], grammar)
    if compiled["clauses"][0].get("unsupported"):
        errors.append(f"Vilemaw's Lair did not compile: {compiled['unsupported_clauses']}")
    elif compiled["passive"]["battlefield_fields"]["move_restrictions"] != LAIR:
        errors.append(f"the clause did not print the restriction: {compiled['passive']}")
    for text, family_id in (("Units can't move to base.", "global_move_restriction"),
                            ("I can't move to base.", "self_move_restriction"),
                            ("They can't move it this turn.", "timed_move_restriction"),
                            ("Units can't move from here to a battlefield.", "other_destination_restriction")):
        if not cg.compile_clause(text, grammar).get("unsupported"):
            errors.append(f"{family_id} was compiled; only Vilemaw's shape is in this wave: {text!r}")

    if errors:
        print("FAILED: move restriction checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("move restriction checks passed: a Standard Move to the forbidden Base is neither offered nor "
          "accepted and is refused by name, an effect may still choose it and has only that instruction "
          "ignored (359.3.e.6) while the rest of the spell runs, and the four other restriction shapes "
          "stay unparsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
