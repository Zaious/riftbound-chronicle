#!/usr/bin/env python3
"""Taking control of a permanent (package 11, Possession: "Choose an enemy unit at a battlefield. Take control of it and
recall it.").

GPT 2026-10-12 (PACKAGE11 ruling 12): control and ownership are apart; damage, exhaustion and buff stay; an ability already
on the Chain does not change controller (Core 191.4.b); it is recalled to its new controller's Base; taken during a Combat,
the recall takes it out of that Combat. The engine's shape: op gain_control {target, player}; recall reads the current
controller's Base (455).

  P1 resolved      Possession played by p1 choosing p2's e1 at bf1 (2 damage, exhausted, buffed): e1 is p1's, in p1's
                   Base, still damaged, exhausted and buffed; its owner is p2
  P2 owner         that unit killed afterwards goes to its owner's (p2's) trash
  P3 the Chain     an ability of e1's already on the Chain keeps p2 as its controller
  P4 illegal       p1's own unit, or p2's unit in p2's Base, is refused as the choice
  P5 combat        e1 defending in a Combat at bf1: after the spell resolves (its Cleanup synchronizing designations)
                   e1 is in p1's Base with no Combat designation
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
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, find_location, hash_value,  # noqa: E402
                       object_identity, validate_program, validate_state)
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


def report() -> int:
    if errors:
        print("FAILED: taking control of a permanent")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: Possession takes control of the enemy unit chosen at a Battlefield and recalls it to the new controller's "
          "Base - owner, damage, exhaustion and buff unchanged; its abilities already on the Chain keep their controller; "
          "killed later it goes to its owner's trash; during a Combat the recall takes it out of the Combat (P1-P5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
