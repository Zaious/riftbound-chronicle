#!/usr/bin/env python3
"""
Gate for C-24 (ADR-0007 §12): granted replacements.

Must hold:
  - grant_replacement on a board object creates a granted replacement bound
    to the object's identity, once, for this turn; the next kill of that
    object is replaced by heal / exhaust / recall and the unit survives;
  - it applies once: a second kill kills; an unused grant is cleared by the
    Expiration Step of its turn and another turn's grant survives it;
  - after the target leaves and returns (new identity) the grant no longer
    applies and the kill kills;
  - the validator requires exactly one of source_object / granted, a
    granted uses_remaining of 1, and a target_object_id equal to the target;
  - granting to an object off the board is illegal;
  - a granted and a source-backed replacement on one event still go through
    the ordinary order decision.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, object_identity, validate_state  # noqa: E402
from resolution_bridge import run_expiration_step  # noqa: E402

HIGHLANDER = {"op": "grant_replacement", "object_id": "u1", "controller": "p1", "granted_by": "highlander", "effect_id": "grant",
              "replacement": {"mode": "replace_with", "event_op": "kill", "replacement_effects": [
                  {"op": "heal_all_damage", "object_id": "$granted_target"}, {"op": "exhaust", "object_id": "$granted_target"}, {"op": "recall", "object_id": "$granted_target"}]}}


def main() -> int:
    errors: list[str] = []
    state = base_state(); state["turn_id"] = "turn-7"
    state["players"]["p1"]["zones"]["base"].remove("u1"); state["battlefields"]["bf1"]["objects"].append("u1")  # u1 at bf1 with 1 damage

    def ev(result, i=0):
        return result["trace"][i] if result.get("committed") else {}

    granted = apply_program(state, program("highlander", HIGHLANDER))
    if not granted.get("committed"):
        errors.append(f"grant_replacement did not commit: {granted.get('reason') or granted.get('errors')}")
        print("FAILED: granted replacement checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    after = granted["next_state"]
    grant = next((r for r in after["replacement_effects"] if "granted" in r), None)
    if not grant or grant["granted"] != {"target_object": "u1", "target_identity": "u1@0", "duration": "this_turn", "turn_id": "turn-7", "granted_by": "highlander"} or grant["uses_remaining"] != 1 or grant["target_object_id"] != "u1":
        errors.append(f"granted replacement shape wrong: {grant}")
    if validate_state(after):
        errors.append(f"state with a granted replacement invalid: {validate_state(after)}")
    # the next kill is replaced: healed, exhausted, recalled to base; the unit survives
    saved = apply_program(after, program("kill", {"op": "kill", "object_id": "u1", "effect_id": "k"}))
    e = ev(saved)
    if not saved.get("committed") or e.get("outcome") != "replaced_with" or "u1" not in saved["next_state"]["players"]["p1"]["zones"]["base"]:
        errors.append(f"the granted replacement did not replace the kill: {e.get('outcome')} {saved.get('reason') or saved.get('errors')}")
    else:
        u1 = saved["next_state"]["objects"]["u1"]
        if u1["damage"] != 0 or not u1["exhausted"] or object_identity(saved["next_state"], "u1") != "u1@0" or any("granted" in r for r in saved["next_state"]["replacement_effects"]):
            errors.append(f"replacement effects (heal, exhaust, recall) or one-use cleanup wrong: {u1} {saved['next_state']['replacement_effects']}")
        again = apply_program(saved["next_state"], program("kill2", {"op": "kill", "object_id": "u1", "effect_id": "k2"}))
        if not again.get("committed") or "u1" not in again["next_state"]["players"]["p1"]["zones"]["trash"]:
            errors.append("a second kill after the one-use grant did not kill")
    # leave and return: new identity → grant no longer applies
    gone = apply_program(after, program("bounce", {"op": "return_to_hand", "object_id": "u1", "effect_id": "b"}))
    if not gone.get("committed"):
        errors.append(f"could not bounce the granted target: {gone.get('reason') or gone.get('errors')}")
    else:
        back = gone["next_state"]
        if object_identity(back, "u1") == "u1@0":
            errors.append("leaving the board did not change the target's identity")
        back["players"]["p1"]["zones"]["hand"].remove("u1"); back["players"]["p1"]["zones"]["base"].append("u1")
        if any("granted" in r for r in back["replacement_effects"]):
            errors.append("the grant survived the target leaving the board")
        # even if the entry were still present, a changed identity must not apply
        stale = copy.deepcopy(back); stale["replacement_effects"].append(copy.deepcopy(grant))
        killed = apply_program(stale, program("kill3", {"op": "kill", "object_id": "u1", "effect_id": "k3"}))
        if not killed.get("committed") or ev(killed).get("outcome") != "applied" or "u1" not in killed["next_state"]["players"]["p1"]["zones"]["trash"]:
            errors.append(f"a grant bound to the old identity still applied after leave-and-return: {ev(killed).get('outcome')} {killed.get('errors')}")
    # expiration clears this turn's grant, keeps another turn's
    timing = fixture(); timing["phase"] = "ending"; timing["ending_step"] = {"status": "triggers_scheduled", "turn_id": "turn-7"}; timing["priority"] = None
    other = copy.deepcopy(after)
    old_grant = copy.deepcopy(grant); old_grant["replacement_id"] = "granted:older"; old_grant["granted"]["turn_id"] = "turn-6"
    other["replacement_effects"].append(old_grant)
    old_only = copy.deepcopy(after); old_only["replacement_effects"] = [copy.deepcopy(old_grant)]
    old_kill = apply_program(old_only, program("kill-old", {"op": "kill", "object_id": "u1", "effect_id": "old-kill"}))
    if not old_kill.get("committed") or "u1" not in old_kill["next_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append("a granted replacement stamped for another turn remained active")
    expired = run_expiration_step(timing, other)
    if not expired.get("committed") or [r["replacement_id"] for r in expired["next_effect_state"]["replacement_effects"]] != ["granted:older"] or expired["trace"]["expire_this_turn"].get("granted_replacements") != [grant["replacement_id"]]:
        errors.append(f"expiration did not clear exactly this turn's grant: {expired.get('reason')} {[r.get('replacement_id') for r in expired.get('next_effect_state', {}).get('replacement_effects', [])]}")
    # validator: exactly one variant, uses 1, target binding
    both = copy.deepcopy(after); both["replacement_effects"][-1]["source_object"] = "u1"
    neither = copy.deepcopy(after); del neither["replacement_effects"][-1]["granted"]
    many = copy.deepcopy(after); many["replacement_effects"][-1]["uses_remaining"] = 2
    mismatch = copy.deepcopy(after); mismatch["replacement_effects"][-1]["target_object_id"] = "u2"
    for label, bad in (("both", both), ("neither", neither), ("uses", many), ("target", mismatch)):
        if not validate_state(bad):
            errors.append(f"validator accepted a malformed granted replacement ({label})")
    # off-board target → illegal
    off = copy.deepcopy(state); off["battlefields"]["bf1"]["objects"].remove("u1"); off["players"]["p1"]["zones"]["hand"].append("u1")
    refused = apply_program(off, program("highlander", HIGHLANDER))
    if refused.get("committed") or refused.get("applied") is not False or refused.get("reason_code") != "illegal_operation":
        errors.append(f"granting to an off-board object was not illegal: {refused.get('reason_code')} {refused.get('errors')}")
    # coexisting with a source-backed prevention → order decision
    guarded = copy.deepcopy(after)
    guarded["replacement_effects"].append({"replacement_id": "guard", "controller": "p1", "source_object": "u1", "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"})
    two = apply_program(guarded, program("kill4", {"op": "kill", "object_id": "u1", "effect_id": "k4"}))
    if two.get("committed") or two.get("replacement_decision_required") is not True or sorted(two.get("replacement_ids", [])) != sorted([grant["replacement_id"], "guard"]):
        errors.append(f"a granted and a source-backed replacement did not go through the order decision: {two.get('reason')} {two.get('replacement_ids')}")
    snap = copy.deepcopy(state)
    if state != snap or apply_program(state, program("highlander", HIGHLANDER)) != granted:
        errors.append("grant_replacement mutated its input or is not deterministic")

    if errors:
        print("FAILED: granted replacement checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a granted replacement binds to the target's identity for one turn, replaces the next kill by heal / exhaust / recall exactly once, no longer applies after the target leaves and returns, is cleared by its turn's Expiration Step and not by another turn's, must be exactly one of granted or source-backed, cannot be granted off the board, and shares the order decision with source-backed replacements.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
