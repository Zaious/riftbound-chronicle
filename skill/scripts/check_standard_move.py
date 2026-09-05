#!/usr/bin/env python3
"""
Gate for C-28 (ADR-0008 §6): the atomic Standard Move and Ganking.

Must hold:
  - the Turn Player moves ready Units they control from their Base to a
    Battlefield or from a Battlefield to their own Base; every selected Unit
    exhausts at once as the cost and shares one destination; origins may
    differ; the relocation is the Move operation, so a Unit's move trigger
    is scheduled and Cleanup ran;
  - a missing cost confirmation stops for a cost_choice decision, nothing
    moved; an exhausted Unit, a Unit the actor does not control, a Unit
    already at the destination, and Battlefield→Battlefield without
    Ganking are illegal; Ganking allows Battlefield→Battlefield only — it
    waives nothing else (Base→Battlefield unchanged, an enemy Base never);
    a Battlefield holding two other players' Units is refused (144.4.a.1);
  - timing: a Closed State, a Showdown, the opponent's turn, another
    phase, and a staged or open Combat are illegal (144.1);
  - a malformed declaration, an unknown Battlefield or a stale unit
    identity is invalid_input;
  - purity, determinism, engine-check wrapping and the CLI off-cwd.
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

from check_combat_staging import contested_board, trigger  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import STANDARD_MOVE_DECLARATION_VERSION, stage_combat, standard_move  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import state_hash, validate_state as validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def declare(units, destination, *, actor="p1", confirm=True, identities=None):
    value = {"schema_version": STANDARD_MOVE_DECLARATION_VERSION, "actor": actor, "units": list(units), "destination": destination}
    if confirm:
        value["cost_confirmation"] = {"exhaust_confirmed": True}
    if identities:
        value["unit_identities"] = identities
    return value


def main() -> int:
    errors: list[str] = []
    quiet = fixture()
    state = base_state()
    state["objects"]["u1"]["move_triggers"] = [trigger("u1-on-move", "p1", "u1")]
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("u3")
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    to_bf1 = {"kind": "battlefield", "battlefield": "bf1"}

    snap_t, snap_e = copy.deepcopy(quiet), copy.deepcopy(state)
    moved = standard_move(quiet, state, declare(["u1", "u3"], to_bf1))
    if not moved.get("committed"):
        errors.append(f"a Base→Battlefield Standard Move of two Units did not commit: {moved.get('reason') or moved.get('errors')}")
    else:
        e, t = moved["next_effect_state"], moved["next_timing_state"]
        if e["battlefields"]["bf1"]["objects"] != ["u1", "u3"] or not e["objects"]["u1"]["exhausted"] or not e["objects"]["u3"]["exhausted"]:
            errors.append(f"Units did not arrive exhausted at one destination: {e['battlefields']['bf1']['objects']}")
        if [i["id"] for i in t["chain"]["items"]] != ["u1-on-move"] or moved["trace"]["cost"] != {"exhausted": ["u1", "u3"], "simultaneous": True}:
            errors.append(f"the Move trigger was not scheduled or the cost not recorded: {[i.get('id') for i in t['chain']['items']]} {moved['trace'].get('cost')}")
        if validate_timing(t) or validate_state(e):
            errors.append(f"states after the move invalid: {validate_timing(t)} {validate_state(e)}")
        check = build_engine_check("standard_move", moved, input_hashes={"timing_state": state_hash(quiet), "effect_state": hash_value(state), "move_declaration": "sha256:" + "7" * 64})
        if check["outcome"] != "supported" or "ganking" not in check["coverage"]["supported_scope"]:
            errors.append(f"engine-check did not wrap the move as supported: {check['outcome']}")
    if quiet != snap_t or state != snap_e or standard_move(quiet, state, declare(["u1", "u3"], to_bf1)) != moved:
        errors.append("standard_move mutated its inputs or is not deterministic")
    unconfirmed = standard_move(quiet, state, declare(["u1"], to_bf1, confirm=False))
    if unconfirmed.get("committed") or unconfirmed.get("reason_code") != "cost_confirmation_required" or unconfirmed.get("decision_controller") != "p1":
        errors.append(f"an unconfirmed exhaust cost did not stop for a decision: {unconfirmed.get('reason_code')}")
    else:
        check = build_engine_check("standard_move", unconfirmed, input_hashes={"timing_state": state_hash(quiet), "effect_state": hash_value(state), "move_declaration": "sha256:" + "7" * 64})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "cost_choice":
            errors.append(f"the cost confirmation did not wrap as cost_choice: {check.get('decision_required')}")
    tired = copy.deepcopy(state); tired["objects"]["u3"]["exhausted"] = True
    if standard_move(quiet, tired, declare(["u1", "u3"], to_bf1)).get("reason_code") != "unit_exhausted":
        errors.append("an exhausted Unit paid the exhaust cost (144.2)")
    if standard_move(quiet, state, declare(["u2"], to_bf1)).get("reason_code") != "unit_not_controlled_board_unit":
        errors.append("the opponent's Unit was moved")
    # from a Battlefield: own Base yes, another Battlefield only with Ganking
    at_bf = copy.deepcopy(state); at_bf["players"]["p1"]["zones"]["base"].remove("u1"); at_bf["battlefields"]["bf1"]["objects"].append("u1")
    home = standard_move(quiet, at_bf, declare(["u1"], {"kind": "base"}))
    if not home.get("committed") or "u1" not in home["next_effect_state"]["players"]["p1"]["zones"]["base"] or not home["next_effect_state"]["objects"]["u1"]["exhausted"]:
        errors.append(f"Battlefield→own Base was refused: {home.get('reason_code')} {home.get('errors')}")
    if standard_move(quiet, at_bf, declare(["u1"], {"kind": "battlefield", "battlefield": "bf2"})).get("reason_code") != "ganking_required":
        errors.append("Battlefield→Battlefield without Ganking was allowed (144.4.c)")
    if standard_move(quiet, at_bf, declare(["u1"], to_bf1)).get("reason_code") != "already_at_destination":
        errors.append("a Unit was moved to the Battlefield it is at")
    if standard_move(quiet, state, declare(["u1"], {"kind": "base"})).get("reason_code") != "already_at_base":
        errors.append("a Unit at its Base was moved to its Base")
    ganker = copy.deepcopy(at_bf); ganker["objects"]["u1"]["keywords"] = ["ganking"]
    gank = standard_move(quiet, ganker, declare(["u1"], {"kind": "battlefield", "battlefield": "bf2"}))
    if not gank.get("committed") or gank["next_effect_state"]["battlefields"]["bf2"]["objects"] != ["u1"] or gank["trace"]["ganking_used"] != ["u1"] or not gank["next_effect_state"]["objects"]["u1"]["exhausted"]:
        errors.append(f"Ganking did not allow Battlefield→Battlefield with the exhaust cost: {gank.get('reason_code')} {gank.get('errors')}")
    mixed = copy.deepcopy(ganker)  # u1 (ganking) at bf1, u3 at base: different origins, one destination
    both = standard_move(quiet, mixed, declare(["u1", "u3"], {"kind": "battlefield", "battlefield": "bf2"}))
    if not both.get("committed") or sorted(both["next_effect_state"]["battlefields"]["bf2"]["objects"]) != ["u1", "u3"] or both["trace"]["ganking_used"] != ["u1"]:
        errors.append(f"different origins to one destination failed: {both.get('reason_code')} {both.get('errors')}")
    if standard_move(quiet, mixed, declare(["u1", "u3"], {"kind": "base"})).get("reason_code") != "already_at_base":
        errors.append("a mixed selection with a Unit at its Base was accepted for a move home")
    granted = copy.deepcopy(at_bf)
    granted["objects"]["u1"]["keyword_modifiers"] = [{"modifier_id": "g", "keyword": "ganking", "source": "spell", "duration": "this_turn", "turn_id": "turn-0", "target_identity": "u1@0"}]
    if not standard_move(quiet, granted, declare(["u1"], {"kind": "battlefield", "battlefield": "bf2"})).get("committed"):
        errors.append("a granted Ganking did not allow Battlefield→Battlefield")
    stale_grant = copy.deepcopy(granted); stale_grant["objects"]["u1"]["keyword_modifiers"][0]["turn_id"] = "turn-9"
    if standard_move(quiet, stale_grant, declare(["u1"], {"kind": "battlefield", "battlefield": "bf2"})).get("reason_code") != "ganking_required":
        errors.append("a Ganking granted for another turn still applied")
    crowded = copy.deepcopy(state)
    crowded["players"]["p3"] = {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [], "rune_deck": []}, "resources": {"energy": 0, "power": {}}}
    crowded["objects"]["u5"] = {"owner": "p3", "controller": "p3", "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False}
    crowded["players"]["p2"]["zones"]["base"].remove("u2"); crowded["battlefields"]["bf1"]["objects"] += ["u2", "u5"]
    timing3 = fixture(); timing3["players"] = ["p1", "p2", "p3"]; timing3["turn_order"] = ["p1", "p2", "p3"]
    if standard_move(timing3, crowded, declare(["u1"], to_bf1)).get("reason_code") != "destination_has_two_other_players":
        errors.append("a Battlefield with two other players' Units was a valid destination (144.4.a.1)")
    # timing
    closed = fixture(priority="p1", items=[item("spell-0", "p2", "spell", "default")])
    if standard_move(closed, state, declare(["u1"], to_bf1)).get("reason_code") != "standard_move_requires_neutral_open":
        errors.append("a Standard Move ran in a Closed State (144.1.b)")
    showdown = fixture(showdown=True, focus="p1", priority="p1"); showdown["showdown"]["kind"] = "non_combat"; showdown["showdown"]["battlefield"] = "bf2"
    if standard_move(showdown, state, declare(["u1"], to_bf1)).get("reason_code") != "standard_move_requires_neutral_open":
        errors.append("a Standard Move ran during a Showdown (144.1.c)")
    theirs = fixture(); theirs["turn_player"] = "p2"; theirs["priority"] = "p2"; theirs["turn_order"] = ["p2", "p1"]; theirs["players"] = ["p2", "p1"]
    if standard_move(theirs, state, declare(["u1"], to_bf1)).get("reason_code") != "standard_move_requires_own_main_phase":
        errors.append("a Standard Move ran on the opponent's turn (144.1.a)")
    ending = fixture(); ending["phase"] = "ending"; ending["priority"] = None
    if standard_move(ending, state, declare(["u1"], to_bf1)).get("reason_code") not in {"standard_move_requires_own_main_phase", "procedure_blocks_discretionary_action"}:
        errors.append("a Standard Move ran outside the Main Phase (144.1.a)")
    staged = stage_combat(quiet, contested_board())
    if staged.get("committed") and standard_move(staged["next_timing_state"], contested_board(), declare(["u1"], {"kind": "base"})).get("reason_code") != "standard_move_blocked_by_combat":
        errors.append("a Standard Move ran with a Combat staged (144.1.c)")
    # invalid input
    if standard_move(quiet, state, declare(["u1"], {"kind": "battlefield", "battlefield": "bf9"})).get("valid") is not False:
        errors.append("an unknown Battlefield was accepted")
    if standard_move(quiet, state, declare(["u1"], to_bf1, identities={"u1": "u1@4"})).get("valid") is not False:
        errors.append("a stale unit identity was accepted")
    if standard_move(quiet, state, {"schema_version": "x"}).get("valid") is not False or standard_move(quiet, state, declare([], to_bf1)).get("valid") is not False:
        errors.append("a malformed declaration was accepted")
    with tempfile.TemporaryDirectory(prefix="standard-move-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(quiet), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(state), encoding="utf-8")
        (temp / "d.json").write_text(json.dumps(declare(["u1", "u3"], to_bf1)), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "standard-move", str(temp / "t.json"), str(temp / "e.json"), str(temp / "d.json"), "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI standard-move failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: standard move checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a Standard Move is the Turn Player's action in their Main Phase in Neutral Open with no Combat staged or in progress: ready Units they control exhaust together as the cost and go to one destination from any origins, Base to Battlefield or Battlefield to own Base, Battlefield to Battlefield only with active Ganking which waives nothing else; the relocation is the Move operation with its triggers and Cleanup; an unconfirmed cost is a decision, a forbidden route illegal, a malformed declaration invalid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
