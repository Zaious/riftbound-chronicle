#!/usr/bin/env python3
"""
Gate for C-26 (ADR-0008 §1–3): Combat staging, opening, designations and
Attack/Defend trigger synchronization.

Must hold:
  - stage_combat from a quiet Neutral Open Cleanup boundary: no candidate is
    a supported no-op; one candidate stages it; two need the Turn Player's
    location_selection (never the first key), refused from another player,
    invalid on an unknown Battlefield or a stale input hash; a Battlefield
    with three controllers is unsupported, never reduced to a pair; two
    teammates or a Battlefield without Contested is no candidate;
  - open_combat: attacker is contested_by, defender the other participant;
    a new Combat Showdown gives the attacker Focus; an existing Showdown at
    that Battlefield keeps its Focus; a Showdown elsewhere blocks; missing or
    foreign contested_by is unsupported, not guessed; participants changed
    after staging is refused; Units present gain designations and their
    Attack/Defend triggers go on the Combat Chain attacker first, defender
    last; same-controller collisions ask trigger_order; no trigger keeps the
    state open;
  - designations follow presence at Cleanup: a later Unit gains its
    designation and trigger once per identity; losing and regaining it does
    not trigger again; leaving through a non-Board zone and returning is a
    new identity and triggers again; a Unit elsewhere loses its designation;
    resolve_with_program runs the same synchronization after its Cleanup;
  - validators refuse an open Combat without its Combat Showdown, a
    designation with an unknown role, and a designation on a non-Unit;
  - determinism, purity, engine-check wrapping (supported / decision_required
    location_choice / unsupported / illegal) and the CLI off-cwd.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import LOCATION_DECISION_ID, combined_input_hash, open_combat, stage_combat, sync_combat_designations  # noqa: E402
from effect_ir import apply_program, hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import state_hash, validate_state as validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def trigger(trigger_id, controller, source, order=0, condition=None):
    value = {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": order,
             "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False}
    if condition:
        value["condition"] = {"kind": condition}
    return value


def contested_board(contested_by="p1", *, extra_units=()):
    """u1 (p1) and u2 (p2) at bf1, Contested applied by contested_by."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1"); state["players"]["p2"]["zones"]["base"].remove("u2")
    state["battlefields"]["bf1"]["objects"] += ["u1", "u2"]
    state["battlefields"]["bf1"].update({"contested": True, "contested_by": contested_by})
    for object_id, owner, where in extra_units:
        state["objects"][object_id] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
        if where.startswith("base:"):
            state["players"][where[5:]]["zones"]["base"].append(object_id)
        else:
            state["battlefields"].setdefault(where, {"controller": None, "objects": []})["objects"].append(object_id)
    return state


def decide(timing, effect, value, controller="p1", stale=False):
    return {"schema_version": "engine-decisions.v1", "input_hash": ("sha256:" + "0" * 64) if stale else combined_input_hash(timing, effect),
            "decisions": [{"decision_id": LOCATION_DECISION_ID, "stage": "procedure", "kind": "location_selection", "controller": controller, "value": value}]}


def main() -> int:
    errors: list[str] = []
    quiet = fixture()
    board = contested_board()

    # --- staging ----------------------------------------------------------------------------
    snap_t, snap_e = copy.deepcopy(quiet), copy.deepcopy(board)
    staged = stage_combat(quiet, board)
    record = staged.get("next_timing_state", {}).get("combat") if staged.get("committed") else None
    if not record or record["status"] != "staged" or record["battlefield"] != "bf1" or record["participants"] != ["p1", "p2"] or record["attacker"] is not None or staged["next_effect_state"] != board:
        errors.append(f"one staged Combat was not recorded: {staged.get('reason')} {record}")
    if quiet != snap_t or board != snap_e or stage_combat(quiet, board) != staged:
        errors.append("stage_combat mutated its inputs or is not deterministic")
    none = stage_combat(quiet, base_state())
    if not none.get("committed") or "combat" in none["next_timing_state"] or none["trace"].get("outcome") != "no_staged_combat":
        errors.append(f"zero candidates was not a supported no-op: {none.get('reason')}")
    two = contested_board(extra_units=(("u3", "p1", "bf2"), ("u4", "p2", "bf2")))
    two["battlefields"]["bf2"].update({"contested": True, "contested_by": "p2"})
    ask = stage_combat(quiet, two)
    if ask.get("committed") or ask.get("reason_code") != "location_selection_required" or ask.get("decision_controller") != "p1" or ask.get("options") != ["bf1", "bf2"]:
        errors.append(f"two staged Combats did not ask the Turn Player for a location_selection: {ask.get('reason_code')} {ask.get('options')}")
    else:
        check = build_engine_check("combat_step", ask, input_hashes={"timing_state": state_hash(quiet), "effect_state": hash_value(two)})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "location_choice" or check["decision_required"]["decision_ids"] != [LOCATION_DECISION_ID]:
            errors.append(f"location selection did not wrap as location_choice: {check.get('decision_required')}")
    chosen = stage_combat(quiet, two, decide(quiet, two, "bf2"))
    if not chosen.get("committed") or chosen["next_timing_state"]["combat"]["battlefield"] != "bf2" or chosen["trace"]["selection"] != "turn_player_decision":
        errors.append(f"the Turn Player's location choice was not honoured: {chosen.get('reason') or chosen.get('errors')}")
    other = stage_combat(quiet, two, decide(quiet, two, "bf2", controller="p2"))
    if other.get("committed") or other.get("reason_code") != "decision_controller_mismatch":
        errors.append("another player's location choice was accepted")
    if stage_combat(quiet, two, decide(quiet, two, "bf9")).get("valid") is not False or stage_combat(quiet, two, decide(quiet, two, "bf2", stale=True)).get("valid") is not False:
        errors.append("an unknown Battlefield or a stale decision hash was accepted")
    three = contested_board(extra_units=(("u5", "p3", "bf1"),))
    three["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [], "rune_deck": []}, "resources": {"energy": 0, "power": {}}}
    timing3 = fixture(); timing3["players"] = ["p1", "p2", "p3"]; timing3["turn_order"] = ["p1", "p2", "p3"]
    crowded = stage_combat(timing3, three)
    if crowded.get("committed") or crowded.get("unsupported") is not True or crowded.get("reason_code") != "multi_player_battlefield":
        errors.append(f"three controllers at one Battlefield were reduced to a pair or refused as illegal: {crowded.get('reason_code')}")
    team = contested_board(); team["players"]["p1"]["team_id"] = "A"; team["players"]["p2"]["team_id"] = "A"
    if stage_combat(quiet, team).get("trace", {}).get("outcome") != "no_staged_combat":
        errors.append("two teammates at a Battlefield staged a Combat")
    uncontested = contested_board(); uncontested["battlefields"]["bf1"].pop("contested"); uncontested["battlefields"]["bf1"].pop("contested_by")
    if stage_combat(quiet, uncontested).get("trace", {}).get("outcome") != "no_staged_combat":
        errors.append("a Battlefield without Contested staged a Combat (323.9)")
    busy = fixture(priority="p2", items=[item("spell-0", "p2", "spell", "default")])
    if stage_combat(busy, board).get("reason_code") != "combat_requires_quiet_cleanup_boundary":
        errors.append("staging ran with a chain open")

    # --- opening ----------------------------------------------------------------------------
    staged_timing = staged["next_timing_state"] if staged.get("committed") else quiet
    opened = open_combat(staged_timing, board)
    if not opened.get("committed"):
        errors.append(f"open_combat did not commit: {opened.get('reason') or opened.get('errors')}")
    else:
        t, e, rec = opened["next_timing_state"], opened["next_effect_state"], opened["next_timing_state"]["combat"]
        if rec["status"] != "open" or rec["attacker"] != "p1" or rec["defender"] != "p2" or t["showdown"] != {"active": True, "kind": "combat", "focus": "p1", "battlefield": "bf1"} or t["priority"] != "p1" or t["chain"]["items"]:
            errors.append(f"opening did not set attacker/defender, a Combat Showdown with the attacker's Focus and an open state: {rec} {t['showdown']} {t['priority']}")
        if e["objects"]["u1"].get("combat_designation") != {"combat_id": rec["combat_id"], "role": "attacker"} or e["objects"]["u2"].get("combat_designation") != {"combat_id": rec["combat_id"], "role": "defender"}:
            errors.append(f"Units present did not gain their controller's designation: {e['objects']['u1'].get('combat_designation')} {e['objects']['u2'].get('combat_designation')}")
        if validate_timing(t) or validate_state(e):
            errors.append(f"opened states invalid: {validate_timing(t)} {validate_state(e)}")
        if open_combat(staged_timing, board) != opened:
            errors.append("open_combat is not deterministic")
        check = build_engine_check("combat_step", opened, input_hashes={"timing_state": state_hash(staged_timing), "effect_state": hash_value(board)})
        if check["outcome"] != "supported" or "combat_opening" not in check["coverage"]["supported_scope"] or "battlefield_control_resolution" not in check["coverage"]["unsupported_scope"]:
            errors.append(f"engine-check did not wrap the opening with its scope: {check['outcome']}")
    # triggers: attacker first, then defender; once per identity
    armed = contested_board()
    armed["objects"]["u1"]["attack_triggers"] = [trigger("u1-attack", "p1", "u1")]
    armed["objects"]["u2"]["defend_triggers"] = [trigger("u2-defend", "p2", "u2")]
    armed["objects"]["u2"]["attack_triggers"] = [trigger("u2-attack", "p2", "u2")]  # must not fire: u2 defends
    armed_staged = stage_combat(quiet, armed)
    armed_open = open_combat(armed_staged["next_timing_state"], armed) if armed_staged.get("committed") else {}
    items = [i["id"] for i in armed_open.get("next_timing_state", {}).get("chain", {}).get("items", [])]
    if not armed_open.get("committed") or items != ["u1-attack", "u2-defend"] or armed_open["trace"].get("state_closed") is not True:
        errors.append(f"Attack/Defend triggers were not scheduled attacker first then defender: {items} {armed_open.get('reason')}")
    else:
        rec = armed_open["next_timing_state"]["combat"]
        if rec["triggered_identities"] != {"attacker": ["u1@0"], "defender": ["u2@0"]}:
            errors.append(f"triggered identities not recorded: {rec['triggered_identities']}")
        sched = armed_open["next_timing_state"]["chain"]["items"]
        if sched[0].get("batch_sequence") != 0 or sched[1].get("batch_sequence") != 2:
            errors.append("the attacker's batch does not precede the defender's (464.2.e.1)")
    collide = copy.deepcopy(armed); collide["objects"]["u1"]["attack_triggers"].append(trigger("u1-attack-2", "p1", "u1"))
    collide_staged = stage_combat(quiet, collide)
    ask_order = open_combat(collide_staged["next_timing_state"], collide) if collide_staged.get("committed") else {}
    if ask_order.get("committed") or ask_order.get("reason_code") != "trigger_order_required" or ask_order.get("decision_controller") != "p1":
        errors.append(f"two same-controller Attack triggers did not ask for a trigger_order decision: {ask_order.get('reason_code')}")
    # attribution and staging drift
    # the effect-state validator already requires contested_by with contested; the
    # attribution that can still be wrong is one naming a player who is not a participant
    foreign = contested_board(contested_by="p3")
    foreign["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [], "rune_deck": []}, "resources": {"energy": 0, "power": {}}}
    foreign_staged = stage_combat(timing3, foreign)
    no_attr = open_combat(foreign_staged["next_timing_state"], foreign) if foreign_staged.get("committed") else {}
    if no_attr.get("committed") or no_attr.get("unsupported") is not True or no_attr.get("reason_code") != "attacker_attribution_missing":
        errors.append(f"a contested_by outside the participants was guessed as attacker or refused as illegal: {foreign_staged.get('reason') or foreign_staged.get('errors')} {no_attr.get('reason_code')}")
    drifted = copy.deepcopy(board); drifted["battlefields"]["bf1"]["objects"].remove("u2"); drifted["players"]["p2"]["zones"]["base"].append("u2")
    gone = open_combat(staged_timing, drifted)
    if gone.get("committed") or gone.get("reason_code") != "combat_no_longer_staged":
        errors.append(f"a Combat whose participants changed after staging still opened: {gone.get('reason_code')}")
    restaged = stage_combat(staged_timing, drifted)
    if not restaged.get("committed") or "combat" in restaged["next_timing_state"]:
        errors.append("re-staging after the participants left did not clear the stale staged record (461.2)")
    # showdowns: existing at this battlefield keeps Focus; elsewhere blocks
    showdown_here = fixture(priority="p2", showdown=True, focus="p2"); showdown_here["showdown"]["kind"] = "non_combat"; showdown_here["showdown"]["battlefield"] = "bf1"
    here_staged = stage_combat(showdown_here, board)
    here_open = open_combat(here_staged["next_timing_state"], board) if here_staged.get("committed") else {}
    if not here_open.get("committed") or here_open["next_timing_state"]["showdown"] != {"active": True, "kind": "combat", "focus": "p2", "battlefield": "bf1"} or here_open["trace"]["opened_with"] != "existing_showdown":
        errors.append(f"an existing Showdown at the Battlefield did not keep its Focus (464.2.c.1.b): {here_open.get('reason')} {here_open.get('next_timing_state', {}).get('showdown')}")
    showdown_elsewhere = copy.deepcopy(showdown_here); showdown_elsewhere["showdown"]["battlefield"] = "bf2"
    elsewhere_state = copy.deepcopy(two)
    elsewhere_staged = stage_combat(showdown_elsewhere, elsewhere_state)
    if not elsewhere_staged.get("committed") or elsewhere_staged["next_timing_state"].get("combat", {}).get("battlefield") != "bf2":
        errors.append(f"during a Showdown, staging did not restrict itself to the Showdown's Battlefield (323.14): {elsewhere_staged.get('reason')}")
    stale_record = copy.deepcopy(staged_timing); stale_record["showdown"] = {"active": True, "kind": "non_combat", "focus": "p2", "battlefield": "bf2"}; stale_record["priority"] = "p2"
    if open_combat(stale_record, board).get("reason_code") != "showdown_elsewhere":
        errors.append("a Showdown at another Battlefield did not block opening")
    unknown_showdown = fixture(priority="p2", showdown=True, focus="p2"); unknown_showdown["showdown"]["kind"] = "non_combat"
    if stage_combat(unknown_showdown, board).get("reason_code") != "showdown_location_unknown":
        errors.append("a Showdown of unknown location was matched to a staged Combat")

    # --- designation synchronization --------------------------------------------------------
    if opened.get("committed"):
        t_open, e_open = opened["next_timing_state"], opened["next_effect_state"]
        late = copy.deepcopy(e_open)
        late["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False, "attack_triggers": [trigger("u3-attack", "p1", "u3")]}
        late["battlefields"]["bf1"]["objects"].append("u3")
        synced = sync_combat_designations(t_open, late)
        if not synced.get("committed") or synced["next_effect_state"]["objects"]["u3"].get("combat_designation", {}).get("role") != "attacker" or [i["id"] for i in synced["next_timing_state"]["chain"]["items"]] != ["u3-attack"]:
            errors.append(f"a later Unit did not gain its designation and trigger at Cleanup: {synced.get('reason')} {[i.get('id') for i in synced.get('next_timing_state', {}).get('chain', {}).get('items', [])]}")
        else:
            t2, e2 = synced["next_timing_state"], synced["next_effect_state"]
            t2_quiet = copy.deepcopy(t2); t2_quiet["chain"] = {"initiated_by": None, "items": [], "consecutive_passes": []}
            again = sync_combat_designations(t2_quiet, e2)
            if not again.get("committed") or again["next_timing_state"]["chain"]["items"]:
                errors.append("a Unit that already carries its designation triggered again")
            lost = copy.deepcopy(e2); del lost["objects"]["u3"]["combat_designation"]
            regained = sync_combat_designations(t2_quiet, lost)
            if not regained.get("committed") or regained["next_timing_state"]["chain"]["items"] or regained["next_effect_state"]["objects"]["u3"].get("combat_designation", {}).get("role") != "attacker" or not regained["trace"]["gained"][0].get("already_triggered_identity"):
                errors.append("losing and regaining the designation with the same identity triggered a second time (383.4.e.2.a)")
            bounced = apply_program(e2, program("bounce", {"op": "return_to_hand", "object_id": "u3", "effect_id": "b"}))
            if bounced.get("committed"):
                back = bounced["next_state"]
                if "combat_designation" in back["objects"]["u3"]:
                    errors.append("return_to_hand left a Combat designation on the new object (124.1)")
                back["players"]["p1"]["zones"]["hand"].remove("u3"); back["battlefields"]["bf1"]["objects"].append("u3")
                back["objects"]["u3"]["attack_triggers"] = [trigger("u3-attack", "p1", "u3")]
                returned = sync_combat_designations(t2_quiet, back)
                if not returned.get("committed") or [i["id"] for i in returned["next_timing_state"]["chain"]["items"]] != ["u3-attack"] or "u3@1" not in returned["next_timing_state"]["combat"]["triggered_identities"]["attacker"]:
                    errors.append(f"a Unit that left through a non-Board zone and returned was not treated as a new object (124): {returned.get('reason')} {returned.get('next_timing_state', {}).get('combat', {}).get('triggered_identities')}")
            away = copy.deepcopy(e2); away["battlefields"]["bf1"]["objects"].remove("u3"); away["players"]["p1"]["zones"]["base"].append("u3")
            left = sync_combat_designations(t2_quiet, away)
            if not left.get("committed") or "combat_designation" in left["next_effect_state"]["objects"]["u3"] or left["trace"]["lost"][0]["object_id"] != "u3":
                errors.append("a Unit no longer at the Combat Battlefield kept its designation (323.2.c)")
        # the resolution bridge synchronizes after its own Cleanup
        spell_state = copy.deepcopy(e_open)
        spell_state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False, "attack_triggers": [trigger("u3-attack", "p1", "u3")]}
        spell_state["players"]["p1"]["zones"]["base"].append("u3")
        closed = copy.deepcopy(t_open)
        closed["chain"] = {"initiated_by": "played_card", "items": [item("spell-1", "p1", "spell", "reaction", "finalized")], "consecutive_passes": ["p1", "p2"]}
        closed["priority"] = "p2"
        move = program("spell-1-effects", {"op": "move_board_object", "object_id": "u3", "destination": {"kind": "battlefield", "battlefield": "bf1"}, "effect_id": "mv"})
        resolved = resolve_with_program(closed, "spell-1", spell_state, move)
        if not resolved.get("committed") or resolved["next_effect_state"]["objects"]["u3"].get("combat_designation", {}).get("role") != "attacker" or "u3-attack" not in [i["id"] for i in resolved["next_timing_state"]["chain"]["items"]] or "u3@0" not in resolved["next_timing_state"]["combat"]["triggered_identities"]["attacker"]:
            errors.append(f"resolve_with_program did not synchronize designations after its Cleanup: {resolved.get('reason')} {resolved.get('stage')} {[i.get('id') for i in resolved.get('next_timing_state', {}).get('chain', {}).get('items', [])]}")
        elif resolved["trace"].get("combat_designations", {}).get("gained", [{}])[0].get("object_id") != "u3":
            errors.append("the resolution trace does not record the designation sync")

    # --- validators ---------------------------------------------------------------------------
    if opened.get("committed"):
        bad_timing = copy.deepcopy(opened["next_timing_state"]); bad_timing["showdown"] = {"active": False, "kind": None, "focus": None}; bad_timing["priority"] = "p1"
        if not validate_timing(bad_timing):
            errors.append("an open Combat without its Combat Showdown was accepted")
        bad_role = copy.deepcopy(opened["next_effect_state"]); bad_role["objects"]["u1"]["combat_designation"]["role"] = "bystander"
        if not validate_state(bad_role):
            errors.append("an unknown designation role was accepted")
        gear = copy.deepcopy(opened["next_effect_state"]); gear["objects"]["u1"]["kind"] = "gear"
        if not validate_state(gear):
            errors.append("a designation on a non-Unit was accepted")
    # --- CLI off-cwd ----------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="combat-staging-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(quiet), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(board), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "combat-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "stage", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI combat-step failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: combat staging checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Combat is staged only where Contested was applied and exactly two opposing players have Units (three controllers are unsupported, never paired), the Turn Player chooses among several staged Battlefields, opening names contested_by as attacker without guessing, gives a new Combat Showdown the attacker's Focus and keeps an existing one's, designates Units present and schedules Attack/Defend triggers attacker first, and Cleanup keeps designations in step with presence, triggering once per object identity.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
