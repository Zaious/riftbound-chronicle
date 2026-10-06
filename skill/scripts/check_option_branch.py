#!/usr/bin/env python3
"""
Gate (package 9, Qiyana - Victorious): "When I conquer, draw 1 or channel 1 rune exhausted."

GPT 2026-10-06 ruling 6: not Core 355.3's bulleted modes - the controller chooses one of the two as the ability
resolves; with an empty Rune Deck the channel may still be chosen and channels zero (Core 430.3), never turned into the
draw for them. The program: choose_option {by controller, options [draw, channel], record} and two instructions each
carrying only_if_chose {record, option} - the one chosen runs, the other is skipped (skipped_option_not_chosen).

Must hold:
  O1  "draw" chosen: p1 draws 1; no rune channeled; the channel instruction skipped
  O2  "channel" chosen: one rune from p1's Rune Deck to p1's Base, exhausted; no card drawn; the draw skipped
  O3  "channel" chosen with an empty Rune Deck: nothing channeled, nothing drawn - the choice is not changed
  O4  no choice handed over: the resolution stops and asks p1 for it (option_selection_required)
  O5  an option not offered, or chosen by another player, is refused
  S   shapes: only_if_chose naming no earlier choose_option, naming an option it does not offer, or malformed - refused
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, validate_program  # noqa: E402

errors: list[str] = []
EFFECTS = [{"op": "choose_option", "effect_id": "pick", "by": "controller", "options": ["draw", "channel"],
            "record": "qiyana", "decision_ref": "qiyana-choice"},
           {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1, "only_if_chose": {"record": "qiyana", "option": "draw"}},
           {"op": "channel_rune", "effect_id": "ch", "player": "p1", "count": 1, "entry_state": "exhausted",
            "only_if_chose": {"record": "qiyana", "option": "channel"}}]


def program(effects=None):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "qiyana", "controller": "p1", "effects": copy.deepcopy(effects or EFFECTS)}


def chose(state, option, controller="p1"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "qiyana-choice", "stage": "resolution", "kind": "option_selection", "controller": controller,
         "value": option}]}


def fail(label, why):
    errors.append(f"{label}: {why}")


def zones(state):
    p1 = state["players"]["p1"]["zones"]
    return {"hand": len(p1["hand"]), "deck": len(p1["main_deck"]), "rune_deck": len(p1["rune_deck"]),
            "base_runes": sorted(o for o in p1["base"] if state["objects"][o].get("kind") == "rune")}


def main() -> int:
    if validate_program(program()):
        fail("program", validate_program(program()))
    s = base_state()
    before = zones(s)
    # O1
    got = apply_program(s, program(), decisions=chose(s, "draw"))
    after = zones(got["next_state"]) if got.get("committed") else None
    if not got.get("committed") or after["hand"] != before["hand"] + 1 or after["base_runes"] != before["base_runes"] \
            or [e.get("outcome") for e in got["trace"]] != ["applied", "applied", "skipped_option_not_chosen"]:
        fail("O1", f"draw chosen: {got.get('reason')} {after} {[e.get('outcome') for e in got.get('trace', [])]}")
    # O2
    got = apply_program(s, program(), decisions=chose(s, "channel"))
    after = zones(got["next_state"]) if got.get("committed") else None
    new_runes = sorted(set(after["base_runes"]) - set(before["base_runes"])) if after else []
    if not got.get("committed") or after["hand"] != before["hand"] or len(new_runes) != 1 \
            or not got["next_state"]["objects"][new_runes[0]].get("exhausted") \
            or [e.get("outcome") for e in got["trace"]][1] != "skipped_option_not_chosen":
        fail("O2", f"channel chosen: {got.get('reason')} {after} {[e.get('outcome') for e in got.get('trace', [])]}")
    # O3
    empty = base_state()
    for rune in list(empty["players"]["p1"]["zones"]["rune_deck"]):
        empty["players"]["p1"]["zones"]["rune_deck"].remove(rune)
        del empty["objects"][rune]
    got = apply_program(empty, program(), decisions=chose(empty, "channel"))
    if not got.get("committed") or zones(got["next_state"])["hand"] != zones(empty)["hand"] \
            or zones(got["next_state"])["base_runes"] != zones(empty)["base_runes"]:
        fail("O3", f"channel chosen with no runes did not channel zero and draw nothing: {got.get('reason')}")
    # O4
    asked = apply_program(s, program())
    if asked.get("committed") or not asked.get("option_selection_required") or asked.get("decision_controller") != "p1":
        fail("O4", f"no choice handed over: {asked.get('reason_code')}")
    # O5
    for label, decisions in (("an option not offered", chose(s, "both")), ("chosen by p2", chose(s, "draw", "p2"))):
        if apply_program(s, program(), decisions=decisions).get("committed"):
            fail("O5", f"{label} was accepted")
    # S
    for label, change in (("no earlier choose_option", lambda e: e.pop(0)),
                          ("an option not offered", lambda e: e[1]["only_if_chose"].update({"option": "both"})),
                          ("malformed", lambda e: e[2].update({"only_if_chose": {"record": "qiyana"}}))):
        bad = copy.deepcopy(EFFECTS)
        change(bad)
        if not validate_program(program(bad)):
            fail("S", f"only_if_chose with {label} validated")
    if errors:
        print("FAILED: option branch checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: Qiyana - Victorious - the controller chooses draw or channel as it resolves and only that branch runs (the "
          "other skipped); channel with an empty Rune Deck channels zero and draws nothing; no choice stops and asks; an "
          "option not offered or another player's choice refused; three shapes refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
