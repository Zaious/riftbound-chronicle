#!/usr/bin/env python3
"""Regression gate for split damage: "Deal 5 damage split among any number of enemy units here."
(Volibear - Furious's attack trigger; Core 355.14, 355.14.a-h, 359.3.f.2, 417).

The engine grammar's own IR - one target decision (min 0, capped by the amount: 355.14.c), each
Target an enemy Unit at the source's current Battlefield, and a division decided at resolution
(355.14.e) - is run on a board where the source v1 (p1's) stands at bf1 with p2's e1 (Might 3),
e2 and e3 (Might 6), p1's f1, and p2's e9 at bf2. Must hold:
  - targets e1, e2, e3 divided 1/2/2: exactly that damage is marked on them, nothing on anyone else;
  - with no division, the program stops at damage_division_required naming the legal Targets, the
    amount, and how many must be kept;
  - refused: a division summing to 4, one naming a Unit that is not a Target, one leaving out a
    legal Target (355.14.f: each Target receives damage), a zero share (the decision validator);
  - six Targets for 5 damage: refused at finalization (target_count_illegal, 355.14.c) and at
    resolution;
  - e2 moved away before resolution: it is no longer a Target; the division covers e1 and e3, and
    one still naming e2 is refused (359.3.e);
  - the source moved to its Base: every Target mistargets ("here" is read on execution,
    359.3.f.2), nothing is dealt;
  - no Target chosen (min 0): a no_op, no division asked for;
  - the validator refuses a split with a max of its own, on another op, without targets, or with
    an amount read off the board;
  - Bonus Damage (Core 715.3: added once, to the amount split) - with the source at a Void Gate
    ("Spells and abilities deal 1 Bonus Damage to units here", bound onto bf1), and again with
    p1's Annie - Fiery ("Your spells and abilities deal 1 Bonus Damage"): 6 is split, six Targets
    are accepted at finalization and seven refused; a division of 6 is dealt exactly as divided
    (no share has the bonus added again) and the split's trace records the bonus once; divisions
    summing to 5 or to 8 are refused; with no division the amount asked for is 6;
  - through the resolution bridge: six Targets finalized with Annie in play, Annie gone before
    it resolves - the six are not counted again against the 5 left; 5 is divided among five of
    them (355.14.h) and a division keeping all six is refused;
  - the damage division is the controller's and is made as it resolves: one made by p2 is
    refused decision_controller_mismatch, one supplied for another stage is refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from engine_decisions import validate_engine_decisions  # noqa: E402

SENTENCE = "Deal 5 damage split among any number of enemy units here."


def unit(owner, might):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False}


def board():
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, owner, might, where in (("v1", "p1", 9, "bf1"), ("e1", "p2", 3, "bf1"), ("e2", "p2", 6, "bf1"),
                                     ("e3", "p2", 6, "bf1"), ("f1", "p1", 2, "bf1"), ("e9", "p2", 4, "bf2"),
                                     ("e4", "p2", 6, "bf1"), ("e5", "p2", 6, "bf1"), ("e6", "p2", 6, "bf1")):
        state["objects"][oid] = unit(owner, might)
        state["battlefields"][where]["objects"].append(oid)
    return settle_contested(state)


def split_program():
    effects = CG.compile_clause(SENTENCE, CG.load_grammar())["program_effects"]
    prog = program("volibear", *copy.deepcopy(effects))
    prog["source_object"] = "v1"
    prog["source_identity"] = "v1@0"      # 'here' reads a source whose identity the program declares
    return prog


def decisions(state, targets, division=None, *, identities=None):
    items = [{"decision_id": "t", "kind": "target_selection", "stage": "trigger_finalization", "controller": "p1",
              "value": list(targets), "selection_identities": {o: object_identity(state, o) for o in targets}}]
    if division is not None:
        items.append({"decision_id": "t-division", "kind": "damage_division", "stage": "resolution", "controller": "p1",
                      "value": dict(division),
                      "selection_identities": identities or {o: object_identity(state, o) for o in division}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": items}


def run(state, targets, division=None, chosen_on=None):
    return apply_program(state, split_program(), decisions=decisions(chosen_on or state, targets, division))


def dealt(before, result):
    after = result["next_state"]
    return {o: after["objects"][o]["damage"] - before["objects"][o]["damage"]
            for o in before["objects"] if before["objects"][o].get("kind") == "unit" and o in after["objects"]
            and after["objects"][o]["damage"] != before["objects"][o]["damage"]}


VOID_GATE = "Spells and abilities deal 1 Bonus Damage to units here."


def void_gate_board():
    """board(), with bf1 carrying the Void Gate statement the clause grammar lowers, and e7 there too."""
    import json
    state = board()
    state["objects"]["e7"] = unit("p2", 6)
    state["battlefields"]["bf1"]["objects"].append("e7")
    lowered = CG.compile_clause(VOID_GATE, CG.load_grammar())["passive"]
    text = json.dumps(lowered.get("state_lists") or {}).replace('"$source_object"', '"bf1"') \
        .replace('"$controller"', '"p2"').replace('"$clause_id"', '"bf1-statement"')
    for key, entries in json.loads(text).items():
        state.setdefault(key, []).extend(entries)
    return settle_contested(state)


def annie_board():
    """board(), with p1's Annie - Fiery in p1's Base ("Your spells and abilities deal 1 Bonus Damage"), and e7."""
    state = board()
    state["objects"]["e7"] = unit("p2", 6)
    state["battlefields"]["bf1"]["objects"].append("e7")
    state["objects"]["annie"] = unit("p1", 3)
    state["players"]["p1"]["zones"]["base"].append("annie")
    state["damage_modifiers"] = [{"modifier_id": "annie-fiery", "source_object": "annie", "controller": "p1", "amount": 1,
                                  "scope": {"kind": "controller_sources"}}]
    return settle_contested(state)


def bonus_cases(errors: list[str]) -> None:
    """Core 715.3: the Bonus Damage is added once, to the amount split - also to how many Targets
    may be chosen - and never again to each share."""
    prog = split_program()
    seven = ["e1", "e2", "e3", "e4", "e5", "e6", "e7"]
    for label, state in (("Void Gate", void_gate_board()), ("Annie - Fiery", annie_board())):
        if validate_state(state):
            errors.append(f"{label}: the board is invalid: {validate_state(state)}")
            continue
        try:
            six_ok = PT._check_play_targets(state, "p1", prog, decisions(state, seven[:6]), stage="trigger_finalization")
            if sorted(six_ok) != sorted(seven[:6]):
                errors.append(f"{label}: six Targets for 5 + 1 Bonus Damage were not all accepted: {six_ok}")
        except PT.PlayError as refusal:
            errors.append(f"{label}: six Targets for 5 + 1 Bonus Damage were refused at finalization "
                          f"({refusal.reason_code}); the bonus raises the cap (715.3)")
        try:
            PT._check_play_targets(state, "p1", prog, decisions(state, seven), stage="trigger_finalization")
            errors.append(f"{label}: seven Targets for 5 + 1 damage were accepted at finalization")
        except PT.PlayError as refusal:
            if refusal.reason_code != "target_count_illegal":
                errors.append(f"{label}: seven Targets were refused for the wrong reason: {refusal.reason_code}")
        done = run(state, ["e1", "e2", "e3"], {"e1": 2, "e2": 2, "e3": 2})
        if not done.get("committed") or dealt(state, done) != {"e1": 2, "e2": 2, "e3": 2}:
            errors.append(f"{label}: a 2/2/2 division of 5 + 1 Bonus Damage was not dealt as divided: "
                          f"{done.get('reason') or done.get('errors')} {dealt(state, done) if done.get('committed') else ''}")
        else:
            split = next((e for e in done["trace"] if e.get("division") is not None), {})
            if (split.get("bonus_damage") or {}).get("amount") != 1 or split["bonus_damage"].get("base_amount") != 5 \
                    or split.get("division_amount") != 6:
                errors.append(f"{label}: the split's trace does not record the bonus once on the amount split: "
                              f"{split.get('bonus_damage')} {split.get('division_amount')}")
        wide = run(state, seven[:6], {o: 1 for o in seven[:6]})
        if not wide.get("committed") or dealt(state, wide) != {o: 1 for o in seven[:6]}:
            errors.append(f"{label}: 6 divided 1 each among six Targets was not dealt: {wide.get('reason') or wide.get('errors')}")
        for why, division in (("summing to 5 (the bonus left out)", {"e1": 1, "e2": 2, "e3": 2}),
                              ("summing to 8 (the bonus added to each share)", {"e1": 2, "e2": 3, "e3": 3})):
            got = run(state, ["e1", "e2", "e3"], division)
            if got.get("committed") or got.get("valid") is not False:
                errors.append(f"{label}: a division {why} was accepted")
        asked = run(state, ["e1", "e2", "e3"])
        if asked.get("reason_code") != "damage_division_required" or asked.get("division_amount") != 6:
            errors.append(f"{label}: with no division the amount asked for is {asked.get('division_amount')}, not 6")


def bridged_bonus_case(errors: list[str]) -> None:
    """Six Targets finalized with Annie - Fiery in play (5 + 1); Annie gone before it resolves. The
    six were counted when chosen (355.14.c); now 5 is divided among five of them (355.14.h)."""
    from check_rules_core import fixture
    from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program
    from rules_core import next_procedure, pass_priority, schedule_triggered_items
    prog = split_program()
    prog.pop("source_identity")               # a registered template; the chain item supplies it
    registry = {prog["program_id"]: prog}
    state = annie_board()
    descriptor = {"trigger_id": "v1-attack", "controller": "p1", "source_object": "v1", "controller_order": 0,
                  "effect_program_id": prog["program_id"], "optional_at_finalize": False,
                  "effect_program_hash": program_hash(prog), "trigger_kind": "triggered",
                  "source_identity": object_identity(state, "v1")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    if not scheduled.get("applied"):
        errors.append(f"bridge: the trigger was not scheduled: {scheduled.get('reason_code')}")
        return
    six = ["e1", "e2", "e3", "e4", "e5", "e6"]
    final = finalize_trigger(scheduled["next_state"], state, registry, decisions(state, six))
    if not final.get("committed"):
        errors.append(f"bridge: six Targets with Annie in play were not finalized: {final.get('reason')} {final.get('message')}")
        return
    timing = final["next_timing_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    step = next_procedure(timing)
    if step.get("procedure") != "resolve_newest_finalized":
        errors.append(f"bridge: the finalized split is not next to resolve: {step}")
        return
    item_id = step["subject"]
    chain_item = next(i for i in timing["chain"]["items"] if i["id"] == item_id)
    dispatched, refusal = dispatch_program(registry, chain_item)
    if refusal:
        errors.append(f"bridge: dispatch refused: {refusal}")
        return
    gone = copy.deepcopy(final["next_effect_state"])
    gone["players"]["p1"]["zones"]["base"].remove("annie")
    gone["players"]["p1"]["zones"]["trash"].append("annie")
    gone["objects"]["annie"]["identity"] = "annie@1"

    def division(values):
        return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(gone),
                "decisions": [{"decision_id": "t-division", "kind": "damage_division", "stage": "resolution",
                               "controller": "p1", "value": dict(values),
                               "selection_identities": {o: object_identity(gone, o) for o in values}}]}

    five = {o: 1 for o in six[:5]}
    kept = resolve_with_program(timing, item_id, gone, dispatched, engine_decisions=division(five))
    if not kept.get("committed") or dealt(gone, {"next_state": kept["next_effect_state"]}) != five:
        errors.append(f"bridge: with Annie gone, 5 among five of the six finalized Targets was not dealt "
                      f"(355.14.h): {kept.get('reason')}")
    all_six = resolve_with_program(timing, item_id, gone, dispatched, engine_decisions=division({o: 1 for o in six}))
    if all_six.get("committed"):
        errors.append("bridge: with Annie gone, a division keeping all six Targets for 5 damage was accepted")


def division_decision_cases(errors: list[str]) -> None:
    """The division is the program controller's, made as the split resolves (355.14.e, 355.14.h)."""
    state = board()
    theirs = decisions(state, ["e1", "e2", "e3"], {"e1": 3, "e2": 1, "e3": 1})
    for entry in theirs["decisions"]:
        if entry["kind"] == "damage_division":
            entry["controller"] = "p2"
    got = apply_program(state, split_program(), decisions=theirs)
    if got.get("committed") or got.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"a damage division made by p2 for p1's split was not refused decision_controller_mismatch: "
                      f"{got.get('reason_code')} {got.get('errors')}")
    early = decisions(state, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2})
    for entry in early["decisions"]:
        if entry["kind"] == "damage_division":
            entry["stage"] = "trigger_finalization"
    got = apply_program(state, split_program(), decisions=early)
    if got.get("committed") or got.get("valid") is not False:
        errors.append(f"a damage division supplied at finalization, not as the split resolves, was accepted: "
                      f"{got.get('reason_code')}")


def main() -> int:
    errors: list[str] = []
    bonus_cases(errors)
    bridged_bonus_case(errors)
    division_decision_cases(errors)
    prog = split_program()
    if validate_program(prog):
        errors.append(f"the grammar's split program is invalid: {validate_program(prog)}")
    state = board()

    done = run(state, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2})
    if not done.get("committed") or dealt(state, done) != {"e1": 1, "e2": 2, "e3": 2}:
        errors.append(f"a 1/2/2 division was not dealt as divided: {done.get('reason') or done.get('errors')} "
                      f"{dealt(state, done) if done.get('committed') else ''}")

    asked = run(state, ["e1", "e2", "e3"])
    if asked.get("reason_code") != "damage_division_required" or asked.get("division_candidates") != ["e1", "e2", "e3"] \
            or asked.get("division_amount") != 5 or asked.get("division_keeps") != 3 or asked.get("committed"):
        errors.append(f"with no division the program did not ask for one: {asked.get('reason_code')} {asked.get('division_candidates')}")

    for label, division in (("summing to 4", {"e1": 1, "e2": 1, "e3": 2}),
                            ("naming a Unit that is not a Target", {"e1": 1, "e2": 2, "e9": 2}),
                            ("leaving out a legal Target", {"e1": 2, "e2": 3})):
        got = run(state, ["e1", "e2", "e3"], division)
        if got.get("committed") or got.get("valid") is not False:
            errors.append(f"a division {label} was accepted: {got.get('reason_code')}")
    zero = decisions(state, ["e1", "e2"], {"e1": 0, "e2": 5})
    if not validate_engine_decisions(zero):
        errors.append("a zero share in a damage division passed the decision validator (Core 355.14.g)")

    six = ["e1", "e2", "e3", "e4", "e5", "e6"]
    try:
        PT._check_play_targets(state, "p1", prog, decisions(state, six), stage="trigger_finalization")
        errors.append("six Targets for 5 damage were accepted at finalization (Core 355.14.c)")
    except PT.PlayError as refusal:
        if refusal.reason_code != "target_count_illegal":
            errors.append(f"six Targets were refused for the wrong reason: {refusal.reason_code}")
    five_ok = PT._check_play_targets(state, "p1", prog, decisions(state, six[:5]), stage="trigger_finalization")
    if sorted(five_ok) != sorted(six[:5]):
        errors.append(f"five Targets for 5 damage were not accepted at finalization: {five_ok}")
    over = run(state, six, {o: 1 for o in six[:5]})
    if over.get("committed"):
        errors.append("six Targets for 5 damage resolved")

    moved = copy.deepcopy(state)
    moved["battlefields"]["bf1"]["objects"].remove("e2")
    moved["battlefields"]["bf2"]["objects"].append("e2")
    moved = settle_contested(moved)
    kept = apply_program(moved, split_program(), decisions=decisions(moved, ["e1", "e2", "e3"], {"e1": 2, "e3": 3}))
    if not kept.get("committed") or dealt(moved, kept) != {"e1": 2, "e3": 3}:
        errors.append(f"a Target that left 'here' was not dropped from the split: {kept.get('reason') or kept.get('errors')}")
    stale = apply_program(moved, split_program(), decisions=decisions(moved, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2}))
    if stale.get("committed"):
        errors.append("a division still naming a Target that left 'here' was accepted")

    home = copy.deepcopy(state)
    home["battlefields"]["bf1"]["objects"].remove("v1")
    home["players"]["p1"]["zones"]["base"].append("v1")
    home = settle_contested(home)
    gone = apply_program(home, split_program(), decisions=decisions(home, ["e1", "e2", "e3"], {"e1": 1, "e2": 2, "e3": 2}))
    if not gone.get("committed") or dealt(home, gone):
        errors.append(f"with its source gone to Base the split still dealt damage (359.3.f.2): {gone.get('reason_code')}")

    none = run(state, [])
    if not none.get("committed") or dealt(state, none):
        errors.append(f"no Target chosen was not a quiet no_op: {none.get('reason_code')} {none.get('errors')}")

    base_effect = copy.deepcopy(split_program()["effects"][0])
    for label, effect in (("a max of its own", {**base_effect, "targets": {**base_effect["targets"], "max": 5}}),
                          ("on a kill", {**{k: v for k, v in base_effect.items() if k != "amount"}, "op": "kill"}),
                          ("without targets", {k: v for k, v in base_effect.items() if k != "targets"}),
                          ("an amount read off the board", {**{k: v for k, v in base_effect.items() if k != "amount"},
                                                            "amount_ref": {"kind": "program_source_current_might"}})):
        if not validate_program(program("bad", effect)):
            errors.append(f"a split {label} was accepted by the validator")

    if errors:
        print("FAILED: split damage" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'deal 5 damage split among any number of enemy units here' - Targets chosen at finalization, no more "
          "than the damage; the division decided at resolution, all of it, at least 1 to each Target kept; a Target "
          "that left 'here' drops out, the source gone mistargets them all, no Target is a no_op; bad divisions and "
          "bad shapes are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
