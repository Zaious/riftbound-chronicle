#!/usr/bin/env python3
"""Regression gate: "My hold effects are also conquer effects, and vice versa." (set 2 package A2: Skyfall of Areion's
Effect Text). An Effect Text continuous effect (score_effects_interchangeable) on the Top-Most card: while it applies, the
card's own "When I hold" abilities also trigger when it conquers, and its "When I conquer" abilities when it holds (Core
383.4.c-d); detached, each works for its own kind of scoring only.

  S1  u1 (at bf1) with a hold trigger and the Equipment attached: a conquer of bf1 schedules it
  S2  u1 with a conquer trigger and the Equipment attached: a hold of bf1 schedules it
  S3  the Equipment detached: a conquer schedules no hold trigger, a hold no conquer trigger
  S4  u1's own conquer trigger on a conquer is scheduled once (not twice) with the Equipment attached
  S5  an Equipment whose Effect Text is "When I hold, ..." attached to u1 (no printed triggers): a hold of bf1 schedules
      it, from u1; detached, nothing
  F   (GPT A2 ruling 10) a "first time I conquer each turn" ability crossed: the Unit's first hold this turn schedules
      it (its limit kept, not dropped); a later first conquer that turn does not (one usage record for both kinds); with
      no hold before, the first conquer does and a second does not
  P   a player-level "When you hold" on the Unit crosses to its conquer too
  G   the line lowers to exactly that Effect Text bundle; near misses do not
  V   the effect with a value other than {} does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from battlefield_control import _score_triggers  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import PROGRAM_VERSION, CORE_RULESET, FAQ_AS_OF, apply_program, validate_state  # noqa: E402

TEXT = "My hold effects are also conquer effects, and vice versa."
BUNDLE = {"effects": [{"kind": "score_effects_interchangeable", "value": {}}]}


def trig(trigger_id):
    return {"trigger_id": trigger_id, "controller": "p1", "source_object": "u1", "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False, "scope": "unit_here"}


def board(field, attached=True):
    s = base_state()
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["battlefields"]["bf1"]["objects"].append("u1")
    s["battlefields"]["bf1"]["controller"] = "p1"
    s["objects"]["u1"][field] = [trig("mine")]
    s["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Equipment"], "effect_text": copy.deepcopy(BUNDLE)}
    s["players"]["p1"]["zones"]["base"].append("g1")
    s = settle_contested(s)
    if attached:
        done = apply_program(s, {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                                 "program_id": "eq", "controller": "p1",
                                 "effects": [{"op": "attach", "effect_id": "at", "object_id": "g1", "to": "u1"}]})
        if not done.get("committed"):
            raise SystemExit(f"the attach did not commit: {done.get('reason') or done.get('errors')}")
        s = done["next_state"]
    return s


def fired(state, how):
    return [d["trigger_id"] for d in _score_triggers(state, "p1", "bf1", how, state.get("turn_id", "turn-0"))
            if d.get("source_object") == "u1"]


def conquered(state, times):
    """u1 has conquered `times` times this turn (the ledger resolve_battlefield_control keeps)."""
    turn = state.get("turn_id", "turn-0")
    state["players"]["p1"]["unit_conquests_this_turn"] = {turn: {state["objects"]["u1"].get("identity", "u1@0"): times}}
    return state


def main() -> int:
    errors: list[str] = []
    s1 = board("hold_triggers")
    if validate_state(s1):
        errors.append(f"board: {validate_state(s1)[:2]}")
    if fired(s1, "conquer") != ["mine"]:
        errors.append(f"S1: a conquer scheduled {fired(s1, 'conquer')}")
    s2 = board("conquer_triggers")
    if fired(s2, "hold") != ["mine"]:
        errors.append(f"S2: a hold scheduled {fired(s2, 'hold')}")
    if fired(board("hold_triggers", attached=False), "conquer") or fired(board("conquer_triggers", attached=False), "hold"):
        errors.append("S3: detached, a hold trigger fired on a conquer or a conquer trigger on a hold")
    if fired(s2, "conquer") != ["mine"]:
        errors.append(f"S4: a conquer scheduled {fired(s2, 'conquer')}")
    plain = board("hold_triggers", attached=False)
    plain["objects"]["u1"].pop("hold_triggers")
    plain["objects"]["g1"]["effect_text"] = {"triggers": {"hold_triggers": [trig("et")]}}
    done = apply_program(plain, {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                                 "program_id": "eq", "controller": "p1",
                                 "effects": [{"op": "attach", "effect_id": "at", "object_id": "g1", "to": "u1"}]})
    if not done.get("committed") or fired(done["next_state"], "hold") != ["et"] or fired(plain, "hold"):
        errors.append(f"S5: an Effect Text hold trigger scheduled {fired(done.get('next_state') or plain, 'hold')} "
                      f"attached, {fired(plain, 'hold')} detached")
    first = board("conquer_triggers")
    first["objects"]["u1"]["conquer_triggers"] = [{**trig("first"), "occurrence": "first_each_turn"}]
    if validate_state(first):
        errors.append(f"F board: {validate_state(first)[:2]}")
    held = copy.deepcopy(first)
    got_hold = fired(held, "hold")
    got_conquer = fired(conquered(held, 1), "conquer")
    if got_hold != ["first"] or got_conquer or validate_state(held):
        errors.append(f"F hold then conquer: hold {got_hold}, first conquer {got_conquer} {validate_state(held)[:1]}")
    fresh = copy.deepcopy(first)
    once, twice = fired(conquered(fresh, 1), "conquer"), fired(conquered(fresh, 2), "conquer")
    if once != ["first"] or twice:
        errors.append(f"F conquers: first {once}, second {twice}")
    if fired(conquered(board("conquer_triggers", attached=False), 1), "hold"):
        errors.append("F: detached, a conquer ability fired on a hold")
    player = board("hold_triggers")
    player["objects"]["u1"]["hold_triggers"] = [{**trig("you"), "scope": "controller"}]
    if fired(player, "conquer") != ["you"]:
        errors.append(f"P: a player-level hold ability on the Unit scheduled {fired(player, 'conquer')} on a conquer")
    got = CG.compile_clause(TEXT, CG.load_grammar())
    if ((got.get("passive") or {}).get("object_fields") or {}).get("effect_text") != BUNDLE:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    for near in ("My hold effects are also conquer effects.", "Your hold effects are also conquer effects, and vice versa."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == got.get("production_id"):
            errors.append(f"G: the near miss {near!r} lowered to the row")
    bad = copy.deepcopy(s1)
    for e in bad.get("continuous_effects") or []:
        if e["kind"] == "score_effects_interchangeable":
            e["value"] = {"both": True}
    if not any("score_effects_interchangeable" in p for p in validate_state(bad)):
        errors.append("V: a value other than {} validated")
    if errors:
        print("score-effects-interchangeable checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("score-effects-interchangeable checks passed: attached, a hold trigger fires on a conquer and a conquer trigger "
          "on a hold, once each; a first-time ability crosses with its limit, one usage record for both kinds; a "
          "player-level one crosses too; detached, neither crosses; lowered; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
