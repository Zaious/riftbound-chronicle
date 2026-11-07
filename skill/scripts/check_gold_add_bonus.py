#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Renata Glasc - Chem-Baroness, "When you or an ally hold, you may exhaust me to play
a Gold gear token exhausted. While your score is within 3 points of the Victory Score, your Gold [ADD] an additional [1]."):

  G1 grammar       the static lowers to gold_add_bonus {energy 1, condition score_within_of_victory 3 who you}; the hold
                   wrapper to a hold_triggers descriptor of scope controller_or_ally; their near misses do not parse
  B1 within        p1 at 5 of 8 points, Renata on p1's board: a Gold token's [Add] [A] adds its Power and 1 Energy more
                   (the event names the bonus and its source)
  B2 not within    p1 at 4 of 8: the Add adds only its Power
  B3 their Gold    p2's Gold token, p1's Renata: no bonus
  B4 off the board Renata in p1's trash: no bonus
  B5 not Gold      another token's Add (a Mech token's): no bonus
  B6 two           two Renatas on p1's board: 2 Energy more
  H1 hold          p1 holds bf1, Renata in p1's Base (not at bf1): the hold trigger is scheduled for p1 (scope controller,
                   Core 383.4.d.2.b); p2's Renata on p2's board is not
  H2 teams         the same in a state with teams: refused by name (ally_scope_unsupported) - an ally's hold would trigger
                   it, and teams are not modelled
  V  validation    a gold_add_bonus of 0 Energy, or with an unknown condition, does not validate; score_within_of_victory
                   names who it reads (opponent | you)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battlefield_control as BC  # noqa: E402
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

STATIC = "While your score is within 3 points of the Victory Score, your Gold [ADD] an additional :rb_energy_1:."
HOLD = "When you or an ally hold, draw 1."


def lowered(text):
    got = CG.compile_clause(text, CG.load_grammar())
    return (got.get("passive") or {}).get("object_fields") or {}, got.get("production_id")


def board(points=5, *, renatas=(("rn", "p1", "base"),), gold_owner="p1", token_id="gold"):
    s = base_state()
    s["mode"] = {"victory_score": 8}
    s["players"]["p1"]["points"] = points
    fields, _pid = lowered(STATIC)
    for oid, owner, zone in renatas:
        s["objects"][oid] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [],
                             "damage": 0, "exhausted": False, **copy.deepcopy(fields)}
        s["players"][owner]["zones"][zone].append(oid)
    s["objects"]["tok"] = {"owner": gold_owner, "controller": gold_owner, "kind": "gear", "base_might": 0,
                           "might_modifiers": [], "damage": 0, "exhausted": False, "is_token": True, "token_id": token_id}
    s["players"][gold_owner]["zones"]["base"].append("tok")
    for p in ("p1", "p2"):
        s["players"][p]["resources"] = {"energy": 0, "power": {}}
    return s


def add(state):
    owner = state["objects"]["tok"]["controller"]
    program = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
               "program_id": "tok#add", "controller": owner, "source_object": "tok",
               "effects": [{"op": "add_resource", "effect_id": "add", "player": owner, "resource": "power",
                            "universal": True, "amount": 1}]}
    done = IR.apply_program(state, program)
    if not done.get("committed"):
        raise AssertionError(f"the Add did not commit: {done.get('reason') or done.get('errors')}")
    after = done["next_state"]["players"][owner]["resources"]
    return after.get("energy"), after.get("universal_power", 0), (done["trace"][0].get("gold_add_bonus") or {})


def main() -> int:
    errors: list[str] = []
    fields, pid = lowered(STATIC)
    if pid != "while_your_score_is_within_n_your_gold_add_an_additional_energy" or fields != {"gold_add_bonus": {
            "energy": 1, "condition": {"kind": "score_within_of_victory", "count": 3, "who": "you"}}}:
        errors.append(f"G1 grammar: {pid} {fields}")
    hold, hold_pid = lowered(HOLD)
    if hold_pid != "when_you_or_an_ally_hold" or ((hold.get("hold_triggers") or [{}])[0]).get("scope") != "controller_or_ally":
        errors.append(f"G1 grammar: hold {hold_pid} {hold}")
    for near in ("Your Gold [ADD] an additional :rb_energy_1:.", "When you or an ally conquer, draw 1.",
                 "While an opponent's score is within 3 points of the Victory Score, your Gold [ADD] an additional :rb_energy_1:."):
        if lowered(near)[1] in (pid, hold_pid):
            errors.append(f"G1 grammar: the near miss {near!r} parsed")
    s = board(5)
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    energy, power, bonus = add(s)
    if (energy, power) != (1, 1) or bonus.get("sources") != ["rn"]:
        errors.append(f"B1 within: energy {energy} power {power} bonus {bonus}")
    if add(board(4))[:2] != (0, 1):
        errors.append(f"B2 not within: {add(board(4))}")
    if add(board(5, gold_owner="p2"))[:2] != (0, 1):
        errors.append(f"B3 their Gold: {add(board(5, gold_owner='p2'))}")
    if add(board(5, renatas=(("rn", "p1", "trash"),)))[:2] != (0, 1):
        errors.append("B4 off the board: a Renata in the trash gave a bonus")
    if add(board(5, token_id="mech"))[:2] != (0, 1):
        errors.append("B5 not Gold: another token's Add got the bonus")
    if add(board(5, renatas=(("rn", "p1", "base"), ("rn2", "p1", "base"))))[:2] != (2, 1):
        errors.append(f"B6 two: {add(board(5, renatas=(('rn', 'p1', 'base'), ('rn2', 'p1', 'base'))))}")
    s = board(5, renatas=(("rn", "p1", "base"), ("rq", "p2", "base")))
    for oid in ("rn", "rq"):
        s["objects"][oid]["hold_triggers"] = [{**copy.deepcopy(hold["hold_triggers"][0]),
                                               "controller": s["objects"][oid]["controller"], "source_object": oid,
                                               "effect_program_id": f"{oid}-on-hold"}]
    scheduled = BC._score_triggers(s, "p1", "bf1", "hold", s.get("turn_id", "turn-0"))
    sources = sorted(t.get("source_object") for t in scheduled)
    if sources != ["rn"]:
        errors.append(f"H1 hold: scheduled from {sources}")
    # H2: "or an ally" - with teams an ally's hold triggers it too, and teams are not modelled: refused by name, never
    # read as the controller's hold alone (GPT's A2 review, reading 6)
    teamed = copy.deepcopy(s)
    teamed["mode"] = {**(teamed.get("mode") or {}), "teams": True}
    try:
        BC._score_triggers(teamed, "p1", "bf1", "hold", teamed.get("turn_id", "turn-0"))
        errors.append("H2 teams: the hold trigger was read in a state with teams")
    except BC.ScoringUnsupported as exc:
        if exc.code != "ally_scope_unsupported":
            errors.append(f"H2 teams: refused as {exc.code}")
    for label, bad in (("0 Energy", {"energy": 0, "condition": {"kind": "score_within_of_victory", "count": 3, "who": "you"}}),
                       ("an unknown condition", {"energy": 1, "condition": {"kind": "nonsense"}})):
        b = board(5)
        b["objects"]["rn"]["gold_add_bonus"] = bad
        if not IR.validate_state(b):
            errors.append(f"V: a gold_add_bonus with {label} validated")
    try:
        IR.evaluate_condition(board(5), {"kind": "score_within_of_victory", "count": 3, "who": "ally"}, controller="p1")
        errors.append("V: score_within_of_victory read 'ally'")
    except IR.ConditionUnsupported:
        pass
    if errors:
        print("gold-add-bonus checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("gold-add-bonus checks passed: while its controller's score is within 3 of the Victory Score, each Add of a Gold "
          "token they control adds 1 Energy more per such source on their board (not an opponent's Gold, not another "
          "token, not from the trash); the player-level hold trigger fires from the Base; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
