#!/usr/bin/env python3
"""Regression gate for "Opponents can't play cards this turn." (Brynhir Thundersong's play
trigger; Core 054.1 Can't beats Can, 052 cards are Main Deck cards, 317.2.c).

Must hold:
  - the engine grammar lowers the sentence, alone and inside "When you play me, ...", to one
    grant_turn_effect of kind cards_play_prohibited, value opponents, controller $controller;
  - after p1's grant resolves on turn 3, p2 is refused a [Reaction] spell it could otherwise
    play in a Closed state (play_prohibited), and a Unit card on its own turn 3 likewise; the
    same plays without the grant commit (the refusal is the grant's, not the timing's);
  - p1 - the granting player - still plays its own cards;
  - an activated ability of p2's is not a card (052): it is not refused by the grant;
  - on turn 4 the grant stamped turn 3 forbids nothing;
  - the legal-action enumerator leaves p2's card out with the same reason;
  - a turn effect of this kind with any other value is refused by the validator, and so is a
    grant op asking for one.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import legal_action as LA  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import apply_program, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "Opponents can't play cards this turn."
WANT = [{"op": "grant_turn_effect", "effect_id": "grant", "turn_effect_kind": "cards_play_prohibited",
         "value": "opponents", "controller": "$controller", "source": "$chain_item"}]


def card(owner, kind, **extra):
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": 2 if kind == "unit" else 0,
            "might_modifiers": [], "damage": 0, "exhausted": False, **extra}


def board(*, grant: bool, turn="turn-3", grant_value="opponents"):
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["r2"] = card("p2", "spell", play_timing="reaction")
    state["objects"]["n2"] = card("p2", "unit")
    state["objects"]["s1"] = card("p1", "spell")
    state["players"]["p2"]["zones"]["hand"] += ["r2", "n2"]
    state["players"]["p1"]["zones"]["hand"].append("s1")
    for player in ("p1", "p2"):
        state["players"][player]["resources"] = {"energy": 5, "power": {}}
    if grant:
        effect = {**WANT[0], "controller": "p1", "source": "u1", "value": grant_value}
        done = apply_program(state, program("brynhir", effect))
        if not done.get("committed"):
            return None, done
        state = done["next_state"]
    state["turn_id"] = turn
    return state, None


def play(state, actor, card_id, kind, timing, timing_state):
    return PT.play_card(timing_state, state, {
        "schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": f"play-{card_id}", "actor": actor, "card": card_id,
        "chain_item": {"id": f"item-{card_id}", "object_kind": kind, "timing": timing},
        "cost": {"base": {"energy": 1, "power": {}}},
        **({"entry_location": {"kind": "base"}} if kind == "unit" else {}),
        "payment_context": {"add_window_closed": True, "confirmed_by": "human"}})


def activate(state, actor, source, timing_state):
    return PT.play_card(timing_state, state, {
        "schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": "activate-1", "actor": actor, "card": source,
        "chain_item": {"id": "ability-1", "object_kind": "ability", "timing": "default"},
        "activation": {"source_object": source, "ability_id": f"{source}:a1"},
        "cost": {"base": {"energy": 0, "power": {}}}})


def outcome(result):
    return "committed" if result.get("committed") else result.get("reason_code")


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    alone = CG.compile_clause(SENTENCE, grammar)
    wrapped = CG.compile_clause("When you play me, opponents can't play cards this turn.", grammar)
    if alone.get("production_id") != "opponents_cant_play_cards_this_turn" or alone.get("program_effects") != WANT:
        errors.append(f"the sentence did not lower to the prohibition: {alone.get('production_id')} {alone.get('program_effects')}")
    if wrapped.get("unsupported") or wrapped.get("program_effects") != WANT:
        errors.append(f"inside 'When you play me' it did not lower to the same program: {wrapped.get('reason_code')}")

    closed_p2 = fixture(items=[item("spell-9", "p1", "spell", "default")], priority="p2")
    closed_p1 = fixture(items=[item("spell-9", "p2", "spell", "default")], priority="p1")
    p2_turn = {**fixture(priority="p2"), "turn_player": "p2"}
    granted, refusal = board(grant=True)
    plain, _ = board(grant=False)
    if granted is None:
        errors.append(f"the grant did not commit: {refusal.get('reason') or refusal.get('errors')}")
    else:
        for label, state, want in (("with the grant", granted, "play_prohibited"), ("without it", plain, "committed")):
            got = outcome(play(state, "p2", "r2", "spell", "reaction", closed_p2))
            if got != want:
                errors.append(f"p2's [Reaction] spell in a Closed state, {label}: {got}, wanted {want}")
            got = outcome(play(state, "p2", "n2", "unit", "default", p2_turn))
            if got != want:
                errors.append(f"p2's Unit card on its turn, {label}: {got}, wanted {want}")
        own = outcome(play(granted, "p1", "s1", "spell", "default", fixture()))
        if own != "committed":
            errors.append(f"the granting player's own card was refused: {own}")
        ability_plain = outcome(activate(plain, "p2", "u2", p2_turn))
        ability_granted = outcome(activate(granted, "p2", "u2", p2_turn))
        if ability_plain != "committed" or ability_granted != "committed":
            errors.append(f"an activated ability is not a card (Core 052): with the grant {ability_granted}, "
                          f"without {ability_plain}")
        later, _ = board(grant=True, turn="turn-4")
        if outcome(play(later, "p2", "r2", "spell", "reaction", closed_p2)) != "committed":
            errors.append("the grant stamped turn 3 still forbade a play on turn 4")
        _, candidates = LA._enumerate_play_card(None, closed_p2, granted, "p2")
        summary, _ = LA._enumerate_play_card(None, closed_p2, granted, "p2")
        excluded = {e["object_id"]: e["reason_code"] for e in summary.get("excluded", [])}
        if excluded.get("r2") != "play_prohibited" or any(c["action"]["card"] == "r2" for c in candidates):
            errors.append(f"the enumerator offered p2's card under the grant: excluded {excluded}")
        forged = copy.deepcopy(granted)
        forged["turn_effects"][-1]["value"] = "everyone"
        if not validate_state(forged):
            errors.append("a cards_play_prohibited turn effect with value 'everyone' was accepted")
        bad, why = board(grant=True, grant_value="ready")
        if bad is not None:
            errors.append("a grant op asking for cards_play_prohibited with value 'ready' committed")

    if errors:
        print("FAILED: play prohibition" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'Opponents can't play cards this turn.' lowers to one turn effect; after it, the opponent is refused a "
          "card play it could otherwise make (a Reaction spell, a Unit on its own turn) and the grantor is not; an "
          "activated ability is untouched (052); the next turn it forbids nothing; the enumerator agrees; other values "
          "are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
