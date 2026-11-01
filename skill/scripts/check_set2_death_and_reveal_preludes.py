#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): two printed passives that change an event before it happens.

Soraka - Wanderer's printed replacement (the card the Core's replacement-ordering example is about): a kill
Replacement Effect over another friendly Unit at the card's location with less Might than the card.

  D1 saved           p1's damaged 2-Might Unit at the card's Battlefield, killed: healed, exhausted, in p1's Base
  D2 not less        a 5-Might friendly Unit there (the card has 4): dies
  D3 elsewhere       a friendly 2-Might Unit in p1's Base while the card is at bf1: dies
  D4 the card        the card itself: dies (it does not have less Might than itself)
  D5 enemy           an enemy Unit there: dies

"If you would reveal cards from a deck, look at the top card first. You may recycle it. Then reveal those cards."
(Void Hatchling) - reveal_preludes, before a reveal its controller makes from the top of a deck.

  R1 recycled        p1 reveals the top 2: first looks at the top card, recycles it (to the bottom, a new object); the
                     two revealed are the next two
  R2 kept            the same, not recycled: the original top two are revealed
  R3 asked           no answer given: the reveal stops for p1's optional choice
  R4 not theirs      p2 reveals the top of p2's deck: nothing asked
  R5 reveal until    reveal_until is preceded the same way
  V                  a prelude of another kind does not validate

    python skill/scripts/check_set2_death_and_reveal_preludes.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
SORAKA = "If another unit you control here would die, if it has less Might than me, instead heal it, exhaust it, and recall it."
HATCHLING = "If you would reveal cards from a deck, look at the top card first. You may recycle it. Then reveal those cards."


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def program(controller, *effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "p", "controller": controller, "effects": list(effects)}


def soraka_board():
    import json
    lowered = CG.compile_clause(SORAKA, CG.load_grammar())["passive"]["state_lists"]["replacement_effects"]
    text = json.dumps(lowered)
    for symbol, value in (("$source_object", "sk"), ("$controller", "p1"), ("$clause_id", "sk-statement")):
        text = text.replace(json.dumps(symbol), json.dumps(value))
    state = base_state()
    state["objects"].update({"sk": unit("p1", 4), "f1": unit("p1", 2, damage=1), "f2": unit("p1", 5),
                             "f3": unit("p1", 2), "e1": unit("p2", 2)})
    state["battlefields"]["bf1"]["objects"] = ["sk", "f1", "f2", "e1"]
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["players"]["p1"]["zones"]["base"].append("f3")
    state["replacement_effects"] = json.loads(text)
    return settle_contested(state)


def hatchling_board():
    state = base_state()
    state["objects"]["vh"] = unit("p1", 1, reveal_preludes=[{"prelude_id": "look-top-may-recycle",
                                                             "kind": "look_at_top_may_recycle"}])
    state["players"]["p1"]["zones"]["base"].append("vh")
    for i in range(4):
        state["objects"][f"d{i}"] = unit("p1", 1)
        state["objects"][f"o{i}"] = unit("p2", 1)
    state["players"]["p1"]["zones"]["main_deck"][:0] = [f"d{i}" for i in range(4)]
    state["players"]["p2"]["zones"]["main_deck"][:0] = [f"o{i}" for i in range(4)]
    return state


def answer(state, value, ref="reveal-prelude:vh:rv"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": ref, "stage": "resolution", "kind": "optional_choice", "controller": "p1",
                           "value": value}]}


def main() -> int:
    for label, victim, saved in (("D1", "f1", True), ("D2", "f2", False), ("D3", "f3", False), ("D4", "sk", False),
                                 ("D5", "e1", False)):
        state = soraka_board()
        problems = validate_state(state)
        if problems:
            fail(label, f"board invalid: {problems[:2]}")
            continue
        done = apply_program(state, program("p2", {"op": "kill", "effect_id": "k", "object_id": victim}))
        if not done.get("committed"):
            fail(label, f"{done.get('reason_code')} {done.get('reason') or done.get('errors')}")
            continue
        after = done["next_state"]
        owner = after["objects"][victim]["owner"]
        if saved:
            obj = after["objects"][victim]
            if victim not in after["players"][owner]["zones"]["base"] or obj["damage"] or not obj["exhausted"]:
                fail(label, f"not saved: base {after['players'][owner]['zones']['base']} {obj}")
        elif victim not in after["players"][owner]["zones"]["trash"]:
            fail(label, f"{victim} did not die")
    reveal = {"op": "reveal", "effect_id": "rv", "from": "main_deck_top", "count": 2, "player": "p1"}
    state = hatchling_board()
    problems = validate_state(state)
    if problems:
        fail("R board", problems[:2])
    done = apply_program(state, program("p1", reveal), decisions=answer(state, True))
    if not done.get("committed"):
        fail("R1", f"{done.get('reason_code')} {done.get('reason')}")
    else:
        rv = next(t for t in done["trace"] if t.get("effect_id") == "rv")
        deck = done["next_state"]["players"]["p1"]["zones"]["main_deck"]
        if [r["object_id"] for r in rv["revealed"]] != ["d1", "d2"] or deck[-1] != "d0" or deck[0] != "d1" \
                or object_identity(done["next_state"], "d0") == object_identity(state, "d0"):
            fail("R1", f"revealed {[r['object_id'] for r in rv['revealed']]}, deck {deck}")
    done = apply_program(state, program("p1", reveal), decisions=answer(state, False))
    rv = next((t for t in done.get("trace") or [] if t.get("effect_id") == "rv"), {})
    if not done.get("committed") or [r["object_id"] for r in rv.get("revealed", [])] != ["d0", "d1"]:
        fail("R2", f"{done.get('reason_code')} {rv.get('revealed')}")
    done = apply_program(state, program("p1", reveal))
    if done.get("committed") or "reveal-prelude:vh:rv" not in (done.get("decision_ids") or []):
        fail("R3", f"{done.get('committed')} {done.get('reason_code')} {done.get('decision_ids')}")
    theirs = {"op": "reveal", "effect_id": "rv", "from": "main_deck_top", "count": 1, "player": "p2"}
    done = apply_program(state, program("p2", theirs))
    if not done.get("committed"):
        fail("R4", f"an opponent's reveal stopped: {done.get('reason_code')}")
    until = {"op": "reveal_until", "effect_id": "rv", "player": "p1", "until": {"kind": "unit"}}
    done = apply_program(state, program("p1", until), decisions=answer(state, True))
    rv = next((t for t in done.get("trace") or [] if t.get("effect_id") == "rv"), {})
    if not done.get("committed") or rv.get("found") != "d1" or not rv.get("preludes"):
        fail("R5", f"{done.get('reason_code')} found {rv.get('found')} preludes {rv.get('preludes')}")
    bad = hatchling_board()
    bad["objects"]["vh"]["reveal_preludes"] = [{"prelude_id": "x", "kind": "look_at_top_may_banish"}]
    if not validate_state(bad):
        fail("V", "a prelude of another kind validated")
    if errors:
        print("FAILED: set 2 a death replaced 'here' / a look before a reveal")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: another friendly unit here with less Might is healed, exhausted and recalled instead of dying (374); a "
          "reveal from the top of a deck by the card's controller is preceded by a look at the top card, which they may "
          "recycle, and then reveals the deck as it is")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
