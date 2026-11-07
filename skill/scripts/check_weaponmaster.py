#!/usr/bin/env python3
"""ADR-0017 §5: Weaponmaster (Core 821) through the real play, play completion, trigger finalization and resolution.

p1 plays a unit with Weaponmaster. p1 controls Equipment: g1 in its Base (Equip: one calm Power and one any-domain
Power), g2 attached to u1 (Equip: 1 Energy and one any-domain Power), g3 with no Equip cost, g5 (Equip: one calm Power
only); p2 controls g4.

  W1 trigger     the play completion schedules one optional Weaponmaster trigger, bound to the engine's program
  W2 discount    finalized with g1 and paid: the any-domain Power is taken off (821.1.c.2-c.3), only the calm Power is
                 paid; resolved, g1 is attached to the new unit, which has its Might Bonus and [Tank]
  W3 moved       g2, attached to u1, is moved: 1 Energy paid, nothing for the any-domain Power; u1 loses g2's Might Bonus
  W4 no cost     g3 has no Equip cost: the cost cannot be paid, the ability leaves the chain, g3 stays (821.1.c.4-c.5)
  W5 no [A]      g5's Equip cost has no any-domain Power: it is paid unreduced (821.1.c.3)
  W6 declined    "you may": declining finalizes nothing and attaches nothing
  W7 enemy       p2's Equipment is not a legal choice
  W8 gone        the unit left the board before resolution: nothing is attached (821.1.c.5)
  V1 shape       equip_cost_of carries a decision_ref and a non-negative reduce_power_any; weaponmaster_attach names
                 its target and its unit
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import effect_ir as IR  # noqa: E402
import engine_decisions as ed  # noqa: E402
import play_transaction as PT  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import effective_might, has_keyword, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

FAILS: list[str] = []
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + str(detail)) if detail != '' and not ok else ''}")
    if not ok:
        FAILS.append(name)


def equipment(owner, **fields):
    return {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, "tags": ["Equipment"], **fields}


def equip_row(energy=0, power=None, any_power=0):
    additional = [{"cost_id": "equip:any", "mandatory": True, "payment": {"kind": "power_any", "amount": any_power}}] if any_power else []
    return {"equip": {"cost": {"energy": energy, "power": power or {}, **({"additional": additional} if additional else {})},
                      "effect_program_id": "equip", "keyword": "equip"}}


def board():
    state = base_state()
    zones = state["players"]["p1"]["zones"]
    zones["main_deck"].remove("c1")
    zones["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, "keywords": ["weaponmaster"]})
    state["objects"]["g1"] = equipment("p1", might_bonus=2, effect_text={"keywords": [{"keyword": "tank"}]},
                                       activated_abilities=equip_row(power={"calm": 1}, any_power=1))
    state["objects"]["g2"] = equipment("p1", might_bonus=1, attached_to="u1", activated_abilities=equip_row(energy=1, any_power=1))
    state["objects"]["g3"] = equipment("p1", might_bonus=1)
    state["objects"]["g4"] = equipment("p2", might_bonus=1, activated_abilities=equip_row(power={"calm": 1}))
    state["objects"]["g5"] = equipment("p1", might_bonus=1, activated_abilities=equip_row(power={"calm": 1}))
    zones["base"] += ["g1", "g2", "g3", "g5"]
    state["players"]["p2"]["zones"]["base"].append("g4")
    state["players"]["p1"]["resources"] = {"energy": 4, "power": {"calm": 2}}
    return state


def declaration():
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"}, "payment_context": dict(CLOSED)}


def played(state):
    done = PT.play_card(fixture(), state, declaration())
    if not done.get("committed"):
        raise SystemExit(f"the play was refused: {done.get('reason')}")
    after = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(after, "unit-1", done["next_effect_state"], None)


def choose(state, equipment_id):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [
        {"decision_id": IR.WEAPONMASTER_EQUIPMENT, "stage": "trigger_finalization", "kind": "target_selection",
         "controller": "p1", "value": [equipment_id],
         "selection_identities": {equipment_id: object_identity(state, equipment_id) or f"{equipment_id}@0"}}]}


def finalize(done, equipment_id, *, perform=True, state=None):
    state = state or done["next_effect_state"]
    program = IR.weaponmaster_program(state, "c1", "p1")
    return finalize_trigger(done["next_timing_state"], state, {program["program_id"]: program}, choose(state, equipment_id),
                            perform_optional_trigger=perform, pay_trigger_cost=perform, payment_context=CLOSED), program


def resolve(finalized, program, decisions):
    timing = finalized["next_timing_state"]
    for _ in range(4):
        if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
            break
        timing = RC.pass_priority(timing, timing["priority"])["next_state"]
    return resolve_with_program(timing, "c1:weaponmaster", finalized["next_effect_state"], program, engine_decisions=decisions)


def main() -> int:
    start = board()
    check("the board is valid", not validate_state(start), validate_state(start))
    done = played(start)
    items = done.get("next_timing_state", {}).get("chain", {}).get("items", [])
    check("W1 one Weaponmaster trigger", [i.get("id") for i in items] == ["c1:weaponmaster"], [i.get("id") for i in items])
    if not items:
        print(f"check_weaponmaster: FAILED {', '.join(FAILS)}")
        return 1
    after = done["next_effect_state"]
    before = after["players"]["p1"]["resources"]

    got, program = finalize(done, "g1")
    paid = (got.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources")
    check("W2 finalized with g1: only its calm Power is paid", got.get("committed")
          and paid == {**before, "power": {"calm": before["power"]["calm"] - 1}}, (got.get("reason"), before, paid))
    if got.get("committed"):
        res = resolve(got, program, choose(got["next_effect_state"], "g1"))
        end = res.get("next_effect_state") or {}
        check("W2 resolved: g1 is attached to the new unit", (end.get("objects") or {}).get("g1", {}).get("attached_to") == "c1",
              res.get("reason") or (res.get("effect_result") or {}).get("reason"))
        if end:
            check("W2 the unit has g1's Might Bonus and [Tank]",
                  effective_might(end, "c1") == effective_might(after, "c1") + 2 and has_keyword(end, "c1", "tank"))

    got, program = finalize(done, "g2")
    paid = (got.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources")
    check("W3 finalized with g2: 1 Energy paid, nothing for its any-domain Power", got.get("committed")
          and paid == {**before, "energy": before["energy"] - 1}, (got.get("reason"), paid))
    if got.get("committed"):
        res = resolve(got, program, choose(got["next_effect_state"], "g2"))
        end = res.get("next_effect_state") or {}
        check("W3 g2 moved from u1 to the new unit", (end.get("objects") or {}).get("g2", {}).get("attached_to") == "c1"
              and effective_might(end, "u1") == effective_might(after, "u1") - 1, res.get("reason"))

    got, _program = finalize(done, "g3")
    stayed = got.get("next_effect_state") or after
    check("W4 g3 has no Equip cost: the ability does not finalize and g3 stays",
          not any(i.get("id") == "c1:weaponmaster" and i.get("state") == "finalized"
                  for i in (got.get("next_timing_state") or {}).get("chain", {}).get("items", []))
          and stayed["objects"]["g3"].get("attached_to") is None, (got.get("reason_code"), got.get("reason")))

    got, _program = finalize(done, "g5")
    paid = (got.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources")
    check("W5 g5's cost has no any-domain Power: paid unreduced (one calm)", got.get("committed")
          and paid == {**before, "power": {"calm": before["power"]["calm"] - 1}}, (got.get("reason"), paid))

    got, _program = finalize(done, "g1", perform=False)
    end = got.get("next_effect_state") or after
    check("W6 declined: nothing paid, nothing attached", end["objects"]["g1"].get("attached_to") is None
          and end["players"]["p1"]["resources"] == before, got.get("reason"))

    got, _program = finalize(done, "g4")
    check("W7 p2's Equipment is not a legal choice", not got.get("committed"), got.get("reason"))

    got, program = finalize(done, "g1")
    if got.get("committed"):
        gone_state = IR.apply_program(got["next_effect_state"], {
            "schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "kill", "controller": "p2", "source_object": "u2",
            "effects": [{"op": "kill", "effect_id": "k", "object_id": "c1"}]})["next_state"]
        res = resolve({**got, "next_effect_state": gone_state}, program, choose(gone_state, "g1"))
        end = res.get("next_effect_state") or gone_state
        check("W8 the unit left the board: g1 is not attached", end["objects"]["g1"].get("attached_to") is None,
              res.get("reason"))

    bad_cost = IR.weaponmaster_program(after, "c1", "p1")
    bad_cost["effects"][0]["payment"][0]["reduce_power_any"] = -1
    check("V1 a negative reduction does not validate", bool(validate_program(bad_cost)))
    bad_op = IR.weaponmaster_program(after, "c1", "p1")
    del bad_op["effects"][1]["to"]
    check("V1 weaponmaster_attach without its unit does not validate", bool(validate_program(bad_op)))
    print(f"check_weaponmaster: {'FAILED ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
