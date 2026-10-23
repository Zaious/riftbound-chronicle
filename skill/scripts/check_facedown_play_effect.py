#!/usr/bin/env python3
"""Choices of what is played from facedown are made at that battlefield, and checked there again (package 12; Core
2026-10-09, in effect 2026-10-16: 811.1.d.2, 811.1.d.5, 811.1.d.3.a, 811.1.d.4, 359.3.e.2.a).

A spell played from facedown chooses its targets at the battlefield it was played from; the on-play trigger of a
permanent that came from facedown chooses at the battlefield it was played to - each target separately, a target whose own restriction
can never be met there left free. As it resolves, a target no longer there is illegal (359.3.e.2.a). The play effect of a
permanent no longer on the board cannot read where it was played from: it mistargets (811.1.d.3.a). Set one's card is
Blastcone Fae ("When you play me, give a unit -2 might this turn, to a minimum of 1 might"); the 07-16 text already asked
the battlefield restriction of it (811.1.d.2), and the engine did not apply it.

  F1 there          played from facedown at bf1: an enemy unit at bf1 chosen, it gets -2
  F2 elsewhere      a unit at bf2 chosen: refused at finalization (target_outside_facedown_battlefield)
  F3 moved away     chosen at bf1, moved to bf2 before it resolves: illegal, nothing changes (359.3.e.2.a)
  F4 source gone    chosen at bf1, then the Fae leaves the board: the play effect mistargets (811.1.d.3.a)
  F5 from the hand  played from the hand: a unit at bf2 is a legal choice
  F6 the flag       a permanent played from facedown hands its play triggers the battlefield it was played to; from
                    the hand, none
  F7 hidden spell   a spell played from facedown at bf1 targeting a unit there: the unit moved to bf2 before it
                    resolves is illegal (359.3.e.2.a)
  F8 a Base         a target restricted to a Base (a restriction that can never be met at a battlefield) is left free

    python skill/scripts/check_facedown_play_effect.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (PROGRAM_VERSION, effective_might, find_location, hash_value, object_identity,  # noqa: E402
                       restrict_to_facedown_battlefield, validate_state)
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority, schedule_triggered_items  # noqa: E402

errors: list[str] = []
FAE = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
       "program_id": "fae-fx", "controller": "p1", "source_object": "fae",
       "effects": [{"op": "modify_might", "effect_id": "mm", "amount": -2, "duration": "this_turn", "source": "fae",
                    "minimum": 1, "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}]}
REGISTRY = {"fae-fx": FAE}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might=4):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board():
    """fae (p1) and e2 (p2) at bf1; e1 (p2) at bf2."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, owner in (("fae", "p1"), ("e1", "p2"), ("e2", "p2")):
        state["objects"][oid] = unit(owner)
    state["battlefields"]["bf1"]["objects"] = ["fae", "e2"]
    state["battlefields"]["bf2"]["objects"] = ["e1"]
    return settle_contested(state)


def pending(state, facedown=True):
    descriptor = {"trigger_id": "fae-play", "controller": "p1", "source_object": "fae", "controller_order": 0,
                  "effect_program_id": "fae-fx", "optional_at_finalize": False, "trigger_kind": "triggered",
                  "batch_sequence": 0, "batch_id": "play:unit-1", "source_identity": object_identity(state, "fae"),
                  **({"facedown_battlefield": "bf1"} if facedown else {})}
    return schedule_triggered_items(fixture(), [descriptor])["next_state"]


def finalize(state, target, facedown=True):
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [target], "selection_identities": {target: object_identity(state, target)}}]}
    return finalize_trigger(pending(state, facedown), state, REGISTRY, decisions)


def resolve(finalized, between=None):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    if between is not None:
        effect = between(effect)
    return resolve_with_program(timing, "fae-play", effect, FAE)


def relocate(state, oid, where):
    s = copy.deepcopy(state)
    loc = find_location(s, oid)
    (s["battlefields"][loc[1]]["objects"] if loc[0] == "battlefield" else s["players"][loc[1]]["zones"][loc[2]]).remove(oid)
    if where == "trash":
        s["players"][s["objects"][oid]["owner"]]["zones"]["trash"].append(oid)
        s["objects"][oid]["identity"] = f"{oid}@9"
    else:
        s["battlefields"][where]["objects"].append(oid)
    return settle_contested(s)


def might(state, oid):
    return effective_might(state, oid)


def code(got):
    return got.get("reason") or (got.get("effect_result") or {}).get("reason_code")


def outcome(got, effect_id="mm"):
    trace = got.get("trace") if isinstance(got.get("trace"), dict) else {}
    return next((x.get("outcome") for x in trace.get("effect") or [] if x.get("effect_id") == effect_id), None)


def part_trigger() -> None:
    s = board()
    if validate_state(s):
        return fail("board", validate_state(s)[:2])
    done = finalize(s, "e2")
    got = resolve(done) if done.get("committed") else done
    if not got.get("committed") or might(got["next_effect_state"], "e2") != 2:
        fail("F1 there", f"{code(got)} e2 might {might(got.get('next_effect_state') or s, 'e2')}")
    away = finalize(s, "e1")
    if away.get("committed") or "target_outside_facedown_battlefield" not in repr(away):
        fail("F2 elsewhere", f"a unit at bf2 chosen for the facedown play effect: {away.get('committed')} {away.get('reason')}")
    done = finalize(s, "e2")
    moved = resolve(done, lambda e: relocate(e, "e2", "bf2")) if done.get("committed") else done
    if not moved.get("committed") or might(moved["next_effect_state"], "e2") != 4 \
            or outcome(moved) not in {"ignored_illegal_target", "skipped_illegal_target"}:
        fail("F3 moved away", f"{code(moved)} e2 might {might(moved.get('next_effect_state') or s, 'e2')} {outcome(moved)}")
    done = finalize(s, "e2")
    gone = resolve(done, lambda e: relocate(e, "fae", "trash")) if done.get("committed") else done
    if not gone.get("committed") or might(gone["next_effect_state"], "e2") != 4:
        fail("F4 source gone", f"{code(gone)} e2 might {might(gone.get('next_effect_state') or s, 'e2')} {outcome(gone)}")
    free = finalize(s, "e1", facedown=False)
    got = resolve(free) if free.get("committed") else free
    if not got.get("committed") or might(got["next_effect_state"], "e1") != 2:
        fail("F5 from the hand", f"{code(got)}")


def part_flag() -> None:
    """A permanent played from facedown (its chain entry says so) hands its play trigger the battlefield."""
    for label, facedown, want in (("F6 the flag", True, "bf1"), ("F6 the flag (hand)", False, None)):
        state = base_state()
        state["players"]["p1"]["zones"]["main_deck"].remove("c1")
        state["players"]["p1"]["zones"]["hand"].append("c1")
        state["objects"]["c1"].update({"kind": "unit", "base_might": 2, "printed_cost": {"energy": 1, "power": {}},
                                       "play_triggers": [{"trigger_id": "c1-on-play", "controller": "p1",
                                                          "source_object": "c1", "controller_order": 0,
                                                          "effect_program_id": "c1-fx", "optional_at_finalize": False}]})
        state["battlefields"]["bf1"]["controller"] = "p1"
        state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
        declared = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                    "play_id": "play-1", "actor": "p1", "card": "c1",
                    "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                    "cost": {"base": {"energy": 1, "power": {}}}, "entry_location": {"kind": "battlefield", "battlefield": "bf1"},
                    "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
        played = pt.play_card(fixture(), state, declared)
        if not played.get("committed"):
            fail(label, f"{played.get('reason_code')} {played.get('reason')}")
            continue
        effect = copy.deepcopy(played["next_effect_state"])
        if facedown:
            effect["chain_items"]["unit-1"]["played_from_hidden"] = "bf1"
        timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
        done = resolve_with_program(timing, "unit-1", effect, None)
        trig = next((i for i in (done.get("next_timing_state") or {}).get("chain", {}).get("items", [])
                     if i.get("id") == "c1-on-play"), None)
        if not done.get("committed") or trig is None or trig.get("facedown_battlefield") != want:
            fail(label, f"{done.get('reason')} the trigger carries {None if trig is None else trig.get('facedown_battlefield')}, "
                        f"not {want}")


def part_spell() -> None:
    """A spell played from facedown at bf1, targeting e2 there; e2 moved to bf2 before it resolves."""
    for label, hidden, want in (("F7 hidden spell", True, 4), ("F7 from the hand", False, 2)):
        s = board()
        s["objects"]["sp"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
        spell = {"card": "sp", "controller": "p1", "effect_program_id": "sp-fx",
                 "played_targets": [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection",
                                     "controller": "p1", "value": ["e2"], "selection_identities": {"e2": object_identity(s, "e2")}}]}
        if hidden:
            spell["played_from_hidden"] = "bf1"
        s["chain_items"] = {"spell-1": spell}
        s = relocate(s, "e2", "bf2")
        timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
        prog = {**FAE, "program_id": "sp-fx", "source_object": None}
        prog.pop("source_object")
        got = resolve_with_program(timing, "spell-1", s, prog)
        if not got.get("committed") or might(got["next_effect_state"], "e2") != want:
            fail(label, f"{code(got)} e2 might {might(got.get('next_effect_state') or s, 'e2')} {outcome(got)}")


def part_free() -> None:
    restricted = restrict_to_facedown_battlefield(
        {"effects": [{"op": "x", "target": {"decision_ref": "a", "location": "base"}},
                     {"op": "y", "target": {"decision_ref": "b", "kind": "unit"}}]}, "bf1")
    a, b = (e["target"] for e in restricted["effects"])
    if "at_battlefield" in a or b.get("at_battlefield") != "bf1":
        fail("F8 a Base", f"{a} {b}")


def main() -> int:
    part_trigger()
    part_flag()
    part_spell()
    part_free()
    if errors:
        print("FAILED: choices of what is played from facedown")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: what is played from facedown chooses at that battlefield - a spell where it was played from, a permanent's "
          "play effect where it was played to - checked there again as it resolves (359.3.e.2.a); the play effect of a "
          "permanent gone from the board mistargets (811.1.d.3.a); a target restricted to a Base is left free (F1-F8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
