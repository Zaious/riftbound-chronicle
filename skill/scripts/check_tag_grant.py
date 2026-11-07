#!/usr/bin/env python3
"""Regression gate: "I am a Mech." (set 2 package A2: Experimental Hexplate [Effect Text]; Core 133.8, 435.1.c).

  G1  a Unit observed with its printed tags and granted_tags ["Mech"] reads both; one whose printed tags were never
      observed stays unknown (None), never guessed
  G2  an Equipment whose Effect Text is a tag_grant, attached for real to p1's unit, gives that unit the tag; detached,
      the unit has its printed tags only; "Your Mechs have [Shield]." then reaches it while attached, not after
  G3  the printed form lowers to granted_tags; a tag_grant without a tag is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, has_keyword, object_tags, validate_state  # noqa: E402


def scene():
    state = base_state()
    state["objects"]["host"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                                "damage": 0, "exhausted": False, "tags": ["Recruit"]}
    state["objects"]["plate"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False, "tags": ["Equipment"],
                                 "effect_text": {"effects": [{"kind": "tag_grant", "value": {"tag": "Mech"}}]}}
    state["objects"]["boss"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                                "damage": 0, "exhausted": False, "tags": [],
                                "static_auras": [{"aura_id": "mech-shield", "keyword": "shield",
                                                  "criteria": {"kind": "unit", "controller_relation": "friendly", "tag": "Mech"}}]}
    state["players"]["p1"]["zones"]["base"] += ["host", "plate", "boss"]
    return state


def run(state, *effects):
    done = apply_program(state, program("p", *effects))
    if not done.get("committed"):
        raise SystemExit(f"program refused: {done.get('reason_code')} {done.get('errors') or done.get('reason')}")
    return done["next_state"]


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause("I am a Mech.", CG.load_grammar())
    if got.get("production_id") != "i_am_a_tag" or (got.get("passive") or {}).get("object_fields") != {"granted_tags": ["Mech"]}:
        errors.append(f"G3: lowered to {got.get('production_id')} {got.get('passive')}")
    state = scene()
    if validate_state(state):
        errors.append(f"fixture invalid: {validate_state(state)[:2]}")
    own = copy.deepcopy(state)
    own["objects"]["host"]["granted_tags"] = ["Mech"]
    if object_tags(own, "host") != ["Recruit", "Mech"] or validate_state(own):
        errors.append(f"G1: granted_tags read {object_tags(own, 'host')} ({validate_state(own)[:1]})")
    unseen = copy.deepcopy(own)
    del unseen["objects"]["host"]["tags"]
    if object_tags(unseen, "host") is not None:
        errors.append(f"G1: an object with no observed printed tags read {object_tags(unseen, 'host')}")
    on = run(state, {"op": "attach", "effect_id": "a", "object_id": "plate", "to": "host"})
    if object_tags(on, "host") != ["Recruit", "Mech"] or not has_keyword(on, "host", "shield"):
        errors.append(f"G2: attached, the host reads {object_tags(on, 'host')}, Shield {has_keyword(on, 'host', 'shield')}")
    off = run(on, {"op": "detach", "effect_id": "d", "object_id": "plate"})
    if object_tags(off, "host") != ["Recruit"] or has_keyword(off, "host", "shield"):
        errors.append(f"G2: detached, the host reads {object_tags(off, 'host')}, Shield {has_keyword(off, 'host', 'shield')}")
    bad = copy.deepcopy(on)
    for effect in bad.get("continuous_effects") or []:
        if effect.get("kind") == "tag_grant":
            effect["value"] = {}
    if not any("tag_grant" in e or "value must be {tag" in e for e in validate_state(bad)):
        errors.append("G3: a tag_grant without a tag was accepted")
    if errors:
        print("tag grant checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("tag grant checks passed: own granted tags and an Effect Text's tag read beside the printed ones; unknown stays "
          "unknown; a tag aura reaches the host only while attached; lowered; a tagless grant refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
