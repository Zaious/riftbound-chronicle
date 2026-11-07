#!/usr/bin/env python3
"""Regression gate: "While you control this battlefield, friendly [Repeat] costs cost [1] less." (set 2 package A2: Marai
Spire). A Battlefield's static (repeat_cost_reduction N): while the actor controls it, each [Repeat] offer of the actor's
play has its Energy reduced by N, not below 0 (Core 356.4.c, 356.4.c.2).

  D1  p1 controls bf1 (the static); c1 prints [Repeat] [2] and costs [2]; paid: 2 + 1 = 3 Energy spent, it resolves twice
  D2  bf1 controlled by p2: the Repeat costs its full [2] (4 spent)
  D3  [Repeat] [1] with a 3-Energy discount: 0, never below (2 spent)
  V   a non-positive amount does not validate
  G   the printed line lowers to exactly that field
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_next_spell_repeat import BODY, resolve, scene  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402

TEXT = "While you control this battlefield, friendly [Repeat] costs cost :rb_energy_1: less."


def board(controller="p1", reduction=1, repeat=2):
    s = scene(granted_to=None)
    s["battlefields"]["bf1"].update({"controller": controller, "repeat_cost_reduction": reduction})
    s["objects"]["c1"]["optional_additional_costs"] = [{"cost_offer_id": "rp", "payment": {"kind": "energy", "amount": repeat},
                                                       "repeat": True}]
    s["players"]["p1"]["resources"] = {"energy": 4, "power": {}}
    return s


def play(s):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}, "effect_program_id": "c1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    env = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s), "decisions": [
        {"decision_id": "self_offer:rp", "kind": "optional_choice", "stage": "play_declaration", "controller": "p1", "value": True}]}
    return play_card(fixture(), s, decl, engine_decisions=env, effect_program=copy.deepcopy(BODY))


def main() -> int:
    errors: list[str] = []
    for label, s, left, drawn in (("D1", board(), 1, 2), ("D2", board(controller="p2"), 0, 2),
                                  ("D3", board(reduction=3, repeat=1), 2, 2)):
        if IR.validate_state(s):
            errors.append(f"{label}: board {IR.validate_state(s)[:2]}")
            continue
        played = play(s)
        if not played.get("committed"):
            errors.append(f"{label}: refused {played.get('reason_code')} {played.get('reason')}")
            continue
        energy = played["next_effect_state"]["players"]["p1"]["resources"]["energy"]
        if energy != left:
            errors.append(f"{label}: {energy} Energy left, expected {left}")
        done = resolve(played)
        if not done.get("committed") or len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != drawn:
            errors.append(f"{label}: resolved {done.get('reason')}; drew {len((done.get('next_effect_state') or {}).get('players', {}).get('p1', {}).get('zones', {}).get('hand', []))}")
    bad = board(reduction=0)
    if not any("repeat_cost_reduction" in p for p in IR.validate_state(bad)):
        errors.append("V: a reduction of 0 validated")
    got = CG.compile_clause(TEXT, CG.load_grammar())
    if (got.get("passive") or {}).get("battlefield_fields") != {"repeat_cost_reduction": 1}:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    if errors:
        print("repeat-cost discount checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("repeat-cost discount checks passed: with the Battlefield controlled a [Repeat] costs 1 Energy less (not below "
          "0), with it the opponent's the full cost; the spell resolves twice either way; validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
