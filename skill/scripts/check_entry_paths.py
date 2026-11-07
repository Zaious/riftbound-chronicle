#!/usr/bin/env python3
"""Boundary gate (set 2 package A2; GPT A2 ruling 6, Bushwhack "Friendly units enter ready this turn."): "enter" is not
"play". Core lets objects enter the board by other paths (Create, Replace); this engine has exactly two that bring a
Unit onto the board from outside it - a card played (resolution_bridge.complete_permanent_play, limited plays and plays
from facedown included) and a token played (effect_ir play_token) - and both read the entry-state turn effects
(entry_state_for_played_units). Every other site that adds an object to a board location moves or attaches an object
ALREADY on the board, or adds a rune. A new site fails this gate until it is classified - so an entry path cannot be
added without deciding whether "enter ready" reaches it.

  P1 sites      every line of effect_ir.py / resolution_bridge.py that appends to a Battlefield's objects or a Base is
                inside one of the classified branches below, and every classified branch still has such a line
  P2 reads      the two entry paths read entry_state_for_played_units
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPEND = re.compile(r'\[("objects"|"base")\]\.append\(')
ENTERS = {("effect_ir.py", "play_token"), ("resolution_bridge.py", "complete_permanent_play")}
ON_BOARD_ALREADY = {("effect_ir.py", "_place_on_board"), ("effect_ir.py", "move_board_object"),
                    ("effect_ir.py", "recall"), ("effect_ir.py", "channel_rune")}
BRANCH = re.compile(r'^\s*(?:el)?if op == "([a-z_]+)"|^def ([a-z_]+)\(')


def sites(name: str) -> list[tuple[str, int]]:
    """(the op branch or function each append sits in, its line) for one file."""
    out, where = [], None
    for number, line in enumerate((HERE / name).read_text(encoding="utf-8").splitlines(), 1):
        found = BRANCH.match(line)
        if found:
            where = found.group(1) or found.group(2)
        if APPEND.search(line) and ('["battlefields"]' in line or '["zones"]["base"]' in line):
            out.append((where, number))
    return out


def main() -> int:
    errors: list[str] = []
    known = ENTERS | ON_BOARD_ALREADY
    seen = set()
    for name in ("effect_ir.py", "resolution_bridge.py"):
        for where, number in sites(name):
            seen.add((name, where))
            if (name, where) not in known:
                errors.append(f"P1: {name}:{number} adds an object to a board location in {where!r}, which is not "
                              f"classified - an entry path must decide whether 'enter ready' reaches it")
    for missing in sorted(known - seen):
        errors.append(f"P1: the classified site {missing} no longer adds to a board location - update the gate")
    source = {n: (HERE / n).read_text(encoding="utf-8") for n in ("effect_ir.py", "resolution_bridge.py")}
    for name, where in sorted(ENTERS):
        text = source[name]
        start = text.find(f'op == "{where}"') if name == "effect_ir.py" else text.find(f"def {where}(")
        body = text[start:start + 12000]
        if name == "resolution_bridge.py":
            # the card's play reads it through entry_state_for (the entry state of a permanent being played)
            helper = text.find("def entry_state_for(")
            body = (body if "entry_state_for(" in body else "") + text[helper:helper + 6000]
        if start < 0 or "entry_state_for_played_units" not in body:
            errors.append(f"P2: the entry path {where!r} ({name}) does not read entry_state_for_played_units")
    if errors:
        print("FAILED: entry paths")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: the two paths that bring a Unit onto the board (a card played, a token played) both read the entry-state "
          "turn effects; every other board placement moves or attaches what is already there, or adds a rune (P1, P2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
