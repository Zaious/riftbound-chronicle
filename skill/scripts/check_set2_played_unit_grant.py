#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "Friendly units played from anywhere other than a player's hand have [Accelerate]."
(Rek'Sai - Breacher) - played_unit_keyword_grants: while the card is on the board, a Unit its side plays from a zone
other than a hand is offered Accelerate's optional cost (Core 805.1.b), as if it had the keyword while played
(805.2.a); on the board it does nothing (805.3).

  G1 Champion Zone    p1 plays a Fury Unit without the keyword from its Champion Zone: Accelerate is offered; paid, the
                      Unit enters ready, [1][Fury] taken
  G2 hand             the same Unit from p1's hand: nothing offered
  G3 opponent         the grant is p2's: nothing offered to p1
  G4 off the board    the granting card in p1's trash: nothing offered
  V                   a grant of another keyword, or over every friendly unit, does not validate

    python skill/scripts/check_set2_played_unit_grant.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from resolution_bridge import complete_permanent_play  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
GRANT = {"grant_id": "played-not-from-hand-accelerate", "keyword": "accelerate",
         "criteria": {"kind": "unit", "controller_relation": "friendly", "source_not": "hand"}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(*, zone="champion_zone", granter="p1", granter_where="base"):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"].setdefault(zone, []).append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, "domains": ["fury"],
                                   "printed_cost": {"energy": 1, "power": {}}})
    state["objects"]["rb"] = {"owner": granter, "controller": granter, "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "played_unit_keyword_grants": [dict(GRANT)]}
    state["players"][granter]["zones"][granter_where].append("rb")
    state["players"]["p1"]["resources"] = {"energy": 5, "power": {"fury": 2}}
    return state


def play(state, zone, paid):
    decl = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "entry_location": {"kind": "base"},
            **({"source": {"kind": zone}} if zone != "hand" else {}),
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                 "decisions": [{"decision_id": cost_id, "kind": "optional_choice", "stage": "play_declaration",
                                "controller": "p1", "value": paid} for cost_id in ("accelerate", "accelerate:energy")]}
    return pt.play_card(fixture(), state, decl, engine_decisions=decisions)


def main() -> int:
    state = board()
    problems = validate_state(state)
    if problems:
        fail("board", problems[:2])
    offer, reason = pt.accelerate_offer(state, "c1", actor="p1", source_kind="champion_zone")
    if offer is None or offer.get("payment") != {"kind": "power", "domain": "fury", "amount": 1} or offer.get("granted_by") != ["rb"]:
        fail("G1 offer", f"{offer} {reason}")
    played = play(state, "champion_zone", True)
    if not played.get("committed"):
        fail("G1 play", f"{played.get('reason_code')} {played.get('reason')}")
    else:
        after, trace, _ = complete_permanent_play(played["next_effect_state"], "unit-1")
        if trace.get("error") or after["objects"]["c1"]["exhausted"] \
                or after["players"]["p1"]["resources"].get("power", {}).get("fury") != 1:
            fail("G1 ready", f"{trace.get('error')} exhausted={after['objects']['c1']['exhausted']} {after['players']['p1']['resources']}")
    hand = board(zone="hand")
    if pt.accelerate_offer(hand, "c1", actor="p1", source_kind="hand") != (None, None):
        fail("G2 hand", "Accelerate offered to a Unit played from a hand")
    theirs = board(granter="p2")
    if pt.accelerate_offer(theirs, "c1", actor="p1", source_kind="champion_zone") != (None, None):
        fail("G3 opponent", "an opponent's grant reached p1's Unit")
    gone = board(granter_where="trash")
    if pt.accelerate_offer(gone, "c1", actor="p1", source_kind="champion_zone") != (None, None):
        fail("G4 off the board", "a grant from the trash reached the Unit")
    for label, change in (("another keyword", {"keyword": "ganking"}),
                          ("every friendly unit", {"criteria": {"kind": "unit", "controller_relation": "friendly"}})):
        bad = board()
        bad["objects"]["rb"]["played_unit_keyword_grants"] = [{**GRANT, **change}]
        if not validate_state(bad):
            fail("V " + label, "validated")
    if errors:
        print("FAILED: set 2 friendly units played from elsewhere have [Accelerate]")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a Unit its side plays from a zone other than a hand is offered Accelerate while the granting card is on the "
          "board (805.1.b, 805.2.a); paid, it enters ready; from a hand, an opponent's grant, or a card off the board, nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
