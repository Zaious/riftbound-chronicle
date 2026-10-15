#!/usr/bin/env python3
"""A card's own printed statics work once it is played - not only when a state starts with it on the Board (package 13,
C2: every state a game reaches, Core 365.1).

Measured 2026-10-15: Draven - Showboat ("+1 Might per point") played from hand after the state's legacy families were
migrated kept its printed Might - its dynamic_might was migrated against its hand identity and pruned on the play. The
same held for a printed Bonus Damage, Might aura or Replacement Effect carried in the state's lists: an entry added for a
card on the Board, never for one that arrives. The engine now reads them from the object:

  S1 dynamic      a unit with dynamic_might (per its controller's points), in hand in a mid-game state (continuous effects
                  present), played and resolved: its Might includes the points; in hand it did not count
  S2 conditional  conditional_might the same way (while buffed)
  S3 bonus        printed_damage_modifiers: its controller's Bonus Damage counts once it is on the Board, not before; a
                  Battlefield's (units at itself) counts for a unit there
  S4 aura         printed_might_auras: the aura applies from the Board, with its controller's side
  S5 replacement  printed_replacements: materialized as it enters (its own id, its controller, itself bound); a kill of it
                  is then prevented; returned to hand the entry is gone; played again it is there again
  S6 the same     each printed form gives what the legacy form gave for a card on the Board from the start
  V  shape        a malformed printed field, a template carrying the fields where it is supplies, a Battlefield's bonus
                  naming another Battlefield - each refused

    python skill/scripts/check_printed_statics.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
errors: list[str] = []
BONUS = [{"amount": 1, "scope": {"kind": "controller_sources"}}]
AURA = [{"amount": 2, "condition": {"kind": "friendly_unit_defends_alone"}}]
GUARD = [{"mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": None,
          "target_object_id": "$source_object"}]


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def mid_game(migrated: bool = True, **printed) -> dict:
    """p1's x1 (a 3-Might unit costing 2) in hand carrying `printed`; the state is mid-game: another unit has a Might
    change this turn, in the legacy form, and a program has run since - the state was migrated while x1 was in hand,
    the measured case."""
    state = base_state()
    state["objects"]["x1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "printed_cost": {"energy": 2, "power": {}},
                              **copy.deepcopy(printed)}
    state["players"]["p1"]["zones"]["hand"].append("x1")
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    state["players"]["p1"]["points"] = 3
    state["objects"]["u1"]["might_modifiers"] = [{"amount": 1, "duration": "this_turn", "source": "x", "turn_id": "turn-0"}]
    if not migrated:
        return state
    ran = IR.apply_program(state, program({"op": "modify_might", "effect_id": "m", "object_id": "u2", "amount": 1,
                                           "duration": "this_turn", "source": "u2"}))
    if not ran.get("committed") or "continuous_effects" not in ran["next_state"]:
        raise SystemExit(f"the mid-game program did not commit: {ran.get('reason') or ran.get('errors')}")
    return ran["next_state"]


def play_x1(state):
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                "card": "x1", "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    played = PT.play_card(fixture(priority="p1"), state, declared)
    if not played.get("committed"):
        return None, played.get("reason_code") or played.get("reason")
    resolving = {**fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"]),
                 "turn_player": "p1"}
    done = resolve_with_program(resolving, "unit-1", played["next_effect_state"], None)
    if not done.get("committed"):
        return None, done.get("reason_code") or done.get("reason") or done.get("errors")
    return done["next_effect_state"], None


def program(*effects):
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "probe", "controller": "p2",
            "effects": list(effects)}


def main() -> int:
    # S1
    state = mid_game(dynamic_might=[{"modifier_id": "own-text", "amount": 1, "per": {"kind": "controller_points"}}])
    in_hand = IR.effective_might(state, "x1")
    after, why = play_x1(state)
    if after is None or IR.effective_might(after, "x1") != 6 or in_hand != 3:
        fail("S1 dynamic", f"{why} in hand {in_hand}, played {IR.effective_might(after, 'x1') if after else None}")
    # S2
    state = mid_game(conditional_might=[{"modifier_id": "clause", "amount": 1, "condition": {"kind": "is_buffed"}}])
    after, why = play_x1(state)
    if after is not None:
        after["objects"]["x1"]["buffed"] = True
    # 3, +1 the Buff's own, +1 this card's
    if after is None or IR.effective_might(after, "x1") != 5:
        fail("S2 conditional", f"{why} played and buffed {IR.effective_might(after, 'x1') if after else None}")
    # S3
    state = mid_game(printed_damage_modifiers=BONUS)
    before = IR.bonus_damage(state, "p1", None)[0]
    after, why = play_x1(state)
    if after is None or before != 0 or IR.bonus_damage(after, "p1", None)[0] != 1 or IR.bonus_damage(after, "p2", None)[0] != 0:
        fail("S3 bonus", f"{why} in hand {before}, played {IR.bonus_damage(after, 'p1', None)[0] if after else None}")
    field = mid_game()
    field["battlefields"]["bf1"]["printed_damage_modifiers"] = [{"amount": 1, "scope": {"kind": "location", "battlefield": "bf1"}}]
    field["objects"]["e9"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    field["battlefields"]["bf1"]["objects"].append("e9")
    field["battlefields"]["bf1"].update(controller="p2")
    there = "e9"
    if IR.validate_state(field) or there is None or IR.bonus_damage(field, "p2", there)[0] != 1 \
            or IR.bonus_damage(field, "p2", "x1")[0] != 0:
        fail("S3 bonus", f"a Battlefield's bonus to units at it: {IR.validate_state(field)[:2]} {there}")
    # S4
    state = mid_game(printed_might_auras=AURA)
    before = [e for e in IR.printed_aura_effects(state) if e["effect_id"].startswith("printed:might_aura:")
              and IR._effect_active(state, e)[0]]
    after, why = play_x1(state)
    live = [e for e in IR.printed_aura_effects(after) if e["effect_id"].startswith("printed:might_aura:")
            and IR._effect_active(after, e)[0]] if after else []
    if after is None or before or len(live) != 1 or live[0]["affects"]["criteria"]["aura_controller"] != "p1":
        fail("S4 aura", f"{why} active in hand {len(before)}, played {live}")
    # S5
    state = mid_game(printed_replacements=GUARD)
    after, why = play_x1(state)
    entry = next((r for r in (after or {}).get("replacement_effects") or []), None)
    if after is None or entry is None or (entry["replacement_id"], entry["controller"], entry["source_object"],
                                          entry["target_object_id"]) != ("x1:printed:0", "p1", "x1", "x1"):
        fail("S5 replacement", f"{why} materialized {entry}")
    else:
        killed = IR.apply_program(after, program({"op": "kill", "effect_id": "k", "object_id": "x1"}))
        if not killed.get("committed") or IR.find_location(killed["next_state"], "x1") != ("player", "p1", "base"):
            fail("S5 replacement", f"the kill was not prevented: {killed.get('reason') or killed.get('errors')}")
        back = IR.apply_program(after, program({"op": "return_to_hand", "effect_id": "r", "object_id": "x1"}))
        gone = back.get("next_state") or {}
        if not back.get("committed") or gone.get("replacement_effects"):
            fail("S5 replacement", f"returned to hand, the entry stayed: {back.get('reason') or back.get('errors')} "
                                   f"{gone.get('replacement_effects')}")
        else:
            gone["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
            again, why = play_x1(gone)
            if again is None or [r["replacement_id"] for r in again.get("replacement_effects") or []] != ["x1:printed:0"]:
                fail("S5 replacement", f"played again: {why} {(again or {}).get('replacement_effects')}")
    # S6: on the Board from the start, the printed form gives what the legacy form gave
    for label, printed, legacy, read in (
            ("dynamic", {"dynamic_might": [{"modifier_id": "own-text", "amount": 1, "per": {"kind": "controller_points"}}]},
             None, lambda s: IR.effective_might(s, "x1")),
            ("bonus", {"printed_damage_modifiers": BONUS},
             {"damage_modifiers": [{"modifier_id": "m", "source_object": "x1", "controller": "p1", **BONUS[0]}]},
             lambda s: IR.bonus_damage(s, "p1", None)[0])):
        on_board = mid_game(False, **printed)
        on_board["players"]["p1"]["zones"]["hand"].remove("x1")
        on_board["players"]["p1"]["zones"]["base"].append("x1")
        old = copy.deepcopy(on_board)
        if legacy is not None:
            for key in printed:
                old["objects"]["x1"].pop(key)
            old.update(copy.deepcopy(legacy))
        if read(on_board) != read(old) or read(IR.migrate_legacy_effects(old)) != read(on_board):
            fail("S6 the same", f"{label}: printed {read(on_board)}, legacy {read(old)}")
    # V
    for label, change in (
            ("a bonus with an id", lambda s: s["objects"]["x1"].update(printed_damage_modifiers=[{**BONUS[0], "modifier_id": "m"}])),
            ("a bonus at a location", lambda s: s["objects"]["x1"].update(printed_damage_modifiers=[
                {"amount": 1, "scope": {"kind": "location", "battlefield": "bf1"}}])),
            ("an aura of an unknown condition", lambda s: s["objects"]["x1"].update(printed_might_auras=[
                {"amount": 2, "condition": {"kind": "nope"}}])),
            ("a template carrying its controller", lambda s: s["objects"]["x1"].update(printed_replacements=[
                {**GUARD[0], "controller": "p1"}])),
            ("a Battlefield's bonus at another", lambda s: s["battlefields"]["bf1"].update(printed_damage_modifiers=[
                {"amount": 1, "scope": {"kind": "location", "battlefield": "bf2"}}]))):
        bad = mid_game(False)
        change(bad)
        if not IR.validate_state(bad):
            fail("V shape", f"{label} validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: printed statics")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a card's own printed Might statics, Bonus Damage, Might aura and Replacement Effects work once it is played "
          "in a mid-game state - read live from the object or materialized as it enters, gone when it leaves, back when "
          "played again - and give what the legacy forms gave for a card on the Board from the start (S1-S6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
