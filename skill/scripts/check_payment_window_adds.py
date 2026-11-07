#!/usr/bin/env python3
"""Regression gate (GPT's set 2 A2 review, blocker 3; Core 445.2.c): the answers decision_space gives a payment window
are every state the window can reach - any number of the payer's [Add] Reactions, any of them, whatever each adds - not
the fewest that cover what is due; where they cannot be listed whole, the window is unproved by name.

  A1 two Adds        pay 2 holding 1 Energy and two ready Fury Runes: the answer with both Runes' Energy Adds is listed;
                     applied, then paid, p1 holds 1 Energy (GPT's probe P3). The answers are exactly the states every
                     order of every subset of the Runes' activations reaches (each run through game_loop.payment_adds)
  A2 more than 1     one Rune adding 2 Energy, 0 held, 2 due: the window offers it (the old answers wanted two sources for
                     a shortfall of 2 and offered nothing); with 1 due it is still offered, beyond the shortfall
  A3 mixed           one Add adding 1 Energy and 1 Fury Power: offered, and the pool holds both after it
  A4 two abilities   one Fury Rune, two [Add]s (exhaust: Energy; recycle: Power): none, either, and exhaust then recycle -
                     four answers
  A5 an event        an [Add] whose cost kills its source, which carries a leave-the-board trigger: payment_adds refuses it
                     by name (payment_window_add_triggered) and the window is unproved - never answered without it
  A6 a choice        an [Add] whose program asks for a target: the window is unproved by name
  A7 the cap         the activations tried past WINDOW_CALL_CAP: unproved

    python skill/scripts/check_payment_window_adds.py
"""
from __future__ import annotations

import copy
import itertools
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_game_loop as CGL  # noqa: E402
import check_unless_pay as H  # noqa: E402
import closed_environment as CE  # noqa: E402
import decision_space as DS  # noqa: E402
import effect_ir as IR  # noqa: E402
import game_loop as GL  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402

errors: list[str] = []
EXHAUST = {"energy": 0, "power": {}, "exhaust": True}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def add(resource, amount, domain=None):
    return {"op": "add_resource", "effect_id": f"add-{resource}", "player": "$controller", "resource": resource,
            "amount": amount, **({"domain": domain} if domain else {})}


def catalogue() -> dict:
    cat = CGL.catalogue()
    row = lambda program, cost: {"cost": cost, "effect_program_id": program, "timing": "reaction", "ability_kind": "add"}
    cat["cards"].update({
        "Big Rune": {"object": {"kind": "rune", "domains": ["fury"]}, "activated_abilities": {"exhaust": row("two", EXHAUST)},
                     "programs": {"two": {"effects": [add("energy", 2)]}}},
        "Gem": {"object": {"kind": "gear", "domains": ["fury"]}, "activated_abilities": {"exhaust": row("both", EXHAUST)},
                "programs": {"both": {"effects": [add("energy", 1), add("power", 1, "fury")]}}},
        "Burner": {"object": {"kind": "gear", "domains": ["fury"]},
                   "activated_abilities": {"burn": row("one", {"energy": 0, "power": {}, "additional": [
                       {"cost_id": "kill-self", "mandatory": True,
                        "payment": {"kind": "kill_this", "object_id": "$source_object"}}]})},
                   "programs": {"one": {"effects": [add("energy", 1)]}}},
        "Chooser": {"object": {"kind": "gear", "domains": ["fury"]}, "activated_abilities": {"exhaust": row("aim", EXHAUST)},
                    "programs": {"aim": {"effects": [add("energy", 1), {
                        "op": "ready", "effect_id": "rd",
                        "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}]}}},
    })
    cat["catalogue_hash"] = CE.catalogue_hash(cat)
    return cat


def scene(energy, placed):
    cat = catalogue()
    env = CGL.environment(cat, [(o, ref, "p1", "base") for o, ref in placed])
    s = H.scene(energy)
    for o, _ref in placed:
        s["objects"][o] = env["objects"][o]
        s["players"]["p1"]["zones"]["base"].append(o)
    return s, cat


TIMING = fixture(priority=None, items=[item("spell-1", "p1", "spell", "default"), item("hb", "p2", "spell", "default")])


def window(state, cat, due=2):
    """decision_space's answers to the window Hard Bargain opens (H.run asks for `due` 2; the request carries it)."""
    payload = H.run(state, "instead", window=None)
    payload = {**payload, "payment_due": {"player": "p1", "energy": due}}
    request = {"code": "payment_window_required", "decision_ids": ["payment_window:un"], "controller": "p1",
               "payload": payload}
    return DS.answers(request, TIMING, state, cat, "resolve:spell")


def seqs(out):
    return [[(d["activation"]["source_object"], d["activation"]["ability_id"].rsplit(":", 1)[-1])
             for d in (a.get("settings") or {}).get("payment_adds") or []] for a in out]


def reached(state, cat, out):
    hashes = set()
    for a in out:
        got = GL.payment_adds(TIMING, state, cat, (a.get("settings") or {}).get("payment_adds") or [])
        if not got.get("committed"):
            return None
        hashes.add(IR.hash_value(got["next_effect_state"]))
    return hashes


def brute_force(state, cat):
    """Every order of every subset of the [Add] activations available at the start, each run in sequence."""
    first = DS._window_adds(state, cat, "p1")
    hashes = set()
    for n in range(len(first) + 1):
        for order in itertools.permutations(first, n):
            got = GL.payment_adds(TIMING, state, cat, [copy.deepcopy(d) for d in order])
            if got.get("committed"):
                hashes.add(IR.hash_value(got["next_effect_state"]))
    return hashes


def main() -> int:
    # A1
    s, cat = scene(1, [("fr1", "Fury Rune"), ("fr2", "Fury Rune")])
    kind, who, out = window(s, cat)
    listed = seqs(out)
    if kind != "payment_window" or who != "p1" or [("fr1", "exhaust"), ("fr2", "exhaust")] not in listed:
        fail("A1 two Adds", f"{kind} {who} {listed}")
    else:
        both = next(a for a, q in zip(out, listed) if q == [("fr1", "exhaust"), ("fr2", "exhaust")])
        added = GL.payment_adds(TIMING, s, cat, both["settings"]["payment_adds"])
        paid = H.run(added.get("next_effect_state") or s, "instead")
        if not paid.get("committed") or paid["next_state"]["players"]["p1"]["resources"]["energy"] != 1:
            fail("A1 two Adds", f"after both Adds and the payment: {paid.get('reason_code')}")
    if len({tuple(q) for q in listed}) != len(listed) or reached(s, cat, out) != brute_force(s, cat):
        fail("A1 two Adds", "the answers are not exactly the states every order of every subset reaches")
    # A2
    s, cat = scene(0, [("big", "Big Rune")])
    for due in (2, 1):
        listed = seqs(window(s, cat, due)[2])
        if listed != [[], [("big", "exhaust")]]:
            fail("A2 more than 1", f"due {due}: {listed}")
    added = GL.payment_adds(TIMING, s, cat, window(s, cat)[2][1]["settings"]["payment_adds"])
    if not added.get("committed") or added["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 2:
        fail("A2 more than 1", f"{added.get('reason_code')}")
    # A3
    s, cat = scene(1, [("gem", "Gem")])
    out = window(s, cat)[2]
    if seqs(out) != [[], [("gem", "exhaust")]]:
        fail("A3 mixed", f"{seqs(out)}")
    else:
        pool = GL.payment_adds(TIMING, s, cat, out[1]["settings"]["payment_adds"])["next_effect_state"]["players"]["p1"]["resources"]
        if pool.get("energy") != 2 or (pool.get("power") or {}).get("fury") != 1:
            fail("A3 mixed", f"{pool}")
    # A4
    s, cat = scene(0, [("fr1", "Fury Rune")])
    listed = seqs(window(s, cat)[2])
    if sorted(map(tuple, listed)) != sorted([(), (("fr1", "exhaust"),), (("fr1", "recycle"),),
                                             (("fr1", "exhaust"), ("fr1", "recycle"))]):
        fail("A4 two abilities", f"{listed}")
    # A5
    s, cat = scene(1, [("bn", "Burner")])
    s["objects"]["bn"]["leave_board_triggers"] = [{"trigger_id": "bn-leave", "controller": "p1", "source_object": "bn",
                                                  "controller_order": 0, "effect_program_id": "bn-leave-fx",
                                                  "optional_at_finalize": False}]
    burn = DS._window_adds(s, cat, "p1")
    refused = GL.payment_adds(TIMING, s, cat, burn[:1])
    if refused.get("committed") or refused.get("reason_code") != "payment_window_add_triggered":
        fail("A5 an event", f"payment_adds: {refused.get('committed')} {refused.get('reason_code')} {refused.get('reason')}")
    try:
        window(s, cat)
        fail("A5 an event", "the window was answered though an [Add] in it raises a trigger")
    except DS.Unproved as unproved:
        if "payment_window_add_triggered" not in str(unproved):
            fail("A5 an event", f"unproved for another reason: {unproved}")
    # A6
    s, cat = scene(1, [("ch", "Chooser")])
    try:
        window(s, cat)
        fail("A6 a choice", "the window was answered though an [Add] in it asks for a choice")
    except DS.Unproved as unproved:
        if "_required" not in str(unproved):
            fail("A6 a choice", f"unproved for another reason: {unproved}")
    # A7
    s, cat = scene(1, [("fr1", "Fury Rune"), ("fr2", "Fury Rune")])
    saved, DS.WINDOW_CALL_CAP = DS.WINDOW_CALL_CAP, 2
    try:
        window(s, cat)
        fail("A7 the cap", "answered past the cap")
    except DS.Unproved:
        pass
    finally:
        DS.WINDOW_CALL_CAP = saved
    if errors:
        print("payment window checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("payment window checks passed: every state the payer's [Add] Reactions reach is an answer - both Runes, an Add "
          "of 2, a mixed Add, two Adds on one source - exactly every order of every subset; an Add raising a trigger or "
          "asking a choice, or past the cap, is unproved by name (A1-A7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
