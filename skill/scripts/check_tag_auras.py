#!/usr/bin/env python3
"""Regression gate: a static aura over the friendly Units of one tag (set 2 package A2).

  T1  a keyword aura with criteria tag "Mech": p1's Mech has the keyword; p1's untagged Unit and p2's Mech do not
  T2  the source carries the tag: it has the keyword too (no "other" printed)
  T3  a Might aura with the tag: +N on p1's Mechs (the source included), none elsewhere
  T4  the source off the board: no Unit has either
  T5  the validator refuses an empty or non-string tag; the grammar lowers the printed forms with the tag "Mech"
  T6  a set found by criteria narrowed by with_tag ("Give your Mechs +1 [M] this turn."): p1's Mechs, the untagged and
      p2's Mech untouched; an empty with_tag refused

Synthetic objects only.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, effective_might, has_keyword, validate_program, validate_state  # noqa: E402

CRITERIA = {"kind": "unit", "controller_relation": "friendly", "tag": "Mech"}


def board(auras, *, source_tags=("Mech",)):
    state = base_state()
    units = {"src": ("p1", 3, list(source_tags)), "mech": ("p1", 3, ["Mech"]), "plain": ("p1", 3, []),
             "enemy-mech": ("p2", 3, ["Mech"])}
    for oid, (controller, might, tags) in units.items():
        state["objects"][oid] = {"owner": controller, "controller": controller, "kind": "unit", "base_might": might,
                                 "might_modifiers": [], "damage": 0, "exhausted": False, "tags": tags}
        state["players"][controller]["zones"]["base"].append(oid)
    state["objects"]["src"]["static_auras"] = copy.deepcopy(auras)
    return state


def main() -> int:
    errors: list[str] = []
    shield = [{"aura_id": "mech-shield", "keyword": "shield", "criteria": dict(CRITERIA)}]
    might = [{"aura_id": "mech-might", "amount": 1, "criteria": dict(CRITERIA)}]
    for label, auras in (("shield", shield), ("might", might)):
        problems = validate_state(board(auras))
        if problems:
            errors.append(f"the {label} aura was refused: {problems[:1]}")
    s = board(shield)
    got = {o: has_keyword(s, o, "shield") for o in ("src", "mech", "plain", "enemy-mech")}
    if got != {"src": True, "mech": True, "plain": False, "enemy-mech": False}:
        errors.append(f"T1/T2: shield on {got}")
    if has_keyword(board(shield, source_tags=()), "src", "shield"):
        errors.append("T2: an untagged source had the keyword")
    s = board(might)
    got = {o: effective_might(s, o) for o in ("src", "mech", "plain", "enemy-mech")}
    if got != {"src": 4, "mech": 4, "plain": 3, "enemy-mech": 3}:
        errors.append(f"T3: Might {got}")
    for label, auras in (("shield", shield), ("might", might)):
        s = board(auras)
        s["players"]["p1"]["zones"]["base"].remove("src")
        s["players"]["p1"]["zones"]["trash"].append("src")
        if has_keyword(s, "mech", "shield") or effective_might(s, "mech") != 3:
            errors.append(f"T4: the {label} aura applied with its source in the trash")
    for bad in ("", 3, None):
        auras = [{**shield[0], "criteria": {**CRITERIA, "tag": bad}}]
        if not any("static_auras" in e for e in validate_state(board(auras))):
            errors.append(f"T5: tag {bad!r} was not refused")
    grammar = CG.load_grammar()
    for text, want in (("Your Mechs have [Shield].", shield),
                       ("Your Mechs have +1 :rb_might:.", might)):
        got = ((CG.compile_clause(text, grammar).get("passive") or {}).get("object_fields") or {}).get("static_auras")
        if got != want:
            errors.append(f"T5: {text!r} lowered to {got}")
    give = {"op": "modify_might", "effect_id": "buff", "amount": 1, "duration": "this_turn", "source": "$chain_item",
            "affected": {"criteria": {"kind": "unit", "controller_relation": "friendly", "location": "board",
                                      "with_tag": "Mech"}}}
    s = board([])
    done = apply_program(s, program("mechs", copy.deepcopy(give)))
    if not done.get("committed"):
        errors.append(f"T6: the tagged set was not applied: {done.get('errors') or done.get('reason')}")
    else:
        got = {o: effective_might(done["next_state"], o) for o in ("src", "mech", "plain", "enemy-mech")}
        if got != {"src": 4, "mech": 4, "plain": 3, "enemy-mech": 3}:
            errors.append(f"T6: Might after the tagged set {got}")
    bad = copy.deepcopy(give)
    bad["affected"]["criteria"]["with_tag"] = ""
    if not validate_program(program("mechs", bad)):
        errors.append("T6: an empty with_tag was not refused")
    if errors:
        print("tag aura checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("tag aura checks passed: a keyword or Might aura over the friendly Units of one tag, the source included when "
          "it carries it, none off the board; a bad tag refused; the grammar lowers the printed forms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
