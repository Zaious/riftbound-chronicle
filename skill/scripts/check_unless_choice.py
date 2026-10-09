#!/usr/bin/env python3
"""A targeted instruction its target's controller may replace (package 10, Shakedown; GPT 2026-10-08 ruling 7).

The card deals 6 to the unit chosen before it, unless that unit's controller has the caster draw 2 instead. The choice is
the TARGET's controller's, made as the instruction resolves (Core 355.10.e); chosen "instead", the caster draws 2 (a short
deck Draws and Burns Out as usual) and no damage is dealt; the target illegal, the instruction is ignored whole and nobody
chooses.

  U1 asked         the resolution stops for the target's controller (p2): option_selection_required
  U2 instruction   p2 lets it happen: u2 takes 6, nobody draws
  U3 instead       p2 chooses instead: p1 draws 2, u2 takes nothing (outcome chose_instead)
  U4 wrong chooser p1 answers the option: refused
  U5 target gone   u2 left the board before: the instruction is ignored, nobody is asked, nobody draws
  U6 short deck    p1 has one card left and p2 chooses instead: the draw stops where a plain Draw 2 does (Burn Out)
  V  validation    {decision_ref, instead} only, instead one draw, on a targeted deal_damage only
  G  grammar       the card's whole body lowered to this one instruction; its near misses are not

    python skill/scripts/check_unless_choice.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board():
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p2", "objects": ["u2"]}
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["objects"]["u2"]["base_might"] = 8
    return state


def deal(state):
    return {"op": "deal_damage", "effect_id": "dmg", "amount": 6,
            "target": {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit",
                       "bound_identity": object_identity(state, "u2")},
            "unless": {"decision_ref": "un", "instead": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 2}]}}


def program(*effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "shakedown", "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects]}


def answer(state, value, who="p2"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "un", "kind": "option_selection", "stage": "resolution", "controller": who, "value": value}]}


def hand(result):
    return len(result["next_state"]["players"]["p1"]["zones"]["hand"])


def main() -> int:
    s = board()
    asked = apply_program(s, program(deal(s)))
    if asked.get("reason_code") != "option_selection_required" or asked.get("decision_controller") != "p2":
        fail("U1 asked", f"{asked.get('reason_code')} {asked.get('decision_controller')}")
    let = apply_program(s, program(deal(s)), decisions=answer(s, "instruction"))
    if not let.get("committed") or let["next_state"]["objects"]["u2"]["damage"] != 6 or hand(let) != 0:
        fail("U2 instruction", f"{let.get('reason') or let.get('errors')}")
    instead = apply_program(s, program(deal(s)), decisions=answer(s, "instead"))
    if not instead.get("committed") or instead["next_state"]["objects"]["u2"]["damage"] != 0 or hand(instead) != 2 \
            or instead["trace"][0].get("outcome") != "chose_instead":
        fail("U3 instead", f"{instead.get('reason') or instead.get('errors')} {instead.get('trace')}")
    mine = apply_program(s, program(deal(s)), decisions=answer(s, "instead", "p1"))
    if mine.get("committed"):
        fail("U4 wrong chooser", "the caster chose for the target's controller")
    gone = board()
    target = deal(gone)
    gone["battlefields"]["bf1"]["objects"].remove("u2")
    gone["players"]["p2"]["zones"]["trash"].append("u2")
    ignored = apply_program(gone, program(target))
    if not ignored.get("committed") or ignored.get("option_selection_required") or hand(ignored) != 0 \
            or ignored["trace"][0].get("outcome") not in ("ignored_illegal_target", "skipped_illegal_target"):
        fail("U5 target gone", f"{ignored.get('reason_code')} {ignored.get('trace')}")
    short = board()
    short["players"]["p1"]["zones"]["main_deck"] = ["c1"]
    short["players"]["p1"]["zones"]["trash"].append("c2")
    burned = apply_program(short, program(deal(short)), decisions=answer(short, "instead"))
    plain = apply_program(short, program({"op": "draw", "effect_id": "dr", "player": "p1", "count": 2}))
    # the "instead" Draw stops exactly where a plain Draw 2 does on this deck (a Burn Out asks for its randomization)
    if burned.get("committed") != plain.get("committed") or burned.get("reason_code") != plain.get("reason_code") \
            or burned.get("reason") != plain.get("reason") or plain.get("committed"):
        fail("U6 short deck", f"instead: {burned.get('reason_code')} {burned.get('reason')}; plain draw: "
                              f"{plain.get('reason_code')} {plain.get('reason')}")
    for label, change in (("an extra key", lambda e: e["unless"].update({"by": "p2"})),
                          ("two instead instructions", lambda e: e["unless"]["instead"].append(dict(e["unless"]["instead"][0], effect_id="dr2"))),
                          ("a kill instead", lambda e: e["unless"].update({"instead": [{"op": "kill", "effect_id": "k", "player": "p1", "count": 1}]})),
                          ("on an untargeted deal", lambda e: (e.pop("target"), e.update({"object_id": "u2"})))):
        wrong = deal(s)
        change(wrong)
        if not validate_program(program(wrong)):
            fail("V validation", f"{label} was accepted")
    if validate_program(program(deal(s))):
        fail("V validation", f"the card's own instruction is invalid: {validate_program(program(deal(s)))}")
    # G: the card's whole body, lowered by the clause grammar, is this instruction (target chosen at play, enemy)
    import clause_grammar as cg
    grammar = cg.load_grammar()
    body = cg.compile_clause("Choose an enemy unit. Deal 6 to it unless its controller has you draw 2.", grammar)
    effects = body.get("program_effects") or []
    if body.get("unsupported") or len(effects) != 1 or effects[0].get("amount") != 6 \
            or (effects[0].get("target") or {}).get("controller_relation") != "enemy" \
            or effects[0].get("unless", {}).get("instead", [{}])[0].get("count") != 2:
        fail("G grammar", f"{body.get('production_id')} {effects}")
    for near in ("Choose an enemy unit. Deal 6 to it unless you draw 2.",
                 "Choose a friendly unit. Deal 6 to it unless its controller has you draw 2.",
                 "Deal 6 to it unless its controller has you draw 2."):
        if cg.compile_clause(near, grammar).get("production_id") == body.get("production_id"):
            fail("G grammar", f"{near!r} lowered to the row")
    if errors:
        print("FAILED: unless-choice checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'unless its controller has you draw 2' - the target's controller chooses as it resolves; instead, the "
          "caster draws and nothing is dealt; an illegal target asks nobody (U1-U6, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
