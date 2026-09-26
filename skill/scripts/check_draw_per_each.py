#!/usr/bin/env python3
""""Draw 1 for each of your [Mighty] units." (Kadregrin the Infernal) - a draw counted as it executes.

The engine grammar lowers the sentence (alone and inside "When you play me, ...") to one draw
with count_per {kind: units_you_control, mighty: true}: the printed number times how many units
the program's controller controls on the board with Might 5 or greater (Core 708), by their
current Might (710).

Must hold, on real apply_program runs:
  - two Mighty units of p1 (one of them the card itself): p1 draws 2;
  - a 4 Might unit does not count; given +1 Might before the draw it does (710);
  - p2's Mighty unit does not count; a Might 5 unit in p1's hand does not (not on the board);
  - no Mighty unit: nothing is drawn, a named no_op (count_per_zero);
  - "draw 2 for each": 2 per unit;
  - validator: count_per on another op, another kind, or with no printed count is refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import apply_program, validate_program, validate_state  # noqa: E402

UNIT = {"kind": "unit", "might_modifiers": [], "damage": 0, "exhausted": False}


def board():
    state = base_state()
    state["players"]["p1"]["zones"]["banishment"] += state["players"]["p1"]["zones"]["main_deck"]
    state["players"]["p1"]["zones"]["main_deck"] = []
    for n in range(8):
        state["objects"][f"d{n}"] = {**UNIT, "kind": "spell", "owner": "p1", "controller": "p1", "base_might": 0}
        state["players"]["p1"]["zones"]["main_deck"].append(f"d{n}")
    state["objects"]["kad"] = {**UNIT, "owner": "p1", "controller": "p1", "base_might": 8}
    state["objects"]["big"] = {**UNIT, "owner": "p1", "controller": "p1", "base_might": 5}
    state["objects"]["four"] = {**UNIT, "owner": "p1", "controller": "p1", "base_might": 4}
    state["objects"]["theirs"] = {**UNIT, "owner": "p2", "controller": "p2", "base_might": 6}
    state["objects"]["held"] = {**UNIT, "owner": "p1", "controller": "p1", "base_might": 7}
    state["players"]["p1"]["zones"]["base"] += ["kad", "four"]
    state["battlefields"]["bf1"]["objects"] += ["big", "theirs"]
    state["players"]["p1"]["zones"]["hand"].append("held")
    return settle_contested(state)


def draws(state, effects):
    before = len(state["players"]["p1"]["zones"]["hand"])
    done = apply_program(state, program("kadregrin", *copy.deepcopy(effects)))
    if not done.get("committed"):
        return None, done
    return len(done["next_state"]["players"]["p1"]["zones"]["hand"]) - before, done


def bound(effects):
    return [dict(e, player="p1") for e in effects]


def main() -> int:
    errors: list[str] = []
    wrapped = CG.compile_clause("When you play me, draw 1 for each of your [Mighty] units.", CG.load_grammar())
    want = [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1,
             "count_per": {"kind": "units_you_control", "mighty": True}}]
    if wrapped.get("production_id") != "when_you_play_me" or wrapped.get("program_effects") != want:
        errors.append(f"Kadregrin's sentence did not lower to one counted draw: {wrapped}")
    effects = bound(want)
    start = board()
    if validate_state(start):
        print(f"FAILED: the board is invalid: {validate_state(start)}")
        return 1
    got, done = draws(start, effects)
    if got != 2:
        errors.append(f"two Mighty units of p1 (the card itself and a Might 5 one) should draw 2, drew {got} "
                      f"({(done or {}).get('reason') or (done or {}).get('errors')})")
    read = next((e for e in done.get("trace") or [] if e.get("effect_id") == "dr"), {}).get("count_read", {})
    if read.get("counted") != ["big", "kad"]:
        errors.append(f"the draw should record which units it counted: {read}")
    pumped = copy.deepcopy(start)
    pumped["continuous_effects"] = [{"effect_id": "pump", "kind": "might_arithmetic",
                                     "source": {"object": "four", "identity": None, "name": "pump"},
                                     "affects": {"scope": "object", "object": "four", "identity": "four@0"},
                                     "layer": "arithmetic", "sublayer": "increase", "timestamp": 1,
                                     "value": {"amount": 1, "mode": "delta"}, "duration": {"kind": "permanent"}, "passive": False}]
    if draws(pumped, effects)[0] != 3:
        errors.append("a 4 Might unit given +1 is Mighty by its current Might (710) and should count")
    none = copy.deepcopy(start)
    for unit in ("kad", "big"):
        none["objects"][unit]["base_might"] = 4
    got, done = draws(none, effects)
    trace = next((e for e in (done or {}).get("trace") or [] if e.get("effect_id") == "dr"), {})
    if got != 0 or trace.get("outcome") != "no_op" or trace.get("reason") != "count_per_zero":
        errors.append(f"no Mighty unit: nothing drawn, a named no_op: {got} {trace}")
    twice = [dict(effects[0], count=2)]
    if draws(start, twice)[0] != 4:
        errors.append("'draw 2 for each' should draw 2 per Mighty unit")

    for bad, why in (({"op": "kill", "effect_id": "k", "object_id": "kad", "count": 1, "count_per": {"kind": "units_you_control", "mighty": True}}, "on a kill"),
                     ({"op": "draw", "effect_id": "d", "player": "p1", "count": 1, "count_per": {"kind": "units_you_control"}}, "without mighty"),
                     ({"op": "draw", "effect_id": "d", "player": "p1", "count_per": {"kind": "units_you_control", "mighty": True}}, "with no printed count"),
                     ({"op": "draw", "effect_id": "d", "player": "p1", "count": 1, "count_per": {"kind": "cards_in_hand", "mighty": True}}, "another kind")):
        if not validate_program(program("bad", bad)):
            errors.append(f"count_per {why} validated")

    if errors:
        print("FAILED: draw for each" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'draw 1 for each of your [Mighty] units' draws once per unit its controller controls on the board with "
          "current Might 5+ (708, 710), read as it executes; opponents' units, units in hand and 4 Might units do not count; "
          "none is a named no_op.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
