#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "Counter an enemy spell or ability that chooses a friendly unit or gear." (Not So
Fast) - a target that is a Chain item, not an object (selector chain_item, effect_ir.CHAIN_VIEW): an enemy spell, an
enemy activated or triggered ability, whose own targets chose a Unit or Gear on the countering player's side.

On a Chain of four items - p2's spell targeting p1's unit, p2's triggered ability targeting p1's gear, p2's spell
targeting p2's own unit, p1's spell targeting p1's unit:

  C1 options       the two enemy items that chose p1's things, and no other
  C2 a spell       played targeting p2's spell, resolved: that spell is countered - off the Chain, its card in p2's trash
  C3 an ability    played targeting p2's triggered ability, resolved: it leaves the Chain, no card moves
  C4 not chosen    p2's spell about its own unit, or p1's own spell, may not be chosen
  C5 gone          the targeted unit gone from the board before resolution: the item no longer chooses a friendly unit,
                   the counter is not followed (359.3.e)
  C6 no Chain      run with no Chain to read: the target is refused by name
  V                a Chain-item target that names an object kind does not validate

    python skill/scripts/check_set2_counter_chain_item.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

errors: list[str] = []
RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
TARGET = {"decision_ref": "t", "chosen_zone_class": "non_board", "location": "chain", "chain_item": True,
          "item_kinds": ["spell", "ability"], "controller_relation": "enemy",
          "chooses": {"kinds": ["unit", "gear"], "controller_relation": "friendly"}}
NSF = {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "nsf-effects", "controller": "p1",
       "effects": [{"op": "counter", "effect_id": "ctr", "target": dict(TARGET)}]}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def chosen(ref, value):
    return [{"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": "p2",
             "value": [value], "selection_identities": {value: f"{value}@0"}}]


def boards():
    state = base_state()
    for card, owner in (("es", "p2"), ("eo", "p2"), ("fs", "p1"), ("nsf", "p1")):
        state["objects"][card] = {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0, "might_modifiers": [],
                                  "damage": 0, "exhausted": False, "printed_cost": {"energy": 0, "power": {}},
                                  **({"play_timing": "reaction"} if card == "nsf" else {})}
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("g1")
    state["players"]["p1"]["zones"]["hand"].append("nsf")
    state["chain_items"] = {"spell-e": {"card": "es", "controller": "p2", "played_targets": chosen("t", "u1")},
                            "spell-o": {"card": "eo", "controller": "p2", "played_targets": chosen("t", "u2")},
                            "spell-f": {"card": "fs", "controller": "p1",
                                        "played_targets": [{**chosen("t", "u1")[0], "controller": "p1"}]}}
    timing = fixture(priority="p1", items=[item("spell-e", "p2", "spell", "default"),
                                           {**item("trig-e", "p2", "ability", "default"),
                                            "finalized_targets": [{"decision_id": "t", "stage": "trigger_finalization",
                                                                   "kind": "target_selection", "controller": "p2",
                                                                   "value": ["g1"], "selection_identities": {"g1": "g1@0"}}]},
                                           item("spell-o", "p2", "spell", "default"),
                                           item("spell-f", "p1", "spell", "default")])
    return timing, state


def play_and_resolve(timing, state, target, *, before_resolution=None):
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [target],
         "selection_identities": {target: IR.chain_item_identity(target)}}]}
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-nsf", "actor": "p1", "card": "nsf",
            "effect_program_id": NSF["program_id"], "chain_item": {"id": "spell-nsf", "object_kind": "spell", "timing": "reaction"},
            "cost": {"base": {"energy": 0, "power": {}}}}
    played = PT.play_card(timing, state, decl, engine_decisions=decisions, effect_program=NSF)
    if not played.get("committed"):
        return played, None
    t, e = played["next_timing_state"], played["next_effect_state"]
    from rules_core import finalize_oldest_pending, next_procedure
    if next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = finalize_oldest_pending(t)["next_state"]
    for actor in ("p1", "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    if before_resolution:
        e = before_resolution(copy.deepcopy(e))
    return played, resolve_with_program(t, "spell-nsf", e, NSF)


def main() -> int:
    timing, state = boards()
    problems = IR.validate_state(state)
    if problems:
        fail("board", problems[:3])
        return report()
    token = IR.CHAIN_VIEW.set(IR.chain_view_of(timing, state))
    try:
        options = sorted(PT.legal_target_options(state, "p1", NSF, TARGET))
    finally:
        IR.CHAIN_VIEW.reset(token)
    if options != ["spell-e", "trig-e"]:
        fail("C1", f"options {options}")
    played, done = play_and_resolve(timing, state, "spell-e")
    if done is None or not done.get("committed"):
        fail("C2", f"{(done or played).get('reason_code') or (done or played).get('reason')} {(done or played).get('stage')}")
    else:
        e = done["next_effect_state"]
        ids = [i["id"] for i in done["next_timing_state"]["chain"]["items"]]
        if "spell-e" in ids or "spell-e" in (e.get("chain_items") or {}) or "es" not in e["players"]["p2"]["zones"]["trash"]:
            fail("C2", f"chain {ids}, trash {e['players']['p2']['zones']['trash']}")
    played, done = play_and_resolve(timing, state, "trig-e")
    if done is None or not done.get("committed"):
        fail("C3", f"{(done or played).get('reason_code') or (done or played).get('reason')} {(done or played).get('stage')}")
    elif "trig-e" in [i["id"] for i in done["next_timing_state"]["chain"]["items"]]:
        fail("C3", "the triggered ability is still on the Chain")
    for label, target in (("C4 its own unit", "spell-o"), ("C4 a friendly spell", "spell-f")):
        played, _done = play_and_resolve(timing, state, target)
        if played.get("committed") or played.get("reason_code") != "target_illegal_at_play":
            fail(label, f"{played.get('committed')} {played.get('reason_code')}")

    def unit_gone(e):
        e["battlefields"]["bf1"]["objects"] = [o for o in e["battlefields"]["bf1"]["objects"] if o != "u1"]
        for zone in e["players"]["p1"]["zones"].values():
            if "u1" in zone:
                zone.remove("u1")
        e["players"]["p1"]["zones"]["trash"].append("u1")
        return e
    played, done = play_and_resolve(timing, state, "spell-e", before_resolution=unit_gone)
    if done is None or not done.get("committed") or "spell-e" not in [i["id"] for i in done["next_timing_state"]["chain"]["items"]]:
        fail("C5", f"{(done or {}).get('reason_code')} {(done or {}).get('reason')}")
    bare = copy.deepcopy(NSF)
    bare["effects"][0]["target"] = {k: v for k, v in TARGET.items() if k != "decision_ref"} | {"object_id": "spell-e"}
    result = IR.apply_program(state, bare)
    if result.get("committed") and result.get("countered_chain_items"):
        fail("C6", "a Chain-item target was followed with no Chain to read")
    wrong = copy.deepcopy(NSF)
    wrong["effects"][0]["target"]["kind"] = "spell"
    if not IR.validate_program(wrong):
        fail("V", "a Chain-item target with an object kind validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: set 2 counter an enemy spell or ability that chooses a friendly unit or gear")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a Chain item as the target - an enemy spell or ability whose targets chose a friendly unit or gear - "
          "countered off the Chain (a spell's card to its owner's trash; an ability leaves no card); another item may not "
          "be chosen; the chosen unit gone, the counter is not followed; no Chain to read, refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
