#!/usr/bin/env python3
"""A condition on an instruction's own target, and "Otherwise" as that condition not holding (package 10, Solari Chief).

"When you play me, choose an enemy unit. If it is stunned, kill it. Otherwise, stun it." The kill's condition is read off
its target as it executes (Core 359.3.d); "Otherwise" runs only when that CONDITION did not hold - not whenever the kill
was not performed (a kill whose target became illegal, or a replaced one, still had a stunned unit: no stun follows).

The engine's shape: predicate target_state_holds {condition {kind is_stunned}} on the instruction itself; predicate
predicate_not_met {effect_id} on the next one, true only when the referenced instruction was skipped for its own
condition (predicate_result false). That skip is its own outcome, skipped_condition_not_met - not an ignored instruction
(IGNORED_OUTCOMES), so an "it" linked to it (dependency_mode unless_ignored) still runs.

  L1 linked        the stun carrying depends_on the kill (unless_ignored), as the overlay assembles "it": an unstunned
                   target - the kill skipped by its condition - is still stunned

  P1 stunned       the chosen enemy unit is stunned: it is killed, and the stun does not run
  P2 not stunned   it is not stunned: the kill is skipped (its condition), and it is stunned
  P3 gone          it left the board before the ability resolved: a target no longer on the board is not stunned, so
                   the kill is skipped by its condition; "otherwise" then reaches a target that is gone and is ignored
                   (Core 359.3.e) - nothing is applied
  S  shapes        an unknown target condition, and "otherwise" naming an instruction with no condition, refused

    python skill/scripts/check_target_state_otherwise.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402

TARGET = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}
PROGRAM = [{"op": "kill", "effect_id": "kill", "target": dict(TARGET),
            "predicate": {"kind": "target_state_holds", "condition": {"kind": "is_stunned"}}},
           {"op": "stun", "effect_id": "stun", "target": dict(TARGET),
            "predicate": {"kind": "predicate_not_met", "effect_id": "kill"}}]
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(stunned: bool):
    state = base_state()
    state["objects"]["e1"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p2"]["zones"]["base"].append("e1")
    if stunned:   # stunned for real (its expiry recorded, Core 423.2)
        done = apply_program(state, {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                                     "program_id": "pre-stun", "controller": "p1",
                                     "effects": [{"op": "stun", "effect_id": "s0", "object_id": "e1"}]})
        assert done.get("committed"), done.get("errors") or done.get("reason")
        state = done["next_state"]
    return state


def run(state, effects=None, *, before=None):
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "solari", "controller": "p1", "effects": copy.deepcopy(effects or PROGRAM)}
    chosen_on = before or state
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": ["e1"], "selection_identities": {"e1": object_identity(chosen_on, "e1") or "e1@0"}}]}
    return apply_program(state, program, decisions=decisions)


def outcomes(result):
    return {t.get("effect_id"): t.get("outcome") for t in result.get("trace") or []}


def main() -> int:
    got = run(board(True))
    o = outcomes(got)
    if not got.get("committed") or "e1" not in got["next_state"]["players"]["p2"]["zones"]["trash"] \
            or o.get("stun") != "skipped_linked_dependency":
        fail("P1 stunned", f"{got.get('reason')} {o}")
    got = run(board(False))
    o = outcomes(got)
    if not got.get("committed") or o.get("kill") != "skipped_condition_not_met" \
            or got["next_state"]["objects"]["e1"].get("stunned") is not True:
        fail("P2 not stunned", f"{got.get('reason')} {o}")
    linked = [dict(PROGRAM[0]), {**PROGRAM[1], "depends_on": "kill", "dependency_mode": "unless_ignored"}]
    got = run(board(False), linked)
    if not got.get("committed") or got["next_state"]["objects"]["e1"].get("stunned") is not True:
        fail("L1 linked", f"{got.get('reason')} {outcomes(got)}")
    original = board(True)
    gone = copy.deepcopy(original)
    gone["players"]["p2"]["zones"]["base"].remove("e1")
    gone["players"]["p2"]["zones"]["hand"].append("e1")
    gone["objects"]["e1"]["identity"] = "e1@1"
    got = run(gone, before=original)
    o = outcomes(got)
    if not got.get("committed") or "applied" in o.values():
        fail("P3 gone", f"{got.get('reason')} {o}")
    bad_condition = copy.deepcopy(PROGRAM)
    bad_condition[0]["predicate"]["condition"] = {"kind": "is_buffed"}
    no_condition = copy.deepcopy(PROGRAM)
    no_condition[0].pop("predicate")
    for label, effects in (("unknown condition", bad_condition), ("otherwise with no condition", no_condition)):
        program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "program_id": "solari", "controller": "p1", "effects": effects}
        if not validate_program(program):
            fail("S shapes", f"{label} accepted")
    if errors:
        print("FAILED: target-state / otherwise checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a condition on the instruction's own target is read as it executes, and 'otherwise' runs only when that "
          "condition did not hold (P1-P3, L1, S)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
