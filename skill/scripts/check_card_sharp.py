#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Card Sharp, "When you play me, you and each opponent may play a Gold gear token
exhausted. For each opponent who did, you play a Gold gear token exhausted."): play_token per player inside each_player,
each player's own optional (optional.by, Core 355.10.e, 355.12); then a play_token repeated once per opponent whose copy
was performed (repeat_per each_player_applied).

  S1 both     p1 and p2 each take one: p1 ends with 2 Gold tokens (its own and one more), p2 with 1; each exhausted, in
              its player's Base, with the Gold's printed ability
  S2 p2 no    p2 declines: p1 has 1, p2 none
  S3 p1 no    p1 declines, p2 takes: p1 has 1 (the one for p2), p2 has 1
  S4 asked    no decisions: the resolution asks p1 first (turn order from its controller); then p2 for its own
  S5 decider  p2's choice made by p1: refused
  G  grammar  the text lowers to the each_player and the repeated play; near misses do not
  V           repeat_per naming no earlier each_player, or on another op, does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, CORE_RULESET, FAQ_AS_OF, apply_program, hash_value, validate_program  # noqa: E402

TEXT = ("You and each opponent may play a Gold gear token exhausted. For each opponent who did, you play a Gold gear "
        "token exhausted.")
CONTEXT = {"turn": {"turn_player": "p1", "turn_order": ["p1", "p2"]}}


def lowered():
    return CG.compile_clause(TEXT, CG.load_grammar()).get("program_effects")


def program(effects):
    def bind(value):
        if isinstance(value, dict):
            return {k: bind(v) for k, v in value.items()}
        if isinstance(value, list):
            return [bind(v) for v in value]
        return "p1" if value == "$controller" else value
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "sharp", "controller": "p1", "source_object": "u1", "effects": bind(copy.deepcopy(effects))}


def run(s, effects, answers):
    decisions = [{"decision_id": f"gold@{p}", "stage": "resolution", "kind": "optional_choice", "controller": by,
                  "value": v} for p, (by, v) in answers.items()]
    return apply_program(s, program(effects), decisions={"schema_version": "engine-decisions.v1",
                                                         "input_hash": hash_value(s), "decisions": decisions},
                         context=CONTEXT)


def golds(state, player):
    return sorted(o for o in state["players"][player]["zones"]["base"]
                  if state["objects"][o].get("token_id") == "gold" and state["objects"][o].get("exhausted")
                  and state["objects"][o].get("activated_abilities"))


def main() -> int:
    errors: list[str] = []
    effects = lowered()
    if [e.get("op") for e in effects or []] != ["each_player", "play_token"] \
            or effects[1].get("repeat_per", {}).get("players") != "opponents":
        errors.append(f"G grammar: {effects}")
        print("\n".join(errors))
        return 1
    for near in ("Each opponent may play a Gold gear token exhausted. For each opponent who did, you play a Gold gear "
                 "token exhausted.", "You and each opponent may play a Gold gear token exhausted."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == \
                "you_and_each_opponent_may_play_a_gold_gear_token_exhausted_for_each_opponent_who_did_you_play_one":
            errors.append(f"G grammar: the near miss {near!r} parsed")
    if validate_program(program(effects)):
        errors.append(f"V: {validate_program(program(effects))[:2]}")
    s = base_state()
    for label, answers, want in (("S1 both", {"p1": ("p1", True), "p2": ("p2", True)}, (2, 1)),
                                 ("S2 p2 no", {"p1": ("p1", True), "p2": ("p2", False)}, (1, 0)),
                                 ("S3 p1 no", {"p1": ("p1", False), "p2": ("p2", True)}, (1, 1))):
        done = run(s, effects, answers)
        after = done.get("next_state") or {}
        got = (len(golds(after, "p1")), len(golds(after, "p2"))) if done.get("committed") else None
        if got != want:
            errors.append(f"{label}: {got} {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    asked = run(s, effects, {})
    if asked.get("committed") or asked.get("decision_ids") != ["gold@p1"] or asked.get("decision_controller") != "p1":
        errors.append(f"S4 asked: {asked.get('reason_code')} {asked.get('decision_ids')} {asked.get('decision_controller')}")
    second = run(s, effects, {"p1": ("p1", True)})
    if second.get("committed") or second.get("decision_ids") != ["gold@p2"] or second.get("decision_controller") != "p2":
        errors.append(f"S4 asked p2: {second.get('reason_code')} {second.get('decision_ids')} {second.get('decision_controller')}")
    wrong = run(s, effects, {"p1": ("p1", True), "p2": ("p1", True)})
    if wrong.get("committed"):
        errors.append("S5 decider: p2's choice made by p1 was accepted")
    bad = copy.deepcopy(effects)
    bad[1]["repeat_per"]["effect_id"] = "nothing"
    if not validate_program(program(bad)):
        errors.append("V: repeat_per naming no each_player validated")
    bad = copy.deepcopy(effects)
    bad.append({"op": "draw", "effect_id": "dr", "player": "p1", "count": 1,
                "repeat_per": {"kind": "each_player_applied", "effect_id": "each", "players": "opponents"}})
    if not validate_program(program(bad)):
        errors.append("V: repeat_per on a draw validated")
    if errors:
        print("card-sharp checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("card-sharp checks passed: each player decides their own Gold, its controller first; one more Gold for its "
          "controller per opponent who took one; another player's choice refused; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
