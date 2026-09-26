#!/usr/bin/env python3
"""Delayed passives for the NEXT card played this turn (Core 390.4, 391).

  "the next spell you play this turn costs :rb_energy_5: less."   (Raging Firebrand)
  "The next unit you play this turn enters ready."                  (Sun Disc)

Each is a turn effect (grant_turn_effect) the engine grammar lowers verbatim; the play
transaction applies it to the next card of that kind its controller plays this turn and spends
it there, whether or not it changed anything.

Must hold, through real play_card (and resolve_with_program for units):
  spell discount  a 6-Energy spell with 1 Energy in the pool: played, 1 paid, the effect gone;
                  the spell after it pays in full; a 3-Energy spell: 0 paid (356.6), the effect
                  gone; a unit played first is not discounted and does not spend it; the
                  opponent's spell does not; next turn it does nothing; two of them on one
                  spell: both apply (-10) and both are spent
  next unit       the unit played next enters ready and the effect is spent at the play; the
                  unit after it enters exhausted; a spell played first does not spend it; the
                  opponent's unit does not; a unit already on the chain when the effect is made
                  is not "the next unit you play" and enters exhausted; the next unit countered
                  back to hand and played again - under a new chain item id or the same one -
                  enters exhausted, and so does the next unit that entered ready, was bounced and
                  is played again under the same id (the replacement ends with the play it was
                  bound to, 2026-09-28)
  ids             a second next-spell grant after a spent next-unit effect does not reuse the
                  live grant's id; both discounts apply and are spent (review 5 R2-7)
  validator       a next-spell discount with no positive Energy value is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import apply_program, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TURN = "turn-7"


def lowered(text):
    got = CG.compile_clause(text, CG.load_grammar())
    effects = [dict(e, controller="p1", source="firebrand") for e in got.get("program_effects") or []]
    return got, effects


def granted(state, effects):
    done = apply_program(state, program("grant", *copy.deepcopy(effects)))
    assert done.get("committed"), done.get("reason") or done.get("errors")
    return done["next_state"]


def board():
    state = base_state()
    state["turn_id"] = TURN
    for card, kind, owner in (("sp6", "spell", "p1"), ("sp3", "spell", "p1"), ("spb", "spell", "p1"),
                              ("un1", "unit", "p1"), ("un2", "unit", "p1"), ("osp", "spell", "p2"), ("oun", "unit", "p2")):
        state["objects"][card] = {"owner": owner, "controller": owner, "kind": kind, "base_might": 2 if kind == "unit" else 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False}
        state["players"][owner]["zones"]["hand"].append(card)
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    state["players"]["p2"]["resources"] = {"energy": 6, "power": {}}
    return state


def declaration(card, kind, energy, actor="p1", item_id=None):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"play-{card}", "actor": actor, "card": card,
            "chain_item": {"id": item_id or f"item-{card}", "object_kind": kind, "timing": "default"},
            "cost": {"base": {"energy": energy, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if kind == "unit":
        decl["entry_location"] = {"kind": "base"}
    else:
        decl["effect_program_id"] = f"prog-{card}"
    return decl


def spell_program(card, actor="p1"):
    doc = program(f"prog-{card}", {"op": "draw", "effect_id": "dr", "player": actor, "count": 1})
    doc["controller"] = actor
    return doc


def play(state, card, kind, energy, actor="p1"):
    timing = fixture()
    if actor == "p2":
        timing["turn_player"] = "p2"
        timing["priority"] = "p2"
        timing["turn_order"] = ["p2", "p1"]
    return play_card(timing, state, declaration(card, kind, energy, actor),
                     effect_program=spell_program(card, actor) if kind == "spell" else None)


def paid(result, actor="p1"):
    before = result["input_energy"]
    return before - result["next_effect_state"]["players"][actor]["resources"]["energy"]


def run(state, card, kind, energy, actor="p1"):
    got = play(state, card, kind, energy, actor)
    if got.get("committed"):
        got["input_energy"] = state["players"][actor]["resources"]["energy"]
    return got


def kinds(state, kind):
    return [e for e in state.get("turn_effects", []) or [] if e.get("kind") == kind]


def enters(state, card, item_id):
    timing = fixture(priority="p2", items=[item(item_id, "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    done = resolve_with_program(timing, item_id, state, None)
    return done, (done.get("next_effect_state") or {}).get("objects", {}).get(card, {}).get("exhausted")


def main() -> int:
    errors: list[str] = []
    got, discount = lowered("When you play me, the next spell you play this turn costs :rb_energy_5: less.")
    want = [{"op": "grant_turn_effect", "effect_id": "grant", "turn_effect_kind": "next_spell_cost_reduction", "value": 5,
             "controller": "$controller", "source": "$chain_item"}]
    if got.get("production_id") != "when_you_play_me" or got.get("program_effects") != want:
        errors.append(f"Raging Firebrand's sentence did not lower to one next-spell discount of 5: {got}")
    start = board()
    if validate_state(start):
        print(f"FAILED: the board is invalid: {validate_state(start)}")
        return 1
    firebrand = granted(start, discount)
    if [e.get("value") for e in kinds(firebrand, "next_spell_cost_reduction")] != [5]:
        errors.append(f"the grant did not record one discount of 5: {firebrand.get('turn_effects')}")

    first = run(firebrand, "sp6", "spell", 6)
    if not first.get("committed") or paid(first) != 1 or kinds(first["next_effect_state"], "next_spell_cost_reduction"):
        errors.append(f"the next spell (6 Energy) should cost 1 and spend the discount: {first.get('reason')} "
                      f"{first.get('next_effect_state', {}).get('turn_effects')}")
    else:
        rich = copy.deepcopy(first["next_effect_state"])
        rich["players"]["p1"]["resources"]["energy"] = 6
        second = run(rich, "spb", "spell", 6)
        if not second.get("committed") or paid(second) != 6:
            errors.append("the spell after the next one was discounted too")
    cheap = run(firebrand, "sp3", "spell", 3)
    if not cheap.get("committed") or paid(cheap) != 0 or kinds(cheap["next_effect_state"], "next_spell_cost_reduction"):
        errors.append("a 3-Energy spell should cost 0 (356.6) and still spend the discount")
    unit_first = copy.deepcopy(firebrand)
    unit_first["players"]["p1"]["resources"]["energy"] = 2
    unit = run(unit_first, "un1", "unit", 2)
    if not unit.get("committed") or paid(unit) != 2 or not kinds(unit["next_effect_state"], "next_spell_cost_reduction"):
        errors.append("a unit was discounted, or spent the next-spell discount")
    theirs = run(firebrand, "osp", "spell", 6, actor="p2")
    if not theirs.get("committed") or paid(theirs, "p2") != 6 or not kinds(theirs["next_effect_state"], "next_spell_cost_reduction"):
        errors.append("the opponent's spell was discounted, or spent p1's discount")
    later = copy.deepcopy(firebrand)
    later["turn_id"] = "turn-8"
    later["players"]["p1"]["resources"]["energy"] = 6
    late = run(later, "sp6", "spell", 6)
    if not late.get("committed") or paid(late) != 6:
        errors.append("last turn's discount applied this turn")
    twice = granted(firebrand, discount)
    twice["players"]["p1"]["resources"]["energy"] = 0
    both = run(twice, "sp6", "spell", 6)
    if not both.get("committed") or paid(both) != 0 or kinds(both["next_effect_state"], "next_spell_cost_reduction"):
        errors.append(f"two discounts on one spell should both apply and both be spent: {both.get('reason')}")
    spent = run(firebrand, "sp6", "spell", 6)
    if spent.get("committed"):
        spent_state = copy.deepcopy(spent["next_effect_state"])
        spent_state["players"]["p1"]["resources"]["energy"] = 3
        if run(spent_state, "sp3", "spell", 3).get("committed") is not True or paid(run(spent_state, "sp3", "spell", 3)) != 3:
            errors.append("a spent discount applied again")

    # --- the next unit ---------------------------------------------------------------------
    got, ready = lowered("The next unit you play this turn enters ready.")
    if got.get("production_id") != "the_next_unit_you_play_this_turn_enters_ready":
        errors.append(f"Sun Disc's sentence did not lower: {got}")
    disc = granted(board(), ready)
    disc["players"]["p1"]["resources"]["energy"] = 4
    unit = run(disc, "un1", "unit", 2)
    if not unit.get("committed") or kinds(unit["next_effect_state"], "entry_state_for_next_played_unit"):
        errors.append(f"the next unit's play should spend the effect: {unit.get('reason')}")
    else:
        done, exhausted = enters(unit["next_effect_state"], "un1", "item-un1")
        if not done.get("committed") or exhausted is not False:
            errors.append(f"the next unit should enter ready: {done.get('reason')} exhausted={exhausted}")
        # it entered: the play is over, and the replacement with it - returned to hand and played
        # again under the same chain item id, it is a new object (Core 124) and enters exhausted
        if done.get("committed"):
            bounced = apply_program(done["next_effect_state"],
                                    program("bounce", {"op": "return_to_hand", "effect_id": "rt", "object_id": "un1"}))
            replay = play_card(fixture(), bounced["next_state"], declaration("un1", "unit", 2, item_id="item-un1")) \
                if bounced.get("committed") else {}
            if not replay.get("committed") or enters(replay["next_effect_state"], "un1", "item-un1")[1] is not True:
                errors.append(f"the next unit, entered ready, bounced and played again under the same chain item id "
                              f"entered ready again: {bounced.get('reason') or replay.get('reason')}")
        second = run(done["next_effect_state"], "un2", "unit", 2) if done.get("committed") else {}
        if second.get("committed"):
            _, exhausted2 = enters(second["next_effect_state"], "un2", "item-un2")
            if exhausted2 is not True:
                errors.append("the unit after the next one entered ready too")
        else:
            errors.append(f"the second unit could not be played: {second.get('reason')}")
    spell_first = copy.deepcopy(disc)
    spell_first["players"]["p1"]["resources"]["energy"] = 6
    spelled = run(spell_first, "sp6", "spell", 6)
    if not spelled.get("committed") or not kinds(spelled["next_effect_state"], "entry_state_for_next_played_unit"):
        errors.append("a spell spent the next-unit effect")
    theirs = run(disc, "oun", "unit", 2, actor="p2")
    if not theirs.get("committed") or not kinds(theirs["next_effect_state"], "entry_state_for_next_played_unit"):
        errors.append("the opponent's unit spent p1's next-unit effect")
    # a unit already played (on the chain) when the effect is made is not the NEXT unit played
    early = board()
    early["players"]["p1"]["resources"]["energy"] = 2
    on_chain = run(early, "un1", "unit", 2)
    if on_chain.get("committed"):
        after_grant = granted(on_chain["next_effect_state"], ready)
        _, exhausted = enters(after_grant, "un1", "item-un1")
        if exhausted is not True:
            errors.append("a unit played BEFORE the effect was made entered ready")
    else:
        errors.append(f"the early unit could not be played: {on_chain.get('reason')}")

    # review 5 R2-7a: the next unit played, then countered back to hand (Core 425.1) - the effect
    # was spent by that play and its replacement ends with it. Played again - under a new chain
    # item id, or the SAME id reused - it is a new object (Core 124) and enters exhausted. (The
    # replacement stayed on the card and applied again under a reused id before 2026-09-28.)
    countered_disc = granted(board(), ready)
    countered_disc["players"]["p1"]["resources"]["energy"] = 4
    first_play = run(countered_disc, "un1", "unit", 2)
    if not first_play.get("committed"):
        errors.append(f"the unit to be countered could not be played: {first_play.get('reason')}")
    else:
        counter = {**program("counter", {"op": "counter", "effect_id": "c", "chain_item_id": "item-un1", "card_to": "hand"}),
                   "controller": "p2"}
        back = apply_program(first_play["next_effect_state"], counter)
        if not back.get("committed") or "un1" not in back["next_state"]["players"]["p1"]["zones"]["hand"]:
            errors.append(f"the counter did not return un1 to hand: {back.get('reason') or back.get('errors')}")
        else:
            for item_id in ("item-un1-again", "item-un1"):
                again = play_card(fixture(), back["next_state"], declaration("un1", "unit", 2, item_id=item_id))
                if not again.get("committed"):
                    errors.append(f"un1 could not be played again as {item_id}: {again.get('reason')}")
                    continue
                _, exhausted = enters(again["next_effect_state"], "un1", item_id)
                if exhausted is not True:
                    errors.append(f"a countered next unit played again (chain item {item_id}) entered ready again")
    # review 5 R2-7b: turn-effect ids stay distinct when a spent one left the list - a next-unit
    # grant (serial 0), a next-spell grant (1), the unit played (spends 0), another next-spell
    # grant: it must not reuse the live one's id, and both discounts apply to the next spell
    mixed = granted(granted(board(), ready), discount)
    mixed["players"]["p1"]["resources"]["energy"] = 2
    spent_unit = run(mixed, "un1", "unit", 2)
    if not spent_unit.get("committed"):
        errors.append(f"the unit spending the next-unit effect could not be played: {spent_unit.get('reason')}")
    else:
        again = granted(spent_unit["next_effect_state"], discount)
        ids = [e["effect_id"] for e in kinds(again, "next_spell_cost_reduction")]
        again["players"]["p1"]["resources"]["energy"] = 0
        both = run(again, "sp6", "spell", 6)
        if len(ids) != 2 or len(set(ids)) != 2 or not both.get("committed") or paid(both) != 0 \
                or kinds(both["next_effect_state"], "next_spell_cost_reduction"):
            errors.append(f"a second next-spell grant after a spent next-unit effect reused a live id, or the two "
                          f"discounts did not both apply and both get spent: {ids} {both.get('reason')}")

    bad = program("bad", {"op": "grant_turn_effect", "effect_id": "g", "turn_effect_kind": "next_spell_cost_reduction",
                          "value": "ready", "controller": "p1", "source": "x"})
    if apply_program(board(), bad).get("committed"):
        errors.append("a next-spell discount with no Energy value was accepted")

    if errors:
        print("FAILED: next-card delayed passives" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'the next spell you play this turn costs [5] less' discounts exactly the next spell of its controller "
          "this turn (to 0 at most, 356.6) and is spent by it, two stack, units/opponents/next turn untouched; "
          "'the next unit you play this turn enters ready' binds to the next unit played after it and is spent there (391).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
