#!/usr/bin/env python3
"""Counter a targeted spell on the Chain (package 10, Wind Wall and Defy).

"Counter a spell." / "Counter a spell that costs no more than :rb_energy_4: and no more than :rb_rune_rainbow:." The
spell is a target chosen as the countering card is played (Core 355.7, 355.5); countered, its card leaves the Chain for
its owner's trash, it was not played and no cost is refunded (Core 426.1). GPT 2026-10-08 (PACKAGE10_INVENTORY ruling 6):
Defy compares the target's PRINTED (or copied) cost, not what was paid or added (Core 206) - Energy at most 4, Power at
most 1 in total across Domains.

The engine's shape: counter takes a `target` {chosen_zone_class non_board, location chain, kind spell[, max_cost]} in
place of a chain_item_id; the pipeline checks it as any target (evaluate_target, cost_comparison for max_cost) and the
instruction counters the Chain item that card is.

  T1 counter       p2 counters p1's spell c1 on the Chain: c1 in p1's trash, its item gone, not played, no refund
  T2 not a spell   a unit on the board named as the target: an illegal target, nothing countered
  T3 gone          c1 left the Chain before the counter resolves: the instruction is ignored, not an error
  D1 within        Defy's limit (printed [3][Fury]): countered
  D2 energy        printed [5]: an illegal target
  D3 power         printed [3][Fury][Calm] - two Power in total: an illegal target (not one per Domain)
  D4 printed       printed [5], paid [2] after a discount (its cost receipt): still an illegal target - the printed cost
  S  shapes        a counter target without kind spell, or with a chain_item_id beside it, refused
  G  grammar       "Counter a spell." lowers to exactly that target

    python skill/scripts/check_counter_target.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402

TARGET = {"decision_ref": "t", "chosen_zone_class": "non_board", "location": "chain", "kind": "spell"}
LIMIT = {"energy": 4, "power": 1, "cost_basis": "printed_cost", "power_measure": "total_printed_power",
         "authority_status": "official", "official_status": "verified"}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(printed=None, receipt=None):
    """p1's spell c1 on the Chain (item spell-1), printed `printed`; p2's unit e1 in its Base."""
    state = base_state()
    state["objects"]["c1"]["kind"] = "spell"
    state["objects"]["c1"]["printed_cost"] = printed or {"energy": 2, "power": {}}
    state["players"]["p1"]["zones"]["main_deck"] = [c for c in state["players"]["p1"]["zones"]["main_deck"] if c != "c1"]
    entry = {"card": "c1", "controller": "p1"}
    if receipt is not None:
        entry["cost_receipt"] = receipt
    state["chain_items"] = {"spell-1": entry}
    state["objects"]["e1"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p2"]["zones"]["base"].append("e1")
    return state


def program(target):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "counter-prog", "controller": "p2", "effects": [{"op": "counter", "effect_id": "c", "target": target}]}


def run(state, target, chosen):
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p2", "value": [chosen],
         "selection_identities": {chosen: object_identity(state, chosen) or f"{chosen}@0"}}]}
    return apply_program(state, program(target), decisions=decisions)


def outcome(result):
    return [t.get("outcome") for t in result.get("trace") or []]


def countered(result) -> bool:
    s = result.get("next_state") or {}
    return bool(result.get("committed")) and "spell-1" not in (s.get("chain_items") or {}) \
        and "c1" in s["players"]["p1"]["zones"]["trash"]


def main() -> int:
    got = run(board(), TARGET, "c1")
    if not countered(got):
        fail("T1 counter", f"{got.get('reason_code')} {got.get('errors') or got.get('reason')} {outcome(got)}")
    else:
        entry = (got.get("trace") or [{}])[0]
        if entry.get("not_played") is not True or entry.get("costs_refunded") is not False:
            fail("T1 counter", f"the trace does not say not played / no refund: {entry}")
    got = run(board(), TARGET, "e1")
    if countered(got) or (got.get("committed") and "ignored_illegal_target" not in outcome(got)
                          and "skipped_illegal_target" not in outcome(got)):
        fail("T2 not a spell", f"{got.get('reason_code')} {outcome(got)}")
    gone = board()
    chosen_identity = object_identity(gone, "c1")
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(gone), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p2", "value": ["c1"],
         "selection_identities": {"c1": chosen_identity}}]}
    gone["chain_items"] = {}
    gone["players"]["p1"]["zones"]["trash"].append("c1")
    decisions["input_hash"] = hash_value(gone)
    got = apply_program(gone, program(TARGET), decisions=decisions)
    if not got.get("committed") or not (set(outcome(got)) & {"ignored_illegal_target", "skipped_illegal_target"}):
        fail("T3 gone", f"{got.get('reason_code')} {got.get('errors') or got.get('reason')} {outcome(got)}")
    defy = {**TARGET, "max_cost": LIMIT}
    got = run(board({"energy": 3, "power": {"fury": 1}}), defy, "c1")
    if not countered(got):
        fail("D1 within", f"{got.get('reason_code')} {got.get('errors') or got.get('reason')} {outcome(got)}")
    for label, printed, receipt in (("D2 energy", {"energy": 5, "power": {}}, None),
                                    ("D3 power", {"energy": 3, "power": {"fury": 1, "calm": 1}}, None),
                                    ("D4 printed", {"energy": 5, "power": {}},
                                     {"components": [{"cost_id": "base", "paid": True, "energy": 2, "power": {}}],
                                      "total": {"energy": 2, "power": {}}})):
        got = run(board(printed, receipt), defy, "c1")
        if countered(got):
            fail(label, "countered a spell over Defy's printed limit")
        elif got.get("committed") and not (set(outcome(got)) & {"ignored_illegal_target", "skipped_illegal_target"}):
            fail(label, f"committed without naming the illegal target: {outcome(got)}")
    for label, effect in (("no kind", {"op": "counter", "effect_id": "c", "target": {k: v for k, v in TARGET.items() if k != "kind"}}),
                          ("both", {"op": "counter", "effect_id": "c", "target": TARGET, "chain_item_id": "spell-1"})):
        problems = validate_program({**program(TARGET), "effects": [effect]})
        if not problems:
            fail("S shapes", f"{label} accepted")
    lowered = CG.compile_clause("Counter a spell.", CG.load_grammar())
    if lowered.get("production_id") != "counter_a_spell" or (lowered.get("program_effects") or [{}])[0].get("target") != TARGET:
        fail("G grammar", f"{lowered.get('production_id')} {lowered.get('program_effects')}")
    if errors:
        print("FAILED: counter-target checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a counter targets one spell on the Chain and counters its item; Defy's limit reads the printed cost, Power "
          "summed across Domains; an illegal or departed target counters nothing (T1-T3, D1-D4, S, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
