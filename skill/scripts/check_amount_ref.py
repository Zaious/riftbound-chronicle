#!/usr/bin/env python3
""""Deal damage equal to my Might": a typed amount read on execution (Core 359.3.f.2).

`amount_ref: {"kind": "program_source_current_might"}` on deal_damage - the program's own
source's effective Might at the moment the instruction executes, never when the trigger
was scheduled or finalized. Core 359.3.f.2's own Yasuo, Remorseful example: Stupefied in
reaction to his attack trigger, it deals damage equal to his CURRENT Might.

Held here, through the real schedule -> finalize_trigger -> resolve_with_program path for
"When I attack, deal damage equal to my Might to an enemy unit here." (the engine's own
grammar lowering):

  positive     the enemy at the source's battlefield takes exactly the source's Might
  in reaction  the source's Might lowered before resolution: the damage is the lowered
               value (359.3.f.2), not the value when the trigger was finalized
  zero         a source with 0 Might deals nothing: no_op, named, no damage
  left         the source moved to Base first: "here" makes the target illegal and the
               instruction mistargets - its Might is never read
and, on a plain program (no "here"), the identity rule location_ref already follows:
  new object   the source replaced at the same id: refused by name, never read off it
  no identity  a program with no declared source_identity: refused by name
  validator    unknown kind; on an op other than deal_damage; with `amount` too; on an
               affected set - each refused

    python skill/scripts/check_amount_ref.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir  # noqa: E402
import check_trigger_source_identity as TS  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, effective_might, object_identity  # noqa: E402
from resolution_bridge import finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import pass_priority, schedule_triggered_items  # noqa: E402

REF = {"kind": "program_source_current_might"}


def yasuo_program() -> dict:
    lowered = CG.compile_clause("Deal damage equal to my Might to an enemy unit here.", CG.load_grammar())
    doc = TS.program()
    doc["effects"] = copy.deepcopy(lowered["program_effects"])
    return doc


def pick(board: dict, object_id: str) -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": effect_ir.hash_value(board),
            "decisions": [{"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection",
                           "controller": "p1", "value": [object_id],
                           "selection_identities": {object_id: object_identity(board, object_id)}}]}


def run(board: dict, *, before_resolution=None) -> dict:
    prog = yasuo_program()
    entry = TS.descriptor(board)
    entry["effect_program_hash"] = program_hash(prog)
    timing = schedule_triggered_items(fixture(), [entry])["next_state"]
    finalized = finalize_trigger(timing, board, {TS.PROGRAM_ID: prog}, pick(board, "u2"))
    if not finalized.get("committed"):
        return {"stage": "finalize", "result": finalized}
    timing = finalized["next_timing_state"]
    for actor in ("p1", "p2"):
        timing = pass_priority(timing, actor).get("next_state") or timing
    after = copy.deepcopy(board)
    if before_resolution is not None:
        before_resolution(after)
    return {"stage": "resolve", "result": resolve_with_program(timing, TS.TRIGGER, after, prog), "board": after}


def step(done: dict) -> dict:
    trace = done["result"].get("trace") or {}
    return next((e for e in (trace.get("effect") or []) if e.get("op") == "deal_damage"), {}) if isinstance(trace, dict) else {}


def damage(done: dict, object_id: str) -> int:
    return ((done["result"].get("next_effect_state") or {}).get("objects", {}).get(object_id) or {}).get("damage", 0)


def main() -> int:
    errors: list[str] = []
    board = TS.board()
    board["objects"]["u2"]["base_might"] = 9          # survives any hit here, so damage is observable
    might = effective_might(board, "u1")

    done = run(board)
    if done["stage"] != "resolve" or done["result"].get("committed") is not True or damage(done, "u2") != might:
        errors.append(f"positive: expected u2 to take {might}, got stage {done['stage']} damage "
                      f"{damage(done, 'u2') if done['stage'] == 'resolve' else '-'} ({done['result'].get('reason')})")

    def stupefy(s):
        s["objects"]["u1"]["base_might"] = max(1, s["objects"]["u1"].get("base_might", might) - 2)
    lowered = max(1, board["objects"]["u1"].get("base_might", might) - 2)
    done = run(board, before_resolution=stupefy)
    if done["result"].get("committed") is not True or damage(done, "u2") != lowered:
        errors.append(f"in reaction: expected the CURRENT Might {lowered}, got {damage(done, 'u2')} (359.3.f.2)")

    def to_zero(s):
        s["objects"]["u1"]["base_might"] = 0
    done = run(board, before_resolution=to_zero)
    if done["result"].get("committed") is not True or step(done).get("outcome") != "no_op" or damage(done, "u2") != 0:
        errors.append(f"zero: expected a named no_op and no damage, got {step(done).get('outcome')} damage {damage(done, 'u2')}")

    def to_base(s):
        s["battlefields"]["bf1"]["objects"].remove("u1")
        s["players"]["p1"]["zones"]["base"].append("u1")
    done = run(board, before_resolution=to_base)
    if done["result"].get("committed") is not True or step(done).get("outcome") != "ignored_illegal_target" \
            or "amount_read_from" in step(done) or damage(done, "u2") != 0:
        errors.append(f"left: expected a mistarget with the Might never read, got {step(done).get('outcome')}")

    plain = TS.program()
    plain["effects"] = [{"op": "deal_damage", "effect_id": "dmg", "amount_ref": dict(REF),
                         "target": {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit"}}]
    changed = copy.deepcopy(board)
    changed["objects"]["u1"]["identity"] = "u1@9"
    result = apply_program(changed, {**plain, "source_identity": "u1@0"})
    if result.get("committed") is not False or result.get("reason_code") != effect_ir.AMOUNT_REF_IDENTITY_CHANGED:
        errors.append(f"new object: expected {effect_ir.AMOUNT_REF_IDENTITY_CHANGED}, got {result.get('reason_code')}")
    result = apply_program(board, plain)
    if result.get("committed") is not False or result.get("reason_code") != effect_ir.AMOUNT_REF_ABSENT:
        errors.append(f"no identity: expected {effect_ir.AMOUNT_REF_ABSENT}, got {result.get('reason_code')}")

    bad = {
        "an unknown kind": {**plain["effects"][0], "amount_ref": {"kind": "program_source_power"}},
        "an op other than deal_damage": {"op": "heal_damage", "effect_id": "h", "amount_ref": dict(REF),
                                         "target": plain["effects"][0]["target"]},
        "amount and amount_ref together": {**plain["effects"][0], "amount": 3},
        "an affected set": {"op": "deal_damage", "effect_id": "dmg", "amount_ref": dict(REF),
                            "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "any_battlefield"}}},
    }
    for label, effect in bad.items():
        if not effect_ir.validate_program({**plain, "effects": [effect]}):
            errors.append(f"validator: {label} was accepted")

    if errors:
        print("FAILED: amount_ref (equal to my Might)")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("amount_ref: the source's Might read on execution - the current value after a change in reaction, "
          "a named no_op at 0, never read on a mistarget; a changed or undeclared source refused by name; "
          "four malformed shapes refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
