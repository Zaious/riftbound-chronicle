#!/usr/bin/env python3
"""Regression gate: "I cost [N] less to play from anywhere other than your hand." (set 2 package A2: Void Drone, Drag
Under; Core 356.4).

  H1  the card played from its player's hand costs its printed Energy - the reduction does not apply
  H2  the same card played from its trash (a permission granted) costs N less; a card without the text, from the trash,
      costs its printed Energy
  H3  the printed form lowers to the reduction with origin not_hand; another origin is refused by the validator
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXT = "I cost :rb_energy_2: less to play from anywhere other than your hand."


def state_with(fields, zone):
    state = base_state()
    state["objects"]["vd"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "printed_cost": {"energy": 4, "power": {}},
                              **copy.deepcopy(fields)}
    state["players"]["p1"]["zones"][zone].append("vd")
    state["players"]["p1"]["resources"] = {"energy": 4, "power": {}}
    return state


def play(state, zone, energy):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-vd", "actor": "p1", "card": "vd",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": energy, "power": {}}}, "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if zone != "hand":
        decl["source"] = {"kind": zone}
        decl["source_permission"] = {"granted_by": "a-trash-permission"}
    got = play_card(fixture(), state, decl)
    left = (got.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources", {}).get("energy")
    return got, left


def main() -> int:
    errors: list[str] = []
    lowered = CG.compile_clause(TEXT, CG.load_grammar())
    fields = (lowered.get("passive") or {}).get("object_fields") or {}
    if lowered.get("production_id") != "self_cost_reduction_not_from_hand" or fields.get("printed_cost_modifications") != [
            {"modification_id": "own-text", "kind": "energy_reduction", "amount": 2, "origin": "not_hand"}]:
        errors.append(f"H3: lowered to {lowered.get('production_id')} {fields}")
    for label, f, zone, want_left in (("H1 from the hand", fields, "hand", 0), ("H2 from the trash", fields, "trash", 2),
                                      ("H2 no text, from the trash", {}, "trash", 0)):
        state = state_with(f, zone)
        problems = validate_state(state)
        if problems:
            errors.append(f"{label}: fixture invalid {problems[:2]}")
            continue
        got, left = play(state, zone, 4)
        if not got.get("committed") or left != want_left:
            errors.append(f"{label}: committed {got.get('committed')} ({got.get('reason_code')} {got.get('reason')}), "
                          f"Energy left {left}, wanted {want_left}")
    bad = state_with({"printed_cost_modifications": [{"modification_id": "own-text", "kind": "energy_reduction",
                                                      "amount": 2, "origin": "hand"}]}, "hand")
    if not any("origin" in e for e in validate_state(bad)):
        errors.append("H3: an origin other than not_hand was accepted")
    if errors:
        print("not-from-hand cost checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("not-from-hand cost checks passed: full cost from the hand, N less from the trash, none for a card without the "
          "text; lowered; the origin validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
