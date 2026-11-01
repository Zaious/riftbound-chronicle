#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "Choose a unit. The next time that unit would be dealt damage this turn, prevent it.
Draw 1." (Counter Strike) - the engine grammar's production lowers to a one-use granted prevention and a draw.

  P1 granted    the chosen unit u2 carries a one-use, this-turn prevention bound to its identity; p1 drew 1
  P2 prevented  a Deal of 3 to u2 is prevented (no damage) - the next one deals 3 (it applied once)
  P3 others     a Deal to another unit is not prevented
  P4 new object u2 leaves the board and comes back (a new object, Core 124): the prevention no longer applies
  G  grammar    the sentence lowers to exactly that program; its near misses do not lower

    python skill/scripts/check_set2_prevent_next.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "Choose a unit. The next time that unit would be dealt damage this turn, prevent it. Draw 1."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects, pid="cs"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "effects": effects}


def bind(effects):
    """$controller -> p1, $chain_item -> spell-1."""
    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return {"$controller": "p1", "$chain_item": "spell-1"}.get(v, v) if isinstance(v, str) else v
    return walk(copy.deepcopy(effects))


def deal(state, oid, amount=3):
    done = apply_program(state, program([{"op": "deal_damage", "effect_id": "d", "amount": amount, "object_id": oid}], "hit"))
    return done["next_state"] if done.get("committed") else None


def main() -> int:
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    effects = bind(lowered.get("program_effects") or [])
    if [e.get("op") for e in effects] != ["grant_replacement", "draw"]:
        fail("G", f"the sentence lowered to {[e.get('op') for e in effects]}")
        return report()
    state = base_state()
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 5, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("u3")
    hand = len(state["players"]["p1"]["zones"]["hand"])
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u2"],
         "selection_identities": {"u2": object_identity(state, "u2")}}]}
    done = apply_program(state, program(effects), decisions=decisions)
    if not done.get("committed"):
        fail("P1", f"refused: {done.get('reason') or done.get('errors')}")
        return report()
    granted = done["next_state"]
    found = [r for r in granted["replacement_effects"] if r.get("target_object_id") == "u2"]
    if len(found) != 1 or found[0].get("mode") != "prevent_event" or found[0].get("uses_remaining") != 1 \
            or len(granted["players"]["p1"]["zones"]["hand"]) != hand + 1:
        fail("P1", f"granted {found}, hand {len(granted['players']['p1']['zones']['hand'])} (was {hand})")
    first = deal(granted, "u2")
    second = deal(first, "u2") if first else None
    if first is None or first["objects"]["u2"]["damage"] != 0 or second is None or second["objects"]["u2"]["damage"] != 3:
        fail("P2", f"damage after the first Deal {first and first['objects']['u2']['damage']}, after the second "
                   f"{second and second['objects']['u2']['damage']} - not 0 then 3")
    other = deal(granted, "u3")
    if other is None or other["objects"]["u3"]["damage"] != 3:
        fail("P3", "a Deal to another unit was prevented")
    reborn = copy.deepcopy(granted)
    reborn["objects"]["u2"]["identity"] = "u2@9"
    hit = deal(reborn, "u2")
    if hit is None or hit["objects"]["u2"]["damage"] != 3:
        fail("P4", "the prevention applied to a new object")
    for near in ("choose a friendly unit. the next time that unit would be dealt damage this turn, prevent it. draw 1.",
                 "choose a unit. the next time that unit would be dealt damage, prevent it. draw 1."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == \
                "choose_a_unit_the_next_time_that_unit_would_be_dealt_damage_this_turn_prevent_it_draw_n":
            fail("G", f"a near miss lowered: {near!r}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: set 2 next damage prevented")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'the next time that unit would be dealt damage this turn, prevent it' grants one prevention bound to the "
          "chosen unit's identity - the next Deal to it is prevented, the one after is not, no other unit and no new object "
          "is covered - then the draw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
