#!/usr/bin/env python3
"""Regression gate (set 2 package A2, for Aphelios - Exalted: "When you attach an Equipment to me, choose one that hasn't
been chosen this turn - ..."): a triggered ability's mode is chosen as it is finalized (Core 403.2) - a mode_selection at
trigger_finalization by the ability's controller - among the options this object's ability has not chosen this turn
(not_chosen_this_turn, Udyr's ledger); only the chosen option's choices are made; the mode is recorded with them and in
the ledger; with every option chosen this turn the ability leaves the Chain (403.4).

  M1 asked     finalizing with no mode: mode_selection_required, both options offered
  M2 draw      the draw mode chosen: finalized, nothing else asked; it resolves - p1 drew one; the ledger has it
  M3 buff      the buff mode chosen: its target is asked at finalization; chosen, it resolves - u1 buffed
  M4 taken     after M2, a second trigger of the same object this turn: the draw mode is refused, the buff mode is not
  M5 none left with both chosen this turn: the ability leaves the Chain (no_legal_choices)
  M6 wrong     the mode chosen by p2, or at another stage, is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, hash_value, object_identity, validate_program  # noqa: E402
from play_transaction import modes_chosen_this_turn  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import pass_priority, schedule_triggered_items  # noqa: E402

PROGRAM = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
           "program_id": "ap-fx", "controller": "p1", "source_object": "ap",
           "modal": {"choose": 1, "timing": "trigger_finalization", "decision_ref": "mode", "not_chosen_this_turn": True,
                     "options": [{"option_id": "draw", "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]},
                                 {"option_id": "buff", "effects": [{"op": "buff", "effect_id": "bf", "target": {
                                     "decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                     "controller_relation": "friendly"}}]}]}}
REGISTRY = {"ap-fx": PROGRAM}


def board():
    s = base_state()
    s["objects"]["ap"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("ap")
    return s


def pending(state, n=1):
    descriptor = {"trigger_id": f"ap-attach-{n}", "controller": "p1", "source_object": "ap", "controller_order": 0,
                  "effect_program_id": "ap-fx", "optional_at_finalize": False, "trigger_kind": "triggered",
                  "batch_sequence": 0, "batch_id": f"attach:{n}", "source_identity": object_identity(state, "ap")}
    return schedule_triggered_items(fixture(), [descriptor])["next_state"]


def envelope(state, mode=None, target=None, by="p1", stage="trigger_finalization"):
    out = []
    if mode is not None:
        out.append({"decision_id": "mode", "stage": stage, "kind": "mode_selection", "controller": by, "value": mode})
    if target is not None:
        out.append({"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
                    "value": [target], "selection_identities": {target: object_identity(state, target)}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": out} if out else None


def resolve(fin, trigger_id):
    t, e = fin["next_timing_state"], fin["next_effect_state"]
    for actor in ("p1", "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    return resolve_with_program(t, trigger_id, e, PROGRAM)


def main() -> int:
    errors: list[str] = []
    if validate_program(PROGRAM):
        errors.append(f"V: {validate_program(PROGRAM)[:2]}")
    s = board()
    asked = finalize_trigger(pending(s), s, REGISTRY, None)
    if asked.get("committed") or asked.get("reason") != "mode_selection_required" or asked.get("mode_options") != ["draw", "buff"]:
        errors.append(f"M1 asked: {asked.get('reason')} {asked.get('mode_options')}")
    drew = finalize_trigger(pending(s), s, REGISTRY, envelope(s, "draw"))
    after = drew.get("next_effect_state") or {}
    if not drew.get("committed") or modes_chosen_this_turn(after, "ap", "p1") != ["draw"]:
        errors.append(f"M2 draw: {drew.get('reason')} {drew.get('message')}")
    else:
        done = resolve(drew, "ap-attach-1")
        hand = (done.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("hand", [])
        if not done.get("committed") or len(hand) != len(s["players"]["p1"]["zones"]["hand"]) + 1:
            errors.append(f"M2 draw: resolution {done.get('reason') or done.get('reason_code')}")
        again = finalize_trigger(pending(after, 2), after, REGISTRY, envelope(after, "draw"))
        if again.get("committed") or again.get("reason") != "mode_choice_illegal":
            errors.append(f"M4 taken: draw again {again.get('committed')} {again.get('reason')}")
        other = finalize_trigger(pending(after, 2), after, REGISTRY, envelope(after, "buff", target="u1"))
        if not other.get("committed"):
            errors.append(f"M4 taken: buff refused {other.get('reason')} {other.get('message')}")
        both = copy.deepcopy(after)
        both["objects"]["ap"]["modes_chosen"]["by"]["p1"] = ["buff", "draw"]
        left = finalize_trigger(pending(both, 3), both, REGISTRY, None)
        if not left.get("removed") or (left.get("transition") or {}).get("type") != "no_legal_choices":
            errors.append(f"M5 none left: {left.get('reason')} {left.get('transition')}")
    need = finalize_trigger(pending(s), s, REGISTRY, envelope(s, "buff"))
    if need.get("committed") or need.get("reason") != "target_selection_required":
        errors.append(f"M3 buff: target not asked {need.get('reason')}")
    buffed = finalize_trigger(pending(s), s, REGISTRY, envelope(s, "buff", target="u1"))
    if not buffed.get("committed"):
        errors.append(f"M3 buff: {buffed.get('reason')} {buffed.get('message')}")
    else:
        done = resolve(buffed, "ap-attach-1")
        if not done.get("committed") or not (done.get("next_effect_state") or {}).get("objects", {}).get("u1", {}).get("buffed"):
            errors.append(f"M3 buff: resolution {done.get('reason') or done.get('reason_code')}")
    for label, kw in (("by p2", {"by": "p2"}), ("at play", {"stage": "play_declaration"})):
        wrong = finalize_trigger(pending(s), s, REGISTRY, envelope(s, "draw", **kw))
        if wrong.get("committed"):
            errors.append(f"M6 wrong: the mode chosen {label} was accepted")
    if errors:
        print("modal-trigger checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("modal-trigger checks passed: a triggered ability's mode chosen as it is finalized, by its controller, among the "
          "modes not chosen this turn; only that mode's choices made; recorded in the ledger; none left - it leaves the Chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
