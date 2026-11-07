#!/usr/bin/env python3
"""Regression gate: two set-2 play watches (set 2 package A2).

  W1  "When you play a spell on an opponent's turn": a spell played by the controller on the opponent's turn matches;
      the same spell on the controller's own turn, and a unit on the opponent's turn, do not
  W2  "When you play a card with Power cost [A][A] or more": printed Power of two Domains, or two of one, matches; one
      does not; a card with no printed cost is refused by name (Core 206: the printed cost is compared)
  W3  the grammar lowers both printed forms to those watches; the validator accepts them on an object
  W4  "When you attach an Equipment to me": an attach to the source of an object tagged Equipment matches; to another
      host, or of an untagged object, does not; an object with no observed tags is refused by name
  W5  "When you recycle a rune" filters a rune; "When you spend a buff", "When one or more enemy units die" lower to
      their watches (buff_spent by the actor; died, enemy units, one per batch)

Synthetic events and objects only.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import watchers as W  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import validate_state  # noqa: E402


def holds(event_filter, event, state):
    return W._filter_holds(state, event_filter, event, source_object="src", controller="p1")


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    lowered = {}
    for key, text in (("opp", "When you play a spell on an opponent's turn, draw 1."),
                      ("power", "When you play a card with Power cost :rb_rune_rainbow::rb_rune_rainbow: or more, draw 1.")):
        got = CG.compile_clause(text, grammar)
        triggers = ((got.get("passive") or got).get("object_fields") or {}).get("event_triggers") or []
        if len(triggers) != 1:
            errors.append(f"W3: {text!r} lowered to {got.get('production_id')} with {len(triggers)} triggers")
            continue
        lowered[key] = triggers[0]
    if lowered.get("opp", {}).get("watch", {}).get("filter") != {"object_kind": "spell", "on_opponents_turn": True}:
        errors.append(f"W3: the opponent's-turn spell watch filters {lowered.get('opp', {}).get('watch')}")
    if lowered.get("power", {}).get("watch", {}).get("filter") != {"printed_power_at_least": 2}:
        errors.append(f"W3: the Power-cost watch filters {lowered.get('power', {}).get('watch')}")
    state = base_state()
    for oid, kind, power in (("s1", "spell", {}), ("u9", "unit", {}), ("two", "unit", {"fury": 1, "calm": 1}),
                             ("pair", "spell", {"mind": 2}), ("one", "spell", {"mind": 1})):
        state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": 2 if kind == "unit" else 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": False,
                                 "printed_cost": {"energy": 1, "power": power}}
        state["players"]["p1"]["zones"]["trash"].append(oid)
    state["objects"]["bare"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["trash"].append("bare")
    opp = {"object_kind": "spell", "on_opponents_turn": True}
    played = lambda o, turn: {"kind": "played", "object": o, "actor": "p1", "turn_player": turn}
    for label, event, want in (("p1's spell on p2's turn", played("s1", "p2"), True),
                               ("p1's spell on its own turn", played("s1", "p1"), False),
                               ("p1's unit on p2's turn", played("u9", "p2"), False)):
        if holds(opp, event, state) != want:
            errors.append(f"W1: {label} matched {not want}")
    power = {"printed_power_at_least": 2}
    for label, o, want in (("two Domains", "two", True), ("two of one", "pair", True), ("one", "one", False)):
        if holds(power, played(o, "p1"), state) != want:
            errors.append(f"W2: printed Power {label} matched {not want}")
    try:
        holds(power, played("bare", "p1"), state)
        errors.append("W2: a card with no printed cost was compared")
    except W.WatchUnsupported:
        pass
    for key in ("opp", "power"):
        if key not in lowered:
            continue
        s = base_state()
        s["objects"]["u1"]["event_triggers"] = [{**lowered[key], "controller": "p1", "source_object": "u1",
                                                 "effect_program_id": "p"}]
        problems = [e for e in validate_state(s) if "event_triggers" in e]
        if problems:
            errors.append(f"W3: the {key} watch was refused on an object: {problems[:1]}")
    for oid, tags in (("eq", ["Equipment"]), ("plain-gear", []), ("untagged-gear", None)):
        state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": False,
                                 **({"tags": tags} if tags is not None else {})}
        state["players"]["p1"]["zones"]["base"].append(oid)
    attach = {"attached_to_source": True, "object_tagged": "Equipment"}
    for label, event, want in (("an Equipment to the source", {"kind": "attached", "object": "eq", "to": "src"}, True),
                               ("an Equipment to another unit", {"kind": "attached", "object": "eq", "to": "u3"}, False),
                               ("an untagged gear to the source",
                                {"kind": "attached", "object": "plain-gear", "to": "src"}, False)):
        if holds(attach, event, state) != want:
            errors.append(f"W4: {label} matched {not want}")
    try:
        holds(attach, {"kind": "attached", "object": "untagged-gear", "to": "src"}, state)
        errors.append("W4: an object with no observed tags was compared")
    except W.WatchUnsupported:
        pass
    state["objects"]["rn"] = {"owner": "p1", "controller": "p1", "kind": "rune", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("rn")
    rune = {"object_kind": "rune"}
    if not holds(rune, {"kind": "recycled", "object": "rn"}, state) or holds(rune, {"kind": "recycled", "object": "s1"}, state):
        errors.append("W5: a recycled rune is not told from a recycled spell")
    for text, want in (("When you attach an Equipment to me, draw 1.",
                        {"kinds": ["attached"], "scope": "actor", "filter": attach}),
                       ("When you spend a buff, draw 1.", {"kinds": ["buff_spent"], "scope": "actor", "grouping": "each"}),
                       ("When you recycle a rune, draw 1.",
                        {"kinds": ["recycled"], "scope": "actor", "filter": rune, "grouping": "each"}),
                       ("When one or more enemy units die, draw 1.",
                        {"kinds": ["died"], "scope": "any",
                         "filter": {"object_kind": "unit", "object_controller_relation": "enemy"},
                         "grouping": "one_or_more"})):
        got = CG.compile_clause(text, grammar)
        watch = ((((got.get("passive") or got).get("object_fields") or {}).get("event_triggers") or [{}])[0]).get("watch")
        if watch != want:
            errors.append(f"W5: {text!r} lowered to {watch}")
    if errors:
        print("set 2 play watch checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("set 2 play watch checks passed: a spell on an opponent's turn (not on one's own, not a unit); a card with "
          "printed Power cost N or more of any Domains (one fewer not; none printed refused); both lowered and valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
