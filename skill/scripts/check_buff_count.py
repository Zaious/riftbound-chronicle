#!/usr/bin/env python3
"""A Unit that may have any number of buffs (package 9, Lee Sin - Ascetic).

"I can have any number of buffs." GPT 2026-10-06 (PACKAGE9_INVENTORY section 7, ruling 12): it lifts the one-buff limit
(Core 427.1.b.2); each buff adds +1.

The engine's shape: object fields any_number_of_buffs (true) and buff_count (2 or more; absent = one while buffed). A
Buff of such a unit that already has one adds one more; Might counts each (703); spending a buff takes one (702.2.b).

  L1 three buffs    buffed three times: buff_count 3, Might +3
  L2 one only       the same unit without the permission: the second and third Buff are no_op, Might +1
  L3 spend one      one spent at a time: buff_count 2, Might +2; down to one, the count leaves the state; the last
                    one spent, it is unbuffed - each state valid
  L4 cost           a spend_buff cost paid from it takes one buff
  L5 any number     "spend any number of buffs" with a unit holding more than one: a buff_spend {unit: how many}
                    is asked (package 14); two of three spends two, one left; four of three, a card_selection, or
                    another object's identity refused
  S  shapes         buff_count 1, buff_count without the permission, a non-boolean permission - refused
  G  grammar        the clause grammar lowers the sentence to the permission; near misses stay unparsed

    python skill/scripts/check_buff_count.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, apply_program, effective_might, hash_value, spend_one_buff, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(permission=True) -> dict:
    state = base_state()
    state["objects"]["u1"]["damage"] = 0
    if permission:
        state["objects"]["u1"]["any_number_of_buffs"] = True
    assert not validate_state(state), validate_state(state)
    return state


def buff(state) -> dict:
    return apply_program(state, program("buff", {"op": "buff", "effect_id": "b", "object_id": "u1"}))


def buffed(state, n) -> tuple[dict, list]:
    outcomes = []
    for _ in range(n):
        got = buff(state)
        outcomes.append(got["trace"][0].get("outcome") if got.get("committed") else got.get("reason"))
        state = got["next_state"] if got.get("committed") else state
    return state, outcomes


def main() -> int:
    s = board()
    printed = effective_might(s, "u1")
    three, outcomes = buffed(s, 3)
    if three["objects"]["u1"].get("buff_count") != 3 or effective_might(three, "u1") != printed + 3:
        fail("L1 three buffs", f"{outcomes} {three['objects']['u1']} might {effective_might(three, 'u1')}")
    plain, outcomes = buffed(board(permission=False), 3)
    if outcomes[1:] != ["no_op", "no_op"] or effective_might(plain, "u1") != printed + 1 or "buff_count" in plain["objects"]["u1"]:
        fail("L2 one only", f"{outcomes} might {effective_might(plain, 'u1')}")
    # L3: one spent at a time (the shared helper both spend paths call)
    unit = copy.deepcopy(three["objects"]["u1"])
    readings = []
    for _ in range(3):
        spend_one_buff(unit)
        probe = copy.deepcopy(three)
        probe["objects"]["u1"] = copy.deepcopy(unit)
        readings.append((unit.get("buff_count"), bool(unit.get("buffed")), effective_might(probe, "u1") - printed,
                         bool(validate_state(probe))))
    if readings != [(2, True, 2, False), (None, True, 1, False), (None, False, 0, False)]:
        fail("L3 spend one", readings)
    # L4: a spend_buff cost paid from it takes one buff
    paying = copy.deepcopy(three)
    paying["objects"]["sp"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
    paying["players"]["p1"]["zones"].setdefault("hand", []).append("sp")
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-sp", "actor": "p1", "card": "sp",
            "chain_item": {"id": "spell-sp", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}},
                     "additional": [{"cost_id": "bf", "mandatory": True, "payment": {"kind": "spend_buff", "object_id": "u1"}}]}}
    paid = play_card(fixture(), paying, decl)
    if not paid.get("committed") or paid["next_effect_state"]["objects"]["u1"].get("buff_count") != 2:
        fail("L4 cost", f"{paid.get('reason_code')} {paid.get('reason')} "
                        f"{(paid.get('next_effect_state') or {}).get('objects', {}).get('u1')}")
    spend_any = program("spend-any", {"op": "spend_buffs", "effect_id": "sa", "player": "p1", "decision_ref": "spend"})
    choose = apply_program(three, spend_any)
    asked = (choose.get("reason_code"), choose.get("decision_ids"), (choose.get("choice") or {}).get("buff_counts"))
    if choose.get("committed") or asked != ("buff_spend_required", ["spend"], {"u1": 3}):
        fail("L5 any number", f"no buff_spend asked: {choose.get('committed')} {asked}")

    def spending(value, kind="buff_spend", identity=None):
        entry = {"decision_id": "spend", "stage": "resolution", "kind": kind, "controller": "p1",
                 "value": value if kind == "buff_spend" else sorted(value),
                 "selection_identities": {u: identity or f"{u}@0" for u in value}}
        return apply_program(three, spend_any, decisions={"schema_version": "engine-decisions.v1",
                                                          "input_hash": hash_value(three), "decisions": [entry]})
    two = spending({"u1": 2})
    spent = next((t for t in two.get("trace") or [] if t.get("op") == "spend_buffs"), {})
    left = (two.get("next_state") or {}).get("objects", {}).get("u1") or {}
    if not two.get("committed") or (left.get("buff_count"), left.get("buffed")) != (None, True) or spent.get("applied_count") != 2:
        fail("L5 any number", f"spending two of three: {two.get('reason')} {left} {spent}")
    for label, got in (("four of three", spending({"u1": 4})), ("a card_selection", spending({"u1": 1}, kind="card_selection")),
                       ("another object", spending({"u1": 1}, identity="u1@9"))):
        if got.get("committed"):
            fail("L5 any number", f"{label} was accepted")
    for label, fields in (("count 1", {"buffed": True, "any_number_of_buffs": True, "buff_count": 1}),
                          ("no permission", {"buffed": True, "buff_count": 2}),
                          ("not boolean", {"buffed": True, "any_number_of_buffs": "yes"})):
        bad = board(permission=False)
        bad["objects"]["u1"].update(fields)
        if not validate_state(bad):
            fail("S shapes", f"{label} was accepted")
    lowered = CG.compile_clause("I can have any number of buffs.", CG.load_grammar())
    if lowered.get("unsupported") or (lowered.get("passive") or {}).get("object_fields") != {"any_number_of_buffs": True}:
        fail("G grammar", f"{lowered.get('production_id')} {lowered.get('passive')}")
    for near in ("I can have two buffs.", "Other friendly units can have any number of buffs."):
        if not CG.compile_clause(near, CG.load_grammar()).get("unsupported"):
            fail("G grammar", f"{near!r} was parsed")
    if errors:
        print("FAILED: buff count checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a unit with the permission has any number of buffs, each +1 Might, one spent at a time (L1-L5, S, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
