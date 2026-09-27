#!/usr/bin/env python3
"""
Regression gate: when a play wakes the watchers (Core 419.4.a / 419.4.a.1; GPT 2026-09-27).

Abilities that trigger on a card being played trigger when the act of playing it has been
completed by the card's resolution; if the card does not resolve - it was countered - they do not
trigger at all. What the play's COSTS did (a card discarded to pay) happened while paying, and the
watchers of that happen then.

Must hold, through play_card and resolve_with_program on real Chains:
  - normal: p1's spell Finalizes - no play watcher is scheduled; it resolves - p1's "When you play a
    spell" watcher is scheduled, once;
  - countered: p1's spell Finalizes, p2's counter resolves above it and counters it - the spell never
    resolves and the play watcher is never scheduled;
  - cost first: a spell whose additional cost discards a card - the "When you discard one or more
    cards" watcher is scheduled by the play itself (at payment), the "When you play a spell" watcher
    only when the spell resolves;
  - a unit: "When you play a unit" is scheduled as the unit enters (its play completes), not at Finalize.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

HASH = "sha256:" + "b" * 64
SPELL_WATCH = {"kinds": ["played"], "scope": "actor", "filter": {"object_kind": "spell"}}
UNIT_WATCH = {"kinds": ["played"], "scope": "actor", "filter": {"object_kind": "unit"}}
DISCARD_WATCH = {"kinds": ["discarded"], "scope": "player", "grouping": "one_or_more"}


def watcher(state, object_id, trigger_id, watch, owner="p1"):
    state["objects"][object_id] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [],
                                   "damage": 0, "exhausted": False,
                                   "event_triggers": [{"trigger_id": trigger_id, "controller": owner, "source_object": object_id,
                                                       "controller_order": 0, "effect_program_id": f"{trigger_id}-program",
                                                       "optional_at_finalize": False, "watch": watch, "effect_program_hash": HASH}]}
    state["players"][owner]["zones"]["base"].append(object_id)
    return state


def in_hand(state, card, kind="spell", actor="p1"):
    state["objects"][card] = {"owner": actor, "controller": actor, "kind": kind, "base_might": 2 if kind == "unit" else 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"][actor]["zones"]["hand"].append(card)
    return state


def play(state, card="c9", kind="spell", cost=None):
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"play-{card}", "actor": "p1", "card": card,
            "chain_item": {"id": f"{kind}-9", "object_kind": kind, "timing": "default"},
            "cost": cost or {"base": {"energy": 2, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"},
            **({"entry_location": {"kind": "base"}} if kind == "unit" else {})}
    return play_card(fixture(), state, decl)


def resolve(result, items, item_id, body):
    window = fixture(priority="p2", items=items, passes=["p1", "p2"])
    return resolve_with_program(window, item_id, result["next_effect_state"], body)


def scheduled(result, prefix):
    chain = ((result or {}).get("next_timing_state") or {}).get("chain", {}).get("items", [])
    return [i for i in chain if str(i.get("id", "")).startswith(prefix) or str(i.get("trigger_id", "")).startswith(prefix)]


def draw_body(controller="p1"):
    return {**program("body", {"op": "draw", "effect_id": "d", "player": controller, "count": 1}), "controller": controller}


def main() -> int:
    errors: list[str] = []

    # --- normal: nothing at Finalize, once at resolution --------------------------------------
    played = play(in_hand(watcher(base_state(), "w1", "spellwatch", SPELL_WATCH), "c9"))
    if not played.get("committed"):
        errors.append(f"the spell was not played: {played.get('reason')}")
    else:
        if scheduled(played, "spellwatch"):
            errors.append("the play watcher was scheduled at Finalize (Core 419.4.a: at resolution)")
        resolved = resolve(played, [item("spell-9", "p1", "spell", "default", "finalized")], "spell-9", draw_body())
        if not resolved.get("committed") or len(scheduled(resolved, "spellwatch")) != 1:
            errors.append(f"the resolving spell did not schedule its play watcher exactly once: {resolved.get('reason')} "
                          f"{scheduled(resolved, 'spellwatch')}")

    # --- countered: never ------------------------------------------------------------------------
    played = play(in_hand(watcher(base_state(), "w1", "spellwatch", SPELL_WATCH), "c9"))
    if played.get("committed"):
        board = played["next_effect_state"]
        board["players"]["p2"]["zones"]["main_deck"].remove("c4")
        board["chain_items"]["counter-1"] = {"card": "c4", "controller": "p2"}
        counter = {**program("counter", {"op": "counter", "effect_id": "c", "chain_item_id": "spell-9"}), "controller": "p2"}
        window = fixture(priority="p1", items=[item("spell-9", "p1", "spell", "default", "finalized"),
                                              item("counter-1", "p2", "spell", "default", "finalized")], passes=["p1", "p2"])
        countered = resolve_with_program(window, "counter-1", board, counter)
        if not countered.get("committed"):
            errors.append(f"the counter did not resolve: {countered.get('reason')} {countered.get('stage')}")
        else:
            if "spell-9" in (countered["next_effect_state"].get("chain_items") or {}):
                errors.append("the countered spell is still on the Chain")
            if scheduled(countered, "spellwatch"):
                errors.append("a countered spell's play woke its play watcher (Core 419.4.a.1)")
            if any(t.get("trigger_id", "").startswith("spellwatch") for t in countered.get("pending_triggers") or []):
                errors.append("a countered spell's play is pending a play-watcher trigger")

    # --- cost first: the discard at payment, the play at resolution ------------------------------
    board = watcher(watcher(base_state(), "w1", "spellwatch", SPELL_WATCH), "w2", "discardwatch", DISCARD_WATCH)
    board = in_hand(in_hand(board, "c9"), "c8")
    discard_cost = {"base": {"energy": 1, "power": {}},
                    "additional": [{"cost_id": "d", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]}
    played = play(board, cost=discard_cost)
    if not played.get("committed"):
        errors.append(f"the spell with a discard cost was not played: {played.get('reason_code')} {played.get('reason')}")
    else:
        if len(scheduled(played, "discardwatch")) != 1:
            errors.append(f"the discard paid as a cost did not wake its watcher at payment: {scheduled(played, 'discardwatch')}")
        if scheduled(played, "spellwatch"):
            errors.append("the play watcher was scheduled at payment together with the cost's watcher")
        on_chain = [item("spell-9", "p1", "spell", "default", "finalized")]
        resolved = resolve(played, on_chain, "spell-9", draw_body())
        if not resolved.get("committed") or len(scheduled(resolved, "spellwatch")) != 1:
            errors.append(f"the play watcher did not wake when the spell with a cost resolved: {resolved.get('reason')}")

    # --- a unit: as it enters ---------------------------------------------------------------------
    played = play(in_hand(watcher(base_state(), "w1", "unitwatch", UNIT_WATCH), "c9", kind="unit"), kind="unit")
    if not played.get("committed"):
        errors.append(f"the unit was not played: {played.get('reason')}")
    else:
        if scheduled(played, "unitwatch"):
            errors.append("'When you play a unit' was scheduled at Finalize, before the unit entered")
        entered = resolve(played, [item("unit-9", "p1", "unit", "default", "finalized")], "unit-9", None)
        if not entered.get("committed") or len(scheduled(entered, "unitwatch")) != 1:
            errors.append(f"the unit's entry did not wake 'When you play a unit': {entered.get('reason')}")

    if errors:
        print("FAILED: play trigger timing (Core 419.4.a)")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: play watchers wake when the card resolves (a spell, a unit), never at Finalize; a countered card's play "
          "wakes nothing; a cost's discard wakes its watcher at payment (Core 419.4.a, 419.4.a.1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
