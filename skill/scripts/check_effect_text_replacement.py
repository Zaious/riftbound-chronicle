#!/usr/bin/env python3
"""Regression gate: an Effect Text's Replacement Effect about its Top-Most card (set 2 package A2: Guardian Angel
[Effect Text], "If I would die, kill Guardian Angel instead. Heal me, exhaust me, and recall me."). Attached, the death
of the host is replaced (Core 370.1.b): the Equipment is killed instead, the host healed, exhausted and recalled to its
owner's Base; detached, the replacement is gone.

  R1  ga attached to u1 (damaged, at bf1): u1 killed -> u1 in p1's Base, no damage, exhausted; ga in p1's trash
  R2  another friendly unit u3 killed: it dies (the replacement is about the host only)
  R3  ga detached first: u1 killed -> u1 in p1's trash
  R4  attached then detached: no replacement of the attach is left in the state
  R5  after R1 (ga in the trash): no replacement left, and u1 killed again dies
  R6  two Guardian Angels by the same name, ga1 on u1 and ga2 on u3: u1 killed -> ga1 killed (not ga2), u1 healed,
      exhausted, recalled; ga2 still attached to u3 on the board. "Guardian Angel" names the Equipment that appended
      the Effect Text (Core 136.2.d), bound to that object, never any card of that name
  R7  the same two, ga1 detached from u1 first: u1 killed dies (no replacement); ga1 untouched (on the board,
      unattached); ga2 still attached to u3
  V  a bundle replacement naming its own source, or of another event, does not validate
  G   the printed form lowers to that bundle
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402

TEXT = "If I would die, kill Guardian Angel instead. Heal me, exhaust me, and recall me."


def bundle():
    got = CG.compile_clause(TEXT, CG.load_grammar())
    return ((got.get("passive") or {}).get("object_fields") or {}).get("effect_text")


def run(state, *effects, controller="p1"):
    done = IR.apply_program(state, {"schema_version": IR.PROGRAM_VERSION,
                                    "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
                                    "program_id": "x", "controller": controller, "effects": list(effects)})
    if not done.get("committed"):
        raise SystemExit(f"a program did not commit: {done.get('reason') or done.get('errors')}")
    return done["next_state"]


def scene(attached=True):
    s = base_state()
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["battlefields"]["bf1"]["objects"].append("u1")
    s["battlefields"]["bf1"]["controller"] = "p1"
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["objects"]["ga"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Equipment"], "effect_text": copy.deepcopy(bundle())}
    s["players"]["p1"]["zones"]["base"] += ["u3", "ga"]
    s = settle_contested(s)
    if attached:
        s = run(s, {"op": "attach", "effect_id": "at", "object_id": "ga", "to": "u1"})
    return s


def two_angels():
    """ga (ga1) attached to u1 at bf1, a second Guardian Angel ga2 attached to u3 in p1's Base; both named alike."""
    s = scene(attached=False)
    s["objects"]["ga2"] = copy.deepcopy(s["objects"]["ga"])
    s["players"]["p1"]["zones"]["base"].append("ga2")
    for oid in ("ga", "ga2"):
        s["objects"][oid]["name"] = "Guardian Angel"
    return run(s, {"op": "attach", "effect_id": "at1", "object_id": "ga", "to": "u1"},
               {"op": "attach", "effect_id": "at2", "object_id": "ga2", "to": "u3"})


def on_board(state, oid):
    return (IR.find_location(state, oid) or (None,))[0] == "battlefield" \
        or IR.find_location(state, oid) == ("player", state["objects"].get(oid, {}).get("owner"), "base")


def main() -> int:
    errors: list[str] = []
    s = scene()
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    after = run(s, {"op": "kill", "effect_id": "k", "object_id": "u1"}, controller="p2")
    u1 = after["objects"]["u1"]
    if IR.find_location(after, "u1") != ("player", "p1", "base") or u1.get("damage") or not u1.get("exhausted") \
            or "ga" not in after["players"]["p1"]["zones"]["trash"]:
        errors.append(f"R1: u1 {IR.find_location(after, 'u1')} damage {u1.get('damage')} exhausted {u1.get('exhausted')}; "
                      f"ga {IR.find_location(after, 'ga')}")
    again = run(after, {"op": "kill", "effect_id": "k2", "object_id": "u1"}, controller="p2")
    if after.get("replacement_effects") or "u1" not in again["players"]["p1"]["zones"]["trash"]:
        errors.append(f"R5: left {after.get('replacement_effects')}; u1 then at {IR.find_location(again, 'u1')}")
    other = run(s, {"op": "kill", "effect_id": "k", "object_id": "u3"}, controller="p2")
    if "u3" not in other["players"]["p1"]["zones"]["trash"] or "ga" in other["players"]["p1"]["zones"]["trash"]:
        errors.append(f"R2: u3 {IR.find_location(other, 'u3')}, ga {IR.find_location(other, 'ga')}")
    off = run(s, {"op": "detach", "effect_id": "dt", "object_id": "ga"})
    if any(str(r.get("replacement_id", "")).startswith("effect_text:ga:") for r in off.get("replacement_effects") or []):
        errors.append("R4: a replacement of the attach is left after the detach")
    dead = run(off, {"op": "kill", "effect_id": "k", "object_id": "u1"}, controller="p2")
    if "u1" not in dead["players"]["p1"]["zones"]["trash"]:
        errors.append(f"R3: detached, u1 is at {IR.find_location(dead, 'u1')}")
    two = two_angels()
    if IR.validate_state(two):
        errors.append(f"R6 board: {IR.validate_state(two)[:2]}")
    saved = run(two, {"op": "kill", "effect_id": "k", "object_id": "u1"}, controller="p2")
    u1, ga2 = saved["objects"]["u1"], saved["objects"].get("ga2") or {}
    trash = saved["players"]["p1"]["zones"]["trash"]
    if IR.find_location(saved, "u1") != ("player", "p1", "base") or u1.get("damage") or not u1.get("exhausted") \
            or "ga" not in trash or "ga2" in trash or not on_board(saved, "ga2") or ga2.get("attached_to") != "u3" \
            or "u3" in trash:
        errors.append(f"R6: u1 {IR.find_location(saved, 'u1')} damage {u1.get('damage')} exhausted {u1.get('exhausted')}; "
                      f"ga1 {IR.find_location(saved, 'ga')}; ga2 {IR.find_location(saved, 'ga2')} "
                      f"attached_to {ga2.get('attached_to')}")
    loose = run(two, {"op": "detach", "effect_id": "dt", "object_id": "ga"})
    died = run(loose, {"op": "kill", "effect_id": "k", "object_id": "u1"}, controller="p2")
    ga1, ga2 = died["objects"].get("ga") or {}, died["objects"].get("ga2") or {}
    trash = died["players"]["p1"]["zones"]["trash"]
    if "u1" not in trash or "ga" in trash or not on_board(died, "ga") or ga1.get("attached_to") is not None \
            or "ga2" in trash or ga2.get("attached_to") != "u3":
        errors.append(f"R7: u1 {IR.find_location(died, 'u1')}; ga1 {IR.find_location(died, 'ga')} "
                      f"attached_to {ga1.get('attached_to')}; ga2 {IR.find_location(died, 'ga2')} "
                      f"attached_to {ga2.get('attached_to')}")
    for label, bad in (("naming its own source", {**bundle()["replacements"][0], "source_object": "ga"}),
                       ("of another event", {**bundle()["replacements"][0], "event_op": "deal_damage"})):
        b = copy.deepcopy(s)
        b["objects"]["ga"]["effect_text"] = {"replacements": [bad]}
        if not any("effect_text" in p for p in IR.validate_state(b)):
            errors.append(f"V: a bundle replacement {label} validated")
    if not (bundle() or {}).get("replacements"):
        errors.append(f"G: lowered to {bundle()}")
    if errors:
        print("effect text replacement checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("effect text replacement checks passed: attached, the host's death is replaced - the Equipment killed, the host "
          "healed, exhausted and recalled; another unit dies; detached, gone; with two of the same name each kills only "
          "itself; validated; lowered (R1-R7, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
