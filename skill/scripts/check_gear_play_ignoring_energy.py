#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Jayce - Man of Progress, "... you may play a gear with Energy cost no more than [7]
from hand this turn, ignoring its Energy cost. (You must still pay its Power cost.)"): a turn effect,
gear_play_ignoring_energy (value: the Energy limit), its controller may use on one play of a Gear card from the hand this
turn - the play declares cost_override ignore_energy naming it (source turn_effect:<id>); the play spends it (Core
356.1.b.2: only the Energy cost is set to zero, the Power cost still applies).

  G1 grant        grant_turn_effect gear_play_ignoring_energy 7 adds it for p1 this turn; a negative or bool limit refused
  U1 used         a Gear [5][Calm] from p1's hand with the override: 0 Energy and the Calm paid; the turn effect spent
  U2 not used     the same Gear without the override: 5 Energy paid; the turn effect still there
  U3 over         a Gear [8]: the override refused (no turn effect lets this play declare it)
  U4 not a gear   a unit [3] from the hand: refused
  U5 not hand     the Gear played from p1's trash under a permission: refused
  U6 other turn   the turn effect of another turn, or p2's: refused
  U7 spent        after U1 a second Gear with the same override: refused
  E1 enumerator   play_space offers the Gear with the override and without it, two action keys
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import action_space as AS  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_space as PS  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402

GRANT = {"op": "grant_turn_effect", "effect_id": "g", "turn_effect_kind": "gear_play_ignoring_energy", "value": 7,
         "controller": "p1"}


def program(*effects):
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": "jayce", "controller": "p1", "effects": [copy.deepcopy(e) for e in effects]}


def granted(state):
    done = IR.apply_program(state, program(GRANT))
    if not done.get("committed"):
        raise AssertionError(f"the grant did not commit: {done.get('reason') or done.get('errors')}")
    return done["next_state"]


def board(kind="gear", energy=5, power=None, zone="hand", pool=None):
    s = base_state()
    s["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s["players"]["p1"]["zones"][zone].append("c1")
    s["objects"]["c1"].update({"kind": kind, "printed_cost": {"energy": energy, "power": dict(power or {"calm": 1})}})
    s["players"]["p1"]["resources"] = pool or {"energy": 9, "power": {"calm": 2}}
    return s


def play(state, override=None, *, kind="gear", source=None, item="g1"):
    obj = state["objects"]["c1"]
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": f"p-{item}", "actor": "p1", "card": "c1",
            "chain_item": {"id": item, "object_kind": kind, "timing": "default"},
            "cost": {"base": copy.deepcopy(obj["printed_cost"])}, "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if override is not None:
        decl["cost_override"] = override
    if source is not None:
        decl["source"], decl["source_permission"] = source, {"granted_by": "probe"}
    return PT.play_card(fixture(), state, decl)


def main() -> int:
    errors: list[str] = []
    s = granted(board())
    mine = [e for e in s.get("turn_effects") or [] if e["kind"] == "gear_play_ignoring_energy"]
    if len(mine) != 1 or mine[0]["value"] != 7 or mine[0]["controller"] != "p1":
        errors.append(f"G1 grant: {mine}")
    for bad in (-1, True):
        try:
            IR.apply_program(board(), program({**GRANT, "value": bad}))
            got = IR.apply_program(board(), program({**GRANT, "value": bad}))
            if got.get("committed"):
                errors.append(f"G1 grant: a limit of {bad!r} was granted")
        except (ValueError, NotImplementedError):
            pass
    override = {"kind": "ignore_energy", "source": f"turn_effect:{mine[0]['effect_id']}"} if mine else None
    used = play(s, override)
    after = used.get("next_effect_state") or {}
    if not used.get("committed") or after["players"]["p1"]["resources"] != {"energy": 9, "power": {"calm": 1}} \
            or any(e["kind"] == "gear_play_ignoring_energy" for e in after.get("turn_effects") or []):
        errors.append(f"U1 used: {used.get('reason_code')} {used.get('reason')} {after.get('players', {}).get('p1', {}).get('resources')}")
    plain = play(s)
    after = plain.get("next_effect_state") or {}
    if not plain.get("committed") or after["players"]["p1"]["resources"]["energy"] != 4 \
            or not any(e["kind"] == "gear_play_ignoring_energy" for e in after.get("turn_effects") or []):
        errors.append(f"U2 not used: {plain.get('reason_code')} {plain.get('reason')}")
    over = granted(board(energy=8))
    refused = lambda got: not got.get("committed") and "lets this play declare" in str(got.get("reason"))
    if not refused(play(over, override)):
        errors.append("U3 over: an [8] Gear took the override")
    unit = granted(board(kind="unit", energy=3))
    if play(unit, override, kind="unit").get("committed"):
        errors.append("U4 not a gear: a unit took the override")
    trash = granted(board(zone="trash"))
    if not refused(play(trash, override, source={"kind": "trash"})):
        errors.append("U5 not hand: a play from the trash took the override")
    other = copy.deepcopy(s)
    for e in other["turn_effects"]:
        e["turn_id"] = "turn-other"
    theirs = copy.deepcopy(s)
    for e in theirs["turn_effects"]:
        e["controller"] = "p2"
    if play(other, override).get("committed") or play(theirs, override).get("committed"):
        errors.append("U6 other turn: another turn's or p2's turn effect was used")
    if used.get("committed"):
        again = copy.deepcopy(used["next_effect_state"])
        again["objects"]["c9"] = copy.deepcopy(again["objects"]["c1"])
        again["objects"]["c9"].pop("chain_item", None)
        again["players"]["p1"]["zones"]["hand"].append("c9")
        decl_state = again
        second = PT.play_card(fixture(), decl_state, {
            "schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": "p-g2", "actor": "p1", "card": "c9", "chain_item": {"id": "g2", "object_kind": "gear", "timing": "default"},
            "cost": {"base": {"energy": 5, "power": {"calm": 1}}}, "entry_location": {"kind": "base"}, "cost_override": override,
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}})
        if second.get("committed"):
            errors.append("U7 spent: the override was used twice")
    plays = [d for d, _p in PS.play_skeletons(s, None, "p1") if d["card"] == "c1"]
    keys = {AS.action_key_hash({"kind": "play_card", "declaration": d}) for d in plays}
    bare = {AS.action_key_hash({"kind": "play_card", "declaration": d}) for d in plays if not d.get("cost_override")}
    if {bool(d.get("cost_override")) for d in plays} != {False, True} or len(keys) != 2 * len(bare):
        errors.append(f"E1 enumerator: {[d.get('cost_override') for d in plays]} keys {len(keys)}")
    if errors:
        print("gear-play-ignoring-energy checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("gear-play-ignoring-energy checks passed: the turn effect lets one Gear card from its player's hand this turn, "
          "within the Energy limit, ignore its Energy cost (its Power still paid) - declared, checked and spent; over the "
          "limit, not a Gear, not from the hand, another turn's or player's, or spent: refused; the enumerator offers both")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
