#!/usr/bin/env python3
"""The next spell played this turn deals Bonus Damage (package 9, Ravenborn Tome).

":rb_exhaust:: The next spell you play this turn deals 1 Bonus Damage. (Each instance of damage the spell deals is
increased by 1.)" GPT 2026-10-06 (PACKAGE9_INVENTORY section 7, ruling 15): the first spell its controller plays
after this, this turn; each of that spell's own Deals gets +1.

The engine's shape: grant_turn_effect next_spell_bonus_damage {value N} - a next-card turn effect (Core 390.4, 391).
The play of the controller's next spell spends it and binds a Bonus Damage (713-715) to that spell: bonus scope
source_card {object, identity} - a Deal whose program's source is that object, with that identity, gets +N.

  B1 next spell   the next spell's Deal of 2 deals 3, its two Deals each get +1; the turn effect is spent
  B2 only once    the spell after it deals its printed 2
  B3 not others   a Deal of another source (a gear's ability) while the bonus is bound deals its printed 2
  B4 opponent     the opponent's spell played first does not spend it; the controller's next one still has it
  B5 this turn    unspent, the turn's Expiration Step ends it
  B6 split        the bound spell's split Deal is refused by name (715.3 with 355.14.c not modelled); another
                  source's split gets nothing from it
  S  shapes       a value of 0 refused; the state validator refuses a non-integer value

    python skill/scripts/check_next_spell_bonus.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, split_bonus_damage, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program, run_expiration_step  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def board() -> dict:
    state = base_state()
    state["turn_id"] = "turn-4"
    for player, spells in (("p1", ("bolt1", "bolt2")), ("p2", ("obolt",))):
        for spell in spells:
            state["objects"][spell] = {"owner": player, "controller": player, "kind": "spell", "base_might": 0,
                                       "might_modifiers": [], "damage": 0, "exhausted": False,
                                       "printed_cost": {"energy": 1, "power": {}}}
            state["players"][player]["zones"].setdefault("hand", []).append(spell)
        state["players"][player]["resources"] = {"energy": 3, "power": {}}
    state["objects"]["big"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 20, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
    state["players"]["p2"]["zones"]["base"].append("big")
    assert not validate_state(state), validate_state(state)
    return state


def tome(state: dict, value=1) -> dict:
    return apply_program(state, program("tome", {"op": "grant_turn_effect", "effect_id": "g",
                                                 "turn_effect_kind": "next_spell_bonus_damage", "value": value,
                                                 "controller": "p1", "source": "tome"}))


def spell_program(spell: str, controller: str, deals: int = 1) -> dict:
    effects = [{"op": "deal_damage", "effect_id": f"d{i}", "object_id": "big", "amount": 2} for i in range(deals)]
    return {**program(f"{spell}-effects", *effects), "controller": controller, "source_object": spell}


def cast(state: dict, spell: str, controller: str, deals: int = 1) -> dict:
    prog = spell_program(spell, controller, deals)
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": f"play-{spell}", "actor": controller,
            "card": spell, "effect_program_id": prog["program_id"],
            "chain_item": {"id": f"spell-{spell}", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "payment_context": CLOSED}
    timing = fixture()
    if controller == "p2":
        timing = {**timing, "turn_player": "p2", "priority": "p2"}
    played = play_card(timing, state, decl, effect_program=prog)
    if not played.get("committed"):
        return {"refused": played.get("reason_code") or played.get("reason")}
    t = played["next_timing_state"]
    if next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = finalize_oldest_pending(t)["next_state"]
    for actor in (controller, "p1" if controller == "p2" else "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    done = resolve_with_program(t, f"spell-{spell}", played["next_effect_state"], prog)
    return done


def dmg(done: dict) -> int | None:
    state = done.get("next_effect_state")
    return None if state is None else state["objects"]["big"]["damage"]


def main() -> int:
    granted = tome(board())
    if not granted.get("committed"):
        print(f"FAILED: the turn effect was not granted: {granted.get('reason') or granted.get('errors')}")
        return 1
    s = granted["next_state"]
    # B1
    first = cast(s, "bolt1", "p1", deals=2)
    if dmg(first) != 6:
        fail("B1 next spell", f"two Deals of 2 dealt {dmg(first)} in all, not 3 + 3 ({first.get('reason') or first.get('refused')})")
    elif any(e.get("kind") == "next_spell_bonus_damage" for e in first["next_effect_state"].get("turn_effects", []) or []):
        fail("B1 spent", "the turn effect is still there after the next spell was played")
    else:
        # B2
        second = cast(first["next_effect_state"], "bolt2", "p1")
        if dmg(second) != 6 + 2:
            fail("B2 only once", f"the spell after it dealt {dmg(second) - 6 if dmg(second) is not None else second}")
        # B3: another source while the bonus is bound to bolt1's identity
        other = apply_program(first["next_effect_state"], {**program("gear-ability", {"op": "deal_damage", "effect_id": "g",
                                                                                      "object_id": "big", "amount": 2}),
                                                           "source_object": "u1"})
        if not other.get("committed") or other["next_state"]["objects"]["big"]["damage"] != 6 + 2:
            fail("B3 not others", f"{other.get('reason')} {other.get('next_state', {}).get('objects', {}).get('big')}")
    # B4: the opponent's spell first
    theirs = cast(s, "obolt", "p2")
    if dmg(theirs) != 2:
        fail("B4 opponent", f"the opponent's spell dealt {dmg(theirs)} ({theirs.get('reason') or theirs.get('refused')})")
    elif not any(e.get("kind") == "next_spell_bonus_damage" for e in theirs["next_effect_state"].get("turn_effects", []) or []):
        fail("B4 opponent", "the opponent's spell spent p1's next-spell effect")
    # B5
    timing = fixture()
    timing.update({"phase": "ending", "priority": None, "ending_step": {"status": "triggers_scheduled", "turn_id": "turn-4"}})
    expired = run_expiration_step(timing, s)
    after = (expired or {}).get("next_effect_state")
    if after is None or any(e.get("kind") == "next_spell_bonus_damage" for e in after.get("turn_effects", []) or []):
        fail("B5 this turn", f"unspent, it outlived the turn: {expired and expired.get('reason')}")
    # B6: the bound spell's split Deal - refused by name; another source's split is not touched
    if first.get("next_effect_state") is not None:
        bound = first["next_effect_state"]
        try:
            split_bonus_damage(bound, "p1", ["big"], source_object="bolt1")
            fail("B6 split", "a split Deal of the bound spell was not refused")
        except NotImplementedError as exc:
            if "next_spell_bonus_damage" not in str(exc):
                fail("B6 split", f"refused, but not by name: {exc}")
        if split_bonus_damage(bound, "p1", ["big"], source_object="u1")[0] != 0:
            fail("B6 split", "another source's split Deal got the bound spell's Bonus Damage")
    # S
    if tome(board(), value=0).get("committed"):
        fail("S shapes", "a value of 0 was accepted")
    bad = board()
    bad["turn_effects"] = [{"effect_id": "x", "kind": "next_spell_bonus_damage", "controller": "p1", "value": "1",
                            "turn_id": "turn-4", "source": "tome"}]
    if not validate_state(bad):
        fail("S shapes", "a non-integer value passed the state validator")
    # G: the clause grammar lowers the sentence to exactly that turn effect; near misses stay unparsed
    import clause_grammar as CG
    lowered = CG.compile_clause("The next spell you play this turn deals 1 Bonus Damage.", CG.load_grammar())
    if lowered.get("unsupported") or [(e.get("op"), e.get("turn_effect_kind"), e.get("value"))
                                      for e in lowered.get("program_effects") or []] != [
            ("grant_turn_effect", "next_spell_bonus_damage", 1)]:
        fail("G grammar", f"{lowered.get('production_id')} {lowered.get('program_effects')}")
    for near in ("Your spells and abilities deal 1 Bonus Damage this turn.", "The next unit you play this turn deals 1 Bonus Damage."):
        if not CG.compile_clause(near, CG.load_grammar()).get("unsupported"):
            fail("G grammar", f"{near!r} was parsed")
    if errors:
        print("FAILED: next spell bonus damage checks")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("OK: the next spell played this turn deals its Bonus Damage, that spell only (B1-B6, S, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
