#!/usr/bin/env python3
"""
Gate for C-30 (ADR-0008 §8–9): Showdown close and Combat Damage assignment.

Goldens are the official examples of Core 465.2.c:
  - c.3: 5 damage among four 3-Might Units — 2/1/1/1 is illegal, 3/2/0/0 and
    3/0/2/0 are legal, 2/3/0/0 is not (lethal in full before another Unit);
  - c.4: the same Units with 1 damage marked — no Unit may take more than 2
    while another remains: 3/2/0/0 illegal, 2/2/1/0 legal;
  - c.5: a 2-Might Unit with "prevent the first 3 damage" needs 5 assigned to
    have lethal assigned; the preview records the prevented amount and the
    consumed replacement without touching the effect state;
  - c.6: Tank, then no ability, then Backline; c.7: two Tanks in either order
    before the plain Unit; c.8: a Unit with both needs the assigning player's
    choice and cannot sit in between; c.9: two such Units may both be chosen
    as Tank;
  - a Stunned Unit contributes no Might but needs full lethal (423.1); a Unit
    behind a replacement the preview cannot evaluate makes the assignment
    unsupported, never guessed; exactly one legal assignment proceeds by
    itself (one opposing Unit, or 0 damage), two or more stop naming the
    assigning player, attacker first; a foreign assignment, a wrong sum, a
    stale identity are refused;
  - pass_focus closes a Combat Showdown after every player passed once in
    sequence, a play breaks the sequence, a Non-Combat close is the G2
    boundary, and no one plays while the Combat's steps are pending;
  - nothing is Dealt: damage marks and prevent values are unchanged after
    assignment; engine-check wraps the decision as damage_assignment.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_combat_characteristics import opened  # noqa: E402
from check_combat_staging import contested_board  # noqa: E402
from check_rules_core import item  # noqa: E402
from combat import assign_combat_damage, combined_input_hash  # noqa: E402
from effect_ir import hash_value  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import next_procedure, pass_focus, state_hash, validate_timing  # noqa: E402


def add_unit(state, object_id, owner, where, might=3, **fields):
    state["objects"][object_id] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0, "exhausted": False, **fields}
    if where.startswith("base:"):
        state["players"][where[5:]]["zones"]["base"].append(object_id)
    else:
        state["battlefields"][where]["objects"].append(object_id)


def closed_combat(defenders, attacker_might=5):
    """One attacker Unit (u1, p1) of the given Might against the listed p2 defenders at bf1, Showdown closed."""
    state = contested_board()
    state["objects"]["u1"]["base_might"] = attacker_might; state["objects"]["u1"]["damage"] = 0
    state["battlefields"]["bf1"]["objects"].remove("u2"); state["players"]["p2"]["zones"]["base"].append("u2")  # u2 out of the fight
    for object_id, fields in defenders:
        add_unit(state, object_id, "p2", "bf1", **fields)
    timing, effect, _ = opened(state)
    t = pass_focus(timing, "p1")["next_state"]
    t = pass_focus(t, "p2")["next_state"]
    return t, effect


def decide(timing, effect, role, amounts, choices=None, controller=None, identities=None):
    combat_id = timing["combat"]["combat_id"]
    player = timing["combat"][role]
    value = {"amounts": amounts, "requirement_choices": choices} if choices else amounts
    return {"schema_version": "engine-decisions.v1", "input_hash": combined_input_hash(timing, effect), "decisions": [
        {"decision_id": f"damage_assignment:{combat_id}:{role}", "stage": "procedure", "kind": "damage_assignment", "controller": controller or player, "value": value,
         "selection_identities": identities or {u: f"{u}@0" for u in amounts}}]}


def both(timing, effect, attacker_amounts, defender_amounts=None, attacker_choices=None):
    combat_id = timing["combat"]["combat_id"]
    decisions = decide(timing, effect, "attacker", attacker_amounts, attacker_choices)["decisions"]
    if defender_amounts is not None:
        decisions += decide(timing, effect, "defender", defender_amounts)["decisions"]
    return {"schema_version": "engine-decisions.v1", "input_hash": combined_input_hash(timing, effect), "decisions": decisions}


def accepted(result) -> bool:
    """An assignment the engine took: committed (the other side's was the sole legal one) or the next player is asked."""
    return result.get("committed") is True or result.get("reason_code") == "damage_assignment_required"


def main() -> int:
    errors: list[str] = []

    # --- Focus passes close the Combat Showdown --------------------------------------------------
    timing, effect, _ = opened(contested_board())
    one = pass_focus(timing, "p1")
    if not one.get("applied") or one["next_state"]["showdown"]["focus"] != "p2" or one["next_state"]["combat"]["status"] != "open":
        errors.append(f"the first Focus pass did not hand Focus to the next player: {one.get('reason_code')}")
    else:
        two = pass_focus(one["next_state"], "p2")
        if not two.get("applied") or two["next_state"]["combat"]["status"] != "showdown_closed" or two["next_state"]["showdown"]["active"] is not True or next_procedure(two["next_state"]).get("procedure") != "combat_step_pending":
            errors.append(f"every player passing did not close the Combat Showdown into the pending Combat steps: {two.get('reason_code')} {next_procedure(two.get('next_state', timing)).get('procedure')}")
        elif validate_timing(two["next_state"], {"actor": "p1", "kind": "play_card", "timing": "action"}).get("legal") is not False:
            errors.append("a play was legal while the Combat's steps are pending")
        if pass_focus(one["next_state"], "p1").get("applied"):
            errors.append("a player passed Focus twice in one sequence")
    non_combat = copy.deepcopy(timing); non_combat["showdown"]["kind"] = "non_combat"; del non_combat["combat"]
    nc1 = pass_focus(non_combat, "p1")
    nc2 = pass_focus(nc1["next_state"], "p2") if nc1.get("applied") else {}
    if not nc2.get("applied") or nc2["next_state"]["showdown"].get("closing") is not True or nc2.get("next_procedure", {}).get("procedure") != "control_resolution_pending":
        errors.append("a Non-Combat Showdown's close did not become closing with control resolution next (348.2, ADR-0009)")
    if assign_combat_damage(timing, effect).get("reason_code") != "combat_showdown_not_closed":
        errors.append("damage was assigned before the Showdown closed")

    # --- c.3: 5 damage among four 3-Might Units -----------------------------------------------------
    t, e = closed_combat([("d1", {}), ("d2", {}), ("d3", {}), ("d4", {})])
    asked = assign_combat_damage(t, e)
    if asked.get("committed") or asked.get("reason_code") != "damage_assignment_required" or asked.get("decision_controller") != "p1" or asked.get("available") != 5:
        errors.append(f"the attacker was not asked for the assignment of 5: {asked.get('reason_code')} {asked.get('available')}")
    else:
        check = build_engine_check("combat_step", asked, input_hashes={"timing_state": state_hash(t), "effect_state": hash_value(e)})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "damage_assignment":
            errors.append(f"the assignment decision did not wrap as damage_assignment: {check.get('decision_required')}")
    def verdict(amounts, choices=None, defenders=None):
        r = assign_combat_damage(t, e, both(t, e, amounts, defenders, choices))
        return r
    if verdict({"d1": 2, "d2": 1, "d3": 1, "d4": 1}).get("reason_code") != "damage_assignment_illegal":
        errors.append("c.3: 2/1/1/1 was accepted")
    if not accepted(verdict({"d1": 2, "d2": 3, "d3": 0, "d4": 0})):
        errors.append("c.3: the mapping 2/3/0/0 is 3 to one Unit then the leftover 2 to another; it was refused")
    ok1 = verdict({"d1": 3, "d2": 2, "d3": 0, "d4": 0})
    if not accepted(ok1):
        errors.append(f"c.3: 3/2/0/0 was refused: {ok1.get('reason_code')} {ok1.get('reason')}")
    if not accepted(verdict({"d1": 3, "d2": 0, "d3": 2, "d4": 0})):
        errors.append("c.3: any order within the same priority was refused")
    if verdict({"d1": 3, "d2": 3, "d3": 0, "d4": 0}).get("valid") is not False:
        errors.append("a sum above the available damage was accepted")
    foreign = assign_combat_damage(t, e, decide(t, e, "attacker", {"d1": 3, "d2": 2, "d3": 0, "d4": 0}, controller="p2"))
    if foreign.get("reason_code") != "decision_controller_mismatch":
        errors.append("the defender supplied the attacker's assignment")
    stale = assign_combat_damage(t, e, decide(t, e, "attacker", {"d1": 3, "d2": 2, "d3": 0, "d4": 0}, identities={"d1": "d1@3", "d2": "d2@0", "d3": "d3@0", "d4": "d4@0"}))
    if stale.get("valid") is not False:
        errors.append("a stale unit identity in the assignment was accepted")
    # the defenders' 12 among one attacker: sole legal, so both sides complete
    done = verdict({"d1": 3, "d2": 2, "d3": 0, "d4": 0}, defenders=None)
    full = assign_combat_damage(t, e, both(t, e, {"d1": 3, "d2": 2, "d3": 0, "d4": 0}, {"u1": 12}))
    if not full.get("committed") or full["next_timing_state"]["combat"]["status"] != "damage_assigned":
        errors.append(f"a complete pair of assignments did not commit: {full.get('reason_code')} {full.get('reason') or full.get('errors')}")
    else:
        rec = full["next_timing_state"]["combat"]["assignments"]
        if rec["attacker"]["available"] != 5 or rec["defender"]["available"] != 12 or [x["raw_assigned"] for x in rec["attacker"]["entries"]] != [3, 2, 0, 0] or [x["lethal"] for x in rec["attacker"]["entries"]] != [True, False, False, False]:
            errors.append(f"the receipts do not record the assignment: {rec['attacker']['entries']}")
        if full["next_effect_state"] != e:
            errors.append("assignment changed the effect state; nothing is Dealt at assignment (465.2.c.1)")
    auto = assign_combat_damage(t, e, both(t, e, {"d1": 3, "d2": 2, "d3": 0, "d4": 0}))
    if not auto.get("committed") or auto["next_timing_state"]["combat"]["assignments"]["defender"]["selection"] != "sole_legal_assignment":
        errors.append("the defender facing one opposing Unit has exactly one legal assignment; the engine should proceed with it")
    # single opposing unit → the engine proceeds
    t1, e1 = closed_combat([("d1", {})])
    solo = assign_combat_damage(t1, e1)
    if not solo.get("committed") or solo["next_timing_state"]["combat"]["assignments"]["attacker"]["selection"] != "sole_legal_assignment" or solo["next_timing_state"]["combat"]["assignments"]["attacker"]["entries"][0]["raw_assigned"] != 5:
        errors.append(f"one opposing Unit did not let the engine proceed with the sole legal assignment: {solo.get('reason_code')} {solo.get('reason')}")

    # --- c.4: 1 damage already marked → no more than 2 each while others remain ---------------------
    t, e = closed_combat([("d1", {"damage": 1}), ("d2", {"damage": 1}), ("d3", {"damage": 1}), ("d4", {"damage": 1})])
    if assign_combat_damage(t, e, both(t, e, {"d1": 3, "d2": 2, "d3": 0, "d4": 0})).get("reason_code") != "damage_assignment_illegal":
        errors.append("c.4: 3 on a Unit needing 2 while others remained was accepted")
    if not accepted(assign_combat_damage(t, e, both(t, e, {"d1": 2, "d2": 2, "d3": 1, "d4": 0}))):
        errors.append("c.4: 2/2/1/0 was refused")

    # --- c.5: prevent the first 3 → 5 must be assigned to a 2-Might Unit ------------------------------
    t, e = closed_combat([("d1", {"might": 2})], attacker_might=5)
    e["replacement_effects"] = [{"replacement_id": "ward", "controller": "p2", "source_object": "d1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 3, "target_object_id": "d1"}]
    previewed = assign_combat_damage(t, e)
    if not previewed.get("committed"):
        errors.append(f"c.5: the previewed assignment did not commit: {previewed.get('reason_code')} {previewed.get('reason')}")
    else:
        entry = previewed["next_timing_state"]["combat"]["assignments"]["attacker"]["entries"][0]
        if entry["min_lethal_raw"] != 5 or entry["raw_assigned"] != 5 or entry["applied"] != 2 or entry["prevented"] != 3 or entry["consumed_replacements"] != [{"replacement_id": "ward", "mode": "reduce_damage", "prevented": 3}]:
            errors.append(f"c.5: the preview did not compute 5 raw → 2 applied with the Prevent consumed: {entry}")
        if previewed["next_effect_state"]["replacement_effects"][0]["prevent_remaining"] != 3 or previewed["next_effect_state"]["objects"]["d1"]["damage"] != 0:
            errors.append("the preview consumed the Prevent or Dealt damage during assignment")
    t2, e2 = closed_combat([("d1", {"might": 2}), ("d2", {"might": 2})], attacker_might=3)
    e2["replacement_effects"] = [{"replacement_id": "ward", "controller": "p2", "source_object": "d1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 2, "target_object_id": "d1"}]
    if assign_combat_damage(t2, e2, both(t2, e2, {"d1": 4, "d2": 0})).get("valid") is not False:
        errors.append("c.5: an assignment above the available damage passed")
    lethal_first = assign_combat_damage(t2, e2, both(t2, e2, {"d1": 1, "d2": 2}))
    if not accepted(lethal_first):
        errors.append(f"c.5: lethal to the unprotected Unit then the rest to the protected one was refused: {lethal_first.get('reason')}")
    unknown = copy.deepcopy(e); unknown["replacement_effects"][0].update({"mode": "prevent_event"}); del unknown["replacement_effects"][0]["prevent_remaining"]
    blocked = assign_combat_damage(t, unknown)
    if blocked.get("committed") or blocked.get("unsupported") is not True or blocked.get("reason_code") != "assignment_replacement_not_previewable":
        errors.append(f"a replacement the preview cannot evaluate was ignored or guessed: {blocked.get('reason_code')}")

    # --- c.6–c.9: Tank, Backline, both ---------------------------------------------------------------
    t, e = closed_combat([("tank", {"keywords": ["tank"]}), ("plain", {}), ("back", {"keywords": ["backline"]})], attacker_might=7)
    if not accepted(assign_combat_damage(t, e, both(t, e, {"tank": 3, "plain": 3, "back": 1}))):
        errors.append("c.6: Tank, plain, Backline in order was refused")
    if assign_combat_damage(t, e, both(t, e, {"tank": 3, "back": 3, "plain": 1})).get("reason_code") != "damage_assignment_illegal":
        errors.append("c.6: Backline before the plain Unit was accepted")
    if not accepted(assign_combat_damage(t, e, both(t, e, {"plain": 3, "tank": 3, "back": 1}))):
        errors.append("c.6: the order of the dict must not matter, only amounts")
    if assign_combat_damage(t, e, both(t, e, {"tank": 2, "plain": 3, "back": 2})).get("reason_code") != "damage_assignment_illegal":
        errors.append("c.6: a plain Unit received damage while the Tank lacked lethal")
    t, e = closed_combat([("tank1", {"keywords": ["tank"]}), ("tank2", {"keywords": ["tank"]}), ("plain", {})], attacker_might=5)
    if not accepted(assign_combat_damage(t, e, both(t, e, {"tank1": 3, "tank2": 2, "plain": 0}))):
        errors.append("c.7: either Tank first then the other was refused")
    if assign_combat_damage(t, e, both(t, e, {"tank1": 3, "tank2": 0, "plain": 2})).get("reason_code") != "damage_assignment_illegal":
        errors.append("c.7: the plain Unit received damage while a Tank remained")
    t, e = closed_combat([("cait", {"keywords": ["backline"]}), ("p1u", {}), ("p2u", {})], attacker_might=9)
    e["objects"]["cait"]["keyword_modifiers"] = [{"modifier_id": "block", "keyword": "tank", "source": "block", "duration": "this_combat", "combat_id": t["combat"]["combat_id"], "target_identity": "cait@0"}]
    undecided = assign_combat_damage(t, e, both(t, e, {"cait": 3, "p1u": 3, "p2u": 3}))
    if undecided.get("reason_code") != "damage_assignment_illegal" or "465.2.c.8" not in undecided.get("reason", ""):
        errors.append(f"c.8: a Tank+Backline Unit without the player's requirement choice was accepted: {undecided.get('reason_code')} {undecided.get('reason')}")
    if not accepted(assign_combat_damage(t, e, both(t, e, {"cait": 3, "p1u": 3, "p2u": 3}, attacker_choices={"cait": "tank"}))):
        errors.append("c.8: choosing Tank for Caitlyn was refused")
    if not accepted(assign_combat_damage(t, e, both(t, e, {"cait": 3, "p1u": 3, "p2u": 3}, attacker_choices={"cait": "backline"}))):
        errors.append("c.8: choosing Backline for Caitlyn was refused")
    e7 = copy.deepcopy(e); t7 = copy.deepcopy(t); e7["objects"]["u1"]["base_might"] = 7
    # 7 damage: the leftover 1 lands on Caitlyn only under the Backline choice; under Tank she must be lethal first
    late_cait = assign_combat_damage(t7, e7, both(t7, e7, {"p1u": 3, "p2u": 3, "cait": 1}, attacker_choices={"cait": "tank"}))
    if late_cait.get("reason_code") != "damage_assignment_illegal":
        errors.append("c.8: Caitlyn last while chosen as Tank was accepted")
    if not accepted(assign_combat_damage(t7, e7, both(t7, e7, {"p1u": 3, "p2u": 3, "cait": 1}, attacker_choices={"cait": "backline"}))):
        errors.append("c.8: Caitlyn last while chosen as Backline was refused")
    t, e = closed_combat([("cx1", {"keywords": ["backline"]}), ("cx2", {"keywords": ["backline"]}), ("plain", {})], attacker_might=9)
    for c in ("cx1", "cx2"):
        e["objects"][c]["keyword_modifiers"] = [{"modifier_id": "block", "keyword": "tank", "source": "block", "duration": "this_combat", "combat_id": t["combat"]["combat_id"], "target_identity": f"{c}@0"}]
    if not accepted(assign_combat_damage(t, e, both(t, e, {"cx1": 3, "cx2": 3, "plain": 3}, attacker_choices={"cx1": "tank", "cx2": "tank"}))):
        errors.append("c.9: both Caitlyns chosen as Tank before the plain Unit was refused")

    # --- Stunned: no contribution, full lethal ---------------------------------------------------------
    t, e = closed_combat([("d1", {"stunned": True})], attacker_might=5)
    stunned = assign_combat_damage(t, e)
    if not stunned.get("committed") or stunned["next_timing_state"]["combat"]["assignments"]["defender"]["available"] != 0 or stunned["next_timing_state"]["combat"]["assignments"]["attacker"]["entries"][0]["min_lethal_raw"] != 3:
        errors.append(f"a Stunned defender contributed Might or needed less than full lethal (423.1): {stunned.get('reason_code')} {stunned.get('reason')}")
    # --- no Units on one side: the damage step is skipped ------------------------------------------------
    t, e = closed_combat([("d1", {})])  # the only defender died during the Showdown
    e["battlefields"]["bf1"]["objects"].remove("d1"); e["players"]["p2"]["zones"]["trash"].append("d1"); del e["objects"]["d1"]["combat_designation"]
    skipped = assign_combat_damage(t, e)
    if not skipped.get("committed") or skipped["next_timing_state"]["combat"]["status"] != "damage_dealt" or skipped["next_timing_state"]["combat"].get("damage_step_skipped") is not True:
        errors.append(f"with no defenders the damage step was not skipped (465.1): {skipped.get('reason_code')} {skipped.get('reason')}")
    snap_t, snap_e = copy.deepcopy(t1), copy.deepcopy(e1)
    if t1 != snap_t or e1 != snap_e or assign_combat_damage(t1, e1) != solo:
        errors.append("assign_combat_damage mutated its inputs or is not deterministic")

    if errors:
        print("FAILED: combat damage assignment checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: every player passing Focus closes the Combat Showdown into pending Combat steps; assignment is the assigning player's complete decision validated against 465.2.c in full — lethal in full before another Unit, no over-assignment while a Unit remains, Tank first and Backline last with an explicit choice for a Unit that has both, minimum lethal previewed through Prevent values that are recorded and not consumed — with the engine proceeding alone only for the sole legal assignment, unevaluable replacements unsupported, and nothing Dealt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
