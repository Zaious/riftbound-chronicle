#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "Deal 2 to a unit at a battlefield. If it's attacking, deal 4 to it instead." (Sudden
Storm) - one Deal, the larger amount while the target has the Attacker designation as the spell resolves.

  S1 attacking   the chosen unit is an Attacker: it is dealt 4, once (the 2 is not dealt as well)
  S2 not         the chosen unit has no designation: it is dealt 2
  S3 defending   a Defender is not attacking: 2
  G  grammar     the sentence lowers to the two predicated Deals on one decision; its near misses do not

    python skill/scripts/check_set2_instead.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "Deal 2 to a unit at a battlefield. If it's attacking, deal 4 to it instead."
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def dealt(role):
    state = base_state()
    state["objects"]["foe"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 9, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
    if role:
        state["objects"]["foe"]["combat_designation"] = {"role": role, "combat_id": "cb1"}
    state["battlefields"]["bf1"]["objects"].append("foe")
    state = settle_contested(state)
    effects = CG.compile_clause(SENTENCE, CG.load_grammar())["program_effects"]
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": "storm", "controller": "p1", "effects": copy.deepcopy(effects)}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["foe"],
         "selection_identities": {"foe": object_identity(state, "foe")}}]}
    done = apply_program(state, program, decisions=decisions)
    if not done.get("committed"):
        return f"refused: {done.get('reason') or done.get('errors')}"
    return done["next_state"]["objects"]["foe"]["damage"]


def main() -> int:
    lowered = CG.compile_clause(SENTENCE, CG.load_grammar())
    if [e.get("op") for e in lowered.get("program_effects") or []] != ["deal_damage", "deal_damage"]:
        fail("G", f"lowered to {lowered.get('program_effects')}")
    for label, role, want in (("S1 attacking", "attacker", 4), ("S2 not", None, 2), ("S3 defending", "defender", 2)):
        if (got := dealt(role)) != want:
            fail(label, f"dealt {got}, not {want}")
    for near in ("deal 2 to a unit at a battlefield. if it's defending, deal 4 to it instead.",
                 "deal 2 to a unit. if it's attacking, deal 4 to it instead."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == \
                "deal_n_to_a_unit_at_a_battlefield_if_its_attacking_deal_m_to_it_instead":
            fail("G", f"a near miss lowered: {near!r}")
    if errors:
        print("FAILED: set 2 'instead' if attacking")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'if it's attacking, deal 4 to it instead' - an Attacker as the spell resolves is dealt 4, once; any other "
          "unit 2 (359.3.d, 466.2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
