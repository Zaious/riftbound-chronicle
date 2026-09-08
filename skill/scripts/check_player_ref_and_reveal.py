#!/usr/bin/env python3
"""Regression gate for a player referent bound to a reveal (Sabotage).

    "Choose an opponent. They reveal their hand.
     Choose a non-unit card from it, and recycle that card."

Three clauses, two references. "They" is the opponent the first clause chose,
and "it" is the hand the second clause revealed. Codex's contract asks for a
player referent, a closed `excluded_kinds`, a binding to the same reveal
receipt, and counterexamples for private information and a stale identity.

The three ways this goes wrong, and what stops each:

  - **the hand is read before it is revealed.** A choice "from it" that read
    the zone would see every card in an opponent's hand - the single worst
    failure this engine can have. The candidates come from the reveal's own
    marks, so before the reveal there are none, and a card that was never
    revealed can never be named.
  - **"they" is recomputed.** With one opponent, defaulting is invisible and
    correct; with two, it silently picks. The reference is to the *decision*
    the first clause recorded, and a clause that names a player nobody chose
    does not compile.
  - **the mark outlives the card.** A reveal mark carries the identity the
    object had when it was revealed. If the card leaves and returns it is a
    different object (359.3.e.4), and the state carrying the old mark is
    invalid rather than quietly choosable.

Every fixture here is synthetic. The three-player board is there so that
"they" has something to get wrong.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from effect_ir import apply_program, hash_value, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402
from effect_ir import PROGRAM_VERSION, STATE_VERSION  # noqa: E402

CLAUSES = [{"text": "Choose an opponent."},
           {"text": "They reveal their hand."},
           {"text": "Choose a non-unit card from it, and recycle that card."}]


def card(owner, kind):
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": 0,
            "might_modifiers": [], "damage": 0, "exhausted": False}


def table():
    """Three players, so "they" cannot be defaulted. p2 holds a Unit and two
    non-Units; p3 holds a card the gate must never be able to reach."""
    return {
        "schema_version": STATE_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "players": {
            "p1": {"zones": {"main_deck": ["d1"], "hand": [], "trash": [], "banishment": [],
                             "base": [], "rune_deck": []},
                   "resources": {"energy": 0, "power": {}}},
            "p2": {"zones": {"main_deck": ["d2"], "hand": ["h_unit", "h_spell", "h_gear"], "trash": [],
                             "banishment": [], "base": [], "rune_deck": []},
                   "resources": {"energy": 0, "power": {}}},
            "p3": {"zones": {"main_deck": ["d3"], "hand": ["h_other"], "trash": [], "banishment": [],
                             "base": [], "rune_deck": []},
                   "resources": {"energy": 0, "power": {}}},
        },
        "objects": {"d1": card("p1", "spell"), "d2": card("p2", "spell"), "d3": card("p3", "spell"),
                    "h_unit": card("p2", "unit"), "h_spell": card("p2", "spell"),
                    "h_gear": card("p2", "gear"), "h_other": card("p3", "spell")},
        "battlefields": {}, "replacement_effects": [],
    }


def bind(value, bindings):
    if isinstance(value, dict):
        return {k: bind(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    return bindings.get(value, value) if isinstance(value, str) else value


def sabotage_program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "sabotage", "controller": "p1", "source_object": "d1",
            "effects": bind(copy.deepcopy(effects), {"$controller": "p1"})}


def decisions(state, *entries):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": list(entries)}


def pick_player(value, controller="p1"):
    return {"decision_id": "chosen-opponent", "kind": "player_selection", "stage": "resolution",
            "controller": controller, "value": value}


def pick_card(object_id, identity, controller="p1"):
    return {"decision_id": "sabotage-card", "kind": "card_selection", "stage": "resolution",
            "controller": controller, "value": [object_id],
            "selection_identities": {object_id: identity}}


def main() -> int:
    errors: list[str] = []
    grammar = cg.load_grammar()

    # --- the card compiles, and only in this order --------------------------------------------------
    compiled = cg.compile_card(CLAUSES, grammar)
    if any(c.get("unsupported") for c in compiled["clauses"]):
        print("FAILED: player ref / reveal checks")
        print(f"  - Sabotage did not compile: {compiled['unsupported_clauses']}")
        return 1
    effects = compiled["program_effects"]
    if [e["op"] for e in effects] != ["choose_player", "reveal", "recycle"]:
        errors.append(f"the card does not do what it says, in order: {[e['op'] for e in effects]}")
    if effects[1].get("player") != {"decision_ref": effects[0]["decision_ref"]}:
        errors.append(f"'they' is not the player the first clause chose: {effects[1].get('player')}")
    if effects[2]["choice"].get("criteria", {}).get("excluded_kinds") != ["unit"]:
        errors.append(f"'a non-unit card' is not a closed kind exclusion: {effects[2]['choice']}")
    if effects[2]["choice"].get("from") != "revealed":
        errors.append(f"the choice reads a zone rather than the reveal: {effects[2]['choice']}")

    for order, expected in (([1, 0, 2], "player_ref_not_declared"), ([0, 2, 1], "reveal_not_declared")):
        shuffled = cg.compile_card([CLAUSES[i] for i in order], grammar)
        codes = [c.get("reason_code") for c in shuffled["clauses"] if c.get("unsupported")]
        if expected not in codes:
            errors.append(f"clauses in order {order} compiled anyway; expected {expected}, got {codes}")

    # --- private information: nothing is choosable before the reveal --------------------------------
    state = table()
    if validate_state(state):
        errors.append(f"the table fixture is not a valid state: {validate_state(state)}")
    before_reveal = apply_program(state, sabotage_program([effects[0], effects[2]]),
                                  decisions=decisions(state, pick_player("p2")))
    recycled = [t for t in before_reveal.get("trace", []) if t.get("op") == "recycle"]
    if not recycled or recycled[0].get("outcome") != "no_op":
        errors.append(f"a choice from an unrevealed hand found something: {recycled}")
    if before_reveal.get("choice"):
        errors.append(f"the engine offered a choice with nothing revealed: {before_reveal['choice']}")
    after = before_reveal.get("next_state") or state
    if sorted(after["players"]["p2"]["zones"]["hand"]) != ["h_gear", "h_spell", "h_unit"]:
        errors.append("a card left an opponent's hand with no reveal in front of it")

    # --- with the reveal, the candidates are exactly the revealed non-Units --------------------------
    run = apply_program(state, sabotage_program(effects), decisions=decisions(state, pick_player("p2")))
    if run.get("committed"):
        errors.append("the card resolved without anyone choosing which card to recycle")
    choice = run.get("choice") or {}
    if run.get("reason_code") != "card_selection_required":
        errors.append(f"the card resolved without a card being chosen: {run.get('reason_code')}")
    # The options are private to the chooser (128.4), so the summary carries a
    # count and a hash rather than the ids. Two candidates is the whole claim:
    # three revealed cards minus the Unit.
    if choice.get("options_count") != 2:
        errors.append(f"the choosable cards are not the two revealed non-Units: {choice}")
    if choice.get("options_visible_to") != ["p1"]:
        errors.append(f"the options of a private choice were offered to somebody else: {choice}")
    revealed = [t for t in run.get("trace", []) if t.get("op") == "reveal"]
    shown = [r["object_id"] for r in (revealed[0].get("revealed") if revealed else [])]
    if sorted(shown) != ["h_gear", "h_spell", "h_unit"]:
        errors.append(f"the reveal did not show the chosen opponent's whole hand: {shown}")
    if "h_other" in shown:
        errors.append("a third player's hand was revealed; 'they' was not honoured")

    # --- and the whole card runs -------------------------------------------------------------------
    done = apply_program(state, sabotage_program(effects),
                         decisions=decisions(state, pick_player("p2"), pick_card("h_spell", "h_spell@0")))
    if not done.get("committed"):
        errors.append(f"Sabotage did not resolve: {done.get('reason') or done.get('errors')}")
    else:
        after = done["next_state"]
        if "h_spell" in after["players"]["p2"]["zones"]["hand"]:
            errors.append("the chosen card was not recycled out of the hand")
        if "h_spell" not in after["players"]["p2"]["zones"]["main_deck"]:
            errors.append(f"the recycled card did not go to its owner's Main Deck: "
                          f"{after['players']['p2']['zones']['main_deck']}")
        if sorted(after["players"]["p2"]["zones"]["hand"]) != ["h_gear", "h_unit"]:
            errors.append(f"the rest of the hand changed: {after['players']['p2']['zones']['hand']}")
        if after["players"]["p3"]["zones"]["hand"] != ["h_other"]:
            errors.append("the third player's hand was touched")

    # --- choosing a Unit is refused ------------------------------------------------------------------
    unit_pick = apply_program(state, sabotage_program(effects),
                              decisions=decisions(state, pick_player("p2"), pick_card("h_unit", "h_unit@0")))
    if unit_pick.get("committed"):
        errors.append("a Unit was recycled despite 'a non-unit card'")
    # and so is a card that was never revealed
    other_pick = apply_program(state, sabotage_program(effects),
                               decisions=decisions(state, pick_player("p2"), pick_card("h_other", "h_other@0")))
    if other_pick.get("committed"):
        errors.append("a card from an unrevealed hand was recycled")

    # --- "they" belongs to the chooser, and to this program's controller ----------------------------
    wrong = apply_program(state, sabotage_program(effects),
                          decisions=decisions(state, pick_player("p2", controller="p2")))
    if wrong.get("committed") or wrong.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"somebody else chose the opponent: {wrong.get('reason_code')}")
    self_pick = apply_program(state, sabotage_program(effects), decisions=decisions(state, pick_player("p1")))
    if self_pick.get("committed"):
        errors.append("the controller chose themself as 'an opponent'")

    # --- a stale reveal mark is not a choosable card ------------------------------------------------
    stale = copy.deepcopy(state)
    stale["reveals"] = [{"object_id": "h_spell", "identity": "h_spell@0", "zone": "hand",
                         "visible_to": "all", "session": "old", "kind": "reveal"}]
    if validate_state(stale):
        errors.append(f"a fresh reveal mark was rejected: {validate_state(stale)}")
    stale["objects"]["h_spell"]["identity"] = "h_spell@1"   # the card left and came back (359.3.e.4)
    problems = validate_state(stale)
    if not any("stale identity" in problem for problem in problems):
        errors.append(f"a reveal mark surviving the card's identity change was accepted: {problems}")

    if errors:
        print("FAILED: player ref / reveal checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("player ref / reveal checks passed: nothing in a hand is choosable before the reveal, the "
          "candidates are the revealed non-Units of the chosen opponent only, a third player's hand is "
          "untouched, and a reveal mark that outlived the card's identity makes the state invalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
