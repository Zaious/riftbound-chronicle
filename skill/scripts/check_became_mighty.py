#!/usr/bin/env python3
"""Regression gate: "When a unit you control becomes [Mighty]" (set 2 package A2: Fiora - Worthy, Fiora - Grand Duelist).

Core 709: the event is a crossing - a Unit below 5 Might that reaches 5 or more; Core 710: a Unit on the board is read at
its current Might.

  M1  with the watcher on the board, the first batch records the board and wakes nothing; a program giving p1's 4-Might
      unit +1 wakes the watcher once, about that unit; the next batch, the unit still 5, wakes nothing; down to 4 and up
      to 5 again wakes it again
  M2  a unit that arrives on the board at 5 Might wakes nothing (it did not change from less than 5); p2's unit
      becoming Mighty wakes nothing (not one p1 controls); two of p1's at once wake it twice
  M5  (GPT A2 ruling 2) a unit printed at 4 that arrives on the board already at 5 (a continuous effect on it as it
      arrives) is a named boundary: the batch is refused unsupported (became_mighty_on_entry_boundary), never answered
      either way; printed at 5 or more it wakes nothing (M2)
  M3  with no watcher listening the ledger is dropped and nothing is computed; a watcher in the hand does not listen
  M4  both printed forms lower to the watch; the ledger is validated
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import watchers as W  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import validate_state  # noqa: E402

TEXTS = ("When a unit you control becomes [Mighty], draw 1.", "When one of your units becomes [Mighty], draw 1.")


def unit(owner, might):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(trigger):
    state = base_state()
    state["objects"]["fw"] = {**unit("p1", 3), "event_triggers": [{**copy.deepcopy(trigger), "controller": "p1",
                                                                   "source_object": "fw", "effect_program_id": "fw-1"}]}
    state["players"]["p1"]["zones"]["base"].append("fw")
    for oid, owner, might in (("a4", "p1", 4), ("b4", "p1", 4), ("e4", "p2", 4)):
        state["objects"][oid] = unit(owner, might)
        state["players"][owner]["zones"]["base"].append(oid)
    return state


def give(state, targets, amount, controller="p1"):
    """A real one-program Might modifier (Core 478), as the resolution bridge would resolve it."""
    program = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
               "program_id": "give", "controller": controller,
               "effects": [{"op": "modify_might", "effect_id": f"m{i}", "amount": amount, "duration": "this_turn",
                            "source": "fw", "target": {"object_id": t, "kind": "unit", "chosen_zone_class": "board",
                                       "bound_identity": IR.object_identity(state, t) or f"{t}@0"}}
                           for i, t in enumerate(targets)]}
    done = IR.apply_program(state, program)
    if not done.get("committed"):
        raise SystemExit(f"the Might program was refused: {done.get('reason_code')} {done.get('errors')}")
    return done["next_state"]


def batch(state, label):
    woken, counted = W.schedule_live(state, [], turn_id=state.get("turn_id", "turn-0"), batch_label=label)
    return [w["watched_object"] for w in woken if w.get("watched_kind") == "became_mighty"], counted


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    lowered = []
    for text in TEXTS:
        got = CG.compile_clause(text, grammar)
        triggers = ((got.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or []
        if got.get("production_id") != "when_a_unit_you_control_becomes_mighty" or len(triggers) != 1:
            errors.append(f"M4: {text!r} lowered to {got.get('production_id')}")
            continue
        lowered.append(triggers[0])
    if not lowered:
        errors.append("M4: nothing lowered")
    else:
        trigger = lowered[0]
        if trigger["watch"] != {"kinds": ["became_mighty"], "scope": "controller", "filter": {"object_kind": "unit"},
                                "grouping": "each"}:
            errors.append(f"M4: the watch is {trigger['watch']}")
        state = board(trigger)
        if [e for e in validate_state(state) if "event_triggers" in e]:
            errors.append(f"M4: the watch was refused on an object: {validate_state(state)[:1]}")
        # M1
        woke, state = batch(state, "b0")
        if woke or state.get(W.MIGHTY_LEDGER, {}).get("a4@0") is not False:
            errors.append(f"M1: the first batch woke {woke}, ledger {state.get(W.MIGHTY_LEDGER)}")
        if validate_state(state):
            errors.append(f"M1: the recorded ledger is invalid: {validate_state(state)[:2]}")
        state = give(state, ["a4"], 1)
        woke, state = batch(state, "b1")
        if woke != ["a4"]:
            errors.append(f"M1: +1 to the 4-Might unit woke {woke}")
        woke, state = batch(state, "b2")
        if woke:
            errors.append(f"M1: the unit still at 5 woke {woke} again")
        state = give(state, ["a4"], -1)
        woke, state = batch(state, "b3")
        state = give(state, ["a4"], 1)
        woke2, state = batch(state, "b4")
        if woke or woke2 != ["a4"]:
            errors.append(f"M1: down to 4 woke {woke}, up to 5 again woke {woke2}")
        # M2
        state["objects"]["big"] = unit("p1", 6)
        state["players"]["p1"]["zones"]["base"].append("big")
        woke, state = batch(state, "b5")
        if woke:
            errors.append(f"M2: a unit arriving at 6 Might woke {woke}")
        state = give(state, ["e4"], 1, controller="p2")
        woke, state = batch(state, "b6")
        if woke:
            errors.append(f"M2: p2's unit becoming Mighty woke {woke}")
        fresh = board(trigger)
        _w, fresh = batch(fresh, "c0")
        fresh = give(fresh, ["a4", "b4"], 1)
        woke, fresh = batch(fresh, "c1")
        if sorted(woke) != ["a4", "b4"]:
            errors.append(f"M2: two units becoming Mighty together woke {woke}")
        # M5
        lifted = copy.deepcopy(state)
        lifted["objects"]["n4"] = unit("p1", 4)
        lifted["players"]["p1"]["zones"]["base"].append("n4")
        lifted = give(lifted, ["n4"], 1)
        try:
            woke, _ = batch(lifted, "b7")
            errors.append(f"M5: a unit printed 4 arriving at 5 was answered: woke {woke}")
        except W.WatchUnsupported as exc:
            if exc.reason_code != "became_mighty_on_entry_boundary":
                errors.append(f"M5: refused as {exc.reason_code}")
        # M3
        quiet = copy.deepcopy(state)
        quiet["players"]["p1"]["zones"]["base"].remove("fw")
        quiet["players"]["p1"]["zones"]["hand"].append("fw")
        woke, quiet = batch(quiet, "d0")
        if woke or W.MIGHTY_LEDGER in quiet:
            errors.append(f"M3: with the watcher in the hand: woke {woke}, ledger kept {W.MIGHTY_LEDGER in quiet}")
        plain = base_state()
        _w, plain_after = batch(plain, "d1")
        if W.MIGHTY_LEDGER in plain_after:
            errors.append("M3: a board with no watcher got a ledger")
        bad = copy.deepcopy(state)
        bad[W.MIGHTY_LEDGER] = {"a4@0": 1}
        if not any("mighty_observed" in e for e in validate_state(bad)):
            errors.append("M4: a ledger naming no true / false was accepted")
    if errors:
        print("became-Mighty checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("became-Mighty checks passed: a board unit going from less than 5 to 5 or more wakes the watcher once, each "
          "time; one arriving at 5, the opponent's, and one still Mighty do not; no ledger without a listener; both "
          "printed forms lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
