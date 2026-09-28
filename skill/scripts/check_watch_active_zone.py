#!/usr/bin/env python3
"""
Regression gate (GPT 2026-09-27, group 乙): a watcher listens where its card's text makes it work.

"A watcher listens only while its source is on the board" may not be applied to an ability whose
text works from the trash (Immortal Phoenix: "When you kill a unit with a spell, you may pay ... to
play me from your trash"). Must hold, through watchers.schedule_live and the resolution bridge:
  - a descriptor with active_zone "trash" wakes while its source is in its owner's trash, and not
    while it is on the board;
  - without active_zone, a source in the trash does not wake (the board / Legend Zone rule stands);
  - a source that enters the trash in the same event that meets the condition wakes (Core
    383.2.c.1: Immortal Phoenix triggers even when the unit the spell killed was that Phoenix);
  - an unknown active_zone is refused by the state validator.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

DIED = {"kinds": ["died"], "scope": "any"}


def descriptor(trigger_id, source, **extra):
    return {"trigger_id": trigger_id, "controller": "p1", "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": True, "watch": copy.deepcopy(DIED), **extra}


def board(*, phoenix_in, active_zone="trash"):
    """p2's unit v1 at p1's Base... the victim; p1's phoenix `ph` in the trash or at its Base."""
    state = base_state()
    state["objects"]["v1"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 1, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p2"]["zones"]["base"].append("v1")
    extra = {"active_zone": active_zone} if active_zone else {}
    state["objects"]["ph"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "event_triggers": [descriptor("ph-watch", "ph", **extra)]}
    state["players"]["p1"]["zones"][phoenix_in].append("ph")
    return state


def kill(state, target):
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "spell-1", state, {**program("kill", {"op": "kill", "effect_id": "k", "object_id": target}),
                                                            "controller": "p1"})


def woke(result):
    items = (result.get("next_timing_state") or {}).get("chain", {}).get("items", [])
    return [i["id"].split("@")[0] for i in items]


def main() -> int:
    errors: list[str] = []
    for label, state in (("in the trash", board(phoenix_in="trash")), ("on the board", board(phoenix_in="base")),
                         ("in the trash, no active_zone", board(phoenix_in="trash", active_zone=None))):
        if found := validate_state(state):
            errors.append(f"{label}: the fixture is invalid: {found[:2]}")
    if errors:
        print("FAILED:\n" + "\n".join("  - " + e for e in errors))
        return 1
    done = kill(board(phoenix_in="trash"), "v1")
    if not done.get("committed") or woke(done) != ["ph-watch"]:
        errors.append(f"an active_zone 'trash' watcher in the trash did not wake on a death: {woke(done)} {done.get('reason')}")
    done = kill(board(phoenix_in="base"), "v1")
    if not done.get("committed") or woke(done):
        errors.append(f"an active_zone 'trash' watcher on the board woke: {woke(done)}")
    done = kill(board(phoenix_in="trash", active_zone=None), "v1")
    if not done.get("committed") or woke(done):
        errors.append(f"a watcher with no active_zone woke from the trash: {woke(done)}")
    # Core 383.2.c.1: the source enters the trash in the very event that meets the condition
    done = kill(board(phoenix_in="base"), "ph")
    if not done.get("committed") or woke(done) != ["ph-watch"]:
        errors.append(f"a trash watcher whose source died in the same event did not wake (383.2.c.1): {woke(done)} {done.get('reason')}")
    bad = board(phoenix_in="trash")
    bad["objects"]["ph"]["event_triggers"][0]["active_zone"] = "hand"
    if not validate_state(bad):
        errors.append("an active_zone outside the known zones was accepted")
    if errors:
        print("FAILED: watcher active zone")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: an active_zone 'trash' watcher wakes from its owner's trash and not from the board, a source "
          "entering the trash in the same event wakes (383.2.c.1), no active_zone keeps the board rule, "
          "and an unknown zone is refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
