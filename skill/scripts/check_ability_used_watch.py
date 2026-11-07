#!/usr/bin/env python3
"""Regression gate: "When you use an activated ability of a gear" (set 2 package A2: Prize of Progress). Core 377.2: to
use an activated ability is to play it; the use is recorded as the ability is finalized and wakes its watchers when the
ability resolves (read by analogy with a card's play, Core 420.4.a).

  U1  p1 activates its gear's ability and it resolves: the watcher wakes, about the gear; activated but not yet
      resolved, nothing woke
  U2  p1's unit's ability resolving wakes nothing (not a gear); a gear whose ability kills it as its cost still wakes it
      (the use is about the gear as it was)
  U3  the printed form lowers to the watch; another player's use does not match (scope actor)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import watchers as W  # noqa: E402
from check_effect_ir import program  # noqa: E402
from check_play_transaction import effect_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, finalize_oldest_pending  # noqa: E402

TEXT = "When you use an activated ability of a gear, draw 1."


def board(watch):
    state = effect_state(energy=0, power={}, hand=())
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["objects"]["pp"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False,
                              "event_triggers": [{**copy.deepcopy(watch), "controller": "p1", "source_object": "pp",
                                                  "effect_program_id": "pp-1"}]}
    state["players"]["p1"]["zones"]["base"] += ["g1", "pp"]
    return state


def activate(state, source, *, kill_cost=False):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"use-{source}", "actor": "p1", "card": source,
            "chain_item": {"id": "ability-1", "object_kind": "ability", "timing": "default"},
            "activation": {"source_object": source, "ability_id": f"{source}:a1"},
            "cost": {"base": {"energy": 0, "power": {}},
                     **({"additional": [{"cost_id": "self", "mandatory": True, "payment": {"kind": "kill_this"}}]}
                        if kill_cost else {})},
            "effect_program_id": f"{source}:a1"}
    body = program(f"{source}:a1", {"op": "draw", "effect_id": "d", "player": "p1", "count": 1})
    body["controller"] = "p1"
    played = play_card(fixture(), state, decl, effect_program=body)
    if not played.get("committed"):
        return played, None
    fin = finalize_oldest_pending(played["next_timing_state"])["next_state"]
    fin["chain"]["consecutive_passes"] = ["p1", "p2"]
    return played, resolve_with_program(fin, "ability-1", played["next_effect_state"], body)


def woke(result):
    items = (result or {}).get("next_timing_state", {}).get("chain", {}).get("items", [])
    return [i["trigger_event"]["object"] for i in items if (i.get("trigger_event") or {}).get("kind") == "ability_used"]


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    triggers = ((got.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or []
    if got.get("production_id") != "when_you_use_an_activated_ability_of_a_gear" or len(triggers) != 1 \
            or triggers[0]["watch"] != {"kinds": ["ability_used"], "scope": "actor", "filter": {"object_kind": "gear"}}:
        errors.append(f"U3: lowered to {got.get('production_id')} {triggers}")
    else:
        watch = triggers[0]
        state = board(watch)
        if validate_state(state):
            errors.append(f"fixture invalid: {validate_state(state)[:2]}")
        played, resolved = activate(board(watch), "g1")
        if resolved is None or not resolved.get("committed"):
            errors.append(f"U1: the gear's ability did not resolve: {(resolved or played).get('reason')}")
        else:
            if woke(played):
                errors.append(f"U1: the use woke {woke(played)} at Finalize, before the ability resolved")
            if woke(resolved) != ["g1"]:
                errors.append(f"U1: the gear's ability resolving woke {woke(resolved)}")
        _p, unit_use = activate(board(watch), "u1")
        if unit_use is None or not unit_use.get("committed") or woke(unit_use):
            errors.append(f"U2: a unit's ability woke {woke(unit_use)} ({(unit_use or {}).get('reason')})")
        _p, killed = activate(board(watch), "g1", kill_cost=True)
        if killed is None or not killed.get("committed") or woke(killed) != ["g1"]:
            errors.append(f"U2: a gear killed as its ability's cost woke {woke(killed)} ({(killed or _p).get('reason')})")
        theirs = {"kind": "ability_used", "object": "g9", "actor": "p2", "controller": "p2", "object_kind": "gear"}
        if W.watch_matches(state, watch["watch"], theirs, source_object="pp", controller="p1"):
            errors.append("U3: p2's use matched p1's watcher")
    if errors:
        print("ability-used watch checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("ability-used watch checks passed: a gear's activated ability wakes the watcher when it resolves, not at "
          "Finalize; a unit's does not; a gear killed as the cost still does; another player's use does not match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
