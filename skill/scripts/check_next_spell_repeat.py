#!/usr/bin/env python3
"""Regression gate: "Give the next spell you play this turn [Repeat] equal to its cost." (set 2 package A2: Temporal
Portal). A next-card turn effect (next_spell_repeat, value own_cost): the next spell its controller plays this turn offers
a [Repeat] costing the spell's printed cost (Core 820.1, 206), chosen like any optional cost (356.2.b.1); the play spends
the effect whether or not it is paid.

  N1  granted, then c1 (printed [2], "draw 1") played with the Repeat paid: 4 Energy paid, it resolves twice (two cards
      drawn); the effect is gone
  N2  granted, c1 played with the Repeat declined: 2 paid, one card drawn; the effect is gone all the same
  N3  no grant: c1 offers no such Repeat (its intent is not asked)
  N4  the opponent's grant does not reach p1's spell
  N5  granted, c1 played with the Repeat paid, then countered by p2 before it resolves (Core 426.1): the effect is
      spent, the 4 Energy stay paid (426.1.c: no cost refunded), c1 is in p1's trash, off the Chain, and nothing was
      drawn; the countered item cannot be resolved afterwards
  G   the printed line lowers to the grant
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

TEXT = "Give the next spell you play this turn [Repeat] equal to its cost."
GRANT = {"op": "grant_turn_effect", "effect_id": "gr", "turn_effect_kind": "next_spell_repeat", "value": "own_cost",
         "controller": "p1"}
BODY = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
        "program_id": "c1-effects", "controller": "p1", "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]}


def scene(granted_to="p1"):
    s = base_state()
    s["players"]["p1"]["zones"]["main_deck"] = ["c2", "d1", "d2"]
    s["objects"]["d1"] = copy.deepcopy(s["objects"]["c2"])
    s["objects"]["d2"] = copy.deepcopy(s["objects"]["c2"])
    s["players"]["p1"]["zones"]["hand"].append("c1")
    s["objects"]["c1"]["printed_cost"] = {"energy": 2, "power": {}}
    s["players"]["p1"]["resources"] = {"energy": 4, "power": {}}
    if granted_to:
        done = IR.apply_program(s, {**BODY, "program_id": "grant", "controller": granted_to,
                                    "effects": [{**GRANT, "controller": granted_to}]})
        if not done.get("committed"):
            raise SystemExit(f"the grant did not commit: {done.get('reason') or done.get('errors')}")
        s = done["next_state"]
    return s


def play(s, paid=None):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p", "actor": "p1", "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}, "effect_program_id": "c1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    offer = [e["effect_id"] for e in s.get("turn_effects") or [] if e.get("kind") == "next_spell_repeat" and e["controller"] == "p1"]
    decisions = [{"decision_id": f"self_offer:granted_repeat:{offer[0]}", "kind": "optional_choice", "stage": "play_declaration",
                  "controller": "p1", "value": paid}] if paid is not None and offer else []
    env = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s), "decisions": decisions}
    return play_card(fixture(), s, decl, engine_decisions=env, effect_program=copy.deepcopy(BODY))


def resolve(played):
    timing = RC.finalize_oldest_pending(played["next_timing_state"]).get("next_state") or played["next_timing_state"]
    timing["chain"]["consecutive_passes"] = ["p1", "p2"]
    return resolve_with_program(timing, "spell-1", played["next_effect_state"], copy.deepcopy(BODY))


def countered() -> list[str]:
    """N5: the Repeat paid, then p2 counters the spell (the counter op on its Chain item) before it resolves."""
    played = play(scene(), True)
    if not played.get("committed"):
        return [f"N5: the play was refused: {played.get('reason_code')} {played.get('reason')}"]
    deck_before = list(played["next_effect_state"]["players"]["p1"]["zones"]["main_deck"])
    hand_before = list(played["next_effect_state"]["players"]["p1"]["zones"]["hand"])
    done = IR.apply_program(played["next_effect_state"], {**BODY, "program_id": "p2-counter", "controller": "p2",
                                                          "effects": [{"op": "counter", "effect_id": "ctr",
                                                                       "chain_item_id": "spell-1"}]})
    if not done.get("committed"):
        return [f"N5: the counter did not commit: {done.get('reason') or done.get('errors')}"]
    after, errors = done["next_state"], []
    p1 = after["players"]["p1"]
    if any(e.get("kind") == "next_spell_repeat" and e.get("controller") == "p1" for e in after.get("turn_effects") or []):
        errors.append("N5: the effect was not spent by the countered spell")
    if p1["resources"]["energy"] != 0:
        errors.append(f"N5: {p1['resources']['energy']} Energy after the counter, expected 0 (no cost refunded)")
    if "spell-1" in (after.get("chain_items") or {}) or "c1" not in p1["zones"]["trash"]:
        errors.append(f"N5: chain items {sorted(after.get('chain_items') or {})}, p1 trash {p1['zones']['trash']}")
    if p1["zones"]["hand"] != hand_before or p1["zones"]["main_deck"] != deck_before:
        errors.append(f"N5: hand {p1['zones']['hand']} / deck {p1['zones']['main_deck']} changed - the spell's effect happened")
    # the timing side of the counter, as resolution_bridge does it in the same commit (ADR-0011 §5, Core 426.1)
    countered_ids = done.get("countered_chain_items") or []
    if countered_ids != ["spell-1"]:
        errors.append(f"N5: countered chain items {countered_ids}")
    timing = RC.finalize_oldest_pending(played["next_timing_state"]).get("next_state") or played["next_timing_state"]
    removal = RC.remove_chain_item(timing, "spell-1")
    if removal.get("applied") is not True:
        return errors + [f"N5: the timing chain refused the removal: {removal.get('reason_code')}"]
    timing = removal["next_state"]
    if any(i["id"] == "spell-1" for i in timing["chain"]["items"]):
        errors.append("N5: the countered spell is still on the timing chain")
    late = resolve_with_program(timing, "spell-1", after, copy.deepcopy(BODY))
    if late.get("committed"):
        errors.append("N5: the countered spell still resolved")
    return errors


def main() -> int:
    errors: list[str] = []
    for label, paid, energy_left, drawn in (("N1", True, 0, 2), ("N2", False, 2, 1)):
        s = scene()
        played = play(s, paid)
        if not played.get("committed"):
            errors.append(f"{label}: the play was refused: {played.get('reason_code')} {played.get('reason')}")
            continue
        after = played["next_effect_state"]
        if after["players"]["p1"]["resources"]["energy"] != energy_left:
            errors.append(f"{label}: {after['players']['p1']['resources']['energy']} Energy left, expected {energy_left}")
        if any(e.get("kind") == "next_spell_repeat" for e in after.get("turn_effects") or []):
            errors.append(f"{label}: the effect was not spent")
        done = resolve(played)
        if not done.get("committed"):
            errors.append(f"{label}: resolution refused: {done.get('reason')}")
            continue
        hand = done["next_effect_state"]["players"]["p1"]["zones"]["hand"]
        if len(hand) != drawn:
            errors.append(f"{label}: {len(hand)} card(s) drawn, expected {drawn}")
    errors += countered()
    plain = play(scene(granted_to=None), True)
    if not plain.get("committed"):
        errors.append(f"N3: {plain.get('reason_code')} {plain.get('reason')}")
    elif plain["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 2:
        errors.append("N3: a Repeat was paid with no grant")
    theirs = scene(granted_to="p2")
    if play(theirs, None).get("reason_code") == "optional_cost_intent_required":
        errors.append("N4: the opponent's grant offered p1's spell a Repeat")
    got = CG.compile_clause(TEXT, CG.load_grammar())
    if got.get("program_effects") != [{**GRANT, "effect_id": "grant", "controller": "$controller", "source": "$chain_item"}]:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('program_effects')}")
    if errors:
        print("next-spell Repeat checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("next-spell Repeat checks passed: the next spell offers a Repeat at its printed cost - paid, it resolves twice; "
          "declined, once; either way the grant is spent; countered, the grant is spent, the Repeat stays paid and nothing "
          "resolves; none without a grant or from the opponent's; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
