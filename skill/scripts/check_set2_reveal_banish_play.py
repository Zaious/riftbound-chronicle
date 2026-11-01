#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "Reveal the top 2 cards of your Main Deck. You may banish one, then play it,
reducing its cost by [2]. Draw any you didn't banish." (Void Rush) and "... You may banish one, then play it. Recycle the
rest." (Rek'Sai - Void Burrower) - choose_objects from the revealed cards into a group, banish over the group, a play
linked to that banish, and draw_rest / recycle over what the group left.

  B1 banished, played, rest drawn   p1 picks top1: it is banished and its play started (a Chain item, Core 420.3) with
                                    its cost reduced; top2 drawn (a draw event)
  B2 rest recycled                  the same, with "Recycle the rest": top2 to the bottom of the Main Deck
  B3 none banished                  p1 picks none ("you may"): nothing banished or played; both revealed cards drawn
  B4 not revealed                   a card that was not revealed cannot be picked
  V                                 draw_rest naming no group, or banish with group_ref beside another holder, refused

    python skill/scripts/check_set2_reveal_banish_play.py
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
HEAD = [{"op": "reveal", "effect_id": "rv", "from": "main_deck_top", "count": 2, "player": "p1"},
        {"op": "choose_objects", "effect_id": "pick", "decision_ref": "pick", "group": "kept",
         "choice": {"selection_kind": "unordered_set", "from": "revealed", "by": "controller", "count": {"up_to": 1},
                    "visibility": "public"}},
        {"op": "banish", "effect_id": "ban", "player": "p1", "group_ref": "kept"},
        {"op": "limited_play", "effect_id": "lp", "linked": {"effect_id": "ban", "from": "banishment"},
         "cost_basis": {"kind": "discount_energy", "amount": 2}}]
DRAW_REST = {"op": "draw_rest", "effect_id": "dr", "player": "p1", "rest_of": "kept"}
RECYCLE_REST = {"op": "recycle", "effect_id": "rc", "rest_of": "kept"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board():
    state = base_state()
    for card, kind in (("top1", "unit"), ("top2", "spell")):
        state["objects"][card] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": 2, "might_modifiers": [],
                                  "damage": 0, "exhausted": False, "printed_cost": {"energy": 3, "power": {}}}
    state["players"]["p1"]["zones"]["main_deck"][:0] = ["top1", "top2"]
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    return state


def run(tail, pick):
    state = board()
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "rush", "controller": "p1", "effects": copy.deepcopy(HEAD) + [tail]}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "pick", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": pick,
         "selection_identities": {c: object_identity(state, c) or f"{c}@0" for c in pick}}]}
    return apply_program(state, program, decisions=decisions)


def main() -> int:
    done = run(DRAW_REST, ["top1"])
    if not done.get("committed"):
        fail("B1", f"refused: {done.get('reason') or done.get('errors')}")
    else:
        plays = done.get("limited_plays") or []
        z = done["next_state"]["players"]["p1"]["zones"]
        drawn = [e.get("object") for e in done.get("events") or [] if e.get("kind") == "drawn"]
        if [p.get("card") for p in plays] != ["top1"] or "top2" not in z["hand"] or drawn != ["top2"]:
            fail("B1", f"plays {plays}, hand {z['hand']}, drawn {drawn}")
    done = run(RECYCLE_REST, ["top1"])
    if not done.get("committed") or done["next_state"]["players"]["p1"]["zones"]["main_deck"][-1:] != ["top2"]:
        fail("B2", f"{done.get('reason') or done['next_state']['players']['p1']['zones']['main_deck']}")
    done = run(DRAW_REST, [])
    if not done.get("committed") or done.get("limited_plays") or \
            not {"top1", "top2"} <= set(done["next_state"]["players"]["p1"]["zones"]["hand"]):
        fail("B3", f"none picked: {done.get('reason') or done.get('limited_plays')}")
    done = run(DRAW_REST, ["c1"])
    if done.get("committed"):
        fail("B4", "a card that was not revealed was picked")
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "bad", "controller": "p1", "effects": copy.deepcopy(HEAD)}
    program["effects"][2]["objects"] = ["top1"]
    if not validate_program(program):
        fail("V", "banish with group_ref and objects validated")
    if errors:
        print("FAILED: set 2 reveal, banish one, play it")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: of the revealed cards the one its controller picks is banished and played from Banishment (420.3), the "
          "rest drawn or recycled; picking none plays nothing; only a revealed card can be picked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
