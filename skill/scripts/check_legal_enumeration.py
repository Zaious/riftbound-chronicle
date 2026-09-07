#!/usr/bin/env python3
"""Regression gate for C-57 (ADR-0015 §1): bounded legal-action enumeration.

Must hold:
  - every enumerable family reports, in order, and says whether it enumerated
    or abstained — silence about a family is never "the player has no such
    action";
  - `complete_action_set` stays false, and `validate_result` refuses any
    result that claims otherwise;
  - it enumerates only from the acting player's own hand: the opponent's hand
    is in the same observed state and never reaches a candidate or the result;
  - a candidate is produced only when both checks pass — the timing kernel
    says legal and the *same* affordability function the payment path uses
    says the pool covers the cost. An unaffordable card is excluded by name,
    and a card whose printed cost the observation does not carry is
    `printed_cost_not_observed` rather than assumed free;
  - a family with nothing to read abstains by name rather than reporting that
    the player has no such action — `activate_ability` has no per-object
    catalogue yet and says so;
  - each family abstains when one observation it needs is missing, and says
    which — the per-family mutation gate;
  - Standard Move enumerates a ready controlled Unit's destinations and
    excludes an exhausted one; Hide only offers cards the observer knows are
    Hidden, at Battlefields the actor controls, and not into a full Facedown
    Zone;
  - the result is deterministic and its hash covers the enumeration record.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import legal_action as la  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402


def effect_state(**over):
    state = base_state()
    state["mode"] = {"victory_score": 8}
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["resources"] = {"energy": 3, "power": {"fury": 1}}
    # c1 is affordable, c2 is not, c4 is the opponent's and never enumerated
    for card in ("c1", "c2"):
        state["players"]["p1"]["zones"]["main_deck"].remove(card)
        state["players"]["p1"]["zones"]["hand"].append(card)
    state["players"]["p2"]["zones"]["main_deck"].remove("c4")
    state["players"]["p2"]["zones"]["hand"].append("c4")
    state["objects"]["c1"].update({"kind": "unit", "printed_cost": {"energy": 1, "power": {}}})
    state["objects"]["c2"].update({"kind": "spell", "printed_cost": {"energy": 9, "power": {}}})
    state["objects"]["c4"].update({"kind": "unit", "printed_cost": {"energy": 0, "power": {}}})
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2,
                              "might_modifiers": [], "damage": 0, "exhausted": True}
    state["players"]["p1"]["zones"]["base"].append("u3")
    state["battlefields"]["bf1"]["controller"] = "p1"
    for key, value in over.items():
        state[key] = value
    return state


def observe(*, completeness=None, timing=None, effect=None):
    return la.build_observation(
        perspective="player1",
        source={"kind": "engine_state", "state_seq": 7},
        context={"ruleset_core": "2026-07-16", "faq_as_of": "2026-07-16", "format": "standard",
                 "card_data_version": "r3a1"},
        timing_state=timing if timing is not None else fixture(),
        effect_state=effect if effect is not None else effect_state(),
        facts={},
        pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete",
                      "pending_decisions": "complete", **(completeness or {})},
    )


def family(result, name):
    return next(record for record in result["enumeration"]["families"] if record["family"] == name)


def main() -> int:
    errors: list[str] = []

    full = observe()
    result = la.enumerate_actions(full, "p1")
    if found := la.validate_result(result):
        errors.append(f"the enumerated result does not validate: {found}")
    if [record["family"] for record in result["enumeration"]["families"]] != list(la.ENUMERABLE_FAMILIES):
        errors.append(f"not every family reported, in order: {[r['family'] for r in result['enumeration']['families']]}")
    if result["complete_action_set"] is not False or result["candidate_source_mode"] != "engine_enumerated":
        errors.append("the enumerated result does not declare its own boundary")

    # --- the two checks ------------------------------------------------------------------------
    plays = family(result, "play_card")
    if plays["candidates"] != ["play:c1"]:
        errors.append(f"play_card did not enumerate exactly the affordable card: {plays['candidates']} {plays.get('excluded')}")
    if not any(item.get("object_id") == "c2" and item.get("reason_code") == "cost_unpayable" for item in plays["excluded"]):
        errors.append(f"the unaffordable card was not excluded by name: {plays['excluded']}")
    action = next(a for a in result["enumeration"]["actions"] if a["candidate_id"] == "play:c1")
    if action["action"]["checks"] != ["timing", "cost"] or action["required_facts"] != ["hand:p1", "printed_cost:c1", "resources:p1"]:
        errors.append(f"the candidate does not carry its checks and what it needed: {action}")

    # --- the opponent's hand is never reached for --------------------------------------------
    if any("c4" in candidate["candidate_id"] for candidate in result["candidates"]):
        errors.append("the enumeration offered a card from the opponent's hand")
    if '"c4"' in json.dumps(result):
        errors.append("the enumeration leaked the opponent's hand into its result")

    # --- a cost the enumeration must not decide -------------------------------------------------
    unpriced = effect_state()
    del unpriced["objects"]["c1"]["printed_cost"]
    silent = family(la.enumerate_actions(observe(effect=unpriced), "p1"), "play_card")
    if silent["candidates"] or not any(item.get("reason_code") == "printed_cost_not_observed" for item in silent["excluded"]):
        errors.append(f"a card with no observed printed cost was offered anyway: {silent}")

    # --- a family with nothing to read abstains, it does not report "none" ----------------------
    abilities = family(result, "activate_ability")
    if abilities["status"] != "abstained" or "capability_missing" not in abilities["reason_code"]:
        errors.append(f"activate_ability did not abstain for a missing capability: {abilities}")

    # --- the per-family mutation gate -----------------------------------------------------------
    for name, group in (("play_card", "resources"), ("standard_move", "board"), ("hide", "hands")):
        crippled = observe(completeness={group: "partial"})
        record = family(la.enumerate_actions(crippled, "p1"), name)
        if record["status"] != "abstained" or group not in record["reason_code"]:
            errors.append(f"{name} did not abstain when {group} was incomplete: {record['status']} {record['reason_code']}")
        if not record["missing_information"]:
            errors.append(f"{name} abstained without naming what was missing")
        if record["candidates"]:
            errors.append(f"{name} abstained and still produced candidates")

    # --- Standard Move --------------------------------------------------------------------------
    moves = family(result, "standard_move")
    if moves["candidates"] != ["move:u1:bf1"]:
        errors.append(f"standard_move did not enumerate the ready Unit's one destination: {moves['candidates']}")
    if not any(item.get("object_id") == "u3" and item.get("reason_code") == "unit_is_exhausted" for item in moves["excluded"]):
        errors.append(f"an exhausted Unit was not excluded by name: {moves['excluded']}")
    closed = copy.deepcopy(fixture())
    closed["phase"] = "beginning"
    closed["priority"] = None
    quiet = la.enumerate_actions(observe(timing=closed), "p1")
    if family(quiet, "standard_move")["candidates"] or family(quiet, "play_card")["candidates"]:
        errors.append("the enumeration offered actions outside the Main Phase")

    # --- Hide ------------------------------------------------------------------------------------
    hidden = effect_state()
    hidden["objects"]["c1"]["hidden"] = True
    hides = family(la.enumerate_actions(observe(effect=hidden), "p1"), "hide")
    if hides["candidates"] != ["hide:c1:bf1"]:
        errors.append(f"hide did not offer exactly the Hidden card at the controlled Battlefield: {hides['candidates']}")
    if family(result, "hide")["candidates"]:
        errors.append("hide offered a card that is not Hidden")
    full_zone = copy.deepcopy(hidden)
    full_zone["players"]["p1"]["zones"]["trash"].remove("c3")
    full_zone["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": [
        {"object_id": "c3", "controller": "p1", "hidden_on_turn": "turn-2"}]}
    record = family(la.enumerate_actions(observe(effect=full_zone), "p1"), "hide")
    if record["candidates"] or not any(item.get("reason_code") == "facedown_zone_full" for item in record["excluded"]):
        errors.append(f"hide offered a card into a full Facedown Zone: {record}")
    uncontrolled = copy.deepcopy(hidden)
    uncontrolled["battlefields"]["bf1"]["controller"] = "p2"
    if family(la.enumerate_actions(observe(effect=uncontrolled), "p1"), "hide")["candidates"]:
        errors.append("hide offered a Battlefield the actor does not control (811.1)")

    # --- passing ---------------------------------------------------------------------------------
    if family(result, "pass_priority")["candidates"] or family(result, "pass_focus")["candidates"]:
        errors.append("passing was offered in a Neutral Open state with no chain")

    # --- the boundary is enforced, not merely stated -----------------------------------------------
    lying = copy.deepcopy(result)
    lying["complete_action_set"] = True
    lying["result_hash"] = la.canonical_hash({k: v for k, v in lying.items() if k != "result_hash"})
    if not la.validate_result(lying):
        errors.append("a result claiming a complete action set was accepted")
    dropped = copy.deepcopy(result)
    dropped["enumeration"] = {**dropped["enumeration"],
                              "families": [f for f in dropped["enumeration"]["families"] if f["family"] != "hide"]}
    dropped["result_hash"] = la.canonical_hash({k: v for k, v in dropped.items() if k != "result_hash"})
    if not la.validate_result(dropped):
        errors.append("a result that dropped a family was accepted")
    unexplained = copy.deepcopy(result)
    unexplained["enumeration"]["families"][0] = {**unexplained["enumeration"]["families"][0],
                                                 "status": "abstained", "missing_information": []}
    unexplained["result_hash"] = la.canonical_hash({k: v for k, v in unexplained.items() if k != "result_hash"})
    if not la.validate_result(unexplained):
        errors.append("a family abstained with no reason and was accepted")

    if la.enumerate_actions(observe(), "p1") != result:
        errors.append("the enumeration is not deterministic")
    wrong = la.enumerate_actions(full, "p2")
    if wrong.get("valid") is not False or not wrong.get("errors"):
        errors.append("enumerating for a player this perspective is not was accepted")

    if errors:
        print("FAILED: legal-action enumeration checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"legal-action enumeration checks passed: {len(la.ENUMERABLE_FAMILIES)} families, "
          f"{len(result['candidates'])} candidates, complete_action_set false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
