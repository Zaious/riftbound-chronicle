#!/usr/bin/env python3
"""
Gate for C-27 (ADR-0008 §4–5): Battlefield Defend triggers, Shield / alone /
aura reads, and this-combat keyword modifiers.

Must hold:
  - Shield adds to effective_might only while the Unit carries the Defender
    designation: a bare Shield is +1, Shield X is +X, an attacker's Shield
    adds nothing, a Unit without a designation adds nothing; printed and
    granted Shield values sum (Stalwart Poro + Shield 3 = Shield 4);
  - a keyword modifier of another Combat or another turn is inactive;
  - attacking_or_defending_alone holds with a designation and no other
    friendly Unit at the location (a teammate's Unit counts as friendly, an
    enemy's does not); without a designation it never holds;
  - friendly_unit_defends_alone auras add to each friendly lone Defender
    only while the source is on the board; attackers and enemies get none;
  - a negative total reads as 0 (143.2.b) while current_might keeps the
    arithmetic value; lethal Cleanup reads the clamped value;
  - a Battlefield's Defend trigger fires at opening only when the
    Battlefield's controller is the defender (190.6.a, 190.6.d): controlled
    by the attacker or uncontrolled fires nothing; the chain item is
    controlled by the Battlefield's controller with the Battlefield as source;
  - resolving that trigger with grant_keyword binds Shield 2 to the chosen
    Unit's identity and the Combat in progress — any Unit, not only one
    "here" — while the same grant outside a Combat is unsupported;
  - validators refuse a keyword modifier without its combat_id, an aura of
    unknown condition, a Battlefield trigger of bad shape; determinism.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_combat_staging import contested_board  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from combat import open_combat, stage_combat  # noqa: E402
from effect_ir import apply_program, current_might, effective_might, hash_value, perform_lethal_cleanup, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402


def opened(effect_state, timing=None):
    timing = timing or fixture()
    staged = stage_combat(timing, effect_state)
    assert staged.get("committed"), staged.get("reason") or staged.get("errors")
    result = open_combat(staged["next_timing_state"], effect_state)
    assert result.get("committed"), result.get("reason") or result.get("errors")
    return result["next_timing_state"], result["next_effect_state"], result


def main() -> int:
    errors: list[str] = []

    # --- Shield -------------------------------------------------------------------------------------
    board = contested_board()
    board["objects"]["u2"]["keywords"] = ["shield"]
    board["objects"]["u1"]["keywords"] = ["shield"]; board["objects"]["u1"]["shield_value"] = 2
    if effective_might(board, "u2") != 4 or effective_might(board, "u1") != 3:
        errors.append("Shield added Might without a Defender designation")
    timing, state, _ = opened(board)
    combat_id = timing["combat"]["combat_id"]
    if effective_might(state, "u2") != 5 or effective_might(state, "u1") != 3 or current_might(state["objects"]["u2"]) != 4:
        errors.append(f"bare Shield on the defender / Shield 2 on the attacker read wrong: {effective_might(state, 'u2')} {effective_might(state, 'u1')}")
    swapped = contested_board(contested_by="p2"); swapped["objects"]["u1"]["keywords"] = ["shield"]; swapped["objects"]["u1"]["shield_value"] = 2
    _, s2, _ = opened(swapped)
    if effective_might(s2, "u1") != 5:
        errors.append("Shield 2 on the defender did not read +2")
    granted = apply_program(state, program("block", {"op": "grant_keyword", "object_id": "u2", "keyword": "shield", "value": 3, "duration": "this_combat", "source": "block", "effect_id": "g"}), context={"combat": {"combat_id": combat_id, "battlefield": "bf1"}})
    if not granted.get("committed") or effective_might(granted["next_state"], "u2") != 8 or granted["trace"][0].get("shield_total") != 4:
        errors.append(f"printed Shield and granted Shield 3 did not sum to Shield 4 (814.2): {granted.get('reason') or granted.get('errors')} {granted.get('trace')}")
    else:
        modifier = granted["next_state"]["objects"]["u2"]["keyword_modifiers"][0]
        if modifier.get("combat_id") != combat_id or modifier.get("target_identity") != "u2@0" or modifier.get("duration") != "this_combat":
            errors.append(f"the granted Shield is not bound to the Combat and the identity: {modifier}")
        foreign = copy.deepcopy(granted["next_state"]); foreign["objects"]["u2"]["keyword_modifiers"][0]["combat_id"] = "combat:other"
        if effective_might(foreign, "u2") != 5:
            errors.append("a Shield granted for another Combat was read in this one")
        stale = copy.deepcopy(granted["next_state"]); stale["objects"]["u2"]["keyword_modifiers"][0].update({"duration": "this_turn", "turn_id": "turn-9"}); del stale["objects"]["u2"]["keyword_modifiers"][0]["combat_id"]
        if validate_state(stale) or effective_might(stale, "u2") != 5:
            errors.append(f"a Shield granted for another turn was read now: {validate_state(stale)}")
        if validate_state(granted["next_state"]):
            errors.append(f"state with a keyword modifier invalid: {validate_state(granted['next_state'])}")
    bare = apply_program(state, program("nothing", {"op": "grant_keyword", "object_id": "u2", "keyword": "shield", "value": 3, "duration": "this_combat", "source": "block", "effect_id": "g"}))
    if bare.get("committed") or bare.get("unsupported") is not True:
        errors.append("a 'this combat' grant with no Combat context was applied")
    turn_grant = apply_program(state, program("turn", {"op": "grant_keyword", "object_id": "u1", "keyword": "tank", "duration": "this_turn", "source": "spell", "effect_id": "g"}))
    if not turn_grant.get("committed") or turn_grant["next_state"]["objects"]["u1"]["keyword_modifiers"][0].get("turn_id") != "turn-0":
        errors.append(f"a this-turn Tank grant did not record the turn: {turn_grant.get('reason') or turn_grant.get('errors')}")
    snap = copy.deepcopy(state)
    if state != snap or apply_program(state, program("block", {"op": "grant_keyword", "object_id": "u2", "keyword": "shield", "value": 3, "duration": "this_combat", "source": "block", "effect_id": "g"}), context={"combat": {"combat_id": combat_id, "battlefield": "bf1"}}) != granted:
        errors.append("grant_keyword mutated its input or is not deterministic")

    # --- alone -------------------------------------------------------------------------------------
    alone_board = contested_board()
    alone_board["objects"]["u1"]["conditional_might"] = [{"modifier_id": "wielder", "amount": 2, "condition": {"kind": "attacking_or_defending_alone"}}]
    if validate_state(alone_board):
        errors.append(f"attacking_or_defending_alone rejected: {validate_state(alone_board)}")
    if effective_might(alone_board, "u1") != 3:
        errors.append("'alone' held without a designation")
    _, alone_state, _ = opened(alone_board)
    if effective_might(alone_state, "u1") != 5:
        errors.append(f"a lone attacker did not get +2: {effective_might(alone_state, 'u1')}")
    company = copy.deepcopy(alone_state)
    company["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False}
    company["battlefields"]["bf1"]["objects"].append("u3")
    if effective_might(company, "u1") != 3:
        errors.append("a friendly Unit at the same location left the attacker 'alone'")
    teammate = copy.deepcopy(company); teammate["objects"]["u3"].update({"owner": "p3", "controller": "p3"})
    teammate["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [], "rune_deck": []}, "resources": {"energy": 0, "power": {}}, "team_id": "A"}
    teammate["players"]["p1"]["team_id"] = "A"
    if effective_might(teammate, "u1") != 3:
        errors.append("a teammate's Unit did not count as friendly company (740.1.a)")
    # --- aura --------------------------------------------------------------------------------------
    aura_board = contested_board()
    aura_board["objects"]["g1"] = {"owner": "p2", "controller": "p2", "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
    aura_board["players"]["p2"]["zones"]["base"].append("g1")
    aura_board["might_auras"] = [{"modifier_id": "wuju", "source_object": "g1", "controller": "p2", "amount": 2, "condition": {"kind": "friendly_unit_defends_alone"}}]
    if validate_state(aura_board):
        errors.append(f"might_auras rejected: {validate_state(aura_board)}")
    _, aura_state, _ = opened(aura_board)
    if effective_might(aura_state, "u2") != 6 or effective_might(aura_state, "u1") != 3:
        errors.append(f"the aura did not reach the lone friendly Defender only: {effective_might(aura_state, 'u2')} {effective_might(aura_state, 'u1')}")
    crowd = copy.deepcopy(aura_state)
    crowd["objects"]["u4"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False}
    crowd["battlefields"]["bf1"]["objects"].append("u4")
    if effective_might(crowd, "u2") != 4:
        errors.append("a Defender with company still got the 'defends alone' aura")
    gone = copy.deepcopy(aura_state); gone["players"]["p2"]["zones"]["base"].remove("g1"); gone["players"]["p2"]["zones"]["trash"].append("g1")
    if effective_might(gone, "u2") != 4:
        errors.append("an aura whose source left the board still applied")
    bad_aura = copy.deepcopy(aura_board); bad_aura["might_auras"][0]["condition"] = {"kind": "moonlight"}
    if not validate_state(bad_aura):
        errors.append("an unknown aura condition was accepted")

    # --- clamp -------------------------------------------------------------------------------------
    weak = base_state()
    weak["objects"]["u1"]["might_modifiers"] = [{"amount": -5, "duration": "persistent", "source": "curse"}]
    if effective_might(weak, "u1") != 0 or current_might(weak["objects"]["u1"]) != -2:
        errors.append(f"negative Might was not read as 0 while keeping its arithmetic value (143.2.b): {effective_might(weak, 'u1')} {current_might(weak['objects']['u1'])}")
    cleanup = perform_lethal_cleanup(weak)  # u1 carries 1 damage
    if not cleanup.get("committed") or "u1" not in cleanup["next_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append("lethal Cleanup did not read the clamped Might (1 damage on Might 0)")

    # --- Battlefield Defend trigger ----------------------------------------------------------------
    fp = {"trigger_id": "fp-defend", "controller_order": 0, "effect_program_id": "fortified-position", "optional_at_finalize": False}
    fortified = contested_board(); fortified["battlefields"]["bf1"]["controller"] = "p2"; fortified["battlefields"]["bf1"]["defend_triggers"] = [fp]
    fortified["objects"]["u3"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False}
    fortified["players"]["p2"]["zones"]["base"].append("u3")
    if validate_state(fortified):
        errors.append(f"a Battlefield with a Defend trigger was rejected: {validate_state(fortified)}")
    fp_timing, fp_state, fp_open = opened(fortified)
    items = fp_timing["chain"]["items"]
    if [i["id"] for i in items] != ["fp-defend"] or items[0]["controller"] != "p2" or items[0]["source_object"] != "bf1" or fp_timing["combat"].get("battlefield_triggered") != ["defender"]:
        errors.append(f"the Battlefield's Defend trigger did not fire for its controller as defender: {[(i.get('id'), i.get('controller'), i.get('source_object')) for i in items]}")
    by_attacker = copy.deepcopy(fortified); by_attacker["battlefields"]["bf1"]["controller"] = "p1"
    _, _, r = opened(by_attacker)
    if r["next_timing_state"]["chain"]["items"] or r["trace"]["battlefield_triggers"][0].get("fired") is not False:
        errors.append("a Battlefield controlled by the attacker fired 'When you defend here'")
    uncontrolled = copy.deepcopy(fortified); uncontrolled["battlefields"]["bf1"]["controller"] = None
    _, _, r = opened(uncontrolled)
    if r["next_timing_state"]["chain"]["items"] or "refers to no one" not in r["trace"]["battlefield_triggers"][0].get("reason", ""):
        errors.append("an uncontrolled Battlefield fired 'When you defend here' (190.6.d)")
    # resolve the trigger: choose a unit anywhere, it gains Shield 2 this combat
    resolving = copy.deepcopy(fp_timing)
    resolving["chain"]["items"][0]["status"] = "finalized"
    resolving["chain"]["consecutive_passes"] = ["p1", "p2"]
    resolving["priority"] = "p1"
    fp_program = {**program("fortified-position", {"op": "grant_keyword", "effect_id": "g", "keyword": "shield", "value": 2, "duration": "this_combat", "source": "bf1",
                                                   "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}), "controller": "p2", "source_object": "bf1"}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(fp_state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p2", "value": ["u3"], "selection_identities": {"u3": "u3@0"}}]}
    resolved = resolve_with_program(resolving, "fp-defend", fp_state, fp_program, engine_decisions=decisions)
    if not resolved.get("committed"):
        errors.append(f"the Fortified Position trigger did not resolve: {resolved.get('stage')} {resolved.get('reason') or resolved.get('errors')}")
    else:
        u3 = resolved["next_effect_state"]["objects"]["u3"]
        mods = u3.get("keyword_modifiers", [])
        if len(mods) != 1 or mods[0].get("combat_id") != fp_timing["combat"]["combat_id"] or mods[0].get("value") != 2 or mods[0].get("target_identity") != "u3@0":
            errors.append(f"the granted Shield is not bound to the Combat in progress and the chosen identity: {mods}")
        if effective_might(resolved["next_effect_state"], "u3") != 1:
            errors.append("a granted Shield added Might to a Unit that is not a Defender")
        if resolved["next_effect_state"]["objects"]["u2"].get("keyword_modifiers"):
            errors.append("the grant reached a Unit other than the chosen one")
    bad_shape = copy.deepcopy(fortified); bad_shape["battlefields"]["bf1"]["defend_triggers"] = [{"trigger_id": "x", "controller": "p2", "controller_order": 0, "effect_program_id": "y", "optional_at_finalize": False}]
    if not validate_state(bad_shape):
        errors.append("a Battlefield trigger naming a fixed controller was accepted (190.6.a)")
    no_combat_id = copy.deepcopy(granted["next_state"]) if granted.get("committed") else None
    if no_combat_id:
        del no_combat_id["objects"]["u2"]["keyword_modifiers"][0]["combat_id"]
        if not validate_state(no_combat_id):
            errors.append("a this_combat modifier without combat_id was accepted")

    if errors:
        print("FAILED: combat characteristic checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Shield adds only while defending and sums printed with granted values, grants bind to the Combat in progress and the object's identity and are unsupported outside a Combat, 'alone' is team-aware and needs a designation, the lone-Defender aura reaches friendly Units only while its source is on the board, negative Might reads as 0, and a Battlefield's Defend trigger fires only when its controller gains the Defender designation with any Unit as its choice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
