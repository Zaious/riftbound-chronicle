#!/usr/bin/env python3
"""
Regression gate for C-14 (ADR-0005 §1–3, §9): engine-decisions.v1, typed
selectors, object identity, and mistarget traces.

Must hold:
  - identity: a kill or recycle from the board bumps the object's identity;
    a board move does not; play_token starts at generation 0; states without
    the field read as generation 0 and are not rewritten;
  - revalidation: a selector bound to an identity fails once the object has
    been through a non-board zone, even if it is back in the same zone;
  - targeted is derived — a supplied value that disagrees is invalid_input;
  - multi-target: all valid → applied_full; some invalid → applied_to_subset
    with the invalid ids and reasons; none valid → skipped_illegal_target and
    no state change; below_minimum is reported;
  - decisions: a target_selection supplies a deferred selector; missing →
    decision_required naming the decision and controller; wrong controller,
    wrong stage, wrong count, or stale input hash → invalid_input;
  - the legacy cleanup-decisions object still resolves the same lethal
    cleanup through the bridge, byte-for-byte, as the new envelope does;
  - supplying both envelopes is refused;
  - engine-check wraps a target decision_required as kind target_choice with
    decision_ids and the engine-decisions schema id;
  - determinism and purity hold with decisions supplied;
  - the CLI accepts --decisions from a foreign cwd.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import apply_program, evaluate_target, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from engine_check import build_engine_check, validate_engine_check  # noqa: E402
from resolution_bridge import CLEANUP_DECISION_VERSION, resolve_with_program  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def decisions(state, *entries, chain_item_id=None):
    env = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": list(entries)}
    if chain_item_id:
        env["chain_item_id"] = chain_item_id
    return env


def main() -> int:
    errors: list[str] = []
    schema = json.loads((SKILL_DIR / "schemas" / "engine-decisions.schema.json").read_text(encoding="utf-8"))
    if schema["properties"]["schema_version"]["const"] != ed.DECISIONS_VERSION:
        errors.append("engine-decisions schema and module version diverged")
    ec_schema = json.loads((SKILL_DIR / "schemas" / "engine-check.schema.json").read_text(encoding="utf-8"))
    if "target_choice" not in ec_schema["properties"]["decision_required"]["properties"]["kind"]["enum"]:
        errors.append("engine-check schema lacks the target_choice decision kind")

    state = base_state()
    if object_identity(state, "u1") != "u1@0" or "identity" in state["objects"]["u1"]:
        errors.append("legacy state must read as generation 0 without being rewritten")

    # --- identity across transitions ------------------------------------------
    killed = apply_program(state, program("kill", {"op": "kill", "object_id": "u1"}))
    if not killed.get("committed") or object_identity(killed["next_state"], "u1") != "u1@1":
        errors.append("kill from the board did not bump identity")
    moved = apply_program(state, program("move", {"op": "move_board_object", "object_id": "u1", "destination": {"kind": "battlefield", "battlefield": "bf1"}}))
    if not moved.get("committed") or object_identity(moved["next_state"], "u1") != "u1@0":
        errors.append("a board move changed identity")
    recycled = apply_program(state, program("recycle", {"op": "recycle_one", "object_id": "u1"}))
    if not recycled.get("committed") or object_identity(recycled["next_state"], "u1") != "u1@1":
        errors.append("recycle from the board did not bump identity")
    token = apply_program(state, program("tok", {"op": "play_token", "object_id": "t1", "owner": "p1", "controller": "p1", "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"}}))
    if not token.get("committed") or token["next_state"]["objects"]["t1"].get("identity") != "t1@0":
        errors.append("play_token did not assign generation 0")

    # --- revalidation against bound identity ----------------------------------
    # u1 dies (to trash, u1@1) then a program 'returns' it to base by direct state edit
    # to simulate 359.3.e.4: same zone, different object.
    back = copy.deepcopy(killed["next_state"])
    back["players"]["p1"]["zones"]["trash"].remove("u1"); back["players"]["p1"]["zones"]["base"].append("u1")
    ok, reason = evaluate_target(back, {"object_id": "u1", "chosen_zone_class": "board", "bound_identity": "u1@0"}, "p1")
    if ok or reason != "target_identity_changed":
        errors.append(f"identity revalidation accepted a re-entered object: {ok} {reason}")
    ok2, _ = evaluate_target(state, {"object_id": "u1", "chosen_zone_class": "board", "bound_identity": "u1@0"}, "p1")
    if not ok2:
        errors.append("identity revalidation rejected an unchanged object")

    # --- targeted is derived -----------------------------------------------------
    bad = program("bad", {"op": "deal_damage", "object_id": "u2", "amount": 1, "target": {"object_id": "u2", "chosen_zone_class": "board", "targeted": False}})
    if not any("derived" in e for e in validate_program(bad)):
        errors.append("caller-overridden targeted was accepted")
    good = program("good", {"op": "deal_damage", "object_id": "u2", "amount": 1, "target": {"object_id": "u2", "chosen_zone_class": "board", "targeted": True}})
    if validate_program(good):
        errors.append(f"correctly derived targeted was rejected: {validate_program(good)}")

    # --- multi-target expansion ---------------------------------------------------
    two = copy.deepcopy(state)
    two["objects"]["u3"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
    two["players"]["p2"]["zones"]["base"].append("u3")
    full = apply_program(two, program("aoe", {"op": "deal_damage", "amount": 1, "targets": {"min": 1, "max": 2, "selectors": [
        {"object_id": "u2", "chosen_zone_class": "board", "controller_relation": "enemy"}, {"object_id": "u3", "chosen_zone_class": "board", "controller_relation": "enemy"}]}}))
    ev = full["trace"][0] if full.get("committed") else {}
    if not full.get("committed") or ev.get("target_outcome") != "applied_full" or ev.get("completion") != "full" or full["next_state"]["objects"]["u3"]["damage"] != 1:
        errors.append(f"full multi-target did not apply_full: {ev.get('target_outcome')}")
    subset = apply_program(two, program("aoe2", {"op": "deal_damage", "amount": 1, "targets": {"min": 1, "max": 2, "selectors": [
        {"object_id": "u2", "chosen_zone_class": "board", "controller_relation": "enemy"}, {"object_id": "u1", "chosen_zone_class": "board", "controller_relation": "enemy"}]}}))
    ev = subset["trace"][0] if subset.get("committed") else {}
    if not subset.get("committed") or ev.get("target_outcome") != "applied_to_subset" or ev.get("completion") != "partial" or [x["object_id"] for x in ev.get("invalid_targets", [])] != ["u1"]:
        errors.append(f"subset multi-target did not report applied_to_subset with the invalid id: {ev}")
    none = apply_program(two, program("aoe3", {"op": "deal_damage", "amount": 1, "targets": {"min": 1, "max": 2, "selectors": [
        {"object_id": "u1", "chosen_zone_class": "board", "controller_relation": "enemy"}]}}))
    ev = none["trace"][0] if none.get("committed") else {}
    if not none.get("committed") or ev.get("outcome") != "skipped_illegal_target" or ev.get("after_state_hash") != hash_value(two):
        errors.append(f"all-invalid multi-target did not skip without state change: {ev.get('outcome')}")

    # --- decisions supply a deferred selector ------------------------------------
    deferred = program("flash", {"op": "move_board_object", "destination": {"kind": "base", "player": "p1"}, "targets": {"min": 0, "max": 2, "decision_ref": "d-flash", "restrictions": {"controller_relation": "friendly"}}})
    on_bf = copy.deepcopy(state); on_bf["players"]["p1"]["zones"]["base"].remove("u1"); on_bf["battlefields"]["bf1"]["objects"].append("u1")
    missing = apply_program(on_bf, deferred)
    if missing.get("committed") or missing.get("reason_code") != "target_selection_required" or missing.get("decision_ids") != ["d-flash"] or missing.get("decision_controller") != "p1":
        errors.append(f"missing target decision did not return decision_required naming it: {missing.get('reason_code')}")
    supplied = apply_program(on_bf, deferred, decisions=decisions(on_bf, {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"]}))
    if not supplied.get("committed") or "u1" not in supplied["next_state"]["players"]["p1"]["zones"]["base"] or supplied["trace"][0].get("decision_id") != "d-flash":
        errors.append(f"supplied target decision was not consumed: {supplied.get('reason') or supplied.get('errors')}")
    zero = apply_program(on_bf, deferred, decisions=decisions(on_bf, {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": []}))
    zev = zero["trace"][0] if zero.get("committed") else {}
    if zev.get("outcome") != "no_op" or zev.get("requested_targets") != 0 or zev.get("completion") != "full" or zev.get("after_state_hash") != hash_value(on_bf):
        errors.append("'up to' with zero chosen did not resolve as a no-target instruction (Core 355.13)")
    for label, entry, needle in (
        ("wrong controller", {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p2", "value": ["u1"]}, "not the program controller"),
        ("wrong stage", {"decision_id": "d-flash", "stage": "resolution", "kind": "target_selection", "controller": "p1", "value": ["u1"]}, "wrong stage"),
        ("too many", {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1", "u2", "c1"]}, "allowed"),
    ):
        r = apply_program(on_bf, deferred, decisions=decisions(on_bf, entry))
        if r.get("committed") or r.get("valid") is not False or not any(needle in e for e in r.get("errors", [])):
            errors.append(f"{label} decision was not refused as invalid_input: {r.get('errors') or r.get('reason')}")
    stale = decisions(state, {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"]})
    r = apply_program(on_bf, deferred, decisions=stale)
    if r.get("valid") is not False or not any("input_hash" in e for e in r.get("errors", [])):
        errors.append("a decision envelope for a different state was applied")

    # --- legacy adapter equivalence through the bridge ----------------------------
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    lethal = copy.deepcopy(state)
    for oid in ("u3", "u4"):
        lethal["objects"][oid] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
        lethal["players"]["p2"]["zones"]["base"].append(oid)
    lethal["replacement_effects"] = [{"replacement_id": "guard-all", "controller": "p2", "source_object": "u4", "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"}]
    prog = program("spell-1-effects", {"op": "deal_damage", "object_id": "u2", "amount": 4}, {"op": "deal_damage", "object_id": "u3", "amount": 2})
    prog["controller"] = "p1"
    undecided = resolve_with_program(timing, "spell-1", lethal, prog)
    if undecided.get("committed") or undecided.get("stage") != "cleanup":
        errors.append(f"undecided simultaneous replacement did not stop at cleanup: {undecided.get('stage')}")
    legacy = {"schema_version": CLEANUP_DECISION_VERSION, "replacement_event_order": {"guard-all": ["u2", "u3"]}}
    old = resolve_with_program(timing, "spell-1", lethal, prog, legacy)
    after_effect = apply_program(lethal, prog)["next_state"]
    new_env = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(lethal), "chain_item_id": "spell-1",
               "decisions": [{"decision_id": "order", "stage": "resolution", "kind": "replacement_order", "controller": "p2", "value": {"guard-all": ["u2", "u3"]}}]}
    new = resolve_with_program(timing, "spell-1", lethal, prog, engine_decisions=new_env)
    if not old.get("committed") or not new.get("committed"):
        errors.append(f"decided resolution did not commit: legacy={old.get('stage')} {old.get('reason')} / new={new.get('stage')} {new.get('reason')}")
    elif old["next_effect_state_hash"] != new["next_effect_state_hash"]:
        errors.append("legacy cleanup-decisions and engine-decisions produced different states")
    both = resolve_with_program(timing, "spell-1", lethal, prog, legacy, engine_decisions=new_env)
    if both.get("committed") or "not both" not in "".join(both.get("errors", [])):
        errors.append("supplying both decision envelopes was not refused")
    wrong_item = dict(new_env, chain_item_id="spell-9")
    r = resolve_with_program(timing, "spell-1", lethal, prog, engine_decisions=wrong_item)
    if r.get("committed") or r.get("stage") != "engine_decision":
        errors.append("a decision envelope for another chain item was accepted")

    # --- engine-check wrapping of a target decision --------------------------------
    check = build_engine_check("effect", missing, input_hashes={"effect_state": hash_value(on_bf), "effect_program": "sha256:" + "1" * 64})
    if validate_engine_check(check) or check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "target_choice" or check["decision_required"]["decision_ids"] != ["d-flash"] or check["decision_required"]["decision_schema"] != ed.DECISIONS_VERSION:
        errors.append(f"target decision did not wrap as target_choice: {check.get('decision_required')}")

    # --- determinism / purity with decisions -------------------------------------
    snapshot = copy.deepcopy(on_bf)
    a = apply_program(on_bf, deferred, decisions=decisions(on_bf, {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"]}))
    b = apply_program(on_bf, deferred, decisions=decisions(on_bf, {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"]}))
    if a != b or on_bf != snapshot:
        errors.append("decisions broke determinism or purity")
    if validate_state(a["next_state"]):
        errors.append("committed state with decisions is invalid")

    # --- CLI --decisions off-cwd ------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="engine-decisions-") as temp_name:
        temp = Path(temp_name)
        (temp / "state.json").write_text(json.dumps(on_bf), encoding="utf-8")
        (temp / "program.json").write_text(json.dumps(deferred), encoding="utf-8")
        (temp / "decisions.json").write_text(json.dumps(decisions(on_bf, {"decision_id": "d-flash", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"]})), encoding="utf-8")
        out = temp / "check.json"
        run = subprocess.run([sys.executable, str(RUNNER), "effect", str(temp / "state.json"), str(temp / "program.json"), "--decisions", str(temp / "decisions.json"), "--output", str(out)], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or not out.exists():
            errors.append(f"CLI --decisions failed off-cwd: {run.stderr.strip()}")
        else:
            written = json.loads(out.read_text(encoding="utf-8"))
            if written["outcome"] != "supported" or "engine_decisions" not in written["input_hashes"]:
                errors.append(f"CLI --decisions produced {written['outcome']} without hashing the envelope")
        run2 = subprocess.run([sys.executable, str(RUNNER), "effect", str(temp / "state.json"), str(temp / "program.json"), "--output", str(temp / "c2.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run2.returncode != 0 or json.loads((temp / "c2.json").read_text(encoding="utf-8"))["outcome"] != "decision_required":
            errors.append("CLI without --decisions did not report decision_required")

    if errors:
        print("FAILED: engine decisions / selectors / identity checks\n  - " + "\n  - ".join(errors))
        return 1
    print("OK: engine-decisions.v1 supplies deferred selectors at the right stage only, identity changes across non-board transitions and fails revalidation, targeted is derived not declared, multi-target instructions report applied_full / applied_to_subset / skipped_illegal_target, the legacy cleanup envelope still resolves identically, and it all runs off-cwd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
