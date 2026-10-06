#!/usr/bin/env python3
"""An opponent's Move to a Battlefield the source is not at (package 9, Volibear - Imposing).

"When an opponent moves to a battlefield other than mine, draw 1. (Bases are not battlefield.)" GPT 2026-10-06
(PACKAGE9_INVENTORY section 7, ruling 14): the Move's responsibility (Core 411.1, 411.4) - a Standard Move the
opponent makes, or one an effect the opponent controls makes; the source in its Base names no "mine" and is a named
blocker, never guessed.

The engine's shape: a watch over `moved` events, scope opponent_actor, filters destination_kind battlefield and
destination_not_source_battlefield, grouping one_or_more (one trigger per batch of Moves).

  V1 other bf      p2's Standard Move of a unit to bf2 (Volibear at bf1): one trigger
  V2 mine          p2's Move to bf1, Volibear's: none
  V3 one move      p2's one Standard Move of two units to bf2: one trigger, not two
  V4 not opponent  p1's own Move to bf2: none
  V5 effect move   p2's spell moving p2's unit to bf2: one trigger
  V6 base          Volibear in p1's Base, p2 moves to bf2: refused by name (source_not_at_battlefield)
  G  grammar       the clause grammar lowers the sentence to exactly that descriptor; near misses stay unparsed

    python skill/scripts/check_opponent_move_watch.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_move_count_and_legend_triggers import descriptor, effect_move, mine, smove  # noqa: E402
from effect_ir import validate_state  # noqa: E402

WATCH = {"kinds": ["moved"], "scope": "opponent_actor",
         "filter": {"destination_kind": "battlefield", "destination_not_source_battlefield": True},
         "grouping": "one_or_more"}
TO_BF1 = {"kind": "battlefield", "battlefield": "bf1"}
TO_BF2 = {"kind": "battlefield", "battlefield": "bf2"}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(*, volibear_at_base=False):
    """Volibear (v1, p1's) at bf1 - or in p1's Base - with the watch; p2's ready units e1, e2 in p2's Base; p1's p1u in
    p1's Base; bf2 empty and p2's."""
    state = base_state()
    state["turn_id"] = "turn-6"
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": [] if volibear_at_base else ["v1"]}
    state["battlefields"]["bf2"] = {"controller": "p2", "objects": []}
    state["objects"]["v1"] = unit("p1", event_triggers=[descriptor("v-watch", "v1", "p1", watch=copy.deepcopy(WATCH))])
    if volibear_at_base:
        state["players"]["p1"]["zones"]["base"].append("v1")
    for oid in ("e1", "e2"):
        state["objects"][oid] = unit("p2")
        state["players"]["p2"]["zones"]["base"].append(oid)
    state["objects"]["p1u"] = unit("p1")
    state["players"]["p1"]["zones"]["base"].append("p1u")
    assert not validate_state(state), validate_state(state)
    return state


def count(result) -> int | str:
    if not result.get("committed"):
        return f"refused: {result.get('reason_code')} {result.get('reason')}"
    return len(mine(result, "v-watch@"))


def main() -> int:
    got = count(smove(board(), "e1", TO_BF2, actor="p2"))
    if got != 1:
        fail("V1 other bf", got)
    got = count(smove(board(), "e1", TO_BF1, actor="p2"))
    if got != 0:
        fail("V2 mine", got)
    got = count(smove(board(), ["e1", "e2"], TO_BF2, actor="p2"))
    if got != 1:
        fail("V3 one move", got)
    got = count(smove(board(), "p1u", TO_BF2, actor="p1"))
    if got != 0:
        fail("V4 not opponent", got)
    got = count(effect_move(board(), "e1", TO_BF2, controller="p2"))
    if got != 1:
        fail("V5 effect move", got)
    based = smove(board(volibear_at_base=True), "e1", TO_BF2, actor="p2")
    text = f"{based.get('reason_code')} {based.get('reason')}"
    if based.get("committed") or "source_not_at_battlefield" not in text and "is at no Battlefield" not in text:
        fail("V6 base", f"{based.get('committed')} {text}")
    lowered = CG.compile_clause("When an opponent moves to a battlefield other than mine, draw 1.", CG.load_grammar())
    fields = (lowered.get("triggers") or lowered.get("trigger") or {})
    if lowered.get("unsupported") or WATCH != _watch_of(lowered):
        fail("G grammar", f"{lowered.get('production_id')} {lowered.get('reason')} {fields}")
    for near in ("When an opponent moves to my battlefield, draw 1.", "When you move to a battlefield other than mine, draw 1."):
        if not CG.compile_clause(near, CG.load_grammar()).get("unsupported"):
            fail("G grammar", f"{near!r} was parsed")
    if errors:
        print("FAILED: opponent move watch checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: an opponent's Move to a Battlefield other than the source's triggers once per batch; the source at no "
          "Battlefield is refused by name (V1-V6, G)")
    return 0


def _watch_of(lowered: dict):
    """The watch of the lowered clause's event_triggers descriptor, wherever the result carries it."""
    def walk(value):
        if isinstance(value, dict):
            if "watch" in value and isinstance(value["watch"], dict):
                return value["watch"]
            for v in value.values():
                found = walk(v)
                if found is not None:
                    return found
        if isinstance(value, list):
            for v in value:
                found = walk(v)
                if found is not None:
                    return found
        return None
    return walk(lowered)


if __name__ == "__main__":
    raise SystemExit(main())
