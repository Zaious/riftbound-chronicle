#!/usr/bin/env python3
"""Regression gate: "I can be played to a battlefield you're attacking." (set 2 package A2: Rengar - Pouncing). A play
permission (attacking_battlefield): the card may enter a Battlefield where one of its player's Units is designated Attacker
now (Core 355.2.b, 466.2.c).

  A1  p1's u1 attacking at bf1 (p2's, p2's u2 defending): rengar played to bf1 - committed, it is at bf1
  A2  no p1 Attacker there (u1 defending instead): refused
  A3  without the permission, with u1 attacking: refused
  G   the printed line lowers to exactly that permission
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402

TEXT = "I can be played to a battlefield you're attacking."


def scene(role="attacker", permission=True):
    s = base_state()
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["players"]["p2"]["zones"]["base"].remove("u2")
    s["battlefields"]["bf1"].update({"controller": "p2", "objects": ["u2", "u1"], "contested": True, "contested_by": "p1"})
    s["objects"]["u1"]["combat_designation"] = {"combat_id": "cb1", "role": role}
    s["objects"]["u2"]["combat_designation"] = {"combat_id": "cb1", "role": "defender" if role == "attacker" else "attacker"}
    s["objects"]["rengar"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "play_timing": "reaction",
                              **({"play_permissions": ["attacking_battlefield"]} if permission else {})}
    s["players"]["p1"]["zones"]["hand"].append("rengar")
    s["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return s


def play(s):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "rengar",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "reaction"},
            "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "battlefield", "battlefield": "bf1"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return play_card(fixture(), s, decl)


def main() -> int:
    errors: list[str] = []
    ok = play(scene())
    if not ok.get("committed"):
        errors.append(f"A1: refused {ok.get('reason_code')} {ok.get('reason')}")
    for label, s in (("A2", scene(role="defender")), ("A3", scene(permission=False))):
        got = play(s)
        if got.get("committed") or got.get("reason_code") != "entry_location_illegal":
            errors.append(f"{label}: {got.get('committed')} {got.get('reason_code')}")
    lowered = CG.compile_clause(TEXT, CG.load_grammar())
    if (lowered.get("passive") or {}).get("object_fields") != {"play_permissions": ["attacking_battlefield"]}:
        errors.append(f"G: lowered to {lowered.get('production_id')} {lowered.get('passive')}")
    if errors:
        print("play-to-attacking-battlefield checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("play-to-attacking-battlefield checks passed: played to a Battlefield where its player has an Attacker; refused "
          "where its player only defends, or without the permission; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
