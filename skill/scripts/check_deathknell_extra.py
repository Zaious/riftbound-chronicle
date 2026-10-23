#!/usr/bin/env python3
"""Deathknell triggers that trigger an additional time (Karthus - Eternal), order-independent over simultaneous deaths.

The card's static makes each Deathknell trigger of its controller trigger once more (Core 383.3: a copy of the trigger the
game generated). Death triggers are added to the Chain as Pending Items before the dying cards move to the trash (Core
808.1.d.2; Cleanup 383.2.c.3 before 323.4), so a static on the board as simultaneous deaths are noted counts even when its
card dies in the same action (deaths from one game action are simultaneous, 370.1.a.2). Replacement Effects are applied
first: a card whose death was replaced and that stays on the board counts; one a replacement took off the board does
not. The result never depends on the order the engine applies the deaths in (effect_ir.group_pending_triggers).

  K1 doubled        p1's Deathknell unit killed with the card on the board: two triggers, the copy naming the card
  K2 opponent's     p2's Deathknell unit killed: one trigger (it is not the card's controller's)
  K3 plain death    a death trigger without Deathknell: one trigger
  K4 card gone      the card in the trash: one trigger
  K5 two cards      two such statics: three triggers
  K6 the card dies  the card itself, with no Deathknell of its own, killed: nothing copied
  S1 batch, orders  the card and a Deathknell unit dying in one simultaneous batch, in both orders: two triggers each time
  S2 one spell      "kill two units" choosing the card and the Deathknell unit, in both orders: two triggers each time
  S3 apart          the card killed by one instruction, the unit by a later one: one trigger
  S4 replaced, stays  the card's death prevented in the batch (it stays on the board): two triggers
  S5 replaced, gone   the card's death replaced by a return to its owner's hand (off the board): one trigger
  S6 two cards die  two such cards dying with the unit: three triggers, in both orders
  S7 only Deathknell  an object with a Deathknell and another trigger on its own death: only the Deathknell one copied
  G  grammar        the production lowers to the field; its near misses do not

    python skill/scripts/check_deathknell_extra.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, apply_simultaneous_kill_batch, hash_value,  # noqa: E402
                       object_identity, validate_state)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXT = "Your [Deathknell] effects trigger an additional time."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def death_trigger(oid, owner, suffix="dk", **extra):
    return {"trigger_id": f"{oid}-{suffix}", "controller": owner, "source_object": oid, "controller_order": 0,
            "effect_program_id": f"{oid}-{suffix}-fx", "optional_at_finalize": False, **extra}


def board(fields, *, cards=1):
    state = base_state()
    for n in range(cards):
        state["objects"][f"kar{n}"] = unit("p1", base_might=5, **copy.deepcopy(fields))
        state["players"]["p1"]["zones"]["base"].append(f"kar{n}")
    for oid, owner, keyword in (("dk1", "p1", True), ("plain1", "p1", False), ("dk2", "p2", True)):
        state["objects"][oid] = unit(owner, death_triggers=[death_trigger(oid, owner)],
                                     **({"keywords": ["deathknell"]} if keyword else {}))
        state["players"][owner]["zones"]["base"].append(oid)
    # S7: a Deathknell and another ability that triggers on its own death, each saying which it is
    state["objects"]["mixed"] = unit("p1", keywords=["deathknell"], death_triggers=[
        death_trigger("mixed", "p1", "dk", keyword="deathknell"), death_trigger("mixed", "p1", "die", keyword="own_death")])
    state["players"]["p1"]["zones"]["base"].append("mixed")
    return state


def program(effects, controller="p2"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "kill", "controller": controller, "effects": effects}


def ids(result):
    if not result.get("committed"):
        return f"refused: {result.get('reason') or result.get('errors')}"
    return sorted(t["trigger_id"] for t in result.get("pending_triggers") or [])


def killed(state, oid):
    return ids(apply_program(state, program([{"op": "kill", "effect_id": "k", "object_id": oid}])))


def batch(state, order):
    return ids(apply_simultaneous_kill_batch(state, list(order)))


def two_targets(state, order):
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "kind": "target_selection", "stage": "play_declaration", "controller": "p2",
         "value": list(order), "selection_identities": {o: object_identity(state, o) for o in order}}]}
    effect = {"op": "kill", "effect_id": "k", "targets": {"min": 2, "max": 2, "decision_ref": "t",
                                                          "restrictions": {"chosen_zone_class": "board", "kind": "unit"}}}
    return ids(apply_program(state, program([effect]), decisions=decisions))


DOUBLED = ["dk1-dk", "dk1-dk#extra:kar0:1"]


def main() -> int:
    lowered = cg.compile_clause(TEXT, cg.load_grammar())
    fields = ((lowered.get("passive") or {}).get("object_fields") or {})
    if lowered.get("production_id") != "your_deathknell_effects_trigger_an_additional_time" or fields != {"deathknell_extra_times": 1}:
        print(f"FAILED: the static does not lower: {lowered.get('production_id')} {fields}")
        return 1
    s = board(fields)
    if validate_state(s):
        fail("G grammar", f"the board is invalid: {validate_state(s)}")
        return report()
    if killed(s, "dk1") != DOUBLED:
        fail("K1 doubled", killed(s, "dk1"))
    if killed(s, "dk2") != ["dk2-dk"]:
        fail("K2 opponent's", killed(s, "dk2"))
    if killed(s, "plain1") != ["plain1-dk"]:
        fail("K3 plain death", killed(s, "plain1"))
    gone = copy.deepcopy(s)
    gone["players"]["p1"]["zones"]["base"].remove("kar0")
    gone["players"]["p1"]["zones"]["trash"].append("kar0")
    if killed(gone, "dk1") != ["dk1-dk"]:
        fail("K4 card gone", killed(gone, "dk1"))
    two = board(fields, cards=2)
    if len(killed(two, "dk1")) != 3:
        fail("K5 two cards", killed(two, "dk1"))
    if killed(s, "kar0") != []:
        fail("K6 the card dies", killed(s, "kar0"))
    for order in (("kar0", "dk1"), ("dk1", "kar0")):
        if batch(s, order) != DOUBLED:
            fail("S1 batch, orders", f"{order}: {batch(s, order)}")
        if two_targets(s, order) != DOUBLED:
            fail("S2 one spell", f"{order}: {two_targets(s, order)}")
    after_card = apply_program(s, program([{"op": "kill", "effect_id": "k", "object_id": "kar0"}]))
    if killed(after_card["next_state"], "dk1") != ["dk1-dk"]:
        fail("S3 apart", killed(after_card["next_state"], "dk1"))
    stays = copy.deepcopy(s)
    stays["replacement_effects"] = [{"replacement_id": "keep-kar0", "controller": "p1", "source_object": "kar0",
                                     "mode": "prevent_event", "event_op": "kill", "optional": False,
                                     "uses_remaining": 1, "target_object_id": "kar0"}]
    for order in (("kar0", "dk1"), ("dk1", "kar0")):
        if batch(stays, order) != DOUBLED:
            fail("S4 replaced, stays", f"{order}: {batch(stays, order)}")
    leaves = copy.deepcopy(s)
    leaves["replacement_effects"] = [{"replacement_id": "hand-kar0", "controller": "p1", "source_object": "kar0",
                                      "mode": "replace_with", "event_op": "kill", "optional": False,
                                      "uses_remaining": 1, "target_object_id": "kar0",
                                      "replacement_effects": [{"op": "return_to_hand", "object_id": "kar0"}]}]
    for order in (("kar0", "dk1"), ("dk1", "kar0")):
        got = batch(leaves, order)
        if got != ["dk1-dk"]:
            fail("S5 replaced, gone", f"{order}: {got}")
    for order in (("kar0", "kar1", "dk1"), ("dk1", "kar1", "kar0")):
        got = batch(two, order)
        if got != ["dk1-dk", "dk1-dk#extra:kar0:1", "dk1-dk#extra:kar1:1"]:
            fail("S6 two cards die", f"{order}: {got}")
    if killed(s, "mixed") != ["mixed-die", "mixed-dk", "mixed-dk#extra:kar0:1"]:
        fail("S7 only Deathknell", killed(s, "mixed"))
    for near in ("Your [Deathknell] effects trigger twice.", "Your [Vision] effects trigger an additional time.",
                 "Deathknell effects trigger an additional time."):
        if cg.compile_clause(near, cg.load_grammar()).get("production_id") == lowered.get("production_id"):
            fail("G grammar", f"{near!r} lowered to the row")
    return report()


def report() -> int:
    if errors:
        print("FAILED: Deathknell extra checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'your [Deathknell] effects trigger an additional time' - each of its controller's Deathknell triggers once "
          "more, read from the board as the deaths are noted: not an opponent's, not another death trigger, not once the "
          "card is gone; dying in the same action still counts, in any order, by batch or by one spell; apart it does "
          "not; a replaced death that stays counts, one taken off the board does not (K1-K6, S1-S7, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
