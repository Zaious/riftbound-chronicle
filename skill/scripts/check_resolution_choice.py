#!/usr/bin/env python3
"""A triggered ability's board choice made AS IT RESOLVES is not a re-chosen target
(package 5, 2026-09-27).

Core 355.10.f: an object identified in an instruction a player "must" complete is not a
target - "You must recycle one of your runes" is chosen as the ability resolves. The
resolution bridge refused every resolution-stage target_selection on a finalized trigger
that was not one of its finalized targets (target_changed_after_finalization), so such a
choice could never be made there. Held here, on a play trigger whose program is
[recycle one of p1's runes on the board (choice, decision_ref rune-pick)]:

  - finalized with no targets; resolved with a resolution-stage selection of p1's rune ra
    for rune-pick: committed, ra at the bottom of p1's Rune Deck, rb still in the Base;
  - with one rune there is nothing to choose: it is recycled with no decision;
  - still refused: the same selection supplied at the trigger_finalization stage, a
    selection naming p2's rune (not a candidate), and - on a program with a TARGET - a
    fresh selection for the target's decision_ref (target_changed_after_finalization,
    unchanged: check_trigger_finalization.py).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_trigger_finalization import PROGRAM_ID, RULESET, TRIGGER, board, choose, enter, program, to_resolution  # noqa: E402
from effect_ir import hash_value, object_identity  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program  # noqa: E402

RUNE_PROGRAM = {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": PROGRAM_ID,
                "controller": "p1", "source_object": "c1",
                "effects": [{"op": "recycle", "effect_id": "rc", "player": "p1", "decision_ref": "rune-pick",
                             "order_ref": "rune-order",
                             "choice": {"selection_kind": "single", "from": "board", "by": "controller",
                                        "criteria": {"kind": "rune", "controller_relation": "friendly"}}}]}


def rune_board(mine: tuple[str, ...]) -> dict:
    state = board(with_hash=False)
    state["objects"]["c1"]["play_triggers"][0]["effect_program_hash"] = program_hash(RUNE_PROGRAM)
    for rune, owner, exhausted in (("ra", "p1", False), ("rb", "p1", True), ("rc", "p2", False)):
        if owner == "p1" and rune not in mine:
            continue
        state["objects"][rune] = {"owner": owner, "controller": owner, "kind": "rune", "domain": "calm", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": exhausted}
        state["players"][owner]["zones"]["base"].append(rune)
    return state


def pick(state: dict, rune: str, stage: str = "resolution") -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": "rune-pick", "stage": stage, "kind": "target_selection", "controller": "p1",
                           "value": [rune], "selection_identities": {rune: object_identity(state, rune) or f"{rune}@0"}}]}


def ready_to_resolve(mine: tuple[str, ...]):
    registry = {PROGRAM_ID: RUNE_PROGRAM}
    timing, state = enter(rune_board(mine))
    finalized = finalize_trigger(timing, state, registry, None)
    if not finalized.get("committed"):
        return None, None, None, f"finalization refused: {finalized.get('stage')} {finalized.get('reason')}"
    ready = to_resolution(finalized["next_timing_state"])
    dispatched, refusal = dispatch_program(registry, ready["chain"]["items"][0])
    if refusal is not None:
        return None, None, None, f"dispatch refused: {refusal}"
    return ready, state, dispatched, None


def main() -> int:
    errors: list[str] = []
    ready, state, dispatched, why = ready_to_resolve(("ra", "rb"))
    if why:
        errors.append(why)
    else:
        done = resolve_with_program(ready, TRIGGER, state, dispatched, engine_decisions=pick(state, "ra"))
        zones = (done.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
        if not done.get("committed") or zones.get("rune_deck", [])[-1:] != ["ra"] or "rb" not in zones.get("base", []):
            errors.append(f"a resolution-stage rune choice was not honoured: {done.get('stage')} {done.get('reason')} {zones}")
        early = resolve_with_program(ready, TRIGGER, state, dispatched, engine_decisions=pick(state, "ra", "trigger_finalization"))
        if early.get("committed"):
            errors.append("the rune choice supplied at the finalization stage was honoured at resolution")
        theirs = resolve_with_program(ready, TRIGGER, state, dispatched, engine_decisions=pick(state, "rc"))
        if theirs.get("committed"):
            errors.append("p2's rune was recycled as 'one of your runes'")
    ready, state, dispatched, why = ready_to_resolve(("ra",))
    if why:
        errors.append(why)
    else:
        one = resolve_with_program(ready, TRIGGER, state, dispatched)
        zones = (one.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("zones", {})
        if not one.get("committed") or zones.get("rune_deck", [])[-1:] != ["ra"]:
            errors.append(f"one rune was not recycled without a decision: {one.get('reason')} {zones}")

    # a TARGET is still never re-chosen at resolution
    registry = {PROGRAM_ID: program()}
    timing, target_state = enter(board())
    finalized = finalize_trigger(timing, target_state, registry, choose(target_state, "u2"))
    ready = to_resolution(finalized["next_timing_state"])
    dispatched, _ = dispatch_program(registry, ready["chain"]["items"][0])
    other = resolve_with_program(ready, TRIGGER, target_state, dispatched,
                                 engine_decisions=choose(target_state, "u9", stage="resolution"))
    if other.get("committed") or other.get("reason") != "target_changed_after_finalization":
        errors.append(f"a target re-chosen at resolution was not refused: {other.get('reason')}")

    if errors:
        print("FAILED: resolution-stage choice" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a triggered ability's own board choice is made as it resolves (Core 355.10.f) - p1's chosen rune is "
          "recycled to its Rune Deck, one rune needs no decision; the same choice at the finalization stage, p2's rune, "
          "and a target re-chosen at resolution are refused.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
