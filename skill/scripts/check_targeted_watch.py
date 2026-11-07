#!/usr/bin/env python3
"""Regression gate: Targeting Effects (Core 383.4.b) - "When you choose me with a spell" (Jae Medarda) and "When you
choose a friendly unit" (Spirit Wheel, Irelia - Blade Dancer). Set 2 package A2.

  C1  p1's spell chooses p1's unit at bf1: the friendly-unit watcher wakes, about that unit, its trigger on the Chain
      after the spell (383.4.b.2); the me-with-a-spell watcher does not (another object)
  C2  p1's spell chooses the me-with-a-spell watcher itself: both watchers wake
  C3  p1's spell chooses p2's unit: neither wakes
  C4  p1's triggered ability chooses p1's unit as it is finalized: the friendly-unit watcher wakes; chosen by that
      ability, the me-with-a-spell watcher does not (an ability is not a spell)
  C5  p2's choice wakes neither of p1's watchers (scope actor: "you choose"); a unit card in a trash is not a unit on the
      board; both printed forms lower to the watches; the play and the finalization emit `targeted`
  GPT A2 ruling 3, tested apart:
  C6  one spell choosing the SAME unit in two of its slots: one Targeting Effect (one object targeted once by it)
  C7  one spell choosing two DIFFERENT friendly units: one each - two of p1's triggers, so p1 orders them (383.3.d)
  C8  one spell whose discard cost wakes p1's "when you discard one or more cards" and whose choice wakes the
      friendly-unit watcher: both in ONE batch above the spell - p1 orders them (383.3.d), no fixed costs-first batch
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_trigger_source_identity as TS  # noqa: E402
import clause_grammar as CG  # noqa: E402
import watchers as W  # noqa: E402
from check_effect_ir import program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, object_identity, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import finalize_trigger, program_hash  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, schedule_triggered_items  # noqa: E402

TEXTS = {"me_spell": "When you choose me with a spell, draw 1.", "friendly": "When you choose a friendly unit, draw 1.",
         "discard": "When you discard one or more cards, draw 1."}


def lowered() -> dict:
    grammar = CG.load_grammar()
    out = {}
    for key, text in TEXTS.items():
        got = CG.compile_clause(text, grammar)
        out[key] = (((got.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or [None])[0]
    return out


def board(watches: dict) -> dict:
    """TS.board (u1 p1's and u2 p2's at bf1, e3 p2's at bf2) plus p1's two watchers in p1's Base: jae (a unit, chosen by
    a spell) and wheel (a gear, a friendly unit chosen); c1, a spell, in p1's hand."""
    state = TS.board()
    for oid, kind, key in (("jae", "unit", "me_spell"), ("wheel", "gear", "friendly")):
        state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": 2 if kind == "unit" else 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": False,
                                 "event_triggers": [{**copy.deepcopy(watches[key]), "controller": "p1",
                                                     "source_object": oid, "effect_program_id": f"{oid}-1"}]}
        state["players"]["p1"]["zones"]["base"].append(oid)
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    return state


def cast(state: dict, target: str, *more: str, discard: bool = False) -> dict:
    """p1 plays c1, a spell dealing 1 to `target` (and to each of `more`, each its own slot; chosen at play, Core 355.5),
    with a mandatory discard of one card as an additional cost when asked."""
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}},
                     **({"additional": [{"cost_id": "d", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]}
                        if discard else {})},
            "effect_program_id": "spell-1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    effects = [{"op": "deal_damage", "amount": 1, "effect_id": f"dmg{k}", "object_id": t,
                "target": {"object_id": t, "chosen_zone_class": "board", "kind": "unit"}}
               for k, t in enumerate((target,) + more)]
    return play_card(fixture(), state, decl, effect_program=program("spell-1-effects", *effects))


def woke(result: dict) -> list[tuple[str, str]]:
    items = (result.get("next_timing_state") or {}).get("chain", {}).get("items", [])
    return sorted((i["source_object"], i["trigger_event"]["object"]) for i in items
                  if (i.get("trigger_event") or {}).get("kind") == "targeted")


def ability_choice(state: dict, target: str) -> dict:
    """u1's triggered ability (p1's), "Give a unit +1 Might this turn", finalized choosing `target` (Core 355.5.b)."""
    prog = TS.program()
    prog["effects"] = [{"op": "modify_might", "effect_id": "buff", "amount": 1, "duration": "this_turn",
                        "source": "u1", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}]
    entry = TS.descriptor(state)
    entry["effect_program_hash"] = program_hash(prog)
    timing = schedule_triggered_items(fixture(), [entry])["next_state"]
    pick = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection",
                           "controller": "p1", "value": [target],
                           "selection_identities": {target: object_identity(state, target)}}]}
    return finalize_trigger(timing, state, {TS.PROGRAM_ID: prog}, pick)


def main() -> int:
    errors: list[str] = []
    watches = lowered()
    if any(w is None for w in watches.values()):
        errors.append(f"C5: a printed form did not lower: {watches}")
    else:
        if watches["me_spell"]["watch"] != {"kinds": ["targeted"], "scope": "actor",
                                            "filter": {"is_source": True, "chosen_by_spell": True}}:
            errors.append(f"C5: the me-with-a-spell watch is {watches['me_spell']['watch']}")
        problems = validate_state(board(watches))
        if problems:
            errors.append(f"fixture invalid: {problems[:2]}")
        for label, target, want in (("C1 p1's unit u1", "u1", [("wheel", "u1")]),
                                    ("C2 the watcher jae itself", "jae", [("jae", "jae"), ("wheel", "jae")]),
                                    ("C3 p2's unit u2", "u2", [])):
            got = cast(board(watches), target)
            if len(want) == 2:
                # two of p1's abilities woken together: p1 orders them (Core 383.3.d) - asked for, naming both
                named = sorted(n.split("@")[0] for n in got.get("trigger_ids") or [])
                if got.get("reason_code") != "trigger_order_required" or named != ["on-choose-friendly-unit",
                                                                                    "on-chosen-by-spell"]:
                    errors.append(f"{label}: wanted both woken and their order asked, got {got.get('reason_code')} {named}")
                continue
            if not got.get("committed"):
                errors.append(f"{label}: the spell was refused: {got.get('reason_code')} {got.get('reason')}")
                continue
            if woke(got) != want:
                errors.append(f"{label}: woke {woke(got)}, wanted {want}")
            chain = [i["id"] for i in got["next_timing_state"]["chain"]["items"]]
            if want and chain[0] != "spell-1":
                errors.append(f"{label}: the Targeting Effect is not after the spell on the Chain: {chain}")
        for label, target, want in (("C4 p1's unit u1", "u1", [("wheel", "u1")]),
                                    ("C4 jae, by an ability", "jae", [("wheel", "jae")])):
            got = ability_choice(board(watches), target)
            if not got.get("committed"):
                errors.append(f"{label}: finalization refused: {got.get('reason')} {got.get('message')}")
                continue
            if woke(got) != want:
                errors.append(f"{label}: woke {woke(got)}, wanted {want}")
            if want and "targeting_effects" not in got:
                errors.append(f"{label}: the finalization records no targeting_effects")
        got = cast(board(watches), "u1", "u1")
        if not got.get("committed") or woke(got) != [("wheel", "u1")]:
            errors.append(f"C6 same unit twice: {got.get('reason_code')} woke {woke(got)}")
        two = board(watches)
        two["objects"]["u5"] = copy.deepcopy(two["objects"]["u1"])
        two["objects"]["u5"].pop("identity", None)
        two["players"]["p1"]["zones"]["base"].append("u5")
        got = cast(two, "u1", "u5")
        named = sorted(n.split("@")[0] for n in got.get("trigger_ids") or [])
        if got.get("reason_code") != "trigger_order_required" or named != ["on-choose-friendly-unit"] * 2:
            errors.append(f"C7 two units: {got.get('reason_code')} {named}")
        both = board(watches)
        both["objects"]["disc"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0,
                                   "might_modifiers": [], "damage": 0, "exhausted": False,
                                   "event_triggers": [{**copy.deepcopy(watches["discard"]), "controller": "p1",
                                                       "source_object": "disc", "effect_program_id": "disc-1"}]}
        both["players"]["p1"]["zones"]["base"].append("disc")
        both["players"]["p1"]["zones"]["main_deck"].remove("c2")
        both["players"]["p1"]["zones"]["hand"].append("c2")
        got = cast(both, "u1", discard=True)
        named = sorted(n.split("@")[0] for n in got.get("trigger_ids") or [])
        if got.get("reason_code") != "trigger_order_required" or len(named) != 2 \
                or "on-choose-friendly-unit" not in named:
            errors.append(f"C8 one batch: {got.get('reason_code')} {got.get('reason')} {named}")
        state = board(watches)
        their = {"kind": "targeted", "object": "u1", "actor": "p2", "controller": "p1", "chosen_by": "spell"}
        for oid in ("jae", "wheel"):
            descriptor = state["objects"][oid]["event_triggers"][0]
            if W.watch_matches(state, descriptor["watch"], {**their, "object": "jae" if oid == "jae" else "u1"},
                               source_object=oid, controller="p1"):
                errors.append(f"C5: p2's choice woke p1's {oid}")
        state["objects"]["dead"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2,
                                    "might_modifiers": [], "damage": 0, "exhausted": False}
        state["players"]["p1"]["zones"]["trash"].append("dead")
        wheel = state["objects"]["wheel"]["event_triggers"][0]["watch"]
        if W.watch_matches(state, wheel, {"kind": "targeted", "object": "dead", "actor": "p1", "controller": "p1",
                                          "chosen_by": "spell"}, source_object="wheel", controller="p1"):
            errors.append("C5: a unit card in the trash counted as a friendly unit chosen")
    if errors:
        print("Targeting Effect checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("Targeting Effect checks passed: a spell's and an ability's choices wake 'when you choose a friendly unit' "
          "(after the item, on the Chain); 'when you choose me with a spell' only for a spell choosing the card; "
          "another player's choice, an enemy unit and a card in the trash wake nothing; one unit chosen twice by one "
          "spell is one Targeting Effect, two units two; what the costs and the targeting woke share one batch, ordered "
          "by p1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
