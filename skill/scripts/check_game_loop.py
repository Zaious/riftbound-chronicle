#!/usr/bin/env python3
"""Gate: one transition of a game (package 14, C2) - game_loop's dispatch, and the Cleanups a sequence makes outstanding.

On a synthetic catalogue - a Basic Rune with its two abilities (Core 164.2), a 1-Energy unit, a spell whose resolution
makes a delayed trigger, a Battlefield:

  G1 closure     every procedure rules_core.next_procedure can name is dispatched (game_loop.PROCEDURES) or is a
                 player's (DISCRETIONARY); every Core 319 occasion has a clause (CLEANUP_CLAUSES)
  G2 Cleanup     (the counterexample) a Standard Move of a unit to an uncontrolled Battlefield: alone, the Move leaves no
                 Cleanup outstanding and the Battlefield's Showdown waits for some later one; through run_action the
                 Move makes a Cleanup outstanding (319.6/319.8 - the Board changed, an object changed Location) and that
                 Cleanup, the next procedure, stages and opens the Showdown in the same turn (Core 323.7, 323.11)
  G3 runes       a Rune's [E] ability (164.2.a): activated, it is Pending, and the next procedure finalizes and resolves
                 it in one transition (Core 337.2) - 1 Energy in the pool, the Rune exhausted; its "Recycle this"
                 (164.2.b): the Rune goes to the bottom of its owner's Rune Deck (161.2.b) and 1 Power of its Domain is
                 added; a declaration naming another object for "Recycle this" is refused, invalid (204.1.b)
  G4 programs    game_loop.item_program: a card's program by its id; a delayed trigger's from the instruction that made it
                 (the trigger's hash checked by dispatch - an edited instruction is refused by name); a keyword's, the
                 engine's own (Temporary); a play's cost receipt bound for a body that reads it (356.4.f.1)
  G5 order       a Cleanup made outstanding while the Scoring Step waits goes ahead of it (Core 315.2)
  G6 status      (GPT PACKAGE14 ruling 5) 319.7 reads the rules-meaningful statuses (game_loop.STATUS_PROJECTION): a
                 unit exhausted, stunned, buffed, given a control change, a Battlefield contested, a card revealed, a
                 Might changed by a modifier, and (GPT's round-two review) an applied Layer effect that changes no Might
                 or keyword - a unit made a copy of another by the engine's own copy_object (copy_traits: its rules
                 text, its triggered abilities), a gear's Effect Text appended to the unit it is attached to by attach
                 (ability_append) - each is a status change; the engine's own records (identity, modes
                 chosen, control_changed, pending_recall) and marked damage are not, and make no Cleanup. A Cleanup
                 run once more over a settled state adds nothing: no chain item, no trigger, the Showdown as it was

    python skill/scripts/check_game_loop.py
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import closed_environment as CE  # noqa: E402
import combat as CB  # noqa: E402
import effect_ir as IR  # noqa: E402
import game_loop as GL  # noqa: E402
import legal_action as LA  # noqa: E402
import play_space as PS  # noqa: E402
import resolution_bridge as RB  # noqa: E402
import rules_core as RC  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, RULE_NUMBERING  # noqa: E402

errors: list[str] = []


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


RUNE_ROWS = {"exhaust": {"cost": {"energy": 0, "power": {}, "exhaust": True}, "effect_program_id": "add_energy",
                         "timing": "reaction", "ability_kind": "add"},
             "recycle": {"cost": {"energy": 0, "power": {}, "additional": [
                 {"cost_id": "recycle-self", "mandatory": True, "payment": {"kind": "recycle_self", "object_id": "$source_object"}}]},
                 "effect_program_id": "add_power", "timing": "reaction", "ability_kind": "add"}}
DELAYED = {"op": "create_delayed_trigger", "effect_id": "later",
           "delayed": {"delayed_id": "later", "controller": "$controller", "source_object": "$source_object",
                       "controller_order": 0, "optional_at_finalize": False, "effect_program_id": "later-effects",
                       "waits_for": {"kind": "turn", "moment": "end_of_turn", "turn": "this_turn"}},
           "effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1}]}


def catalogue() -> dict:
    value = {
        "schema_version": CE.CATALOGUE_VERSION,
        "environment": {"format": "1v1", "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING,
                        "card_pool": "synthetic"},
        "cards": {
            "Fury Rune": {"object": {"kind": "rune", "domains": ["fury"]}, "activated_abilities": copy.deepcopy(RUNE_ROWS),
                          "programs": {"add_energy": {"effects": [{"op": "add_resource", "effect_id": "add", "player": "$controller",
                                                                   "resource": "energy", "amount": 1}]},
                                       "add_power": {"effects": [{"op": "add_resource", "effect_id": "add", "player": "$controller",
                                                                  "resource": "power", "domain": "fury", "amount": 1}]}}},
            "Grunt": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 2, "domains": ["fury"]}},
            "Later": {"object": {"kind": "spell", "printed_cost": {"energy": 0, "power": {}}, "domains": ["fury"]},
                      "programs": {"play": {"effects": [DELAYED]}}},
            "Field": {"object": {"kind": "battlefield"}},
        },
        "catalogue_hash": "",
    }
    value["catalogue_hash"] = CE.catalogue_hash(value)
    return value


def environment(cat: dict, placed: list[tuple[str, str, str, str]]) -> dict:
    state = {"schema_version": "riftbound-effect-state.v1", "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
             "players": {p: {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [],
                                       "rune_deck": [], "champion_zone": []},
                             "resources": {"energy": 0, "power": {}}, "points": 0} for p in ("p1", "p2")},
             "objects": {}, "battlefields": {"bf1": CE.place_battlefield(cat, "Field", "bf1")},
             "replacement_effects": [], "mode": {"victory_score": 8}, "turn_id": "turn-1"}
    state["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": []}
    for object_id, ref, owner, zone in placed:
        state["objects"][object_id] = CE.place(cat, ref, owner=owner, object_id=object_id)
        if zone == "bf1":
            state["battlefields"]["bf1"]["objects"].append(object_id)
        else:
            state["players"][owner]["zones"][zone].append(object_id)
    return state


def g1_closure() -> None:
    source = (SCRIPT_DIR / "rules_core.py").read_text(encoding="utf-8")
    named = set(re.findall(r'procedure="([a-z_]+)"', source))
    handled = set(GL.PROCEDURES) | GL.DISCRETIONARY
    if not named or named - handled:
        fail("G1 closure", f"procedures next_procedure names that game_loop neither dispatches nor gives a player: "
                           f"{sorted(named - handled)}")
    clauses = {r.split(".")[0] + "." + r.split(".")[1] for r in GL.CLEANUP_CLAUSES}
    if clauses != {f"319.{n}" for n in range(1, 9)}:
        fail("G1 closure", f"Core 319's eight occasions are not all read: {sorted(clauses)}")


def g2_cleanup(cat: dict) -> None:
    effect = environment(cat, [("u1", "Grunt", "p1", "base")])
    timing = fixture()
    move = LA.standard_move_declaration(effect, "p1", ["u1"], {"kind": "battlefield", "battlefield": "bf1"})
    alone = CB.standard_move(timing, effect, move)
    if not alone.get("committed"):
        fail("G2 Cleanup", f"the Move itself was refused: {alone.get('reason_code')} {alone.get('reason')}")
        return
    if RC.CLEANUP_TASK in alone["next_timing_state"]["outstanding_tasks"]:
        fail("G2 Cleanup", "the Move alone made a Cleanup outstanding - the counterexample no longer shows the gap")
    if RC.next_procedure(alone["next_timing_state"]).get("discretionary_actions_allowed") is not True:
        fail("G2 Cleanup", "after the Move alone the game is not at an action point - the counterexample changed")
    step = GL.run_action(timing, effect, cat, {"kind": "standard_move", "declaration": move, "actor": "p1"})
    if not step["committed"] or not {"319.6", "319.8"} & set(step["cleanup"]) \
            or RC.CLEANUP_TASK not in step["next_timing_state"]["outstanding_tasks"]:
        fail("G2 Cleanup", f"through run_action the Move made no Cleanup outstanding: {step['cleanup']} "
                           f"{(step.get('next_timing_state') or {}).get('outstanding_tasks')}")
        return
    if RC.next_procedure(step["next_timing_state"]).get("procedure") != "handle_outstanding_tasks":
        fail("G2 Cleanup", "the Cleanup is not the next procedure")
    cleaned = GL.run_procedure(step["next_timing_state"], step["next_effect_state"], cat)
    t = (cleaned.get("next_timing_state") or {})
    if not cleaned["committed"] or not (t.get("showdown") or {}).get("active") or (t.get("showdown") or {}).get("battlefield") != "bf1":
        fail("G2 Cleanup", f"the Cleanup did not stage and open the Showdown at bf1 this turn: {cleaned['label']} "
                           f"{t.get('showdown')} {t.get('staged_showdowns')}")


def _activate(cat: dict, effect: dict, ability: str) -> dict:
    skeleton = next(d for d, _ in PS.ability_skeletons(effect, cat, "p1") if d["activation"]["ability_id"] == ability)
    return skeleton


def g3_runes(cat: dict) -> None:
    effect = environment(cat, [("r1", "Fury Rune", "p1", "base"), ("r2", "Fury Rune", "p1", "rune_deck")])
    timing = fixture()
    declaration = _activate(cat, effect, "r1:exhaust")
    step = GL.run_action(timing, effect, cat, {"kind": "activate_ability", "declaration": declaration})
    if not step["committed"]:
        fail("G3 runes", f"[E]: Add [1] was refused: {step['result'].get('reason_code')} {step['result'].get('reason')}")
        return
    t, e = step["next_timing_state"], step["next_effect_state"]
    for _ in range(4):
        if RC.next_procedure(t).get("discretionary_actions_allowed"):
            break
        nxt = GL.run_procedure(t, e, cat)
        if not nxt["committed"]:
            fail("G3 runes", f"{nxt['label']} refused: {(nxt['result'] or {}).get('reason')}")
            return
        t, e = nxt["next_timing_state"], nxt["next_effect_state"]
    if e["players"]["p1"]["resources"]["energy"] != 1 or not e["objects"]["r1"]["exhausted"] or t["chain"]["items"]:
        fail("G3 runes", f"after the [E] ability: energy {e['players']['p1']['resources']['energy']}, exhausted "
                         f"{e['objects']['r1']['exhausted']}, chain {t['chain']['items']}")
    declaration = _activate(cat, effect, "r1:recycle")
    step = GL.run_action(timing, effect, cat, {"kind": "activate_ability", "declaration": declaration})
    t, e = (step.get("next_timing_state"), step.get("next_effect_state")) if step["committed"] else (None, None)
    while t is not None and not RC.next_procedure(t).get("discretionary_actions_allowed"):
        nxt = GL.run_procedure(t, e, cat)
        t, e = (nxt["next_timing_state"], nxt["next_effect_state"]) if nxt["committed"] else (None, None)
    if t is None or e["players"]["p1"]["zones"]["rune_deck"] != ["r2", "r1"] or "r1" in e["players"]["p1"]["zones"]["base"] \
            or e["players"]["p1"]["resources"]["power"].get("fury") != 1:
        fail("G3 runes", f"'Recycle this: Add [C]' did not recycle the Rune to its deck's bottom and add a fury Power: "
                         f"{(step['result'] or {}).get('reason')} {e and e['players']['p1']}")
    other = copy.deepcopy(declaration)
    other["cost"]["additional"][0]["payment"]["object_id"] = "r2"
    refused = GL.run_action(timing, effect, cat, {"kind": "activate_ability", "declaration": other})
    if refused["committed"]:
        fail("G3 runes", "'Recycle this' naming another object was accepted against the catalogued row")
    # and the payment itself, the catalogued row aside (an uncatalogued object's row): refused as invalid (204.1.b)
    loose = copy.deepcopy(effect)
    loose["objects"]["r1"].pop("card_ref")
    direct = GL.PT.play_card(timing, loose, other, effect_program=GL.action_program(cat, loose, other))
    if direct.get("committed") or direct.get("valid") is not False:
        fail("G3 runes", f"the payment took 'Recycle this' of another object: {direct.get('reason_code')} {direct.get('reason')}")


def g4_programs(cat: dict) -> None:
    effect = environment(cat, [("s1", "Later", "p1", "trash"), ("u1", "Grunt", "p1", "base")])
    item = {"id": "item:s1", "controller": "p1", "object_kind": "spell", "effect_program_id": "Later#play",
            "status": "finalized", "timing": "default"}
    effect["chain_items"] = {"item:s1": {"card": "s1", "controller": "p1",
                                         "cost_receipt": {"components": [{"cost_id": "x"}]}}}
    program = GL.item_program(cat, effect, item)
    if program is None or program["program_id"] != "Later#play" or program["source_object"] != "s1":
        fail("G4 programs", f"a card's program was not found by its id: {program and program.get('program_id')}")
    bound = IR.apply_program({k: v for k, v in effect.items() if k != "chain_items"}, program)
    delayed = (bound.get("next_state") or {}).get("delayed_triggers") or []
    trigger = {"id": "later-item", "controller": "p1", "source_object": "s1", "effect_program_id": "later-effects",
               "effect_program_hash": (delayed[0] if delayed else {}).get("effect_program_hash"), "timing": "triggered"}
    found = GL.item_program(cat, effect, trigger)
    if not delayed or found is None or RB.dispatch_program({found["program_id"]: found}, trigger)[1] is not None:
        fail("G4 programs", f"a delayed trigger's program was not the instruction's own: {found and found.get('effects')}")
    edited = copy.deepcopy(cat)
    edited["cards"]["Later"]["programs"]["play"]["effects"][0]["effects"][0]["count"] = 2
    changed = GL.item_program(edited, effect, trigger)
    refusal = RB.dispatch_program({changed["program_id"]: changed}, trigger)[1] if changed else None
    if not refusal or refusal.get("reason") != "effect_program_hash_mismatch":
        fail("G4 programs", f"an edited delayed instruction was not refused by its hash: {refusal}")
    effect["objects"]["u1"].setdefault("keywords", []).append("temporary")
    keyword = GL.item_program(cat, effect, {"id": "u1:temporary", "controller": "p1", "source_object": "u1",
                                            "effect_program_id": f"{IR.TEMPORARY_PROGRAM_PREFIX}:u1"})
    if keyword is None or keyword != IR.temporary_program(effect, "u1", "p1"):
        fail("G4 programs", "Temporary's program is not the engine's own")
    reading = copy.deepcopy(cat)
    reading["cards"]["Later"]["programs"]["play"]["effects"] = [
        {"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1,
         "predicate": {"kind": "cost_paid", "cost_id": "x", "cost_offer_id": "x"}}]
    receipt_bound = GL.item_program(reading, effect, item)
    if (receipt_bound or {}).get("cost_receipt") != effect["chain_items"]["item:s1"]["cost_receipt"]:
        fail("G4 programs", "a body reading its play's receipt was not given the receipt kept on the chain entry")


def g5_order(cat: dict) -> None:
    effect = environment(cat, [("u1", "Grunt", "p1", "base")])
    t0 = {**fixture(priority=None, tasks=["scoring_step"]), "phase": "beginning"}
    t1 = copy.deepcopy(t0)
    e1 = copy.deepcopy(effect)
    e1["objects"]["u1"]["exhausted"] = True     # a status changed (319.7)
    step = GL._step("procedure", "resolve:ability", t0, effect, {}, True, t1, e1)
    if step["next_timing_state"]["outstanding_tasks"] != ["cleanup", "scoring_step"]:
        fail("G5 order", f"the Cleanup was not put ahead of the Scoring Step: {step['next_timing_state']['outstanding_tasks']}")


def g6_status(cat: dict) -> None:
    effect = environment(cat, [("u1", "Grunt", "p1", "base"), ("u2", "Grunt", "p2", "base")])
    t = fixture()
    real = {"exhausted": lambda e: e["objects"]["u1"].update(exhausted=True),
            "stunned": lambda e: e["objects"]["u1"].update(stunned=True),
            "buffed": lambda e: e["objects"]["u1"].update(buffed=True),
            "controller": lambda e: e["objects"]["u1"].update(controller="p2"),
            "contested": lambda e: e["battlefields"]["bf1"].update(contested=True, contested_by="p1"),
            "revealed": lambda e: e.setdefault("reveals", []).append({"object_id": "u1", "zone": "base", "visible_to": "all"}),
            "might": lambda e: e["objects"]["u1"]["might_modifiers"].append({"amount": 1, "source": "test", "duration": "permanent"})}
    death = [{"trigger_id": "u2:dies", "controller": "p2", "source_object": "u2", "controller_order": 0,
              "effect_program_id": "dies", "optional_at_finalize": False}]

    def copied(e):
        e["objects"]["u2"]["death_triggers"] = copy.deepcopy(death)
        return IR.apply_program(e, {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                                    "program_id": "copy", "controller": "p1",
                                    "effects": [{"op": "copy_object", "effect_id": "cp", "object_id": "u1", "source_object": "u2",
                                                 "request_id": "copy", "traits": ["rules_text"]}]})["next_state"]

    def attached(e):
        e["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False,
                              "death_triggers": [{**death[0], "trigger_id": "g1:dies", "controller": "p1", "source_object": "g1"}]}
        e["players"]["p1"]["zones"]["base"].append("g1")
        return IR.apply_program(e, {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                                    "program_id": "attach", "controller": "p1",
                                    "effects": [{"op": "attach", "effect_id": "at", "object_id": "g1", "to": "u1"}]})["next_state"]
    for label, make in (("copy_traits", copied), ("ability_append", attached)):
        after = make(copy.deepcopy(effect))
        if after is None or IR.validate_state(after):
            fail("G6 status", f"the {label} board is not a valid state: {after and IR.validate_state(after)[:2]}")
            continue
        made = [c for c in after.get("continuous_effects") or [] if c.get("kind") == label]
        if len(made) != 1:
            fail("G6 status", f"the engine made no single {label} continuous effect: {len(made)}")
            continue
        # the same board, the Layer effect alone taken away: the only difference is the applied Layer effect
        before = copy.deepcopy(after)
        before["continuous_effects"] = [c for c in after["continuous_effects"] if c is not made[0] and c != made[0]]
        if "319.7" not in GL.cleanup_clauses(t, before, t, after):
            fail("G6 status", f"an applied {label} Layer effect was not read as a status change")
    internal = {"identity": lambda e: e["objects"]["u1"].update(identity="u1@0"),
                "modes_chosen": lambda e: e["objects"]["u1"].update(modes_chosen=["m1"]),
                "control_changed": lambda e: e["objects"]["u1"].update(control_changed=True),
                "pending_recall": lambda e: e["objects"]["u1"].update(pending_recall=True),
                "damage": lambda e: e["objects"]["u1"].update(damage=1)}
    for label, change in real.items():
        e1 = copy.deepcopy(effect)
        change(e1)
        if "319.7" not in GL.cleanup_clauses(t, effect, t, e1):
            fail("G6 status", f"a {label} change was not read as a status change")
    for label, change in internal.items():
        e1 = copy.deepcopy(effect)
        change(e1)
        clauses = GL.cleanup_clauses(t, effect, t, e1)
        if clauses:
            fail("G6 status", f"the engine's own {label} field made a Cleanup outstanding: {clauses}")
    # an extra Cleanup over a settled state (G2's, the Showdown open) adds nothing
    moved = GL.run_action(fixture(), effect, cat, {"kind": "standard_move", "actor": "p1",
                                                   "declaration": LA.standard_move_declaration(effect, "p1", ["u1"], {"kind": "battlefield", "battlefield": "bf1"})})
    cleaned = GL.run_procedure(moved["next_timing_state"], moved["next_effect_state"], cat)
    if not cleaned["committed"]:
        fail("G6 status", "the Move's Cleanup did not commit")
        return
    t2, e2 = copy.deepcopy(cleaned["next_timing_state"]), cleaned["next_effect_state"]
    t2["outstanding_tasks"] = list(t2["outstanding_tasks"]) + [RC.CLEANUP_TASK]
    again = GL.run_procedure(t2, e2, cat)
    if not again["committed"] or again["next_timing_state"]["chain"] != cleaned["next_timing_state"]["chain"] \
            or again["next_timing_state"]["showdown"] != cleaned["next_timing_state"]["showdown"] \
            or IR.hash_value(again["next_effect_state"]) != IR.hash_value(e2):
        fail("G6 status", "a Cleanup run once more over a settled state changed something or raised a trigger")


def main() -> int:
    cat = catalogue()
    if CE.validate_catalogue(cat):
        fail("catalogue", str(CE.validate_catalogue(cat)[:3]))
    g1_closure()
    g2_cleanup(cat)
    g3_runes(cat)
    g4_programs(cat)
    g5_order(cat)
    g6_status(cat)
    if errors:
        print("FAILED: game loop checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: every procedure next_procedure names is dispatched or a player's; a Move that changes the Board makes a "
          "Cleanup outstanding and the Showdown opens this turn (the Move alone leaves it waiting); a Rune's [E] and "
          "'Recycle this' add their resource in the transition that finalizes them, and 'Recycle this' names only its "
          "source; programs are found by id, a delayed trigger's by its instruction under its hash, a keyword's from the "
          "engine, a receipt-reading body with its receipt; a Cleanup goes ahead of a waiting Scoring Step; 319.7 reads the rules' statuses, not the engine's own records, "
          "and an extra Cleanup adds nothing (G1-G6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
