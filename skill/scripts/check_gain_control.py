#!/usr/bin/env python3
"""Taking control of a permanent (package 11, Possession: "Choose an enemy unit at a battlefield. Take control of it and
recall it.").

GPT 2026-10-12 (PACKAGE11 ruling 12): control and ownership are apart; damage, exhaustion and buff stay; an ability already
on the Chain does not change controller (Core 191.5.b); it is recalled to its new controller's Base; taken during a Combat,
the recall takes it out of that Combat. The engine's shape: op gain_control {target, player}; recall reads the current
controller's Base (457).

  P1 resolved      Possession played by p1 choosing p2's e1 at bf1 (2 damage, exhausted, buffed): e1 is p1's, in p1's
                   Base, still damaged, exhausted and buffed; its owner is p2
  P2 owner         that unit killed afterwards goes to its owner's (p2's) trash
  P3 the Chain     an ability of e1's already on the Chain keeps p2 as its controller
  P4 illegal       p1's own unit, or p2's unit in p2's Base, is refused as the choice
  P5 combat        e1 defending in a Combat at bf1: after the spell resolves (its Cleanup synchronizing designations)
                   e1 is in p1's Base with no Combat designation
  P6 its abilities e1's own triggered ability, its Bonus Damage (printed or legacy) and its own Replacement Effect
                   become p1's (Core 191.5.a); another unit's do not
  P7 three points (GPT PACKAGE13 ruling 2) p2's e1 with a Deathknell and an ability that works from its owner's trash:
                   taken by p1, the Deathknell is p1's and the trash ability stays p2's; killed by p1's spell, its
                   Deathknell (made before it moved) is p1's on the Chain, and in p2's trash the card and its abilities
                   are p2's; a later kill wakes its trash ability as p2's (Core 191.5.a, 191.5.a.1, 383.2.c.3)
  V  shape/grammar gain_control without a player does not validate; the card's two sentences lower to gain_control then
                   recall on one decision; near misses do not

    python skill/scripts/check_gain_control.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, bonus_damage, find_location, hash_value,  # noqa: E402
                       materialize_printed_replacements, object_identity, validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []
POSSESSION_TEXT = "Choose an enemy unit at a battlefield. Take control of it and recall it."


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def possession():
    lowered = cg.compile_clause(POSSESSION_TEXT, cg.load_grammar())
    effects = [{**e, "player": "p1"} if e.get("player") == "$controller" else e for e in lowered.get("program_effects") or []]
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "possession-effects", "controller": "p1",
            "effects": effects}


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board():
    """p2's e1 (2 damage, exhausted, buffed) and p1's a1 at bf1; p2's e2 in p2's Base; Possession in p1's hand."""
    state = base_state()
    state["objects"].update({"e1": unit("p2", damage=2, exhausted=True, buffed=True), "a1": unit("p1"), "e2": unit("p2"),
                             "pos": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                     "might_modifiers": [], "damage": 0, "exhausted": False, "play_timing": "action"}})
    state["battlefields"]["bf1"]["objects"] += ["e1", "a1"]
    state["players"]["p2"]["zones"]["base"].append("e2")
    state["players"]["p1"]["zones"]["hand"].append("pos")
    state["players"]["p1"]["resources"] = {"energy": 3, "power": {}}
    return settle_contested(state)


def cast(state, pick, timing=None):
    prog = possession()
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [pick],
         "selection_identities": {pick: object_identity(state, pick)}}]}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-pos", "actor": "p1", "card": "pos",
            "effect_program_id": prog["program_id"],
            "chain_item": {"id": "spell-pos", "object_kind": "spell", "timing": "action"},
            "cost": {"base": {"energy": 3, "power": {}}}, "payment_context": CLOSED}
    played = play_card(timing or fixture(), state, decl, engine_decisions=decisions, effect_program=prog)
    if not played.get("committed"):
        return {"refused": played.get("reason_code") or played.get("reason")}
    t = played["next_timing_state"]
    if next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = finalize_oldest_pending(t)["next_state"]
    for actor in ("p1", "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    effect = played["next_effect_state"]
    return resolve_with_program(t, "spell-pos", effect, prog,
                                engine_decisions={**decisions, "input_hash": hash_value(effect)})


def where(state, oid):
    loc = find_location(state, oid)
    return None if loc is None else (f"{loc[1]}:{loc[2]}" if loc[0] == "player" else loc[1])


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    # P1
    done = cast(s, "e1")
    after = done.get("next_effect_state") or {}
    e1 = (after.get("objects") or {}).get("e1") or {}
    if not done.get("committed") or e1.get("controller") != "p1" or e1.get("owner") != "p2" or where(after, "e1") != "p1:base" \
            or (e1.get("damage"), e1.get("exhausted"), e1.get("buffed")) != (2, True, True):
        fail("P1 resolved", f"{done.get('refused') or done.get('reason') or done.get('reason_code')} "
                            f"{where(after, 'e1') if after else None} {e1}")
    else:
        # P2
        killed = apply_program(after, {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "k",
                                       "controller": "p2", "effects": [{"op": "kill", "effect_id": "k", "object_id": "e1"}]})
        if not killed.get("committed") or where(killed["next_state"], "e1") != "p2:trash":
            fail("P2 owner", f"killed, e1 is at {where(killed.get('next_state') or after, 'e1')}")
    # P3: an ability of e1's on the Chain (as the effect state records it) keeps p2
    on_chain = copy.deepcopy(s)
    on_chain["chain_items"] = {"e1-ability": {"source_object": "e1", "ability_id": "e1-a", "controller": "p2"}}
    took = apply_program(on_chain, {**possession(), "effects": [
        {"op": "gain_control", "effect_id": "gc", "player": "p1", "object_id": "e1"}]})
    if not took.get("committed") or took["next_state"]["chain_items"]["e1-ability"]["controller"] != "p2" \
            or took["next_state"]["objects"]["e1"]["controller"] != "p1":
        fail("P3 the Chain", f"{took.get('reason') or took.get('errors')}")
    # P6: its own abilities follow it
    owned = copy.deepcopy(s)
    owned["objects"]["e1"]["attack_triggers"] = [{"trigger_id": "e1:t", "controller": "p2", "source_object": "e1",
                                                   "controller_order": 0, "effect_program_id": "e1-t",
                                                   "optional_at_finalize": False}]
    owned["objects"]["e2"]["attack_triggers"] = [{**owned["objects"]["e1"]["attack_triggers"][0], "trigger_id": "e2:t",
                                                   "source_object": "e2"}]
    # e1's Bonus Damage both ways a state carries one - printed on it (read live) and a legacy entry (migrated) - and its
    # own Replacement Effect, already in the list; e2's legacy entry stays p2's
    owned["objects"]["e1"]["printed_damage_modifiers"] = [{"amount": 1, "scope": {"kind": "controller_sources"}}]
    owned["objects"]["e1"]["printed_replacements"] = [{"mode": "prevent_event", "event_op": "kill", "optional": False,
                                                       "uses_remaining": None, "target_object_id": "$source_object"}]
    owned["objects"]["e2"]["printed_replacements"] = copy.deepcopy(owned["objects"]["e1"]["printed_replacements"])
    owned["damage_modifiers"] = [{"modifier_id": f"{o}:bonus", "source_object": o, "controller": "p2", "amount": 1,
                                  "scope": {"kind": "controller_sources"}} for o in ("e1", "e2")]
    materialize_printed_replacements(owned)
    before = (bonus_damage(owned, "p1", None)[0], bonus_damage(owned, "p2", None)[0])
    took = apply_program(owned, {**possession(), "effects": [
        {"op": "gain_control", "effect_id": "gc", "player": "p1", "object_id": "e1"}]})
    after = took.get("next_state") or {}
    got = (bonus_damage(after, "p1", None)[0], bonus_damage(after, "p2", None)[0]) if after else None
    if before != (0, 3) or not took.get("committed") or after["objects"]["e1"]["attack_triggers"][0]["controller"] != "p1" \
            or got != (2, 1) or [r["controller"] for r in after["replacement_effects"]] != ["p1", "p2"] \
            or after["objects"]["e2"]["attack_triggers"][0]["controller"] != "p2":
        fail("P6 its abilities", f"{took.get('reason') or took.get('errors')} bonus {before} -> {got} "
                                 f"{after.get('replacement_effects')} {(after.get('objects') or {}).get('e1', {}).get('attack_triggers')}")
    # P7: taken -> its death trigger -> its owner's trash -> a later trigger of it from there (GPT PACKAGE13 ruling 2)
    p7_three_points(s)
    # P4
    for label, pick in (("p1's own unit", "a1"), ("p2's unit in its Base", "e2")):
        got = cast(board(), pick)
        if got.get("committed"):
            fail("P4 illegal", f"{label} ({pick}) was accepted")
    # P5: during a Combat at bf1, e1 defending
    fought = board()
    fought["objects"]["e1"]["combat_designation"] = {"combat_id": "cb1", "role": "defender"}
    fought["objects"]["a1"]["combat_designation"] = {"combat_id": "cb1", "role": "attacker"}
    timing = fixture(showdown=True, focus="p1")
    timing["combat"] = {"combat_id": "cb1", "battlefield": "bf1", "battlefield_identity": "bf1@0", "status": "open",
                        "attacker": "p1", "defender": "p2", "participants": ["p1", "p2"],
                        "triggered_identities": {"attacker": [], "defender": []}}
    timing["showdown"]["battlefield"] = "bf1"
    got = cast(fought, "e1", timing)
    after = got.get("next_effect_state") or {}
    if not got.get("committed") or where(after, "e1") != "p1:base" or "combat_designation" in after["objects"]["e1"]:
        fail("P5 combat", f"{got.get('refused') or got.get('reason') or got.get('reason_code')} "
                          f"{where(after, 'e1') if after else None} {(after.get('objects') or {}).get('e1', {}).get('combat_designation')}")
    # V
    if not validate_program({**possession(), "effects": [{"op": "gain_control", "effect_id": "gc", "object_id": "e1"}]}):
        fail("V shape", "gain_control without a player validated")
    lowered = cg.compile_clause(POSSESSION_TEXT, cg.load_grammar())
    effects = lowered.get("program_effects") or []
    if [e["op"] for e in effects] != ["gain_control", "recall"] \
            or len({(e.get("target") or {}).get("decision_ref") for e in effects}) != 1:
        fail("V grammar", f"{lowered.get('production_id')} {effects}")
    for near in ("Choose an enemy unit. Take control of it and recall it.", "Choose an enemy unit at a battlefield. Recall it."):
        if cg.compile_clause(near, cg.load_grammar()).get("production_id") == lowered.get("production_id"):
            fail("V grammar", f"a near miss lowered: {near}")
    return report()


def p7_three_points(s) -> None:
    """e1 (p2's) carries a Deathknell and a trash watch (Immortal Phoenix's shape: it works from its owner's trash).
    p1 takes it; a p1 spell kills it; later a p1 spell kills p2's e2."""
    board = copy.deepcopy(s)
    deathknell = {"trigger_id": "e1:dk", "controller": "p2", "source_object": "e1", "controller_order": 0,
                  "effect_program_id": "e1-dk", "optional_at_finalize": False}
    watch = {"trigger_id": "e1:trash", "controller": "p2", "source_object": "e1", "controller_order": 0,
             "effect_program_id": "e1-trash", "optional_at_finalize": True, "watch": {"kinds": ["died"], "scope": "any"},
             "functions_from": ["trash"]}
    board["objects"]["e1"]["death_triggers"] = [deathknell]
    board["objects"]["e1"]["event_triggers"] = [watch]
    if validate_state(board):
        fail("P7 three points", f"the board: {validate_state(board)[:2]}")
        return
    took = apply_program(board, {**possession(), "effects": [
        {"op": "gain_control", "effect_id": "gc", "player": "p1", "object_id": "e1"}]})
    taken = took.get("next_state") or {}
    e1 = (taken.get("objects") or {}).get("e1") or {}
    if not took.get("committed") or e1.get("controller") != "p1" or e1["death_triggers"][0]["controller"] != "p1" \
            or e1["event_triggers"][0]["controller"] != "p2":
        fail("P7 three points", f"taken: {took.get('reason') or took.get('errors')} - on the Board its Deathknell is the new "
                                f"controller's, its trash ability its owner's: {e1.get('death_triggers')} {e1.get('event_triggers')}")
        return

    def kill(state, target):
        timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
        return resolve_with_program(timing, "spell-1", state, {"schema_version": PROGRAM_VERSION, "ruleset": RULESET,
                                                                "program_id": "kill-it", "controller": "p1",
                                                                "effects": [{"op": "kill", "effect_id": "k", "object_id": target}]})
    died = kill(taken, "e1")
    after = died.get("next_effect_state") or {}
    chain = {i["id"].split("@")[0]: i.get("controller") for i in (died.get("next_timing_state") or {}).get("chain", {}).get("items", [])}
    dk = next((c for i, c in chain.items() if "dk" in i), None)
    dead = (after.get("objects") or {}).get("e1") or {}
    if not died.get("committed") or dk != "p1" or where(after, "e1") != "p2:trash" or dead.get("controller") != "p2" \
            or dead["death_triggers"][0]["controller"] != "p2":
        fail("P7 three points", f"killed: {died.get('reason_code') or died.get('reason')} chain {chain} - its Deathknell, made "
                                f"before it moved, is p1's; in p2's trash it and its abilities are p2's: "
                                f"{where(after, 'e1')} {dead.get('controller')}")
        return
    # the Chain's items are untouched by its return to its owner
    if any(c not in ("p1", "p2") for c in chain.values()):
        fail("P7 three points", f"a chain item lost its controller: {chain}")
    later = copy.deepcopy(after)
    later["chain_items"] = {}
    again = kill(later, "e2")
    woke = {i["id"].split("@")[0]: i.get("controller") for i in (again.get("next_timing_state") or {}).get("chain", {}).get("items", [])}
    trash = [c for i, c in woke.items() if "trash" in i]
    if not again.get("committed") or trash != ["p2"]:
        fail("P7 three points", f"a later trash trigger: {again.get('reason_code') or again.get('reason')} {woke} - from its owner's "
                                f"trash it is p2's")


def report() -> int:
    if errors:
        print("FAILED: taking control of a permanent")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: Possession takes control of the enemy unit chosen at a Battlefield and recalls it to the new controller's "
          "Base - owner, damage, exhaustion and buff unchanged; its own abilities become the new controller's, those already "
          "on the Chain keep theirs; "
          "killed later it goes to its owner's trash; during a Combat the recall takes it out of the Combat; its Deathknell is the controller's when it dies and its trash ability its owner's (P1-P7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
