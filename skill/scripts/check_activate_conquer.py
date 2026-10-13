#!/usr/bin/env python3
"""Activating the conquer effects of units at a Battlefield (package 11, Reckoner's Arena: "When you hold here, activate the
conquer effects of units here.").

Core 383.4.g.1 (official text, with this very card as its example), in this engine's words: every conquer effect of every
unit at the Battlefield is read with its conquer part taken as done; if the rest of it holds too, it becomes a Pending item
like a fresh trigger; if any other part fails, it does not. GPT 2026-10-12 (PACKAGE11 ruling 15): "units here" is not limited to
friendly ones; each is put on the Chain by its own unit's controller. The engine's shape: op activate_conquer_effects
{location_ref} - its pending triggers carry the Battlefield as the one scored (scored_battlefield).

  A1 both sides     the Arena (p1's) holds: its hold trigger resolves; p1's u1 ("When I conquer") and p2's e1 ("When I
                    conquer") at it are each Pending, controlled by their own controller
  A2 the rest       p1's u2 at it, "When you conquer, if you have 3+ units at that battlefield" - with two units of p1
                    there it is not activated (named); with a third, it is
  A3 elsewhere      p1's u3 at bf2 with a conquer effect: not activated
  A4 not a unit     a gear of p1's at the Arena with a conquer effect: not activated
  A5 resolved       u1's activated trigger resolves: p1 draws 1
  V  shape/grammar  the op without a location_ref does not validate; the card's text lowers to a hold trigger whose
                    program is the op

    python skill/scripts/check_activate_conquer.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, battlefield_identity,  # noqa: E402
                       validate_program, validate_state)

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
errors: list[str] = []
HERE = {"kind": "program_source_current_battlefield"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def conquer(trigger_id, controller, source, **extra):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-fx", "optional_at_finalize": False, **extra}


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(third=False):
    """bf1 is the Arena (p1 controls it). At bf1: p1's u1 ("When I conquer"), p2's e1 ("When I conquer"), p1's u2 ("When you
    conquer, if you have 3+ units at that battlefield") and p1's gear g1 with a conquer descriptor; p1's u4 there too when
    `third`. At bf2: p1's u3 ("When I conquer")."""
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": []}
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
    state["objects"].update({
        "u1": unit("p1", conquer_triggers=[conquer("u1-c", "p1", "u1")]),
        "e1": unit("p2", conquer_triggers=[conquer("e1-c", "p2", "e1")]),
        "u2": unit("p1", conquer_triggers=[conquer("u2-c", "p1", "u2", scope="controller", condition={
            "kind": "controls_units", "count": 3, "location": "here"})]),
        "g1": {**unit("p1", conquer_triggers=[conquer("g1-c", "p1", "g1")]), "kind": "gear", "base_might": 0},
        "u3": unit("p1", conquer_triggers=[conquer("u3-c", "p1", "u3")]),
        "u4": unit("p1")})
    for oid in ("u1", "u2", "u3", "u4"):
        for player in state["players"].values():
            for zone in player["zones"].values():
                if oid in zone:
                    zone.remove(oid)
    state["battlefields"]["bf1"]["objects"] = ["u1", "e1", "u2", "g1"] + (["u4"] if third else [])
    state["battlefields"]["bf2"]["objects"] = ["u3"]
    if not third:
        state["players"]["p1"]["zones"]["base"].append("u4")
    # p2's e1 at p1's Arena: contested, as the engine settles it (Core 190.3.a) - p1 still controls it
    return settle_contested(state)


def arena(state):
    program = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "arena-hold", "controller": "p1",
               "source_object": "bf1", "source_identity": battlefield_identity(state, "bf1"),
               "effects": [{"op": "activate_conquer_effects", "effect_id": "act", "location_ref": dict(HERE)}]}
    return apply_program(state, program)


def pending(got):
    return sorted((t["trigger_id"], t["controller"]) for t in got.get("pending_triggers") or []) \
        if got.get("committed") else f"refused: {got.get('reason') or got.get('errors')}"


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    got = arena(s)
    found = pending(got)
    if found != [("e1-c", "p2"), ("u1-c", "p1")]:
        fail("A1/A3/A4", f"activated {found}, not exactly u1's (p1) and e1's (p2)")
    step = next((e for e in got.get("trace") or [] if e.get("effect_id") == "act"), {})
    if [x.get("trigger_id") for x in step.get("not_activated") or []] != ["u2-c"]:
        fail("A2 the rest", f"u2's conditional effect not named as not activated: {step.get('not_activated')}")
    with_third = pending(arena(board(third=True)))
    if with_third != [("e1-c", "p2"), ("u1-c", "p1"), ("u2-c", "p1")]:
        fail("A2 the rest", f"with three of p1's units there: {with_third}")
    if got.get("committed"):
        t = next(t for t in got["pending_triggers"] if t["trigger_id"] == "u1-c")
        if t.get("scored_battlefield") != "bf1" or t.get("trigger_kind") != "triggered":
            fail("A1 shape", t)
        hand = len(got["next_state"]["players"]["p1"]["zones"]["hand"])
        drew = apply_program(got["next_state"], {"schema_version": PROGRAM_VERSION, "ruleset": RULESET,
                                                 "program_id": "u1-c-fx", "controller": t["controller"], "source_object": "u1",
                                                 "effects": [{"op": "draw", "effect_id": "d", "player": "p1", "count": 1}]})
        if not drew.get("committed") or len(drew["next_state"]["players"]["p1"]["zones"]["hand"]) != hand + 1:
            fail("A5 resolved", drew.get("reason"))
    bad = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "x", "controller": "p1",
           "effects": [{"op": "activate_conquer_effects", "effect_id": "act"}]}
    if not validate_program(bad):
        fail("V shape", "the op without a location_ref validated")
    card = cg.compile_card([{"text": "When you hold here, activate the conquer effects of units here."}], cg.load_grammar())
    fields = (card.get("passive") or {}).get("battlefield_fields") or (card.get("passive") or {}).get("object_fields") or {}
    if card.get("unsupported_clauses") or not fields.get("hold_triggers"):
        fail("V grammar", f"{card.get('unsupported_clauses')} {card.get('passive')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: activating the conquer effects of units at a Battlefield")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the conquer effects of every unit at the Battlefield - either side, each its own controller's - are checked "
          "as if conquered and put on the Chain when the rest of their condition holds; a unit elsewhere, a gear, or a "
          "condition not met is not activated, by name (A1-A5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
