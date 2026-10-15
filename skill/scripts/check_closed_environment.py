#!/usr/bin/env python3
"""Gate: the closed environment's catalogue - its shape, its objects, its programs, its state check (package 13, C2).

On a synthetic catalogue of three cards (a targeting spell, a unit with an activated ability, a rune):

  E1 shape       the catalogue validates and hashes; another Core, a spell with no play program, a record carrying
                 game state or state-level lists, an ability or a trigger whose program the card does not have, a token
                 a program makes that the catalogue's tokens do not record so, a
                 trigger with a fixed controller or order, a printed replacement counting its uses, or a stale hash,
                 does not
  E2 objects     a placed object carries card_ref, its printed fields and its abilities (ids namespaced by the object,
                 programs by the card), its triggers bound to it and its controller; a Battlefield's own reference is
                 bound to its id; two copies' printed replacements materialize apart; a state of placed objects
                 validates
  E3 programs    a program is bound - every symbol replaced, none left - and an unbound symbol is refused
  E4 the state   a state of placed objects is a state of the environment; an object with no card_ref, a card_ref the
                 catalogue lacks, an edited printed cost, keyword or ability row, a field added or dropped, a card the
                 catalogue says is not fully assembled, a Battlefield with no card_ref or an edited Facedown capacity, a
                 legacy list entry, a printed replacement missing, extra, or kept for a card off the Board, a trigger
                 left with a former controller, or a third player, is named; an entry a play added (Accelerate) is not
                 an edit, nor a permanent whose control changed with its abilities (follow_controller); a token the
                 catalogue does not make or an edited one is named, and the token play_token makes is the catalogue's
  E5 end to end  the placed unit's ability, declared from its row and run with its bound program, is played; the same
                 declaration at another cost is refused as not catalogued

    python skill/scripts/check_closed_environment.py
"""
from __future__ import annotations

import copy
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
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, RULE_NUMBERING, follow_controller, hash_value,  # noqa: E402
                       materialize_printed_replacements, validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, EXHAUST_SELF_COST_ID, play_card  # noqa: E402

errors: list[str] = []


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def catalogue() -> dict:
    value = {
        "schema_version": CE.CATALOGUE_VERSION,
        "environment": {"format": "1v1", "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING,
                        "card_pool": "synthetic"},
        "cards": {
            "Test Spell": {"object": {"kind": "spell", "printed_cost": {"energy": 1, "power": {}}, "domains": ["fury"]},
                           "programs": {"play": {"effects": [{"op": "draw", "effect_id": "dr", "player": "$controller",
                                                              "count": 1}]}}},
            "Test Unit": {"object": {"kind": "unit", "printed_cost": {"energy": 2, "power": {}}, "base_might": 2,
                                     "domains": ["calm"], "keywords": ["ganking"],
                                     "ability_conditions": {"a2": {"kind": "another_card_finalized_this_turn"}},
                                     "entry_replacements": [{"mode": "entry_state", "value": "exhausted"}],
                                     "attack_triggers": [{"trigger_id": "t1", "controller": "$controller",
                                                          "source_object": "$source_object", "controller_order": 0,
                                                          "effect_program_id": "t1", "optional_at_finalize": False}]},
                          "activated_abilities": {"a1": {"cost": {"energy": 1, "power": {}, "exhaust": True},
                                                         "effect_program_id": "a1"},
                                                  "a2": {"cost": {"energy": 0, "power": {}, "additional": [
                                                      {"cost_id": "text-cost", "mandatory": True,
                                                       "payment": {"kind": "spend_buff", "object_id": "$source_object"}}]},
                                                         "effect_program_id": "a1"}},
                          "programs": {"a1": {"effects": [{"op": "draw", "effect_id": "dr", "player": "$controller",
                                                           "count": 1}]},
                                       "tok": {"effects": [{"op": "play_token", "effect_id": "tk", "owner": "$controller",
                                                            "controller": "$controller", "token_kind": "unit",
                                                            "base_might": 1, "token_id": "recruit", "tags": ["Recruit"],
                                                            "object_id_ref": {"kind": "fresh"},
                                                            "destination": {"kind": "base", "player": "$controller"}}]},
                                       "t1": {"effects": [{"op": "reveal", "effect_id": "rv", "player": "$controller",
                                                           "from": "rune_deck_top", "count": 1}],
                                              "conditional_triggers": [{"trigger_id": "b1", "controller": "$controller",
                                                                        "source_object": "$source_object",
                                                                        "controller_order": 0, "effect_program_id": "b1",
                                                                        "optional_at_finalize": False,
                                                                        "condition": {"kind": "revealed_domain",
                                                                                      "effect_id": "rv", "domain": "fury"}}]},
                                       "b1": {"effects": [{"op": "draw", "effect_id": "dr", "player": "$controller",
                                                           "count": 1}]}}},
            "Test Rune": {"object": {"kind": "rune", "domains": ["fury"]}},
            "Test Field": {"object": {"kind": "battlefield", "facedown": {"capacity": 2, "cards": []},
                                      "printed_damage_modifiers": [{"amount": 1, "scope": {"kind": "location",
                                                                                           "battlefield": "$source_object"}}],
                                      "conquer_triggers": [{"trigger_id": "t1", "controller_order": 0,
                                                            "effect_program_id": "t1", "optional_at_finalize": False}],
                                      "move_from_triggers": [{"trigger_id": "t2", "controller_order": 0,
                                                              "effect_program_id": "t1", "optional_at_finalize": False}]},
                           "programs": {"t1": {"effects": [{"op": "draw", "effect_id": "dr", "player": "$controller",
                                                            "count": 1}]}}},
            "Test Aura": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1,
                                     "printed_damage_modifiers": [{"amount": 1, "scope": {"kind": "controller_sources"}}],
                                     "printed_replacements": [{"mode": "prevent_event", "event_op": "kill", "optional": False,
                                                               "uses_remaining": None, "target_object_id": "$source_object"}]}},
            "Test Half": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1},
                          "incomplete": ["the trigger 'When I attack' is not assembled"]},
        },
        "tokens": {"recruit": {"kind": "unit", "base_might": 1, "keywords": [], "tags": ["Recruit"]}},
        "catalogue_hash": "",
    }
    value["catalogue_hash"] = CE.catalogue_hash(value)
    return value


REFS = {"c1": "Test Spell", "c2": "Test Spell", "c3": "Test Spell", "c4": "Test Spell", "u1": "Test Unit",
        "u2": "Test Unit", "r1": "Test Rune"}


def placed_state(cat: dict) -> dict:
    state = base_state()
    for object_id, ref in REFS.items():
        old = state["objects"][object_id]
        obj = CE.place(cat, ref, owner=old["owner"], object_id=object_id)
        obj["exhausted"] = old.get("exhausted", False)
        state["objects"][object_id] = obj
    for battlefield_id in list(state["battlefields"]):
        state["battlefields"][battlefield_id] = {**CE.place_battlefield(cat, "Test Field", battlefield_id),
                                                 **{k: v for k, v in state["battlefields"][battlefield_id].items()
                                                    if k in CE.BATTLEFIELD_DYNAMIC}}
    state["objects"]["a1"] = CE.place(cat, "Test Aura", owner="p1", object_id="a1")
    state["players"]["p1"]["zones"]["base"].append("a1")
    state["objects"]["a2"] = CE.place(cat, "Test Aura", owner="p1", object_id="a2")
    state["players"]["p1"]["zones"]["base"].append("a2")
    # a Recruit token, as play_token makes it
    state["objects"]["tk"] = {"owner": "p1", "controller": "p1", "kind": "unit", "is_token": True, "base_might": 1,
                              "might_modifiers": [], "damage": 0, "exhausted": True, "keywords": [], "identity": "tk@0",
                              "token_id": "recruit", "tags": ["Recruit"]}
    state["players"]["p1"]["zones"]["base"].append("tk")
    materialize_printed_replacements(state)
    return state


def main() -> int:
    cat = catalogue()
    # E1
    if CE.validate_catalogue(cat):
        fail("E1 shape", f"the catalogue does not validate: {CE.validate_catalogue(cat)}")
        return report()
    for label, change in (
            ("another Core", lambda c: c["environment"].update(core="2026-07-16")),
            ("a spell with no play program", lambda c: c["cards"]["Test Spell"].update(programs={})),
            ("a record carrying game state", lambda c: c["cards"]["Test Unit"]["object"].update(damage=1)),
            ("a record carrying a play-bound entry", lambda c: c["cards"]["Test Unit"]["object"]["entry_replacements"].append(
                {"mode": "entry_state", "value": "ready", "chain_item": "unit-1"})),
            ("a record carrying state lists", lambda c: c["cards"]["Test Aura"].update(state_lists={"damage_modifiers": []})),
            ("a trigger with a fixed controller", lambda c: c["cards"]["Test Unit"]["object"]["attack_triggers"][0].update(
                controller="p1")),
            ("a trigger with a fixed order", lambda c: c["cards"]["Test Unit"]["object"]["attack_triggers"][0].update(
                controller_order=1)),
            ("a trigger with a missing program", lambda c: c["cards"]["Test Unit"]["object"]["attack_triggers"][0].update(
                effect_program_id="nope")),
            ("a Battlefield's move-from trigger with a source", lambda c: c["cards"]["Test Field"]["object"]["move_from_triggers"][0].update(
                source_object="$source_object")),
            ("a Battlefield trigger with a controller", lambda c: c["cards"]["Test Field"]["object"]["conquer_triggers"][0].update(
                controller="$controller")),
            ("a conditional trigger running a missing program", lambda c: c["cards"]["Test Unit"]["programs"]["t1"][
                "conditional_triggers"][0].update(effect_program_id="nope")),
            ("a conditional trigger with a fixed controller", lambda c: c["cards"]["Test Unit"]["programs"]["t1"][
                "conditional_triggers"][0].update(controller="p1")),
            ("a token the catalogue does not record", lambda c: c["tokens"].pop("recruit")),
            ("a token recorded otherwise", lambda c: c["tokens"]["recruit"].update(base_might=2)),
            ("a replacement counting its uses", lambda c: c["cards"]["Test Aura"]["object"]["printed_replacements"][0].update(
                uses_remaining=1)),
            ("an ability with a missing program", lambda c: c["cards"]["Test Unit"]["activated_abilities"]["a1"].update(effect_program_id="nope")),
            ("a stale hash", lambda c: c["cards"]["Test Spell"]["object"].update(printed_cost={"energy": 0, "power": {}}))):
        bad = copy.deepcopy(cat)
        change(bad)
        if label != "a stale hash":
            bad["catalogue_hash"] = CE.catalogue_hash(bad)
        if not CE.validate_catalogue(bad):
            fail("E1 shape", f"{label} validated")
    # E2
    state = placed_state(cat)
    if validate_state(state):
        fail("E2 objects", f"a state of placed objects does not validate: {validate_state(state)[:2]}")
        return report()
    unit = state["objects"]["u1"]
    if unit.get("card_ref") != "Test Unit" or unit.get("printed_cost") != {"energy": 2, "power": {}} \
            or set(unit.get("activated_abilities") or {}) != {"u1:a1", "u1:a2"} \
            or unit["activated_abilities"]["u1:a2"]["cost"]["additional"][0]["payment"]["object_id"] != "u1" \
            or set(unit.get("ability_conditions") or {}) != {"u1:a2"} \
            or unit["activated_abilities"]["u1:a1"]["effect_program_id"] != "Test Unit#a1" \
            or unit["attack_triggers"] != [{"trigger_id": "u1:t1", "controller": "p1", "source_object": "u1",
                                            "controller_order": 0, "effect_program_id": "Test Unit#t1",
                                            "optional_at_finalize": False}]:
        fail("E2 objects", f"the placed unit is not its record: {unit}")
    if state["battlefields"]["bf1"]["conquer_triggers"] != [{"trigger_id": "bf1:t1", "controller_order": 0,
                                                             "effect_program_id": "Test Field#t1", "optional_at_finalize": False}]:
        fail("E2 objects", f"the Battlefield's trigger was not bound to it: {state['battlefields']['bf1'].get('conquer_triggers')}")
    if state["battlefields"]["bf1"]["printed_damage_modifiers"][0]["scope"] != {"kind": "location", "battlefield": "bf1"}:
        fail("E2 objects", f"the Battlefield's own reference was not bound: {state['battlefields']['bf1']}")
    replacements = [(r["replacement_id"], r["source_object"], r["target_object_id"]) for r in state["replacement_effects"]]
    if replacements != [("a1:printed:0", "a1", "a1"), ("a2:printed:0", "a2", "a2")]:
        fail("E2 objects", f"two copies' printed replacements did not materialize apart: {replacements}")
    # E3
    bindings = {"$controller": "p1", "$opponent": "p2", "$chain_item": "ability-1", "$source_object": "u1", "$card": "u1"}
    program = CE.instantiate_program(cat, "Test Unit", "a1", bindings)
    if program["effects"][0]["player"] != "p1" or "$" in str(program) or program["program_id"] != "Test Unit#a1":
        fail("E3 programs", f"the program was not bound: {program}")
    branching = CE.instantiate_program(cat, "Test Unit", "t1", bindings)
    if [(c["trigger_id"], c["controller"], c["source_object"], c["effect_program_id"])
            for c in branching.get("conditional_triggers") or []] != [("u1:b1", "p1", "u1", "Test Unit#b1")] \
            or "$" in str(branching) or validate_program(branching):
        fail("E3 programs", f"a program's conditional triggers were not bound: {branching} {validate_program(branching)[:2]}")
    try:
        CE.instantiate_program(cat, "Test Unit", "a1", {k: v for k, v in bindings.items() if k != "$opponent"})
        fail("E3 programs", "a program was instantiated with a symbol unbound")
    except ValueError:
        pass
    # E4
    if CE.environment_problems(state, cat):
        fail("E4 the state", f"a state of placed objects has problems: {CE.environment_problems(state, cat)}")
    for label, change, says in (
            ("no card_ref", lambda s: s["objects"]["c1"].pop("card_ref"), "carries no card_ref"),
            ("an unknown card", lambda s: s["objects"]["c1"].update(card_ref="Nope"), "does not have"),
            ("an edited cost", lambda s: s["objects"]["c1"].update(printed_cost={"energy": 0, "power": {}}), "printed_cost"),
            ("an added keyword", lambda s: s["objects"]["u2"].update(keywords=["ganking", "shield"]), "keywords"),
            ("an edited ability", lambda s: s["objects"]["u1"]["activated_abilities"]["u1:a1"]["cost"].update(energy=0),
             "activated_abilities"),
            ("an added field", lambda s: s["objects"]["u2"].update(play_permissions=[{"zone": "trash"}]), "play_permissions"),
            ("a dropped field", lambda s: s["objects"]["c1"].pop("domains"), "domains"),
            ("a dropped printed entry", lambda s: s["objects"]["u1"].update(entry_replacements=[]), "entry_replacements"),
            ("a Battlefield with no card_ref", lambda s: s["battlefields"]["bf1"].pop("card_ref"), "Battlefield bf1 carries no card_ref"),
            ("an edited Facedown capacity", lambda s: s["battlefields"]["bf1"].update(facedown={"capacity": 3, "cards": []}),
             "facedown_capacity"),
            ("a legacy list entry", lambda s: s.update(damage_modifiers=[{"modifier_id": "x", "source_object": "a1",
                                                                          "controller": "p1", "amount": 5,
                                                                          "scope": {"kind": "controller_sources"}}]),
             "damage_modifiers"),
            ("a missing replacement", lambda s: s["replacement_effects"].pop(), "replacement_effects"),
            ("an extra replacement", lambda s: s["replacement_effects"].append(
                {**s["replacement_effects"][0], "replacement_id": "u1:own", "source_object": "u1", "target_object_id": "u1"}),
             "replacement_effects"),
            ("a replacement of a card off the board", lambda s: (s["players"]["p1"]["zones"]["base"].remove("a1"),
                                                                  s["players"]["p1"]["zones"]["hand"].append("a1")),
             "replacement_effects"),
            ("a trigger left with a former controller", lambda s: s["objects"]["u1"].update(controller="p2"),
             "attack_triggers"),
            ("a card not fully assembled", lambda s: s["objects"].update(
                c1={**CE.place(cat, "Test Half", owner="p1", object_id="c1")}), "not fully assembled"),
            ("a third player", lambda s: s["players"].update(p3=copy.deepcopy(s["players"]["p2"])), "1v1"),
            ("an unknown token", lambda s: s["objects"]["tk"].update(token_id="golem"), "do not make"),
            ("an edited token", lambda s: s["objects"]["tk"].update(base_might=5), "fields other than its record's"),
            # a player's view (action_receipt.actor_view): a mask only where a card can be unseen, carrying only a mask's
            ("a mask on the Board", lambda s: s["objects"].update(u1=CE.mask(s["objects"]["u1"])), "masked where a card is seen"),
            ("a mask carrying more", lambda s: s["objects"].update(c1={**CE.mask(s["objects"]["c1"]), "card_ref": "Test Spell"}),
             "carries more than a mask")):
        bad = copy.deepcopy(state)
        change(bad)
        found = CE.environment_problems(bad, cat)
        if not any(says in p for p in found):
            fail("E4 the state", f"{label} was not named: {found}")
    played = copy.deepcopy(state)
    played["objects"]["u1"]["entry_replacements"].append({"replacement_id": "accelerate:unit-1", "mode": "entry_state",
                                                          "value": "ready", "source": "accelerate", "chain_item": "unit-1",
                                                          "card": "u1"})
    if CE.environment_problems(played, cat):
        fail("E4 the state", f"an entry a play added (Accelerate) was read as an edit: {CE.environment_problems(played, cat)}")
    # a token the procedure itself makes is the catalogue's token (E4)
    from effect_ir import apply_program
    made = apply_program(state, CE.instantiate_program(cat, "Test Unit", "tok", {
        "$controller": "p1", "$opponent": "p2", "$chain_item": "item-1", "$source_object": "u1", "$card": "u1"}))
    fresh = [o for o in (made.get("next_state") or {}).get("objects", {}) if o not in state["objects"]]
    if not made.get("committed") or len(fresh) != 1 or CE.environment_problems(made["next_state"], cat):
        fail("E4 the state", f"a token play_token makes: {made.get('reason') or made.get('errors')} {fresh} "
                             f"{CE.environment_problems(made.get('next_state') or state, cat)[:2]}")
    taken = copy.deepcopy(state)
    taken["objects"]["a1"]["controller"] = "p2"
    follow_controller(taken, "a1", "p2")
    if CE.environment_problems(taken, cat):
        fail("E4 the state", f"a permanent whose control changed with its abilities was read as an edit: "
                             f"{CE.environment_problems(taken, cat)}")
    # E5
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "play_id": "act-1", "actor": "p1", "card": "u1",
                   "chain_item": {"id": "ability-1", "object_kind": "ability", "timing": "default"},
                   "activation": {"source_object": "u1", "ability_id": "u1:a1"},
                   "cost": {"base": {"energy": 1, "power": {}},
                            "additional": [{"cost_id": EXHAUST_SELF_COST_ID, "mandatory": True,
                                            "payment": {"kind": "exhaust", "object_id": "u1"}}]},
                   "effect_program_id": "Test Unit#a1",
                   "payment_context": {"add_window_closed": True, "confirmed_by": "gate"}}
    played = play_card(fixture(), state, declaration, effect_program=program)
    if not played.get("committed"):
        fail("E5 end to end", f"the catalogued ability was refused: {played.get('reason_code')} {played.get('reason')}")
    cheaper = copy.deepcopy(declaration)
    cheaper["cost"]["base"]["energy"] = 0
    refused = play_card(fixture(), state, cheaper, effect_program=program)
    if refused.get("committed") or refused.get("reason_code") != "declaration_not_as_catalogued":
        fail("E5 end to end", f"the ability at another cost was not refused as not catalogued: {refused.get('reason_code')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: the closed environment's catalogue")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the catalogue validates and hashes and refuses another Core, a spell without its program, an ability "
          "or trigger without its program, a trigger with a fixed controller or order, a replacement counting its uses, "
          "a stale hash; placed objects carry their records, triggers bound to them; programs bind every symbol; a state "
          "is the environment's only with every object catalogued and unedited, no legacy list entry, and exactly the "
          "printed replacements its objects materialize, in 1v1; a placed ability plays as its row says and not "
          "otherwise (E1-E5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
