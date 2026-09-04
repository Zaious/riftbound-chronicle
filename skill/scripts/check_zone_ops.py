#!/usr/bin/env python3
"""
Regression gate for C-16 (ADR-0005 §6, §8; DP-06, DP-08): `return_to_hand`,
`recall`, `channel_rune` are three distinct events.

Must hold:
  - return_to_hand: from the board or the owner's trash to the owner's hand;
    new identity; damage, modifiers, exhaustion cleared; not a Move; a token
    ceases to exist; from any other zone → illegal; selector restrictions
    (location, max_might) produce ignored_illegal_target at resolution;
    multi-target expansion works;
  - recall: to the *current controller's* Base; identity unchanged; damage,
    exhaustion, modifiers retained; already at that Base → no_op with
    completion none; not on the board → illegal; never emits a Move trigger;
  - channel_rune: top runes → Base with the stated entry state (ready by
    default); new identities; short deck → partial with requested/applied
    counts; empty → no_op / none; bad entry state → invalid_input;
  - replacement framework accepts the new ops as event_op;
  - engine-check maps illegal operations to `illegal`; the live manifest
    lists the three ops with locators; determinism and purity; off-cwd CLI.
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

from capability_manifest import build_manifest  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import OP_RULES, SUPPORTED_OPS, apply_program, hash_value, object_identity, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def main() -> int:
    errors: list[str] = []
    state = base_state()
    state["objects"]["u1"]["might_modifiers"] = [{"amount": 2, "duration": "this_turn", "source": "x"}]
    state["objects"]["u1"]["exhausted"] = True  # damage 1 already in the fixture
    snapshot = copy.deepcopy(state)

    def ev(result):
        return result["trace"][0] if result.get("committed") else {}

    # --- return_to_hand ------------------------------------------------------------
    back = apply_program(state, program("ret", {"op": "return_to_hand", "object_id": "u1"}))
    e = ev(back)
    if not back.get("committed") or "u1" not in back["next_state"]["players"]["p1"]["zones"]["hand"] or "u1" in back["next_state"]["players"]["p1"]["zones"]["base"]:
        errors.append(f"return_to_hand did not move the unit to its owner's hand: {back.get('reason') or back.get('errors')}")
    else:
        obj = back["next_state"]["objects"]["u1"]
        if object_identity(back["next_state"], "u1") != "u1@1" or obj["damage"] != 0 or obj["might_modifiers"] or obj["exhausted"]:
            errors.append(f"returned object kept something of the old object: {obj}")
        if e.get("not_a_move") is not True or e.get("pending_triggers") or "Core 446.2" not in e.get("rule_locators", []):
            errors.append(f"return_to_hand recorded as a move or with triggers: {e}")
        if validate_state(back["next_state"]):
            errors.append(f"state after return invalid: {validate_state(back['next_state'])}")
    if state != snapshot or apply_program(state, program("ret", {"op": "return_to_hand", "object_id": "u1"})) != back:
        errors.append("return_to_hand mutated its input or is not deterministic")
    # from the owner's trash (Morbid Return)
    from_trash = apply_program(state, program("mr", {"op": "return_to_hand", "object_id": "c3"}))
    if not from_trash.get("committed") or "c3" not in from_trash["next_state"]["players"]["p1"]["zones"]["hand"] or object_identity(from_trash["next_state"], "c3") != "c3@1":
        errors.append("return from the owner's trash failed")
    # from the deck → illegal (engine-check illegal, not invalid_input)
    from_deck = apply_program(state, program("bad", {"op": "return_to_hand", "object_id": "c1"}))
    if from_deck.get("committed") or from_deck.get("valid") is not True or from_deck.get("applied") is not False or from_deck.get("reason_code") != "illegal_operation":
        errors.append(f"return from the deck was not illegal: {from_deck.get('reason_code')} {from_deck.get('errors')}")
    else:
        check = build_engine_check("effect", from_deck, input_hashes={"effect_state": hash_value(state), "effect_program": "sha256:" + "1" * 64})
        if check["outcome"] != "illegal":
            errors.append(f"illegal return wrapped as {check['outcome']}")
    # opponent's trash is not the owner's
    foreign = copy.deepcopy(state); foreign["players"]["p1"]["zones"]["trash"].remove("c3"); foreign["players"]["p2"]["zones"]["trash"].append("c3")
    if apply_program(foreign, program("bad2", {"op": "return_to_hand", "object_id": "c3"})).get("applied") is not False:
        errors.append("return from another player's trash was accepted")
    # token ceases to exist
    with_token = apply_program(state, program("tok", {"op": "play_token", "object_id": "t1", "owner": "p1", "controller": "p1", "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"}}))["next_state"]
    gone = apply_program(with_token, program("ret-tok", {"op": "return_to_hand", "object_id": "t1"}))
    if not gone.get("committed") or "t1" in gone["next_state"]["objects"] or ev(gone).get("destination") != "ceased_to_exist":
        errors.append("a returned token did not cease to exist")
    # Gust: "a unit at a battlefield with 3 Might or less"
    bf = copy.deepcopy(state); bf["players"]["p1"]["zones"]["base"].remove("u1"); bf["battlefields"]["bf1"]["objects"].append("u1")  # might 3+2=5
    gust = program("gust", {"op": "return_to_hand", "object_id": "u1", "target": {"object_id": "u1", "chosen_zone_class": "board", "location": "battlefield", "max_might": 3}})
    too_big = apply_program(bf, gust)
    if not too_big.get("committed") or ev(too_big).get("outcome") != "ignored_illegal_target":
        errors.append(f"Gust on a 5-Might unit was not ignored_illegal_target: {ev(too_big).get('outcome')}")
    bf["objects"]["u1"]["might_modifiers"] = []
    fits = apply_program(bf, gust)
    if not fits.get("committed") or ev(fits).get("outcome") != "applied" or "u1" not in fits["next_state"]["players"]["p1"]["zones"]["hand"]:
        errors.append("Gust on a 3-Might unit at a battlefield did not return it")
    at_base = apply_program(state, gust)
    if ev(at_base).get("outcome") != "ignored_illegal_target":
        errors.append("Gust on a unit at Base was not ignored_illegal_target")
    multi = apply_program(state, program("multi", {"op": "return_to_hand", "targets": {"min": 1, "max": 2, "selectors": [
        {"object_id": "u1", "chosen_zone_class": "board"}, {"object_id": "u2", "chosen_zone_class": "board"}]}}))
    if not multi.get("committed") or ev(multi).get("target_outcome") != "applied_full" or "u2" not in multi["next_state"]["players"]["p2"]["zones"]["hand"]:
        errors.append(f"multi-target return did not apply to both: {ev(multi).get('target_outcome')} {multi.get('reason')}")

    # --- recall ------------------------------------------------------------------------
    bf2 = copy.deepcopy(state); bf2["players"]["p1"]["zones"]["base"].remove("u1"); bf2["battlefields"]["bf1"]["objects"].append("u1")
    recalled = apply_program(bf2, program("rc", {"op": "recall", "object_id": "u1"}))
    e = ev(recalled)
    if not recalled.get("committed") or "u1" not in recalled["next_state"]["players"]["p1"]["zones"]["base"]:
        errors.append(f"recall did not relocate to the controller's base: {recalled.get('reason') or recalled.get('errors')}")
    else:
        obj = recalled["next_state"]["objects"]["u1"]
        if object_identity(recalled["next_state"], "u1") != "u1@0" or obj["damage"] != 1 or len(obj["might_modifiers"]) != 1 or not obj["exhausted"]:
            errors.append(f"recall changed identity or dropped state: {obj}")
        if e.get("not_a_move") is not True or e.get("pending_triggers") or e.get("completion") != "full" or "Core 456.1" not in e.get("rule_locators", []):
            errors.append(f"recall recorded as a move or incomplete: {e}")
    # controlled by the opponent: goes to the controller's base, not the owner's
    stolen = copy.deepcopy(bf2); stolen["objects"]["u1"]["controller"] = "p2"
    to_p2 = apply_program(stolen, program("rc2", {"op": "recall", "object_id": "u1"}))
    if not to_p2.get("committed") or "u1" not in to_p2["next_state"]["players"]["p2"]["zones"]["base"]:
        errors.append("recall of an opponent-controlled unit did not go to the controller's base")
    already = apply_program(state, program("rc3", {"op": "recall", "object_id": "u1"}))
    e = ev(already)
    if not already.get("committed") or e.get("outcome") != "no_op" or e.get("completion") != "none" or already["next_state"] != state:
        errors.append(f"recall of a unit already at its base was not a no-op with completion none: {e.get('outcome')} {e.get('completion')}")
    off_board = apply_program(state, program("rc4", {"op": "recall", "object_id": "c3"}))
    if off_board.get("applied") is not False or off_board.get("reason_code") != "illegal_operation":
        errors.append("recall of a trash card was not illegal")
    # a replacement keyed to recall is accepted by the framework and prevents it
    guarded = copy.deepcopy(bf2)
    guarded["replacement_effects"] = [{"replacement_id": "anchor", "controller": "p1", "source_object": "u1", "mode": "prevent_event", "event_op": "recall", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"}]
    if validate_state(guarded):
        errors.append(f"replacement on recall rejected by validate_state: {validate_state(guarded)}")
    else:
        prevented = apply_program(guarded, program("rc5", {"op": "recall", "object_id": "u1"}))
        if not prevented.get("committed") or ev(prevented).get("outcome") != "replaced_prevented" or "u1" not in prevented["next_state"]["battlefields"]["bf1"]["objects"]:
            errors.append(f"prevent_event on recall did not prevent it: {ev(prevented).get('outcome')} {prevented.get('reason')}")

    # --- channel_rune ------------------------------------------------------------------
    one_rune = apply_program(state, program("ch", {"op": "channel_rune", "player": "p1", "count": 2, "entry_state": "exhausted"}))
    e = ev(one_rune)
    if not one_rune.get("committed") or e.get("requested_count") != 2 or e.get("applied_count") != 1 or e.get("completion") != "partial" or e.get("outcome") != "applied":
        errors.append(f"short channel did not report partial with counts: {e} {one_rune.get('reason') or one_rune.get('errors')}")
    else:
        nxt = one_rune["next_state"]
        if "r1" not in nxt["players"]["p1"]["zones"]["base"] or nxt["players"]["p1"]["zones"]["rune_deck"] or not nxt["objects"]["r1"]["exhausted"] or object_identity(nxt, "r1") != "r1@1":
            errors.append(f"channelled rune not on the base, exhausted, with a new identity: {nxt['objects']['r1']} {nxt['players']['p1']['zones']}")
        if validate_state(nxt):
            errors.append(f"state after channel invalid: {validate_state(nxt)}")
    ready = apply_program(state, program("ch2", {"op": "channel_rune", "player": "p1", "count": 1}))
    if not ready.get("committed") or ready["next_state"]["objects"]["r1"]["exhausted"] or ev(ready).get("completion") != "full":
        errors.append("channel without entry_state did not enter ready with full completion (430.2.a)")
    empty = apply_program(state, program("ch3", {"op": "channel_rune", "player": "p2", "count": 1}))
    e = ev(empty)
    if not empty.get("committed") or e.get("outcome") != "no_op" or e.get("completion") != "none" or e.get("applied_count") != 0:
        errors.append(f"channel from an empty rune deck was not no_op/none: {e}")
    sideways = apply_program(state, program("ch4", {"op": "channel_rune", "player": "p1", "count": 1, "entry_state": "sideways"}))
    if sideways.get("valid") is not False:
        errors.append("an unknown entry_state was not invalid_input")

    # --- manifest and CLI --------------------------------------------------------------------
    for op in ("return_to_hand", "recall", "channel_rune"):
        if op not in SUPPORTED_OPS or not OP_RULES.get(op):
            errors.append(f"{op} missing from SUPPORTED_OPS/OP_RULES")
    live_ops = {o["id"] for o in build_manifest()["operations"]}
    if not {"return_to_hand", "recall", "channel_rune"} <= live_ops:
        errors.append("live capability manifest does not list the three ops")
    with tempfile.TemporaryDirectory(prefix="zone-ops-") as temp_name:
        temp = Path(temp_name)
        (temp / "s.json").write_text(json.dumps(bf2), encoding="utf-8")
        (temp / "p.json").write_text(json.dumps(program("rc", {"op": "recall", "object_id": "u1"})), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "effect", str(temp / "s.json"), str(temp / "p.json"), "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI recall failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: zone op checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: return_to_hand makes a new object with nothing of the old one and is not a Move; recall relocates to the current controller's Base keeping damage, exhaustion and modifiers with the same identity, no-ops when already there, and never fires as a Move; channel_rune enters runes with the stated state, reports partial/none with counts, and gives them new identities; off-board sources are illegal, malformed entry states invalid_input, and the manifest cites all three.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
