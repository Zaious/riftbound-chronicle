#!/usr/bin/env python3
"""
Regression gate: a card's printed tags, and a play trigger whose condition names one (2026-09-27).

Tags are a characteristic (Core 133.8, 143.1) with no rules meaning of their own, read by effects
that name them (133.8.a). The object carries them as `tags`, as printed ("Poro"); every reader goes
through effect_ir.object_tags. condition.v1's controls_units takes an optional `tag`. "When you play
me, if you control a Poro, buff me and draw 1." (Poro Herder) lowers to a play trigger whose
condition is controls_units {count 1, tag Poro}: the conditional statement right after the trigger
condition is part of it (Core 383.2.a.1), read as the play completes (419.4.a).

Must hold:
  - validation: tags a list of distinct non-empty strings; a condition tag a non-empty string; the
    trigger condition only on a play trigger, as {kind, count, tag};
  - controls_units with a tag counts only Units whose printed tags hold it, on the asking side;
  - the grammar lowers the sentence to exactly that descriptor, and 'if you control a unit' stays
    unparsed (the tag table is closed);
  - through the real play transaction and entry: a friendly Poro on the board - scheduled; a Poro
    of the opponent's - not; a friendly non-Poro - not; nothing else - not; the same card without
    the condition - scheduled;
  - mutations caught: an engine that ignores the tag; one that ignores the trigger condition.
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
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "When you play me, if you control a Poro, buff me and draw 1."
CONDITION = {"kind": "controls_units", "count": 1, "tag": "Poro"}


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(neighbour=None, *, condition=True):
    """p1's c1 (the card, tags Freljord) in hand, its play trigger conditioned or not; `neighbour`:
    (owner, tags) of one more Unit in its owner's Base."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    trigger = {"trigger_id": "c1-on-play", "controller": "p1", "source_object": "c1", "controller_order": 0,
               "effect_program_id": "c1-on-play-effects", "optional_at_finalize": False,
               **({"condition": dict(CONDITION)} if condition else {})}
    state["objects"]["c1"].update({"kind": "unit", "base_might": 3, "tags": ["Freljord"], "play_triggers": [trigger]})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    if neighbour:
        owner, tags = neighbour
        state["objects"]["n1"] = unit(owner, tags=list(tags))
        state["players"][owner]["zones"]["base"].append("n1")
    return state


def scheduled(state):
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
    return [i["id"] for i in done["next_timing_state"]["chain"]["items"]]


CASES = {
    "a_friendly_poro": ((("p1", ["Poro"]),), True, ["c1-on-play"]),
    "a_friendly_poro_among_other_tags": ((("p1", ["Freljord", "Poro"]),), True, ["c1-on-play"]),
    "the_opponents_poro": ((("p2", ["Poro"]),), True, []),
    "a_friendly_unit_that_is_not_a_poro": ((("p1", ["Freljord"]),), True, []),
    "no_other_unit": ((), True, []),
    "no_condition": ((), False, ["c1-on-play"]),
}


def run_cases():
    return {label: scheduled(board(*(neighbour or (None,)), condition=conditioned))
            for label, (neighbour, conditioned, _want) in CASES.items()}


def main() -> int:
    errors: list[str] = []
    for bad in ([], ["Poro", "Poro"], "Poro", [""], [3]):
        state = board()
        state["objects"]["c1"]["tags"] = bad
        if bad != [] and not IR.validate_state(state):
            errors.append(f"invalid tags validated: {bad!r}")
    if IR.validate_state(board(("p1", ["Poro"]))):
        errors.append(f"a board with tags is invalid: {IR.validate_state(board(('p1', ['Poro'])))[:2]}")
    if not IR.validate_condition({"kind": "controls_units", "count": 1, "tag": ""}):
        errors.append("an empty condition tag validated")
    for label, broken in (("on a move trigger", "move_triggers"), ("with an extra key", "play_triggers")):
        state = board()
        trigger = state["objects"]["c1"].pop("play_triggers")[0]
        if label == "with an extra key":
            trigger["condition"] = {**CONDITION, "location": "board"}
        state["objects"]["c1"][broken] = [trigger]
        if not IR.validate_state(state):
            errors.append(f"a tag condition {label} validated")
    counted = board(("p1", ["Poro"]))
    counted["objects"]["n2"] = unit("p1", tags=["Poro"])
    counted["players"]["p1"]["zones"]["base"].append("n2")
    for count, want in ((1, True), (2, True), (3, False)):
        if IR.evaluate_condition(counted, {"kind": "controls_units", "count": count, "tag": "Poro"}, controller="p1") != want:
            errors.append(f"controls_units tag Poro count {count} is not {want} with two friendly Poros")
    if IR.evaluate_condition(counted, {"kind": "controls_units", "count": 1, "tag": "Poro"}, controller="p2"):
        errors.append("the opponent was said to control a Poro")
    if IR.object_tags(counted, "c1") != ["Freljord"] or IR.object_tags(counted, "u1") != []:
        errors.append("object_tags did not read the printed tags")
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    descriptor = ((lowered.get("passive") or {}).get("object_fields") or {}).get("play_triggers") or [{}]
    if lowered.get("unsupported") or descriptor[0].get("condition") != CONDITION \
            or [e["op"] for e in lowered.get("program_effects") or []] != ["buff", "draw"]:
        errors.append(f"the sentence lowered to {descriptor} {lowered.get('program_effects')}")
    if not CG.compile_clause("When you play me, if you control a unit, draw 1.", CG.load_grammar()).get("unsupported"):
        errors.append("'if you control a unit' became a tag")
    got = run_cases()
    for label, (_n, _c, want) in CASES.items():
        if got[label] != want:
            errors.append(f"{label}: scheduled {got[label]}, not {want} (Core 383.2.a.1)")
    real_tags, real_eval = IR.object_tags, IR.evaluate_condition
    for label, attribute, replacement in (
            ("ignoring the tag", "object_tags", lambda state, object_id: ["Poro"]),
            ("ignoring the trigger condition", "evaluate_condition", lambda *a, **k: True)):
        setattr(IR, attribute, replacement)
        try:
            moved = [k for k, v in run_cases().items() if v != CASES[k][2]]
        finally:
            IR.object_tags, IR.evaluate_condition = real_tags, real_eval
        if not moved:
            errors.append(f"mutation not caught: an engine {label}")
    if errors:
        print("FAILED: object tags checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: printed tags are validated and read through object_tags; controls_units counts a tag on the asking "
          "side; 'When you play me, if you control a Poro, ...' schedules exactly when a friendly Poro is on the board "
          "as the play completes (383.2.a.1); two engine mutations are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
