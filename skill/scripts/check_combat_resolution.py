#!/usr/bin/env python3
"""
Gate for C-31 (ADR-0008 §10): simultaneous Combat Deal, Combat Cleanup,
result and closure.

Must hold:
  - deal_combat_damage Deals the receipts' applied amounts to every Unit at
    once with the opposing Units as sources; a previewed Prevent is consumed
    now and not applied a second time; FEPR is skipped; a Unit that left is
    skipped;
  - combat_cleanup kills Units with lethal damage and attributes each kill
    to the opposing side's Units and their controller (428.5.c.2), schedules
    their death triggers, heals every remaining Unit, Recalls Attackers when
    Defenders remain (466.1.a.2), and keeps designations in step;
  - determine_combat_result refuses while the Cleanup's chain is pending
    (466.2); a Recall is No Result; a lone remaining designated player wins;
    both remaining is No Result that stages again; neither is No Result;
  - close_combat removes designations, clears the Combat and Showdown
    records, expires every 'this combat' grant of this Combat at once, and
    runs only after resolve_battlefield_control (466.5, ADR-0009) or after a
    both-remain restage;
  - each step refuses out of order; determinism; engine-check wrapping.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_combat_damage_assignment import add_unit, closed_combat  # noqa: E402
from check_combat_staging import trigger  # noqa: E402
from battlefield_control import resolve_battlefield_control  # noqa: E402
from combat import assign_combat_damage, close_combat, combat_cleanup, deal_combat_damage, determine_combat_result, open_combat  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import next_procedure, state_hash, validate_state as validate_timing  # noqa: E402


def main() -> int:
    errors: list[str] = []

    # --- the decisive combat: u1 (5 Might) against d1 (3 Might, death trigger, Prevent 1) ----------------
    t, e = closed_combat([("d1", {"death_triggers": [trigger("d1-deathknell", "p2", "d1")]})], attacker_might=5)
    e["replacement_effects"] = [{"replacement_id": "ward", "controller": "p2", "source_object": "d1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 1, "target_object_id": "d1"}]
    e["objects"]["u1"]["keyword_modifiers"] = [{"modifier_id": "block", "keyword": "shield", "value": 2, "source": "block", "duration": "this_combat", "combat_id": t["combat"]["combat_id"], "target_identity": "u1@0"}]
    assigned = assign_combat_damage(t, e)
    if not assigned.get("committed"):
        errors.append(f"setup: assignment did not commit: {assigned.get('reason_code')} {assigned.get('reason')}")
        print("FAILED: combat resolution checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t1, e1 = assigned["next_timing_state"], assigned["next_effect_state"]
    if deal_combat_damage(t, e).get("reason_code") != "combat_damage_not_assigned":
        errors.append("damage was Dealt before assignment")
    snap_t, snap_e = copy.deepcopy(t1), copy.deepcopy(e1)
    dealt = deal_combat_damage(t1, e1)
    if not dealt.get("committed"):
        errors.append(f"deal_combat_damage did not commit: {dealt.get('reason_code')} {dealt.get('reason') or dealt.get('errors')}")
        print("FAILED: combat resolution checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t2, e2 = dealt["next_timing_state"], dealt["next_effect_state"]
    if e2["objects"]["d1"]["damage"] != 4 or e2["objects"]["u1"]["damage"] != 3 or t2["combat"]["status"] != "damage_dealt":
        errors.append(f"applied amounts were not Dealt at once (5 raw, 1 prevented → 4; 3 → 3): d1 {e2['objects']['d1']['damage']} u1 {e2['objects']['u1']['damage']}")
    if e2["replacement_effects"] or dealt["trace"]["consumed_replacements"][0].get("prevent_remaining_after") != 0 or dealt["trace"].get("replacements_reapplied") is not False:
        errors.append(f"the previewed Prevent was not consumed exactly once at Deal: {e2['replacement_effects']} {dealt['trace'].get('consumed_replacements')}")
    entry = dealt["trace"]["dealt"]["attacker"][0]
    if entry.get("sources") != ["u1"] or entry.get("responsible_player") != "p1" or dealt["trace"].get("fepr_skipped") is not True or t2["chain"]["items"]:
        errors.append(f"the Combat Damage sources / responsibility / skipped FEPR are wrong: {entry} {t2['chain']['items']}")
    if t1 != snap_t or e1 != snap_e or deal_combat_damage(t1, e1) != dealt:
        errors.append("deal_combat_damage mutated its inputs or is not deterministic")
    if combat_cleanup(t1, e1).get("reason_code") != "combat_damage_not_dealt":
        errors.append("the Combat Cleanup ran before damage was Dealt")
    cleaned = combat_cleanup(t2, e2)
    if not cleaned.get("committed"):
        errors.append(f"combat_cleanup did not commit: {cleaned.get('reason_code')} {cleaned.get('reason') or cleaned.get('errors')}")
        print("FAILED: combat resolution checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t3, e3 = cleaned["next_timing_state"], cleaned["next_effect_state"]
    if "d1" not in e3["players"]["p2"]["zones"]["trash"] or e3["objects"]["u1"]["damage"] != 0 or t3["combat"]["cleanup"]["killed"] != ["d1"] or t3["combat"]["cleanup"]["healed"] != ["u1"]:
        errors.append(f"the Cleanup did not kill d1, heal u1: {t3['combat'].get('cleanup')}")
    attribution = t3["combat"]["cleanup"]["attribution"].get("d1", {})
    if attribution.get("killed_by") != ["u1"] or attribution.get("responsible_player") != "p1":
        errors.append(f"the Combat-Damage kill was not attributed to the source Unit and its controller (428.5.c.2): {attribution}")
    if [i["id"] for i in t3["chain"]["items"]] != ["d1-deathknell"] or t3["combat"]["cleanup"]["recalled"]:
        errors.append(f"the death trigger was not scheduled, or Attackers were recalled with no Defender left: {[i.get('id') for i in t3['chain']['items']]} {t3['combat']['cleanup'].get('recalled')}")
    if validate_timing(t3) or validate_state(e3):
        errors.append(f"states after the Cleanup invalid: {validate_timing(t3)} {validate_state(e3)}")
    early = determine_combat_result(t3, e3)
    if early.get("committed") or early.get("reason_code") != "combat_chain_unfinished":
        errors.append(f"the result was determined while the death trigger was pending (466.2): {early.get('reason_code')}")
    settled = copy.deepcopy(t3); settled["chain"] = {"initiated_by": None, "items": [], "consecutive_passes": []}
    resulted = determine_combat_result(settled, e3)
    if not resulted.get("committed") or resulted["next_timing_state"]["combat"]["result"].get("outcome") != "win" or resulted["next_timing_state"]["combat"]["result"].get("winner") != "p1":
        errors.append(f"the attacker alone remaining did not win: {resulted.get('reason_code')} {resulted.get('next_timing_state', {}).get('combat', {}).get('result')}")
    else:
        t4, e4 = resulted["next_timing_state"], resulted["next_effect_state"]
        check = build_engine_check("combat_step", resulted, input_hashes={"timing_state": state_hash(settled), "effect_state": hash_value(e3)})
        if check["outcome"] != "supported" or "combat_result" not in check["coverage"]["supported_scope"]:
            errors.append("engine-check does not declare the result step")
        early_close = close_combat(t4, e4)
        if early_close.get("committed") or early_close.get("reason_code") != "control_resolution_pending":
            errors.append(f"a decisive Combat closed before 466.5 resolved control: {early_close.get('reason_code')}")
        owned = copy.deepcopy(e4); owned["battlefields"]["bf1"]["controller"] = "p1"; owned["mode"] = {"victory_score": 8}
        resolved_control = resolve_battlefield_control(t4, owned)
        closed = close_combat(resolved_control["next_timing_state"], resolved_control["next_effect_state"]) if resolved_control.get("committed") else {}
        if not closed.get("committed"):
            errors.append(f"closing a Combat whose winner already controls the Battlefield failed: {resolved_control.get('reason_code')} {closed.get('reason_code')} {closed.get('reason') or closed.get('errors')}")
        else:
            tc, ec = closed["next_timing_state"], closed["next_effect_state"]
            if "combat" in tc or tc["showdown"] != {"active": False, "kind": None, "focus": None} or tc["priority"] != "p1":
                errors.append(f"close did not clear the Combat and Showdown records: {tc.get('combat')} {tc['showdown']} {tc['priority']}")
            if "combat_designation" in ec["objects"]["u1"] or ec["objects"]["u1"].get("keyword_modifiers") or ec["battlefields"]["bf1"].get("contested") is not False or ec["battlefields"]["bf1"]["controller"] != "p1":
                errors.append(f"close did not remove designations, expire the this-combat grant or clear Contested: {ec['objects']['u1']} {ec['battlefields']['bf1']}")
            if closed["trace"].get("expired_this_combat", [{}])[0].get("modifier_id") != "block" or closed["trace"].get("simultaneous_expiry") is not True:
                errors.append("the expiry of this-combat effects is not recorded as simultaneous")
            if close_combat(resolved_control["next_timing_state"], resolved_control["next_effect_state"]) != closed:
                errors.append("close_combat is not deterministic")
        if close_combat(t3, e3).get("reason_code") != "combat_result_not_determined":
            errors.append("close ran before the result")

    # --- the Recall case: both survive, Attackers are Recalled, No Result ----------------------------------
    t, e = closed_combat([("d1", {"might": 6})], attacker_might=5)
    e["replacement_effects"] = [{"replacement_id": "u1-ward", "controller": "p1", "source_object": "u1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 5, "target_object_id": "u1"}]
    a = assign_combat_damage(t, e)
    d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"]) if a.get("committed") else {}
    c = combat_cleanup(d["next_timing_state"], d["next_effect_state"]) if d.get("committed") else {}
    if not c.get("committed"):
        errors.append(f"the Recall scenario did not reach the Cleanup: {a.get('reason_code')} {d.get('reason_code')} {c.get('reason_code')} {c.get('reason') or c.get('errors')}")
    else:
        tc, ec = c["next_timing_state"], c["next_effect_state"]
        if tc["combat"]["cleanup"]["recalled"] != ["u1"] or "u1" not in ec["players"]["p1"]["zones"]["base"] or "combat_designation" in ec["objects"]["u1"] or ec["objects"]["d1"]["damage"] != 0 or ec["objects"]["u1"]["damage"] != 0:
            errors.append(f"Attackers were not Recalled with Defenders remaining, or Units were not healed: {tc['combat'].get('cleanup')} {ec['objects']['u1'].get('combat_designation')}")
        r = determine_combat_result(tc, ec)
        if not r.get("committed") or r["next_timing_state"]["combat"]["result"].get("outcome") != "no_result" or r["next_timing_state"]["combat"]["result"].get("reason") != "attackers_recalled":
            errors.append(f"a Recall did not give No Result (466.3.d): {r.get('reason_code')} {r.get('next_timing_state', {}).get('combat', {}).get('result')}")
        else:
            if close_combat(r["next_timing_state"], r["next_effect_state"]).get("reason_code") != "control_resolution_pending":
                errors.append("the Recall case closed before control resolution")
            held = copy.deepcopy(r["next_effect_state"]); held["battlefields"]["bf1"]["controller"] = "p2"; held["mode"] = {"victory_score": 8}
            rc = resolve_battlefield_control(r["next_timing_state"], held)
            kept = close_combat(rc["next_timing_state"], rc["next_effect_state"]) if rc.get("committed") else {}
            if not kept.get("committed") or kept["trace"].get("control_step") != "controller_unchanged":
                errors.append(f"closing for a defender who already controls the Battlefield failed: {rc.get('reason_code')} {kept.get('reason_code')} {kept.get('reason')}")

    # --- both remain (a crafted state): No Result that stages again ------------------------------------------
    if c.get("committed"):
        both_t = copy.deepcopy(c["next_timing_state"]); both_e = copy.deepcopy(c["next_effect_state"])
        both_t["combat"]["cleanup"]["recalled"] = []
        both_e["players"]["p1"]["zones"]["base"].remove("u1"); both_e["battlefields"]["bf1"]["objects"].append("u1")
        both_e["objects"]["u1"]["combat_designation"] = {"combat_id": both_t["combat"]["combat_id"], "role": "attacker"}
        rr = determine_combat_result(both_t, both_e)
        if not rr.get("committed") or rr["next_timing_state"]["combat"]["result"].get("reason") != "both_remain" or rr["next_timing_state"]["combat"]["result"].get("restage_required") is not True:
            errors.append(f"both remaining did not give a No Result that stages again (466.3.d.1): {rr.get('reason_code')} {rr.get('next_timing_state', {}).get('combat', {}).get('result')}")
        else:
            reclosed = close_combat(rr["next_timing_state"], rr["next_effect_state"])
            if not reclosed.get("committed") or reclosed["trace"].get("restage_required") is not True or reclosed["next_effect_state"]["battlefields"]["bf1"].get("contested") is not True:
                errors.append(f"the restage close did not keep Contested for the next staging: {reclosed.get('reason_code')} {reclosed.get('reason')}")
            else:
                staged_again = reclosed["next_timing_state"].get("combat") or {}
                if staged_again.get("status") != "staged" or staged_again.get("restaged_from") != rr["next_timing_state"]["combat"]["combat_id"] or staged_again.get("triggered_identities") != {"attacker": [], "defender": []}:
                    errors.append(f"466.3.d.1: closing a both-remain No Result did not stage a new Combat with a fresh identity: {staged_again}")
                if next_procedure(reclosed["next_timing_state"]).get("discretionary_actions_allowed") is not False:
                    errors.append("after the restage the state allowed discretionary actions before the Combat opens")
                again = open_combat(reclosed["next_timing_state"], reclosed["next_effect_state"])
                if not again.get("committed") or again["next_timing_state"]["combat"]["status"] != "open":
                    errors.append(f"the restaged Combat did not open: {again.get('reason_code')} {again.get('reason')}")
    # --- neither remains: No Result; an Uncontrolled Battlefield stays so, a controlled one is the boundary --
    t, e = closed_combat([("d1", {"might": 5})], attacker_might=5)
    a = assign_combat_damage(t, e); d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"]); c2 = combat_cleanup(d["next_timing_state"], d["next_effect_state"])
    if not c2.get("committed") or sorted(c2["next_timing_state"]["combat"]["cleanup"]["killed"]) != ["d1", "u1"]:
        errors.append(f"mutual lethal did not kill both: {c2.get('reason_code')} {c2.get('next_timing_state', {}).get('combat', {}).get('cleanup')}")
    else:
        r2 = determine_combat_result(c2["next_timing_state"], c2["next_effect_state"])
        if not r2.get("committed") or r2["next_timing_state"]["combat"]["result"].get("reason") != "neither_remains":
            errors.append("neither remaining did not give No Result")
        else:
            emptied = copy.deepcopy(r2["next_effect_state"]); emptied["mode"] = {"victory_score": 8}
            rc2 = resolve_battlefield_control(r2["next_timing_state"], emptied)
            empty_close = close_combat(rc2["next_timing_state"], rc2["next_effect_state"]) if rc2.get("committed") else {}
            if not empty_close.get("committed") or empty_close["trace"].get("control_step") != "uncontrolled":
                errors.append(f"an Uncontrolled Battlefield emptied by Combat did not close: {rc2.get('reason_code')} {empty_close.get('reason_code')}")

    if errors:
        print("FAILED: combat resolution checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Combat Damage is Dealt at once from the receipts with the Units as sources and previewed Prevents consumed exactly once; the Combat Cleanup kills with attribution to the Combat Damage sources, schedules death triggers, heals and Recalls Attackers when Defenders remain; the result waits for that chain, a Recall is No Result, a lone player wins, both remaining stages again; closure clears designations, records and this-combat effects together only after resolve_battlefield_control has established control (ADR-0009).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
