#!/usr/bin/env python3
"""A trash-working triggered ability that discards to return itself (package 11, Super Mega Death Rocket!: "When you
conquer, you may discard 1 to return this from your trash to your hand.").

"You may discard 1 to ..." opens the effect, so discarding is the ability's base cost (Core 383.3.b), paid as it is
finalized (383.3.b.1): the payer chooses the card from their hand then (trigger_finalization), and with none to discard
the cost cannot be paid and the ability leaves the Chain (203.3, 405.2). "Return this from your trash to your hand" is
the program's own source (return_to_hand self {from: trash}), as its chain item recorded it: still there, it goes to its
owner's hand as a new object; gone, or back as a new object, the instruction is ignored - the discard stays paid, and no
other card is taken (GPT 2026-10-12 PACKAGE11 ruling 6).

  P1 paid          the card chosen at finalization is discarded; resolved, the card is in its owner's hand, a new object
  P2 declined      the "you may" declined: nothing discarded, the card stays in the trash
  P3 nothing       an empty hand: the cost cannot be paid - removed, nothing happens
  P4 stage         the discard chosen for play_declaration: refused
  P5 gone          paid, then the card recycled out of the trash before resolution: the return ignored, the discarded
                   card still in the trash, the recycled card left where it is
  P6 new object    paid, then the card left and came back to the trash (a new object): the return ignored
  V  shape         a discard without an amount, a zero amount, self from the hand, and self beside a target: refused

    python skill/scripts/check_trigger_discard_return_self.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_trigger_cost import choose, cost, pending, program, resolve  # noqa: E402
from effect_ir import _bump_identity, object_identity, validate_program  # noqa: E402
from resolution_bridge import finalize_trigger  # noqa: E402

errors: list[str] = []
PROG = program("smdr-conquer-effects", "smdr", [cost({"kind": "discard", "amount": 1}),
                                                {"op": "return_to_hand", "effect_id": "ret", "self": {"from": "trash"}}])
REG = {PROG["program_id"]: PROG}
DISCARD = "cost:trigger:smdr-trig:trigger:discard"


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def board(hand=("h1", "h2")):
    state = base_state()
    state["objects"]["smdr"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["trash"].append("smdr")
    for h in hand:
        state["objects"][h] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
        state["players"]["p1"]["zones"]["hand"].append(h)
    return state


def paid(state, pick="h1"):
    return finalize_trigger(pending(state, "smdr", PROG), state, REG, choose(state, DISCARD, pick),
                            perform_optional_trigger=True, pay_trigger_cost=True)


def zones(state):
    z = state["players"]["p1"]["zones"]
    return {"hand": sorted(z["hand"]), "trash": sorted(z["trash"]), "main_deck": list(z["main_deck"])}


def main() -> int:
    s = board()
    fin = paid(s)
    if not fin.get("committed") or fin.get("removed"):
        fail("P1 paid", f"not finalized: {fin.get('reason')} {fin.get('transition')}")
    else:
        after_fin = fin["next_effect_state"]
        if "h1" not in after_fin["players"]["p1"]["zones"]["trash"]:
            fail("P1 paid", f"h1 not discarded: {zones(after_fin)}")
        done = resolve(fin, REG, "smdr-trig")
        if not done.get("committed") or "smdr" not in done["next_effect_state"]["players"]["p1"]["zones"]["hand"]:
            fail("P1 paid", f"not returned: {done.get('reason')} {zones(done.get('next_effect_state') or after_fin)}")
        elif object_identity(done["next_effect_state"], "smdr") == object_identity(s, "smdr"):
            fail("P1 paid", "the card in hand is not a new object")
    declined = finalize_trigger(pending(s, "smdr", PROG), s, REG, None, perform_optional_trigger=False)
    if (declined.get("transition") or {}).get("type") != "optional_trigger_declined" \
            or zones(declined.get("next_effect_state") or s) != zones(s):
        fail("P2 declined", f"{declined.get('transition')} {zones(declined.get('next_effect_state') or s)}")
    empty = board(hand=())
    cannot = finalize_trigger(pending(empty, "smdr", PROG), empty, REG, None, perform_optional_trigger=True, pay_trigger_cost=True)
    if not cannot.get("removed") or zones(cannot.get("next_effect_state") or empty) != zones(empty):
        fail("P3 nothing", f"{cannot.get('reason')} {cannot.get('transition')}")
    wrong = finalize_trigger(pending(s, "smdr", PROG), s, REG, choose(s, DISCARD, "h1", stage="play_declaration"),
                             perform_optional_trigger=True, pay_trigger_cost=True)
    if wrong.get("committed") and not wrong.get("removed"):
        fail("P4 stage", "a discard chosen for play_declaration was accepted")
    fin = paid(s)
    if fin.get("committed") and not fin.get("removed"):
        moved = copy.deepcopy(fin)
        st = moved["next_effect_state"]
        st["players"]["p1"]["zones"]["trash"].remove("smdr")
        st["players"]["p1"]["zones"]["main_deck"].append("smdr")
        done = resolve(moved, REG, "smdr-trig")
        z = zones(done.get("next_effect_state") or st)
        step = next((e for e in ((done.get("effect_result") or {}).get("trace") or []) if e.get("effect_id") == "ret"), {})
        if not done.get("committed") or "smdr" in z["hand"] or "h1" not in z["trash"] or z["main_deck"][-1:] != ["smdr"]:
            fail("P5 gone", f"{done.get('reason')} {z}")
        elif step and step.get("reason") != "source_not_in_zone":
            fail("P5 gone", f"not ignored as gone from its zone: {step}")
        back = copy.deepcopy(fin)
        st = back["next_effect_state"]
        _bump_identity(st, "smdr")
        done = resolve(back, REG, "smdr-trig")
        if not done.get("committed") or "smdr" in done["next_effect_state"]["players"]["p1"]["zones"]["hand"]:
            fail("P6 new object", f"a new object in the trash was returned: {done.get('reason')}")
    for label, effects in (
            ("a discard without an amount", [cost({"kind": "discard"}), PROG["effects"][1]]),
            ("a zero discard", [cost({"kind": "discard", "amount": 0}), PROG["effects"][1]]),
            ("self from the hand", [PROG["effects"][0], {"op": "return_to_hand", "effect_id": "ret", "self": {"from": "hand"}}]),
            ("self beside a target", [PROG["effects"][0], {"op": "return_to_hand", "effect_id": "ret", "self": {"from": "trash"},
                                                            "object_id": "smdr"}])):
        if not validate_program(program("x", "smdr", effects)):
            fail("V shape", f"{label} validated")
    if errors:
        print("FAILED: trigger discard / return-self checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a trash-working trigger's 'discard 1 to return this' - the discard chosen and paid as it is finalized, the "
          "card returned as a new object; declined or nothing to discard, nothing happens; a discard chosen for the play "
          "is refused; the card gone from its trash or a new object, the return ignored and the discard still paid (P1-P6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
