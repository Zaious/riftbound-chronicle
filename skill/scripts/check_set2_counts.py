#!/usr/bin/env python3
"""
Regression gate: a play trigger conditioned on the Gear its controller controls, and a draw counted per other Battlefield
the controller's side controls (2026-10-29).

"When you play me, if you control two or more gear, ready me." lowers to a play trigger whose condition is
controls_units {count 2, of_kind gear} (Core 383.2.a.1), read as the play completes (420.4.a). "Draw 1 for each other
battlefield you or allies control." is a draw with count_per {kind battlefields_your_side_controls, other: true}: the
printed number times the Battlefields controlled by a player on the controller's side (190.2.b), the program's own
source - the Battlefield the ability is printed on - not counted.

Must hold:
  - the gear trigger, through the real play transaction: two friendly Gear - scheduled; three - scheduled; one -
    not; two friendly Units and no Gear - not; two of the opponent's Gear - not;
  - controls_units with of_kind: a kind outside COUNTED_KINDS is refused;
  - the count, on real apply_program runs from a Battlefield source: the source and two others controlled by p1 - 2
    drawn; one other controlled by p2 - not counted; an uncontrolled one - not counted; only the source - nothing drawn,
    a named no_op (count_per_zero);
  - mutations caught: an engine counting Units for of_kind gear; one counting the source Battlefield.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_object_tags import scheduled  # noqa: E402

SENTENCE = "When you play me, if you control two or more gear, ready me."
CONDITION = {"kind": "controls_units", "count": 2, "of_kind": "gear"}
COUNT = {"kind": "battlefields_your_side_controls", "other": True}


def thing(owner, kind):
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": 2 if kind == "unit" else 0,
            "might_modifiers": [], "damage": 0, "exhausted": False}


def gear_board(others):
    """p1's c1 in hand, its play trigger conditioned on two Gear; `others`: [(owner, kind)] in their owner's Base."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    trigger = {"trigger_id": "c1-on-play", "controller": "p1", "source_object": "c1", "controller_order": 0,
               "effect_program_id": "c1-on-play-effects", "optional_at_finalize": False, "condition": dict(CONDITION)}
    state["objects"]["c1"].update({"kind": "unit", "base_might": 3, "play_triggers": [trigger]})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    for n, (owner, kind) in enumerate(others):
        state["objects"][f"o{n}"] = thing(owner, kind)
        state["players"][owner]["zones"]["base"].append(f"o{n}")
    return state


GEAR_CASES = {
    "two_friendly_gear": ([("p1", "gear"), ("p1", "gear")], ["c1-on-play"]),
    "three_friendly_gear": ([("p1", "gear")] * 3, ["c1-on-play"]),
    "one_friendly_gear": ([("p1", "gear")], []),
    "two_friendly_units": ([("p1", "unit"), ("p1", "unit")], []),
    "two_of_the_opponents_gear": ([("p2", "gear"), ("p2", "gear")], []),
}


def bf_board(holders):
    """bf0 (the source) controlled by p1; one more Battlefield per entry of `holders` (its controller or None)."""
    state = base_state()
    state["players"]["p1"]["zones"]["banishment"] += state["players"]["p1"]["zones"]["main_deck"]
    state["players"]["p1"]["zones"]["main_deck"] = []
    for n in range(6):
        state["objects"][f"d{n}"] = thing("p1", "spell")
        state["players"]["p1"]["zones"]["main_deck"].append(f"d{n}")
    state["battlefields"] = {"bf0": {"controller": "p1", "objects": []}}
    for n, holder in enumerate(holders, start=1):
        state["battlefields"][f"bf{n}"] = {"controller": holder, "objects": []}
    return state


COUNT_CASES = {
    "two_others_of_yours": (["p1", "p1"], 2),
    "one_of_yours_one_of_theirs": (["p1", "p2"], 1),
    "one_of_yours_one_uncontrolled": (["p1", None], 1),
    "only_the_source": ([], 0),
}


def drawn(state):
    prog = {**program("seat", {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1, "count_per": dict(COUNT)}),
            "source_object": "bf0"}
    before = len(state["players"]["p1"]["zones"]["hand"])
    done = IR.apply_program(copy.deepcopy(state), prog)
    if not done.get("committed"):
        return f"refused: {done.get('reason') or done.get('errors')}"
    trace = next((e for e in done.get("trace") or [] if e.get("effect_id") == "dr"), {})
    got = len(done["next_state"]["players"]["p1"]["zones"]["hand"]) - before
    return got if got or trace.get("reason") == "count_per_zero" else f"0 without count_per_zero ({trace.get('outcome')})"


def main() -> int:
    errors: list[str] = []
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    descriptor = ((lowered.get("passive") or {}).get("object_fields") or {}).get("play_triggers") or [{}]
    if lowered.get("production_id") != "when_you_play_me_if_you_control_n_or_more_gear" \
            or descriptor[0].get("condition") != CONDITION:
        errors.append(f"the gear sentence lowered to {lowered.get('production_id')} {descriptor}")

    def gear_runs():
        return {label: scheduled(gear_board(others)) for label, (others, _want) in GEAR_CASES.items()}
    for label, got in gear_runs().items():
        if got != GEAR_CASES[label][1]:
            errors.append(f"{label}: scheduled {got}, not {GEAR_CASES[label][1]} (Core 383.2.a.1)")
    if not IR.validate_condition({"kind": "controls_units", "count": 1, "of_kind": "spell"}):
        errors.append("controls_units of_kind spell validated")

    def count_runs():
        return {label: drawn(bf_board(holders)) for label, (holders, _want) in COUNT_CASES.items()}
    for label, got in count_runs().items():
        if got != COUNT_CASES[label][1]:
            errors.append(f"{label}: drew {got}, not {COUNT_CASES[label][1]} (Core 190.2.b)")
    if not IR.validate_program(program("seat", {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1,
                                                 "count_per": {"kind": "battlefields_your_side_controls"}})):
        errors.append("a count_per without other validated")
    # mutations
    saved_eval, saved_count = IR.evaluate_condition, IR.count_per_value

    def units_for_gear(state, condition, **kw):
        return saved_eval(state, {k: v for k, v in condition.items() if k != "of_kind"}, **kw)

    def source_counted(state, spec, controller, source=None):
        return saved_count(state, spec, controller, None)
    try:
        IR.evaluate_condition = units_for_gear
        moved_gear = [k for k, v in gear_runs().items() if v != GEAR_CASES[k][1]]
    finally:
        IR.evaluate_condition = saved_eval
    try:
        IR.count_per_value = source_counted
        moved_count = [k for k, v in count_runs().items() if v != COUNT_CASES[k][1]]
    finally:
        IR.count_per_value = saved_count
    if not moved_gear:
        errors.append("mutation not caught: an engine counting Units for of_kind gear")
    if not moved_count:
        errors.append("mutation not caught: an engine counting the source Battlefield")
    if errors:
        print("FAILED: set 2 gear condition and battlefield count")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"OK: 'if you control two or more gear' schedules the play trigger exactly with two friendly Gear (383.2.a.1); "
          f"'for each other battlefield you or allies control' counts the side's other Battlefields (190.2.b); mutations "
          f"caught on {moved_gear} and {moved_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
