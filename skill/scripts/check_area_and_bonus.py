#!/usr/bin/env python3
"""
Gate for C-20 (ADR-0007 §4–5): Battlefield targets with criteria expansion,
and Bonus Damage.

Must hold:
  - "all enemy units at a battlefield": the Battlefield is the target
    (355.10.b); the units are found by criteria at resolution and are not
    targets — the event says so, lists them, and carries the criteria and
    a snapshot hash; friendly units at the same Battlefield are untouched;
  - "all units at battlefields" targets nothing and expands over every
    Battlefield; an empty Battlefield gives no_op with full completion;
  - a Battlefield target whose identity changed → skipped_illegal_target
    and no damage; choosing a Battlefield that is not in the state at play →
    illegal; a state naming a Battlefield it lacks → invalid_input;
  - Bonus Damage: the controller's sources add once to their own spells
    only; a location source adds only to units at that Battlefield; two
    sources sum once (714); each affected unit gets it separately (715.2);
    reduce_damage sees the total including Bonus (437.1.a.1); a source off
    the board contributes nothing; heal is untouched; unknown scope →
    unsupported; non-positive amount → invalid_input;
  - determinism, purity, engine-check wrapping.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, hash_value, validate_program, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

BF_TARGET = {"object_id": "bf1", "kind": "battlefield", "chosen_zone_class": "board", "bound_identity": "bf1@0"}


def area(amount, *, target=True, relation="enemy", effect_id="area"):
    effect = {"op": "deal_damage", "amount": amount, "effect_id": effect_id,
              "affected": {"criteria": {"kind": "unit", "location": "target_battlefield" if target else "any_battlefield", **({"controller_relation": relation} if relation else {})}}}
    if target:
        effect["target"] = dict(BF_TARGET)
    return effect


def main() -> int:
    errors: list[str] = []
    state = base_state()
    # both units at bf1; u1 friendly to p1 (3 Might, 1 damage), u2 enemy (4 Might)
    state["players"]["p1"]["zones"]["base"].remove("u1"); state["players"]["p2"]["zones"]["base"].remove("u2")
    state["battlefields"]["bf1"]["objects"] += ["u1", "u2"]
    snapshot = copy.deepcopy(state)

    def ev(result):
        return result["trace"][0] if result.get("committed") else {}

    # --- Firestorm: enemy units at the targeted battlefield -------------------------------
    fire = apply_program(state, program("firestorm", area(3)))
    e = ev(fire)
    if not fire.get("committed") or e.get("targeted_battlefield") != "bf1" or e.get("affected_objects") != ["u2"] or e.get("affected_are_targets") is not False:
        errors.append(f"Firestorm did not target the battlefield and affect only enemy units: {fire.get('reason') or fire.get('errors')} {e}")
    else:
        nxt = fire["next_state"]
        if nxt["objects"]["u2"]["damage"] != 3 or nxt["objects"]["u1"]["damage"] != 1:
            errors.append("area damage hit the wrong units")
        if not e.get("criteria_snapshot_hash", "").startswith("sha256:") or e.get("criteria", {}).get("location") != "target_battlefield" or "Core 355.10.b" not in e.get("rule_locators", []):
            errors.append(f"area event lacks criteria snapshot or locators: {e.get('rule_locators')}")
        if any("target" in x for x in e.get("expansion_trace", [{}])[0]) and e["expansion_trace"][0].get("target_outcome"):
            errors.append("an affected unit was treated as a target")
        if validate_state(nxt):
            errors.append(f"state after area invalid: {validate_state(nxt)}")
    if state != snapshot or apply_program(state, program("firestorm", area(3))) != fire:
        errors.append("area expansion mutated input or is not deterministic")
    # Tibbers: all units at battlefields, no target
    tib = apply_program(state, program("tibbers", area(3, target=False, relation=None)))
    e = ev(tib)
    if not tib.get("committed") or e.get("targeted_battlefield") is not None or sorted(e.get("affected_objects", [])) != ["u1", "u2"] or tib["next_state"]["objects"]["u1"]["damage"] != 4:
        errors.append(f"'all units at battlefields' did not expand over every battlefield without a target: {e.get('affected_objects')} {tib.get('reason')}")
    empty = base_state()
    none_there = apply_program(empty, program("firestorm", area(3)))
    e = ev(none_there)
    if not none_there.get("committed") or e.get("outcome") != "no_op" or e.get("completion") != "full" or e.get("affected_objects") != []:
        errors.append(f"an empty battlefield did not give no_op/full: {e.get('outcome')} {e.get('completion')}")
    # invalid battlefield target at resolution: identity changed
    changed = copy.deepcopy(state); changed["battlefields"]["bf1"]["identity"] = "bf1@1"
    gone = apply_program(changed, program("firestorm", area(3)))
    e = ev(gone)
    if not gone.get("committed") or e.get("outcome") != "skipped_illegal_target" or gone["next_state"]["objects"]["u2"]["damage"] != 0:
        errors.append(f"a battlefield target with a changed identity was not skipped: {e.get('outcome')}")
    # validation
    if not any("battlefield target" in x for x in validate_program(program("bad", {**area(3), "target": {"object_id": "u2", "chosen_zone_class": "board"}}))):
        errors.append("target_battlefield criteria with a unit target was accepted")
    if not any("targets nothing" in x for x in validate_program(program("bad2", {**area(3, target=False), "target": dict(BF_TARGET)}))):
        errors.append("any_battlefield criteria with a target was accepted")
    missing = copy.deepcopy(state); missing["battlefields"]["bf1"]["identity"] = "nope"
    if not validate_state(missing):
        errors.append("a malformed battlefield identity was accepted")
    # choosing a battlefield at play: existing → committed; absent → illegal
    hand = base_state(); hand["players"]["p1"]["zones"]["main_deck"].remove("c1"); hand["players"]["p1"]["zones"]["hand"].append("c1")
    hand["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    prog = program("spell-1-effects", {"op": "deal_damage", "amount": 3, "effect_id": "area", "target": {"decision_ref": "bf", "kind": "battlefield", "chosen_zone_class": "board"},
                                       "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "target_battlefield"}}})
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"}, "cost": {"base": {"energy": 1, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}, "effect_program_id": "spell-1-effects"}
    def choose(bf):
        return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(hand), "decisions": [{"decision_id": "bf", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [bf], "selection_identities": {bf: f"{bf}@0"}}]}
    ok = play_card(fixture(), hand, decl, engine_decisions=choose("bf1"), effect_program=prog)
    if not ok.get("committed"):
        errors.append(f"choosing an existing battlefield at play was refused: {ok.get('reason') or ok.get('errors')}")
    bad = play_card(fixture(), hand, decl, engine_decisions=choose("bf9"), effect_program=prog)
    if bad.get("valid") is not True or bad.get("committed") or bad.get("reason_code") != "target_illegal_at_play":
        errors.append(f"choosing a battlefield that is not in the state was not illegal: {bad.get('reason_code')} {bad.get('reason')}")

    # --- Bonus Damage --------------------------------------------------------------------------
    fiery = copy.deepcopy(state)
    fiery["objects"]["a1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
    fiery["players"]["p1"]["zones"]["base"].append("a1")
    fiery["damage_modifiers"] = [{"modifier_id": "annie-fiery", "source_object": "a1", "controller": "p1", "amount": 1, "scope": {"kind": "controller_sources"}}]
    if validate_state(fiery):
        errors.append(f"damage_modifiers rejected: {validate_state(fiery)}")
    single = apply_program(fiery, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))
    e = ev(single)
    if not single.get("committed") or single["next_state"]["objects"]["u2"]["damage"] != 3 or e.get("bonus_damage", {}).get("amount") != 1 or e["bonus_damage"].get("base_amount") != 2:
        errors.append(f"controller's Bonus Damage was not added once to a single target: {e.get('bonus_damage')} {single.get('reason')}")
    p2_prog = {**program("their-bolt", {"op": "deal_damage", "object_id": "u1", "amount": 2, "effect_id": "dmg"}), "controller": "p2"}
    theirs = apply_program(fiery, p2_prog)
    if not theirs.get("committed") or theirs["next_state"]["objects"]["u1"]["damage"] != 3 or "bonus_damage" in ev(theirs):
        errors.append("an opponent's spell received the controller's Bonus Damage")
    off = copy.deepcopy(fiery); off["players"]["p1"]["zones"]["base"].remove("a1"); off["players"]["p1"]["zones"]["trash"].append("a1")
    if apply_program(off, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))["next_state"]["objects"]["u2"]["damage"] != 2:
        errors.append("a source off the board still added Bonus Damage")
    gate = copy.deepcopy(state)
    gate["damage_modifiers"] = [{"modifier_id": "void-gate", "source_object": "bf1", "controller": "p2", "amount": 1, "scope": {"kind": "location", "battlefield": "bf1"}}]
    if validate_state(gate):
        errors.append(f"a Battlefield source was rejected: {validate_state(gate)}")
    at_bf = apply_program(gate, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))
    at_base = copy.deepcopy(gate); at_base["battlefields"]["bf1"]["objects"].remove("u2"); at_base["players"]["p2"]["zones"]["base"].append("u2")
    at_base_res = apply_program(at_base, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))
    if at_bf["next_state"]["objects"]["u2"]["damage"] != 3 or at_base_res["next_state"]["objects"]["u2"]["damage"] != 2:
        errors.append("location-scoped Bonus Damage did not follow the unit's battlefield")
    both = copy.deepcopy(fiery); both["damage_modifiers"] += gate["damage_modifiers"]
    summed = apply_program(both, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))
    if summed["next_state"]["objects"]["u2"]["damage"] != 4 or len(ev(summed).get("bonus_damage", {}).get("sources", [])) != 2:
        errors.append("two Bonus Damage sources were not summed once (714)")
    each = apply_program(fiery, program("firestorm", area(3, relation=None)))
    if not each.get("committed") or each["next_state"]["objects"]["u1"]["damage"] != 5 or each["next_state"]["objects"]["u2"]["damage"] != 4:
        errors.append(f"Bonus Damage was not added separately to each affected unit (715.2): {each.get('reason')}")
    shielded = copy.deepcopy(fiery)
    shielded["replacement_effects"] = [{"replacement_id": "shield", "controller": "p2", "source_object": "u2", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 1, "target_object_id": "u2"}]
    reduced = apply_program(shielded, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))
    if not reduced.get("committed") or reduced["next_state"]["objects"]["u2"]["damage"] != 2 or ev(reduced).get("outcome") != "replaced_modified_applied":
        errors.append(f"Prevent did not see the total including Bonus (437.1.a.1): {ev(reduced).get('outcome')} {reduced['next_state']['objects']['u2']['damage'] if reduced.get('committed') else reduced.get('reason')}")
    healed = apply_program(fiery, program("mend", {"op": "heal_damage", "object_id": "u1", "amount": 1, "effect_id": "h"}))
    if healed["next_state"]["objects"]["u1"]["damage"] != 0 or "bonus_damage" in ev(healed):
        errors.append("Bonus Damage touched a heal")
    weird = copy.deepcopy(fiery); weird["damage_modifiers"][0]["scope"] = {"kind": "everything"}
    odd = apply_program(weird, program("bolt", {"op": "deal_damage", "object_id": "u2", "amount": 2, "effect_id": "dmg"}))
    if odd.get("committed") or odd.get("unsupported") is not True:
        errors.append("an unknown Bonus Damage scope was not unsupported")
    negative = copy.deepcopy(fiery); negative["damage_modifiers"][0]["amount"] = 0
    if not validate_state(negative):
        errors.append("a non-positive Bonus Damage amount was accepted")
    check = build_engine_check("effect", fire, input_hashes={"effect_state": hash_value(state), "effect_program": "sha256:" + "4" * 64})
    if check["outcome"] != "supported" or "battlefield_targets" not in check["coverage"]["supported_scope"]:
        errors.append("engine-check did not declare battlefield targets")

    if errors:
        print("FAILED: area / bonus checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: area instructions target the Battlefield and affect non-target units found by criteria at resolution (recorded with snapshot), skip on an invalid Battlefield, and expand over every Battlefield when nothing is targeted; Bonus Damage is summed once from the controller's and the location's active sources, added per affected unit before Prevent sees the amount, never to heals or opponents' spells, and an unknown scope is unsupported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
