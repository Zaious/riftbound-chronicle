#!/usr/bin/env python3
"""A permanent that forbids its controller's opponents' facedown cards being revealed where it is (package 12, Noxus
Saboteur: "Your opponents' [Hidden] cards can't be revealed here.").

The reading is the site owner's (2026-10-14), a provisional reading and not a published ruling: an opponent playing a
card from facedown turns it face up - a reveal - so at the battlefield the source is at, that play is not open to them.
A facedown card changing zones is still shown as it goes (Core 422.4, the zone change's own procedure, not something a
player does to it); the restriction reaches no card elsewhere, and a card merely mentioning the keyword is untouched
(the Origins FAQ: the Saboteur mentions Hidden without having it). Core 2026-10-09 811.5.a (while face down it does not
count as having the keyword) reads the same way: the card becomes one with Hidden as it is turned face up, which is the reveal
forbidden here.

  S1 forbidden     p1's card hidden at bf1 last turn; p2's Saboteur at bf1: p1 playing it from facedown is refused
                   (hidden_reveal_prohibited)
  S2 elsewhere     the Saboteur at bf2: the play is made
  S3 its own side  the Saboteur is p1's: the play is made
  S4 no flag       the same unit without the restriction: the play is made
  S5 zone change   a p2 card facedown at p1's battlefield with p1's Saboteur there: the Cleanup still moves it to its
                   owner's Trash (shown as it goes) - the restriction stops a play, not the zone change
  G  grammar       the card's line lowers to the flag; near misses do not
  V  validation    the flag is true when present

    python skill/scripts/check_hidden_reveal_restriction.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_cleanup_recall import board as cleanup_board, permanent, step_five  # noqa: E402
from check_costs_and_activation import declaration  # noqa: E402
from check_effect_ir import settle_contested  # noqa: E402
from check_hidden import hide_declaration, hideable  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from hidden import hide_card  # noqa: E402
from play_transaction import play_card  # noqa: E402

FLAG = "prevents_opponent_hidden_reveals_here"
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def hidden_board(*, where="bf1", owner="p2", flag=True):
    """p1's c1 hidden at bf1 last turn; a Saboteur `sab` at `where`, controlled by `owner`."""
    timing = fixture()
    state = hide_card(timing, hideable(), hide_declaration())["next_effect_state"]
    state["turn_id"] = "turn-2"
    state["battlefields"].setdefault("bf2", {"controller": None, "objects": []})
    state["objects"]["sab"] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [],
                               "damage": 0, "exhausted": False, **({FLAG: True} if flag else {})}
    state["battlefields"][where]["objects"].append("sab")
    return timing, settle_contested(state)


def play(timing, state):
    return play_card(timing, state, declaration(source={"kind": "facedown", "battlefield": "bf1"},
                                                cost_override={"kind": "ignore_base_cost", "source": "hidden"},
                                                payment_context=None))


def main() -> int:
    timing, state = hidden_board()
    if validate_state(state):
        fail("board", validate_state(state)[:2])
        return report()
    refused = play(timing, state)
    if refused.get("committed") or refused.get("reason_code") != "hidden_reveal_prohibited":
        fail("S1 forbidden", f"{refused.get('committed')} {refused.get('reason_code')} {refused.get('reason')}")
    for label, kwargs in (("S2 elsewhere", {"where": "bf2"}), ("S3 its own side", {"owner": "p1"}),
                          ("S4 no flag", {"flag": False})):
        t, s = hidden_board(**kwargs)
        made = play(t, s)
        if not made.get("committed"):
            fail(label, f"{made.get('reason_code')} {made.get('reason')}")
    # S5: the Cleanup's zone change still happens
    c = cleanup_board()
    c["objects"]["sab"] = {**permanent("p1", "unit"), FLAG: True}
    c["battlefields"]["bf1"]["objects"].append("sab")
    c = settle_contested(c)
    done = step_five(c)
    if not done.get("committed") or "h_intruder" not in done["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        fail("S5 zone change", f"{done.get('reason')} the opponent's facedown card was not moved to its Trash")
    # G
    grammar = cg.load_grammar()
    card = cg.compile_card([{"text": "Your opponents' [Hidden] cards can't be revealed here."}], grammar)
    if card.get("unsupported_clauses") or (card.get("passive") or {}).get("object_fields") != {FLAG: True}:
        fail("G grammar", f"{card.get('unsupported_clauses')} {(card.get('passive') or {}).get('object_fields')}")
    for near in ("Your [Hidden] cards can't be revealed here.", "Your opponents' cards can't be revealed here."):
        if not cg.compile_card([{"text": near}], grammar).get("unsupported_clauses"):
            fail("G grammar", f"a near miss lowered: {near}")
    # V
    _, bad = hidden_board()
    bad["objects"]["sab"][FLAG] = False
    if not validate_state(bad):
        fail("V validation", "the flag was accepted as false")
    return report()


def report() -> int:
    if errors:
        print("FAILED: the facedown-reveal restriction")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: an opponent's facedown card cannot be played (turned face up) at the battlefield the restriction's source "
          "is at; elsewhere, on its own side or without the flag the play is made; the Cleanup's zone change still moves "
          "an opponent's facedown card (S1-S5, G, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
