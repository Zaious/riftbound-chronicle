#!/usr/bin/env python3
"""A granted [Temporary] with no duration, on "a unit at a battlefield or a gear" (Fading Memories).

  Core 816.1.a  Temporary is present on Permanents - a Unit or a Gear may be granted it;
  Core 816.1.b  short for "At the start of this permanent's controller's Beginning Phase, before
                scoring, kill this" - read from the computed characteristics, so a granted one counts;
  Core 801.3.a.3 a grant that states no duration lasts as long as the object stays on the board.

The engine grammar lowers the sentence to one grant_keyword {temporary, permanent} on a target
with any_of [{kind: unit, location: battlefield}, {kind: gear}].

Must hold:
  - an enemy unit at a battlefield: granted, its controller's Temporary trigger exists, and
    that trigger's program kills it; still Temporary the next turn (no duration);
  - an enemy gear in its base: granted, with its own trigger;
  - a unit in a base, and a spell in the trash: not a legal target - ignored, nothing granted;
  - the object leaves the board (back to hand): the grant is gone with the old object (124);
  - a real turn: p1's granted unit is scheduled with the Beginning Step's triggers (816.1.c);
  - validator / executor: any_of with one alternative, any_of beside a kind, an alternative with
    another field, a permanent Tank, and Temporary on a rune are each refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from check_turn_cycle import duel_board, handled, setup_timing  # noqa: E402
from effect_ir import (apply_program, has_keyword, object_identity, temporary_program, temporary_triggers,  # noqa: E402
                       validate_program, validate_state)
from turn_cycle import begin_turn, enter_beginning_phase, run_awaken_step  # noqa: E402

UNIT = {"kind": "unit", "might_modifiers": [], "damage": 0, "exhausted": False}


def board():
    s = base_state()
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["players"]["p2"]["zones"]["base"].remove("u2")
    s["battlefields"]["bf1"]["objects"] += ["u1", "u2"]
    s["objects"]["g2"] = {**UNIT, "kind": "gear", "owner": "p2", "controller": "p2", "base_might": 0}
    s["objects"]["ub"] = {**UNIT, "owner": "p2", "controller": "p2", "base_might": 3}
    s["players"]["p2"]["zones"]["base"] += ["g2", "ub"]
    return settle_contested(s)


def grant(state, object_id, effect=None):
    effect = copy.deepcopy(effect or GRANT)
    target = {k: v for k, v in effect.pop("target").items() if k != "decision_ref"}
    target.update({"object_id": object_id, "bound_identity": object_identity(state, object_id) or f"{object_id}@0"})
    effect.update({"target": target, "source": "fading"})
    return apply_program(state, program("fading", effect))


def outcome(result):
    return [e.get("outcome") for e in result.get("trace") or []]


def main() -> int:
    global GRANT
    errors: list[str] = []
    lowered = CG.compile_clause("Give a unit at a battlefield or a gear [Temporary].", CG.load_grammar())
    want = [{"op": "grant_keyword", "effect_id": "kw", "keyword": "temporary", "duration": "permanent",
             "source": "$chain_item", "target": {"decision_ref": "t", "chosen_zone_class": "board",
                                                "any_of": [{"kind": "unit", "location": "battlefield"}, {"kind": "gear"}]}}]
    if lowered.get("program_effects") != want:
        print(f"FAILED: the grammar did not lower Fading Memories' sentence: {lowered}")
        return 1
    GRANT = want[0]
    start = board()
    if validate_state(start):
        print(f"FAILED: the board is invalid: {validate_state(start)}")
        return 1

    done = grant(start, "u2")
    after = done.get("next_state") or {}
    if not done.get("committed") or not has_keyword(after, "u2", "temporary"):
        errors.append(f"an enemy unit at a battlefield was not granted Temporary: {outcome(done)} {done.get('reason') or done.get('errors')}")
    else:
        triggers = temporary_triggers(after, "u2", "p2")
        if len(triggers) != 1:
            errors.append(f"the granted unit has no Temporary trigger for its controller: {triggers}")
        killed = apply_program(after, temporary_program(after, "u2", "p2"))
        if not killed.get("committed") or "u2" not in killed["next_state"]["players"]["p2"]["zones"]["trash"]:
            errors.append("the Temporary trigger's program did not kill the granted unit")
        later = copy.deepcopy(after)
        later["turn_id"] = "turn-next"
        if not has_keyword(later, "u2", "temporary"):
            errors.append("the granted Temporary ended with the turn; no duration was stated (801.3.a.3)")
        back = apply_program(after, program("bounce", {"op": "return_to_hand", "effect_id": "r", "object_id": "u2"}))
        if not back.get("committed") or has_keyword(back["next_state"], "u2", "temporary"):
            errors.append("the grant survived the object leaving the board (124)")

    gear = grant(start, "g2")
    if not gear.get("committed") or not has_keyword(gear["next_state"], "g2", "temporary") \
            or len(temporary_triggers(gear["next_state"], "g2", "p2")) != 1:
        errors.append(f"a gear was not granted Temporary: {outcome(gear)} {gear.get('reason') or gear.get('errors')}")
    in_base = grant(start, "ub")
    if not in_base.get("committed") or outcome(in_base) != ["ignored_illegal_target"] or has_keyword(in_base["next_state"], "ub", "temporary"):
        errors.append(f"a unit in a base is not 'a unit at a battlefield': {outcome(in_base)}")
    in_trash = grant(start, "c3")
    if in_trash.get("committed") and has_keyword(in_trash["next_state"], "c3", "temporary"):
        errors.append("a spell in the trash was granted Temporary")

    # a real turn: p1's own granted unit is scheduled with the Beginning Step's triggers (816.1.c)
    e = duel_board()
    e["players"]["p1"]["zones"]["base"].remove("u1")
    e["battlefields"]["bf1"]["objects"].append("u1")
    e["battlefields"]["bf1"]["controller"] = "p1"
    mine = apply_program(e, program("fading", {"op": "grant_keyword", "effect_id": "kw", "keyword": "temporary",
                                               "duration": "permanent", "source": "fading", "object_id": "u1"}))
    if not mine.get("committed"):
        errors.append(f"p1's unit could not be granted Temporary: {mine.get('reason') or mine.get('errors')}")
    else:
        began = begin_turn(setup_timing(), mine["next_state"])
        awake = run_awaken_step(handled(began["next_timing_state"]), began["next_effect_state"]) if began.get("committed") else {}
        entered = enter_beginning_phase(handled(awake["next_timing_state"]), awake["next_effect_state"]) if awake.get("committed") else {}
        scheduled = (entered.get("trace") or {}).get("scheduled_triggers") or []
        if "u1:temporary" not in scheduled:
            errors.append(f"p1's granted Temporary was not scheduled at the Beginning Step: {scheduled} "
                          f"{entered.get('reason') or awake.get('reason') or began.get('reason')}")

    for bad, why in ((dict(GRANT, target={"decision_ref": "t", "chosen_zone_class": "board", "any_of": [{"kind": "unit"}]}), "any_of with one alternative"),
                     (dict(GRANT, target={"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                          "any_of": [{"kind": "unit"}, {"kind": "gear"}]}), "any_of beside a kind"),
                     (dict(GRANT, target={"decision_ref": "t", "chosen_zone_class": "board",
                                          "any_of": [{"kind": "unit", "max_might": 3}, {"kind": "gear"}]}), "an alternative with another field"),
                     (dict(GRANT, keyword="tank"), "a permanent Tank")):
        if not validate_program(program("bad", bad)):
            errors.append(f"{why} validated")
    rune_state = board()
    rune_state["objects"]["r9"] = {**UNIT, "kind": "rune", "owner": "p1", "controller": "p1", "base_might": 0}
    rune_state["players"]["p1"]["zones"]["base"].append("r9")
    rune = apply_program(rune_state, program("fading", {"op": "grant_keyword", "effect_id": "kw", "keyword": "temporary",
                                                        "duration": "permanent", "source": "fading", "object_id": "r9"}))
    if rune.get("committed"):
        errors.append("a rune was granted Temporary (816.1.a: Permanents)")

    if errors:
        print("FAILED: granted Temporary" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'Give a unit at a battlefield or a gear [Temporary].' grants Temporary with no duration to one chosen unit "
          "at a battlefield or gear (816.1.a, 801.3.a.3): its controller's trigger exists and kills it, it outlives the turn, "
          "it ends with the object leaving the board, a base unit / trash spell / rune are refused, and a real Beginning "
          "Step schedules it.")
    return 0


GRANT: dict = {}

if __name__ == "__main__":
    raise SystemExit(main())
