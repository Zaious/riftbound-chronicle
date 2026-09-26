#!/usr/bin/env python3
"""An instruction its controller MAY perform, decided as it resolves (Core 355.12).

"You may kill up to one gear. Draw 1." chooses its target as the spell is played - zero or
one gear (Core 355.13) - whatever its controller will later decide; the decision to perform
the kill is separate and is made as the spell resolves (Core 355.12: all choices are targeted
and chosen independently of the decision to perform the Game Action). So the instruction
carries `optional {decision_ref}`, answered by an optional_choice decision at the resolution
stage, by the program's controller:

  no decision       the program does not run; optional_choice_required, naming the decision
                    and its controller
  performed         the chosen gear goes to its owner's trash; the draw happens
  declined          nothing is killed, the trace says declined, the draw still happens
  nothing chosen    performed with no target: the kill does nothing, the draw happens
  target gone       performed on a gear that left the board: skipped, the draw happens
  wrong hands       decided by the opponent - decision_controller_mismatch; decided at play -
                    refused as the wrong stage
  bounds            two gear for "up to one" are refused at play (target_count_out_of_range)
  malformed         `optional` that is not {decision_ref}, or on a choice, does not validate

Every fixture is synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import find_location, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
KILL = {"op": "kill", "effect_id": "k", "optional": {"decision_ref": "may"},
        "targets": {"min": 0, "max": 1, "decision_ref": "t",
                    "restrictions": {"chosen_zone_class": "board", "kind": "gear"}}}
DRAW = {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}


def board() -> dict:
    """p1 holds the spell c1; p2's gear g1 is in p2's Base; p1's gear g2 in p1's Base."""
    state = base_state()
    p1 = state["players"]["p1"]["zones"]
    p1["main_deck"].remove("c1")
    p1["hand"].append("c1")
    for gear, owner in (("g1", "p2"), ("g2", "p1")):
        state["objects"][gear] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False}
        state["players"][owner]["zones"]["base"].append(gear)
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return settle_contested(state)


def program(effects=None) -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": "c1-effects",
            "controller": "p1", "effects": copy.deepcopy(effects or [KILL, DRAW])}


def play(state: dict, chosen: list[str], effects=None) -> dict:
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
                   "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "c1-effects",
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                 "decisions": [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection",
                                "controller": "p1", "value": list(chosen),
                                "selection_identities": {o: object_identity(state, o) for o in chosen}}]}
    return play_card(fixture(), state, declaration, engine_decisions=decisions, effect_program=program(effects))


def resolve(played: dict, may=None, *, controller="p1", stage="resolution", state=None, effects=None) -> dict:
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    effect_state = state if state is not None else played["next_effect_state"]
    decisions = None
    if may is not None:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(effect_state),
                     "decisions": [{"decision_id": "may", "stage": stage, "kind": "optional_choice",
                                    "controller": controller, "value": may}]}
    return resolve_with_program(timing, "spell-1", effect_state, program(effects), engine_decisions=decisions)


def hand(state: dict) -> int:
    return len(state["players"]["p1"]["zones"]["hand"])


def main() -> int:
    errors: list[str] = []
    state = board()
    if validate_state(state):
        errors.append(f"the fixture board does not validate: {validate_state(state)[:2]}")
    played = play(state, ["g1"])
    if not played.get("committed"):
        errors.append(f"'you may kill up to one gear' with one gear chosen was refused at play: {played.get('reason_code')}")
        print("FAILED: optional instruction\n  - " + "\n  - ".join(errors))
        return 1
    after_play = played["next_effect_state"]

    undecided = resolve(played)
    effect = undecided.get("effect_result") or {}
    if undecided.get("committed") or effect.get("reason_code") != "optional_choice_required" \
            or effect.get("decision_ids") != ["may"] or effect.get("decision_controller") != "p1":
        errors.append(f"no decision: {undecided.get('committed')} {effect.get('reason_code')} {effect.get('decision_ids')}")

    done = resolve(played, True)
    if not done.get("committed"):
        errors.append(f"performed: resolution refused ({done.get('reason')})")
    else:
        after = done["next_effect_state"]
        if find_location(after, "g1") != ("player", "p2", "trash") or find_location(after, "g2") != ("player", "p1", "base"):
            errors.append(f"performed: g1 at {find_location(after, 'g1')}, g2 at {find_location(after, 'g2')}")
        if hand(after) != hand(after_play) + 1:
            errors.append("performed: the draw did not happen")

    declined = resolve(played, False)
    if not declined.get("committed"):
        errors.append(f"declined: resolution refused ({declined.get('reason')})")
    else:
        after = declined["next_effect_state"]
        outcomes = [e.get("outcome") for e in (declined.get("trace") or {}).get("effect") or []]
        if find_location(after, "g1") != ("player", "p2", "base") or outcomes[:1] != ["declined"]:
            errors.append(f"declined: g1 at {find_location(after, 'g1')}, outcomes {outcomes}")
        if hand(after) != hand(after_play) + 1:
            errors.append("declined: the draw did not happen")

    nothing = play(state, [])
    if not nothing.get("committed"):
        errors.append(f"nothing chosen: refused at play ({nothing.get('reason_code')})")
    else:
        run = resolve(nothing, True)
        after = run.get("next_effect_state") or {}
        if not run.get("committed") or find_location(after, "g1") != ("player", "p2", "base") or hand(after) != hand(nothing["next_effect_state"]) + 1:
            errors.append(f"nothing chosen, performed: {run.get('reason')}")

    gone = copy.deepcopy(after_play)
    gone["players"]["p2"]["zones"]["base"].remove("g1")
    gone["players"]["p2"]["zones"]["trash"].append("g1")
    gone["objects"]["g1"]["identity"] = "g1@1"
    run = resolve(played, True, state=gone)
    outcomes = [e.get("outcome") for e in (run.get("trace") or {}).get("effect") or []]
    if not run.get("committed") or outcomes[:1] == ["applied"] or hand(run["next_effect_state"]) != hand(gone) + 1:
        errors.append(f"target gone, performed: {run.get('committed')} {outcomes} {run.get('reason')}")

    wrong = resolve(played, True, controller="p2")
    if wrong.get("committed") or (wrong.get("effect_result") or {}).get("reason_code") != "decision_controller_mismatch":
        errors.append(f"decided by the opponent: {(wrong.get('effect_result') or {}).get('reason_code')}")
    early = resolve(played, True, stage="play_declaration")
    if early.get("committed") or (early.get("effect_result") or {}).get("valid") is not False:
        errors.append(f"decided at play: {early.get('committed')} {(early.get('effect_result') or {}).get('errors')}")

    two = play(state, ["g1", "g2"])
    if two.get("committed") or two.get("reason_code") != "target_count_out_of_range":
        errors.append(f"two gear for 'up to one': {two.get('reason_code')}")

    for label, bad in (("empty", {**KILL, "optional": {}}), ("unnamed", {**KILL, "optional": {"decision_ref": ""}}),
                       ("extra key", {**KILL, "optional": {"decision_ref": "may", "default": True}})):
        if not validate_program(program([bad, DRAW])):
            errors.append(f"a malformed optional ({label}) validated")
    choice = {"op": "establish_selection", "effect_id": "ch", "selection_id": "ch", "decision_ref": "ch",
              "optional": {"decision_ref": "may"},
              "choice": {"selection_kind": "single", "from": "board", "count": {"one": True}, "visibility": "public",
                         "criteria": {"kind": "unit"}}}
    if not validate_program(program([choice])):
        errors.append("optional on a choice validated")

    if errors:
        print("FAILED: optional instruction")
        for problem in errors:
            print("  - " + problem)
        return 1
    print("optional instruction: decided at resolution by its controller; performed, declined, nothing chosen and "
          "target gone each leave the next instruction running; wrong controller, wrong stage and malformed refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
