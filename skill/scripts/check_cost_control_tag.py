#!/usr/bin/env python3
"""Regression gate: a card's own Energy reduction gated by its player controlling a Unit of a printed tag (set 2 package
A2: Production Surge, "This costs [2] less if you control a Mech."; Core 356.4, 356.4.b) - read as the cost is determined,
off the board.

  G1 grammar     the sentence lowers to one energy_reduction of 2 under controls_units {count 1, tag Mech}; the
                 negatives (Power glyph, two Mechs, an opponent controls) do not parse
  P1 own Mech    p1 controls a Mech in its Base: paid with 2 of a printed 4, 2 left of 4
  P2 at a bf     a Mech of p1's at a Battlefield, exhausted: the same
  P3 none        no Mech: 4 paid; 3 Energy cannot pay
  P4 theirs      only p2 controls a Mech: 4 paid
  P5 not board   a Mech card in p1's trash only: 4 paid
  P6 other tag   p1 controls a Poro, no Mech: 4 paid
  P7 token       a Mech token (tags carried by play_token) of p1's: 2 paid
  M1 mutation    the condition's tag dropped: any Unit reduces (the tag is what P6 sees)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
from check_cost_from_board import board, left, play  # noqa: E402

SURGE = "This costs :rb_energy_2: less if you control a Mech."


def lowered(text):
    got = CG.compile_clause(text, CG.load_grammar())
    return (got.get("passive") or {}).get("object_fields") or {}, got.get("production_id")


def tagged(state, oid, tags, *, exhausted=False):
    state["objects"][oid]["tags"] = list(tags)
    state["objects"][oid]["exhausted"] = exhausted
    return state


def main() -> int:
    errors: list[str] = []
    fields, pid = lowered(SURGE)
    want = {"printed_cost_modifications": [{"modification_id": "own-text", "kind": "energy_reduction", "amount": 2,
                                            "condition": {"kind": "controls_units", "count": 1, "tag": "Mech"}}]}
    if pid != "self_cost_reduction_control_tag" or fields != want:
        errors.append(f"G1 grammar: {pid} {fields}")
    for negative in ("This costs :rb_rune_rainbow: less if you control a Mech.",
                     "This costs :rb_energy_2: less if you control two Mechs.",
                     "This costs :rb_energy_2: less if an opponent controls a Mech."):
        if lowered(negative)[1] == "self_cost_reduction_control_tag":
            errors.append(f"G1 grammar: the negative {negative!r} parsed")

    def paid(state, energy=4):
        got = play(state, 4)
        return (energy - left(got)) if got.get("committed") else None

    s = tagged(board(fields, 4, units=[("m1", 3, "base")]), "m1", ["Mech"])
    if paid(s) != 2:
        errors.append(f"P1 own Mech: paid {paid(s)}")
    s = tagged(board(fields, 4, units=[("m1", 3, "bf1")]), "m1", ["Mech"], exhausted=True)
    if paid(s) != 2:
        errors.append(f"P2 at a bf: paid {paid(s)}")
    s = board(fields, 4, units=[("u5", 3, "base")])
    s["objects"]["u5"]["tags"] = []
    if paid(s) != 4 or play(board(fields, 3), 4).get("committed"):
        errors.append(f"P3 none: paid {paid(s)}, or 3 Energy paid")
    s = tagged(board(fields, 4, their_units=[("m2", 3, "base")]), "m2", ["Mech"])
    if paid(s) != 4:
        errors.append(f"P4 theirs: paid {paid(s)}")
    s = tagged(board(fields, 4, trash_units=[("m3", 3)]), "m3", ["Mech"])
    if paid(s) != 4:
        errors.append(f"P5 not board: paid {paid(s)}")
    s = tagged(board(fields, 4, units=[("p5", 3, "base")]), "p5", ["Poro"])
    if paid(s) != 4:
        errors.append(f"P6 other tag: paid {paid(s)}")
    s = tagged(board(fields, 4, units=[("t1", 3, "base")]), "t1", ["Mech"])
    s["objects"]["t1"]["token"] = True
    if paid(s) != 2:
        errors.append(f"P7 token: paid {paid(s)}")
    mutated = copy.deepcopy(fields)
    del mutated["printed_cost_modifications"][0]["condition"]["tag"]
    s = tagged(board(mutated, 4, units=[("p5", 3, "base")]), "p5", ["Poro"])
    if paid(s) != 2:
        errors.append(f"M1 mutation: without the tag a Poro paid {paid(s)} (the mutation should reduce)")
    if errors:
        print("cost-control-tag checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("cost-control-tag checks passed: 'This costs [2] less if you control a Mech.' - a Mech of its player's on the "
          "board (Base or Battlefield, exhausted or not, a token too) takes 2 off; none, an opponent's, one in the trash "
          "or another tag takes nothing; the tag is what decides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
