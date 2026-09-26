#!/usr/bin/env python3
"""
Regression gate: a card's own conditional entry (2026-09-27).

"If an opponent's score is within 3 points of the Victory Score, I enter ready." and "If an
opponent controls a battlefield, I enter ready." are conditional passives (Core 364.3.a) and
entry replacements (369.3) with a condition, read as the
unit enters; without it a Unit enters exhausted (143.4, 359.2.c). The object carries them as
`entry_replacements` entries with a `condition` (score_within_of_victory, or the new leaf
controls_a_battlefield); resolution_bridge.entry_state_for reads it.

Must hold, through the real play transaction and entry:
  - score: the opponent at 5 of 8 (within 3) - ready; at 6 - ready; at 4 - exhausted; only the
    controller within 3 - exhausted; a Mode of Play that does not state its Victory Score - the
    entry is refused by name, not guessed;
  - battlefield: the opponent controls bf1 - ready; the controller controls it - exhausted; no one
    controls one - exhausted; the controller one and the opponent another - ready;
  - the unconditional "I enter ready." is unchanged;
  - invalid: a condition kind the entry does not read, a malformed condition;
  - mutation caught: an entry that ignores the condition always enters ready.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SCORE = "If an opponent's score is within 3 points of the Victory Score, I enter ready."
BATTLEFIELD = "If an opponent controls a battlefield, I enter ready."


def fields_of(text):
    return (CG.compile_clause(text, CG.load_grammar()).get("passive") or {}).get("object_fields") or {}


def board(fields, *, mode=True, p1_points=0, p2_points=0, holders=()):
    """p1's c1, a Unit with `fields`, in hand; bf1/bf2 controlled by `holders` (each with one of
    that player's Units there)."""
    state = base_state()
    if mode:
        state["mode"] = {"victory_score": 8}
    state["players"]["p1"]["points"] = p1_points
    state["players"]["p2"]["points"] = p2_points
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, **copy.deepcopy(fields)})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    for index, holder in enumerate(holders):
        bf = f"bf{index + 1}"
        unit = f"h{index}"
        state["objects"][unit] = {"owner": holder, "controller": holder, "kind": "unit", "base_might": 1, "might_modifiers": [],
                                  "damage": 0, "exhausted": False}
        state["battlefields"][bf] = {"controller": holder, "objects": [unit]}
    return state


def enter(state):
    """Really play c1 to p1's Base and resolve its entry: 'ready', 'exhausted', or the refusal."""
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": "p1", "card": "c1",
                "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    played = PT.play_card(fixture(), state, declared)
    if not played.get("committed"):
        return f"play refused: {played.get('reason_code')}"
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    done = resolve_with_program(timing, "unit-1", played["next_effect_state"], None)
    if not done.get("committed"):
        return "refused: " + str(done.get("reason") or done.get("reason_code"))
    return "exhausted" if done["next_effect_state"]["objects"]["c1"]["exhausted"] else "ready"


def main() -> int:
    errors: list[str] = []
    score, battlefield = fields_of(SCORE), fields_of(BATTLEFIELD)
    if score != {"entry_replacements": [{"replacement_id": "own-text", "mode": "entry_state", "value": "ready",
                                          "condition": {"kind": "score_within_of_victory", "count": 3}}]}:
        errors.append(f"the score sentence lowered to {score}")
    if battlefield != {"entry_replacements": [{"replacement_id": "own-text", "mode": "entry_state", "value": "ready",
                                                "condition": {"kind": "controls_a_battlefield", "controller_relation": "enemy"}}]}:
        errors.append(f"the battlefield sentence lowered to {battlefield}")
    cases = {
        "opponent_within_3": (board(score, p2_points=5), "ready"),
        "opponent_within_2": (board(score, p2_points=6), "ready"),
        "opponent_4_away": (board(score, p2_points=4), "exhausted"),
        "only_the_controller_within_3": (board(score, p1_points=6, p2_points=2), "exhausted"),
        "opponent_controls_bf1": (board(battlefield, holders=("p2",)), "ready"),
        "the_controller_controls_bf1": (board(battlefield, holders=("p1",)), "exhausted"),
        "no_one_controls_a_battlefield": (board(battlefield), "exhausted"),
        "each_controls_one": (board(battlefield, holders=("p1", "p2")), "ready"),
        "unconditional": (board({"entry_replacements": [{"mode": "entry_state", "value": "ready"}]}), "ready"),
    }
    for label, (state, want) in cases.items():
        if found := validate_state(state):
            errors.append(f"the {label} board is invalid: {found}")
            continue
        if (got := enter(state)) != want:
            errors.append(f"{label}: entered {got}, not {want} (Core 364.3.a, 369.3, 143.4)")
    unstated = enter(board(score, mode=False, p2_points=5))
    if not unstated.startswith("refused") or "Victory Score" not in unstated:
        errors.append(f"a Mode of Play without its Victory Score was not refused by name: {unstated}")
    for bad in ({"kind": "runes_at_least", "count": 3}, {"kind": "controls_a_battlefield"},
                {"kind": "controls_a_battlefield", "controller_relation": "neutral"}):
        broken = board({"entry_replacements": [{"mode": "entry_state", "value": "ready", "condition": bad}]})
        if not validate_state(broken):
            errors.append(f"an invalid entry condition validated: {bad}")
    # mutation: an entry that ignores its condition - the case table must see it
    saved = IR.evaluate_condition
    try:
        IR.evaluate_condition = lambda *a, **k: True
        wrong = [label for label, (state, want) in cases.items() if enter(copy.deepcopy(state)) != want]
    finally:
        IR.evaluate_condition = saved
    if sorted(wrong) != ["no_one_controls_a_battlefield", "only_the_controller_within_3", "opponent_4_away",
                         "the_controller_controls_bf1"]:
        errors.append(f"mutation not caught as expected: an entry ignoring its condition was seen on {wrong}")
    if errors:
        print("FAILED: conditional entry checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'If an opponent's score is within 3 of the Victory Score / If an opponent controls a battlefield, I enter "
          "ready.' enter ready exactly where the condition holds as the unit enters (364.3.a, 369.3) and exhausted "
          "otherwise (143.4); an unstated Victory Score is refused by name; invalid conditions are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
