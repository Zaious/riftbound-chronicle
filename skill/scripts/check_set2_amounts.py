#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): two amounts an instruction reads.

  L  "deal damage equal to my [Assault]" (Lucian - Gunslinger): the source's Assault as the Deal executes (Core 807.2,
     359.3.f.2) - printed [Assault] deals 1; with [Assault 2] granted this turn, 3 (instances summed); a source with no
     Assault deals nothing (a named no_op); a source that left the board is not read (the Deal ignored)
  K  "Kill a friendly unit. If you do, give +[M] equal to its Might to another friendly unit this turn." (Deathgrip): the
     killed unit's Might as it died (its last known information, Core 359.3.e.12) - a 4-Might unit with +1 this turn gives
     +5; the kill ignored (its target gone before it executes) - the give is too (359.3.e.14.a)
  R  "Counter that spell and give that unit +[M] equal to that spell's Energy cost this turn." (Riposte): a spell printed
     [3][Fury] countered - its card in its owner's trash - and the unit given +3 (the countered card's printed Energy,
     Core 206; a counter's card is what a later linked instruction reads, 359.3.e.14)
  V  shapes: linked_killed_might naming an instruction that is not a kill, or read by a Deal, is refused; a this-turn
     modify_might of one target may read linked_card_printed_energy (Riposte), with bounds it may not

    python skill/scripts/check_set2_amounts.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, effective_might, object_identity, validate_program,  # noqa: E402
                       validate_state)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might=3, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def program(pid, effects, controller="p1", **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": controller, "effects": effects, **extra}


def lucian_board(keywords=("assault",)):
    state = base_state()
    state["objects"]["lu"] = unit("p1", 3, keywords=list(keywords))
    state["objects"]["foe"] = unit("p2", 6)
    state["battlefields"]["bf1"]["objects"] = ["lu", "foe"]
    return settle_contested(state)


def lucian_deal(state):
    deal = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "program_source_assault"}, "object_id": "foe"}
    done = apply_program(state, program("lucian", [deal], source_object="lu", source_identity=object_identity(state, "lu")))
    if not done.get("committed"):
        return f"refused: {done.get('errors') or done.get('reason')}"
    event = next(e for e in done["trace"]["effect"] if e.get("effect_id") == "dmg") if isinstance(done.get("trace"), dict) else None
    return done["next_state"]["objects"]["foe"]["damage"], (event or {}).get("outcome")


def main() -> int:
    # L
    state = lucian_board()
    if problems := validate_state(state):
        fail("L", f"invalid board: {problems[:2]}")
    else:
        got = lucian_deal(state)
        if not isinstance(got, tuple) or got[0] != 1:
            fail("L", f"printed [Assault]: {got}, not 1 damage (Core 807.2)")
        granted = apply_program(state, program("cleave", [{"op": "grant_keyword", "effect_id": "g", "object_id": "lu",
                                                           "keyword": "assault", "value": 2, "duration": "this_turn",
                                                           "source": "cleave"}]))
        got = lucian_deal(granted["next_state"]) if granted.get("committed") else f"grant refused: {granted.get('errors')}"
        if not isinstance(got, tuple) or got[0] != 3:
            fail("L", f"[Assault] and [Assault 2] granted: {got}, not 3 damage (instances summed)")
        got = lucian_deal(lucian_board(keywords=()))
        if not isinstance(got, tuple) or got[0] != 0:
            fail("L", f"no Assault: {got}, not 0 damage")
        gone = copy.deepcopy(state)
        identity = object_identity(gone, "lu")
        gone["battlefields"]["bf1"]["objects"].remove("lu")
        gone["players"]["p1"]["zones"]["trash"].append("lu")
        gone["objects"]["lu"]["identity"] = "lu@9"
        done = apply_program(gone, program("lucian", [{"op": "deal_damage", "effect_id": "dmg", "object_id": "foe",
                                                       "amount_ref": {"kind": "program_source_assault"}}],
                                           source_object="lu", source_identity=identity))
        if not done.get("committed") or done["next_state"]["objects"]["foe"]["damage"] != 0:
            fail("L", f"a source that left the board was read: {done.get('errors') or done.get('reason')}")
    # K
    state = base_state()
    state["objects"]["victim"] = unit("p1", 4, might_modifiers=[{"amount": 1, "duration": "this_turn", "source": "x"}])
    state["objects"]["heir"] = unit("p1", 2)
    state["players"]["p1"]["zones"]["base"] += ["victim", "heir"]
    grip = [{"op": "kill", "effect_id": "kl", "object_id": "victim"},
            {"op": "modify_might", "effect_id": "mm", "duration": "this_turn", "source": "grip",
             "target": {"object_id": "heir", "chosen_zone_class": "board", "kind": "unit",
                        "bound_identity": object_identity(state, "heir")},
             "amount_ref": {"kind": "linked_killed_might", "effect_id": "kl"}}]
    if problems := validate_program(program("grip", grip)):
        fail("K", f"the program is refused: {problems}")
    else:
        done = apply_program(state, program("grip", grip))
        if not done.get("committed") or effective_might(done["next_state"], "heir") != 7:
            fail("K", f"the heir's Might after the kill: {effective_might(done['next_state'], 'heir') if done.get('committed') else done}, "
                      f"not 7 (+5, the victim's Might as it died, Core 359.3.e.12)")
        gone = copy.deepcopy(state)
        gone["players"]["p1"]["zones"]["base"].remove("victim")
        gone["players"]["p1"]["zones"]["trash"].append("victim")
        ignored = [{**grip[0], "target": {"object_id": "victim", "chosen_zone_class": "board", "kind": "unit",
                                          "bound_identity": object_identity(state, "victim")}},
                   grip[1]]
        ignored[0].pop("object_id")
        done = apply_program(gone, program("grip", ignored))
        if done.get("committed") and effective_might(done["next_state"], "heir") != 2:
            fail("K", f"the kill was ignored and the give still happened: heir {effective_might(done['next_state'], 'heir')}")
    # R: "Counter that spell and give that unit +[M] equal to that spell's Energy cost this turn." (Riposte)
    from check_counter_target import board as chain_board, TARGET as CHAIN_TARGET
    state = chain_board(printed={"energy": 3, "power": {"fury": 1}})
    state["objects"]["mine"] = unit("p2", 2)
    state["players"]["p2"]["zones"]["base"].append("mine")
    riposte_run = [{"op": "counter", "effect_id": "ctr", "target": dict(CHAIN_TARGET)},
                   {"op": "modify_might", "effect_id": "mm", "duration": "this_turn", "source": "riposte",
                    "target": {"object_id": "mine", "chosen_zone_class": "board", "kind": "unit",
                               "bound_identity": object_identity(state, "mine")},
                    "amount_ref": {"kind": "linked_card_printed_energy", "effect_id": "ctr"}}]
    from effect_ir import hash_value
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p2", "value": ["c1"],
         "selection_identities": {"c1": object_identity(state, "c1") or "c1@0"}}]}
    done = apply_program(state, program("riposte", riposte_run, controller="p2"), decisions=decisions)
    if not done.get("committed") or effective_might(done["next_state"], "mine") != 5 \
            or "c1" not in done["next_state"]["players"]["p1"]["zones"]["trash"]:
        fail("R", f"the countered spell's printed [3] as the give: "
                  f"{effective_might(done['next_state'], 'mine') if done.get('committed') else done.get('reason') or done.get('errors')}, "
                  f"not 5 with c1 in its owner's trash")
    # V
    bad = [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1},
           {"op": "modify_might", "effect_id": "mm", "object_id": "u1", "duration": "this_turn", "source": "x",
            "amount_ref": {"kind": "linked_killed_might", "effect_id": "dr"}}]
    if not validate_program(program("bad", bad)):
        fail("V", "linked_killed_might naming a draw validated")
    deal = [{"op": "kill", "effect_id": "kl", "object_id": "u1"},
            {"op": "deal_damage", "effect_id": "d", "object_id": "u2", "amount_ref": {"kind": "linked_killed_might", "effect_id": "kl"}}]
    if not validate_program(program("deal", deal)):
        fail("V", "a Deal reading linked_killed_might validated")
    riposte = [{"op": "discard", "effect_id": "dc", "player": "p1", "count": 1, "decision_ref": "d"},
               {"op": "modify_might", "effect_id": "mm", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"},
                "duration": "this_turn", "source": "$chain_item",
                "amount_ref": {"kind": "linked_card_printed_energy", "effect_id": "dc"}}]
    if problems := validate_program(program("riposte", riposte)):
        fail("V", f"a this-turn modify_might reading linked_card_printed_energy refused: {problems}")
    bounded = copy.deepcopy(riposte)
    bounded[1]["minimum"] = 1
    if not validate_program(program("bounded", bounded)):
        fail("V", "a bounded modify_might reading an amount ref validated")
    if errors:
        print("FAILED: set 2 amounts")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'equal to my [Assault]' is the source's Assault as the Deal executes (807.2); 'equal to its Might' after a "
          "kill is the killed unit's Might as it died (359.3.e.12), ignored with the kill; a this-turn modify_might of one "
          "target reads a linked amount, never with bounds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
