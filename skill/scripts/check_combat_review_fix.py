#!/usr/bin/env python3
"""
Gate for the Round D review-fix (Codex conditional reject on the first
R3-A3 delivery). Each check is a counterexample the first delivery lacked.

Must hold:
  - assignment → Deal is atomic: after assignment, a changed target zone,
    identity or replacement pool makes the Deal refuse the stale receipt as
    invalid_input, never a partial Deal;
  - when an attacker and a defender die together, each kill event names only
    the opposing side's Units as its sources (428.5.c.2) — in the underlying
    Cleanup trace, not only in a summary;
  - Cleanup step 2 precedes 3a/3b: a Shield Unit that arrived at the Combat
    Battlefield during the Showdown becomes a Defender before lethal damage
    is judged and survives; the resolution bridge does the same and reports
    the hash of the state it returns;
  - a Battlefield occupied by a teammate's Units is an invalid Standard Move
    destination (447.2.b); a decision envelope made for one Move declaration
    is refused for another (the declaration is part of the input hash);
  - a mutual Deal whose two events share one replacement descriptor is
    unsupported, not resolved one Deal after the other;
  - after a both-remain No Result the close stages a new Combat and the
    state allows no discretionary action before it opens.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_combat_area_and_mutual import DUEL  # noqa: E402
from check_combat_characteristics import opened  # noqa: E402
from check_combat_damage_assignment import add_unit, closed_combat  # noqa: E402
from check_combat_staging import contested_board  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from check_standard_move import declare  # noqa: E402
from combat import assign_combat_damage, close_combat, combat_cleanup, deal_combat_damage, determine_combat_result, standard_move  # noqa: E402
from effect_ir import apply_program, hash_value  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import next_procedure, validate_timing  # noqa: E402


def main() -> int:
    errors: list[str] = []

    # --- 1. assignment → Deal snapshot ------------------------------------------------------------------
    t, e = closed_combat([("d1", {})], attacker_might=5)
    assigned = assign_combat_damage(t, e)
    if not assigned.get("committed"):
        errors.append(f"setup: {assigned.get('reason_code')} {assigned.get('reason')}")
        print("FAILED: combat review-fix checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t1, e1 = assigned["next_timing_state"], assigned["next_effect_state"]
    if not t1["combat"].get("assignment_snapshot") or t1["combat"]["assignment_snapshot"]["effect_state_hash"] != hash_value(e1):
        errors.append("the assignment did not record the effect-state snapshot it was made on")
    moved = copy.deepcopy(e1); moved["battlefields"]["bf1"]["objects"].remove("d1"); moved["players"]["p2"]["zones"]["base"].append("d1")
    bounced = copy.deepcopy(e1); bounced["objects"]["d1"]["identity"] = "d1@1"
    pooled = copy.deepcopy(e1); pooled["replacement_effects"].append({"replacement_id": "late-ward", "controller": "p2", "source_object": "d1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 2, "target_object_id": "d1"})
    tampered = copy.deepcopy(t1); tampered["combat"]["assignments"]["attacker"]["entries"][0]["applied"] = 1
    for label, tt, ee in (("zone", t1, moved), ("identity", t1, bounced), ("replacement pool", t1, pooled), ("receipt", tampered, e1)):
        r = deal_combat_damage(tt, ee)
        if r.get("valid") is not False or r.get("committed"):
            errors.append(f"a changed {label} between assignment and Deal was not refused atomically: {r.get('reason_code')} {r.get('committed')}")
    if not deal_combat_damage(t1, e1).get("committed"):
        errors.append("the unchanged state was refused")

    # --- 2. per-object kill attribution -------------------------------------------------------------------
    t, e = closed_combat([("d1", {"might": 5})], attacker_might=5)
    a = assign_combat_damage(t, e); d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"]); c = combat_cleanup(d["next_timing_state"], d["next_effect_state"])
    if not c.get("committed"):
        errors.append(f"mutual lethal did not reach the Cleanup: {c.get('reason_code')} {c.get('reason')}")
    else:
        kills = {ev["object_id"]: ev for ev in c["trace"]["lethal_cleanup"] if ev.get("op") == "kill"}
        if kills.get("u1", {}).get("attributed_sources") != ["d1"] or kills.get("d1", {}).get("attributed_sources") != ["u1"]:
            errors.append(f"the underlying kill events do not name only the opposing side: {kills.get('u1', {}).get('attributed_sources')} {kills.get('d1', {}).get('attributed_sources')}")
        if c["trace"]["order"][0] != "323.2 designations":
            errors.append(f"the Combat Cleanup does not start with step 2: {c['trace']['order']}")

    # --- 3. designation before lethal: the late Shield Unit survives -------------------------------------------
    t, e = closed_combat([("d1", {})], attacker_might=5)
    add_unit(e, "d2", "p2", "bf1", might=3, keywords=["shield"], damage=3)  # arrived during the Showdown: no designation yet, 3 damage on 3 Might
    a = assign_combat_damage(t, e)
    if not a.get("committed"):
        errors.append(f"setup: assignment with the late Unit failed: {a.get('reason_code')} {a.get('reason')}")
    else:
        d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"])
        c = combat_cleanup(d["next_timing_state"], d["next_effect_state"]) if d.get("committed") else {}
        if not c.get("committed"):
            errors.append(f"cleanup with the late Unit failed: {d.get('reason_code')} {c.get('reason_code')} {c.get('reason')}")
        else:
            ec = c["next_effect_state"]
            if "d2" not in ec["battlefields"]["bf1"]["objects"] or ec["objects"]["d2"].get("combat_designation", {}).get("role") != "defender" or "d2" in c["trace"]["killed"]:
                errors.append("a Shield Unit designated at Cleanup step 2 was judged lethal before its Shield applied (323.2 before 323.4/323.5)")
            gained = [g["object_id"] for g in c["trace"]["designations"]["gained"]]
            if gained != ["d2"]:
                errors.append(f"step 2 did not designate the late Unit: {gained}")
            sched = [i["id"] for i in c["next_timing_state"]["chain"]["items"]]
            if sched and sched[0] != "d2-defend" and any(i.get("trigger_kind") == "self_death" for i in c["next_timing_state"]["chain"]["items"]):
                errors.append(f"designation triggers were not scheduled before death triggers: {sched}")
    # the same through the resolution bridge: a spell moves a wounded Shield Unit into the Combat
    timing, effect, _ = opened(contested_board(contested_by="p2"))  # p1 defends
    add_unit(effect, "u3", "p1", "base:p1", might=3, keywords=["shield"], damage=3)
    closed = copy.deepcopy(timing)
    closed["chain"] = {"initiated_by": "played_card", "items": [item("spell-1", "p1", "spell", "reaction", "finalized")], "consecutive_passes": ["p1", "p2"]}
    closed["priority"] = "p2"
    move = program("spell-1-effects", {"op": "move_board_object", "object_id": "u3", "destination": {"kind": "battlefield", "battlefield": "bf1"}, "effect_id": "mv"})
    resolved = resolve_with_program(closed, "spell-1", effect, move)
    if not resolved.get("committed"):
        errors.append(f"the bridge did not resolve the move into the Combat: {resolved.get('stage')} {resolved.get('reason') or resolved.get('errors')}")
    else:
        nxt = resolved["next_effect_state"]
        if "u3" not in nxt["battlefields"]["bf1"]["objects"] or nxt["objects"]["u3"].get("combat_designation", {}).get("role") != "defender":
            errors.append("the bridge's Cleanup judged the arriving Shield Unit lethal before designating it (323.2 before 323.4/323.5)")
        if resolved["next_effect_state_hash"] != hash_value(nxt):
            errors.append("the bridge reported a hash that is not the hash of the state it returned")
        if not resolved["trace"].get("combat_designations", {}).get("gained"):
            errors.append("the bridge trace shows no designation gained (vacuous sync)")

    # --- 4. Standard Move: teammate destination and declaration-bound decisions ----------------------------------
    quiet = fixture()
    state = base_state()
    state["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [], "rune_deck": []}, "resources": {"energy": 0, "power": {}}, "team_id": "A"}
    state["players"]["p1"]["team_id"] = "A"
    add_unit(state, "m1", "p3", "bf1", might=2)
    timing3 = fixture(); timing3["players"] = ["p1", "p2", "p3"]; timing3["turn_order"] = ["p1", "p2", "p3"]
    mate = standard_move(timing3, state, declare(["u1"], {"kind": "battlefield", "battlefield": "bf1"}))
    if mate.get("committed") or mate.get("reason_code") != "destination_has_teammate_units":
        errors.append(f"a Battlefield occupied by a teammate's Unit was a valid destination (447.2.b): {mate.get('reason_code')}")
    plain = base_state()
    d1 = declare(["u1"], {"kind": "battlefield", "battlefield": "bf1"})
    d2 = declare(["u1"], {"kind": "battlefield", "battlefield": "bf1"}, confirm=False)
    first = standard_move(quiet, plain, d1)
    if not first.get("committed"):
        errors.append(f"setup: plain move failed: {first.get('reason_code')} {first.get('errors')}")
    else:
        envelope = {"schema_version": "engine-decisions.v1", "input_hash": first["input_hash"], "decisions": []}
        replay = standard_move(quiet, plain, d2, envelope)
        if replay.get("valid") is not False:
            errors.append("a decision envelope made for one Move declaration was accepted for another")
        if standard_move(quiet, plain, d1, envelope).get("committed") is not True:
            errors.append("the envelope bound to the same declaration was refused")

    # --- 5. mutual Deal with a shared replacement descriptor --------------------------------------------------------
    shared = base_state()
    shared["replacement_effects"] = [{"replacement_id": "aegis", "controller": "p1", "source_object": "u1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 2}]
    both = apply_program(shared, program("duel", DUEL))
    if both.get("committed") or both.get("unsupported") is not True:
        errors.append(f"one Prevent over both Deals of the pair was resolved sequentially instead of refused: {both.get('reason')}")
    optional = copy.deepcopy(shared); optional["replacement_effects"][0].update({"optional": True, "target_object_id": "u2"})
    if apply_program(optional, program("duel", DUEL)).get("unsupported") is not True:
        errors.append("an optional replacement inside the simultaneous batch was not refused")

    # --- 6. both remain → a real restage, no free action -------------------------------------------------------------
    t, e = closed_combat([("d1", {"might": 6})], attacker_might=5)
    e["replacement_effects"] = [{"replacement_id": "u1-ward", "controller": "p1", "source_object": "u1", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 5, "target_object_id": "u1"}]
    a = assign_combat_damage(t, e); d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"]); c = combat_cleanup(d["next_timing_state"], d["next_effect_state"])
    if c.get("committed"):
        both_t, both_e = copy.deepcopy(c["next_timing_state"]), copy.deepcopy(c["next_effect_state"])
        both_t["combat"]["cleanup"]["recalled"] = []
        both_e["players"]["p1"]["zones"]["base"].remove("u1"); both_e["battlefields"]["bf1"]["objects"].append("u1")
        both_e["objects"]["u1"]["combat_designation"] = {"combat_id": both_t["combat"]["combat_id"], "role": "attacker"}
        rr = determine_combat_result(both_t, both_e)
        reclosed = close_combat(rr["next_timing_state"], rr["next_effect_state"]) if rr.get("committed") else {}
        if not reclosed.get("committed"):
            errors.append(f"the both-remain close failed: {rr.get('reason_code')} {reclosed.get('reason_code')} {reclosed.get('reason')}")
        else:
            tr = reclosed["next_timing_state"]
            if tr.get("combat", {}).get("status") != "staged" or next_procedure(tr).get("procedure") != "open_combat_pending":
                errors.append(f"after the close no Combat is staged as the next required procedure: {tr.get('combat')} {next_procedure(tr).get('procedure')}")
            if validate_timing(tr, {"actor": "p1", "kind": "play_card", "timing": "default"}).get("legal") is not False or standard_move(tr, reclosed["next_effect_state"], declare(["u1"], {"kind": "base"})).get("committed"):
                errors.append("a discretionary action was legal between the close and the restaged Combat's opening")

    if errors:
        print("FAILED: combat review-fix checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: the Deal refuses any change since assignment, each Combat kill names only the opposing side, designations precede lethal in the Combat Cleanup and in the bridge (which reports its final hash), a teammate-occupied Battlefield and a replayed Move envelope are refused, a shared replacement over a mutual Deal is unsupported, and a both-remain No Result stages a new Combat with no free action before it opens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
