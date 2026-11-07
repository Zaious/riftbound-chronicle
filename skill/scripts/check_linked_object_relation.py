#!/usr/bin/env python3
"""Regression gate: a later instruction conditioned on whether the object an earlier one acted on was an enemy's or a
friendly one (set 2 package A2: Blood Money, "Kill a unit at a battlefield with 2 [M] or less. If it was an enemy unit,
play a Gold gear token exhausted. If it was a friendly unit, play two Gold gear tokens exhausted.").

The predicate linked_object_relation names the earlier instruction and enemy or friendly; it reads the one object that
instruction acted on, controlled by whom when that instruction found it (Core 359.3.e.14) - not after it, when a killed
unit is its owner's again in the trash.

  L1 enemy      p2's unit killed: the enemy branch plays one token, the friendly branch is skipped
  L2 friendly   p1's unit killed: two tokens, the enemy branch skipped
  L3 borrowed   a unit p2 owns but p1 controls killed: friendly (its controller as the kill found it)
  L4 nothing    the chosen unit left and came back (a new object, Core 124): the kill is ignored, neither runs
  L5 replaced   p2's unit with a death replacement (Zhonya-like gear z2: kill z2 instead, exhaust and recall the unit):
                the replacement applies and the unit does not die. The kill is Negated, not Ignored (Core 359.3.e.14.b:
                an instruction whose event is replaced is Negated), and a Negated earlier instruction does not stop a
                later linked one unless it references the game action itself - "if it was an enemy unit" reads the
                unit, not the kill (Hidden Blade's own example: "Its controller draws 2" still happens). So "it" is u2,
                p2's as the kill found it: the enemy branch runs (one token), the friendly branch does not (GPT A2
                ruling 20 asked for this case as evidence; this expectation is Core 359.3.e.14.b's, for its review)
  V  validation the predicate's closed shape; a later instruction named is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def gold(oid, relation):
    return {"op": "play_token", "effect_id": f"g-{oid}", "object_id": oid, "owner": "p1", "controller": "p1",
            "token_kind": "gear", "base_might": 0, "destination": {"kind": "base", "player": "p1"},
            "event_modifiers": {"entry_state": "exhausted"},
            "predicate": {"kind": "linked_object_relation", "effect_id": "k", "relation": relation}}


def program(victim):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "blood-money", "controller": "p1", "source_object": "c1",
            "effects": [{"op": "kill", "effect_id": "k", "target": {"object_id": victim, "chosen_zone_class": "board",
                                                                    "kind": "unit", "bound_identity": f"{victim}@0"}},
                        gold("gold-e", "enemy"),
                        gold("gold-f1", "friendly"), gold("gold-f2", "friendly")]}


def board(borrowed=False):
    s = base_state()
    for oid, owner in (("u1", "p1"), ("u2", "p2")):
        s["players"][owner]["zones"]["base"].remove(oid)
        s["battlefields"]["bf1"]["objects"].append(oid)
    s["battlefields"]["bf1"]["controller"] = "p1"
    if borrowed:
        s["objects"]["u2"]["controller"] = "p1"
    s["battlefields"]["bf1"]["objects"] = ["u1"] + (["u2"] if borrowed else [])
    if not borrowed:
        s["players"]["p2"]["zones"]["base"].append("u2")
    return s


def gone():
    s = board()
    s["objects"]["u2"]["identity"] = "u2@1"
    return s


def replaced():
    """p2's u2 carries a death replacement from p2's gear z2: if u2 would die, kill z2 instead, exhaust and recall u2."""
    s = board()
    s["objects"]["z2"] = {"owner": "p2", "controller": "p2", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p2"]["zones"]["base"].append("z2")
    s["replacement_effects"] = [{"replacement_id": "zhonya-z2", "controller": "p2", "source_object": "z2",
                                 "mode": "replace_with", "event_op": "kill", "optional": False, "uses_remaining": None,
                                 "target_object_id": "u2",
                                 "replacement_effects": [{"op": "kill", "effect_id": "kill-z2", "object_id": "z2"},
                                                         {"op": "exhaust", "effect_id": "ex", "object_id": "$affected"},
                                                         {"op": "recall", "effect_id": "rc", "object_id": "$affected"}]}]
    return s


def tokens(done):
    return sorted(o for o in (done.get("next_state") or {}).get("objects", {}) if o.startswith("gold-"))


def main() -> int:
    errors: list[str] = []
    for label, s, victim, want in (("L1 enemy", board(), "u2", ["gold-e"]),
                                   ("L2 friendly", board(), "u1", ["gold-f1", "gold-f2"]),
                                   ("L3 borrowed", board(borrowed=True), "u2", ["gold-f1", "gold-f2"]),
                                   ("L4 nothing", gone(), "u2", [])):
        if validate_program(program(victim)):
            errors.append(f"{label}: invalid {validate_program(program(victim))}")
            continue
        done = apply_program(s, program(victim))
        if not done.get("committed") or tokens(done) != want:
            errors.append(f"{label}: {done.get('reason') or done.get('errors')} "
                          f"{[(t.get('effect_id'), t.get('outcome')) for t in done.get('trace') or []]} tokens {tokens(done)}")
    # L5: the death replaced - first confirm the replacement really applied (u2 recalled, z2 in the trash), then that the
    # enemy branch ran on the unit the Negated kill acted on (Core 359.3.e.14.b)
    s = replaced()
    done = apply_program(s, program("u2"))
    after = done.get("next_state") or {}
    zones = (after.get("players") or {}).get("p2", {}).get("zones", {})
    if not done.get("committed") or "u2" not in zones.get("base", []) or "z2" not in zones.get("trash", []):
        errors.append(f"L5 replaced: the replacement did not apply as set up: {done.get('reason') or done.get('errors')} "
                      f"p2 zones {zones}")
    elif tokens(done) != ["gold-e"]:
        kill = next((t for t in done.get("trace") or [] if t.get("effect_id") == "k"), {})
        errors.append(f"L5 replaced: the kill was replaced (outcome {kill.get('outcome')!r}); the enemy branch alone should "
                      f"run on u2 (Core 359.3.e.14.b), but the tokens are {tokens(done)}")
    bad = program("u2")
    for label, predicate in (("an unknown relation", {"kind": "linked_object_relation", "effect_id": "k", "relation": "ally"}),
                             ("an extra key", {"kind": "linked_object_relation", "effect_id": "k", "relation": "enemy", "x": 1}),
                             ("a later instruction", {"kind": "linked_object_relation", "effect_id": "g-gold-f2",
                                                      "relation": "enemy"})):
        prog = copy.deepcopy(bad)
        prog["effects"][1]["predicate"] = predicate
        if not validate_program(prog):
            errors.append(f"V: {label} was accepted")
    if errors:
        print("linked-object relation checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("linked-object relation checks passed: 'if it was an enemy / friendly unit' reads the killed unit's controller "
          "as the kill found it - enemy one token, friendly two, a borrowed unit friendly, nothing killed neither, "
          "a replaced (Negated) death still the enemy branch on the unit it acted on (L1-L5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
