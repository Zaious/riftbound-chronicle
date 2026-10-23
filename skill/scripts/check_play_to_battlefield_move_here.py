#!/usr/bin/env python3
"""A play trigger met only on a Battlefield, and a Move "to here" (package 11, Blitzcrank - Impassive: "When you play me to
a battlefield, you may move an enemy unit to here.").

"When you play me to a battlefield" is met as the play completes only when the play put the card at a Battlefield (Core
383.1, 420.4.a): the play trigger's condition {kind: played_to_battlefield}; played to its Base, it does not trigger. The
Move's destination is chosen as the ability is finalized (Core 355.4, 355.15) and can only be "here" - the source's current
Battlefield (destination restriction "here"); a unit already there has nowhere to go (355.4.a). "here" is read again as the
Move executes (359.3.f.2): the source gone from that Battlefield - to its Base or elsewhere - and the chosen destination is
not carried out; it is never re-chosen and never becomes the Base (GPT 2026-10-12, PACKAGE11 ruling 5).

  A1 to a battlefield  played to bf1: the trigger goes on the Chain
  A2 to its base       played to its Base: nothing goes on the Chain (trigger_condition_not_met)
  A3 grammar           "When you play me to a battlefield, ..." lowers to that condition; "When you play me, ..." to none;
                       the near misses do not parse as it
  A4 validation        the condition only on a play trigger, only as {kind}
  B1 here              an enemy unit at bf2 chosen, the destination bf1 (here): it resolves, the unit is at bf1
  B2 not here          bf2 or a Base as the destination: refused at finalization (move_destination_illegal)
  B3 already here      an enemy unit already at bf1: refused at finalization - no legal destination for it
  B4 source to base    finalized, then the source recalled to its Base: the Move is not carried out, the unit stays
  B5 source moved      finalized, then the source moved to bf2: the destination bf1 is no longer here - not carried out
  B6 nobody to move    every enemy unit already here: the trigger leaves the Chain at finalization (403.4)
  B7 declined          the optional trigger declined: nothing moves
  V  validation        here_battlefield is the engine's; "here" only on a chosen destination

    python skill/scripts/check_play_to_battlefield_move_here.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, find_location, hash_value, object_identity,  # noqa: E402
                       validate_program, validate_state)
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority, schedule_triggered_items  # noqa: E402

errors: list[str] = []
PLAY_TRIGGER = {"trigger_id": "c1-on-play", "controller": "p1", "source_object": "c1", "controller_order": 0,
                "effect_program_id": "c1-on-play-effects", "optional_at_finalize": False,
                "condition": {"kind": "played_to_battlefield"}}
MOVE = {"op": "move_board_object", "effect_id": "mv",
        "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"},
        "destination": {"decision_ref": "dest", "restriction": "here"}}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "effects": effects, **extra}


# --- A: the play trigger -------------------------------------------------------------------------------------------

def play_board():
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, "play_triggers": [copy.deepcopy(PLAY_TRIGGER)],
                                   "printed_cost": {"energy": 1, "power": {}}})
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    return state


def play_to(state, entry):
    declared = {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": "p1", "card": "c1",
                "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 1, "power": {}}}, "entry_location": entry,
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    played = pt.play_card(fixture(), state, declared)
    if not played.get("committed"):
        return {"refused": f"{played.get('reason_code')} {played.get('reason')}"}
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "unit-1", played["next_effect_state"], None)


def part_a() -> None:
    for label, entry, want in (("A1 to a battlefield", {"kind": "battlefield", "battlefield": "bf1"}, ["c1-on-play"]),
                               ("A2 to its base", {"kind": "base"}, [])):
        done = play_to(play_board(), entry)
        if not done.get("committed"):
            fail(label, done.get("refused") or done.get("reason"))
            continue
        chain = [i["id"] for i in done["next_timing_state"]["chain"]["items"]]
        if chain != want:
            fail(label, f"the Chain holds {chain}, not {want}")
        if not want and "trigger_condition_not_met" not in repr(done):
            fail(label, "the play to its Base does not say why nothing triggered")
    grammar = cg.load_grammar()
    card = cg.compile_card([{"text": "When you play me to a battlefield, draw 1."}], grammar)
    triggers = (card.get("passive") or {}).get("object_fields", {}).get("play_triggers") or []
    if card.get("unsupported_clauses") or len(triggers) != 1 or triggers[0].get("condition") != {"kind": "played_to_battlefield"}:
        fail("A3 grammar", f"{card.get('unsupported_clauses')} {triggers}")
    plain = cg.compile_card([{"text": "When you play me, draw 1."}], grammar)
    if [t.get("condition") for t in (plain.get("passive") or {}).get("object_fields", {}).get("play_triggers") or []] != [None]:
        fail("A3 grammar", "'When you play me' took a condition")
    for near in ("When you play me to your base, draw 1.",):
        got = cg.compile_card([{"text": near}], grammar)
        if not got.get("unsupported_clauses"):
            fail("A3 grammar", f"a near miss parsed: {near}")
    bad = play_board()
    bad["objects"]["c1"]["move_triggers"] = [dict(PLAY_TRIGGER, trigger_id="c1-on-move")]
    if not validate_state(bad):
        fail("A4 validation", "the condition was accepted on a move trigger")
    bad = play_board()
    bad["objects"]["c1"]["play_triggers"][0]["condition"] = {"kind": "played_to_battlefield", "battlefield": "bf1"}
    if not validate_state(bad):
        fail("A4 validation", "the condition was accepted with more than {kind}")


# --- B: the Move to here -------------------------------------------------------------------------------------------

def unit(owner, might=3):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def move_board(*, all_here=False):
    """bl (p1) at bf1; e2 (p2) at bf1 too; e1 (p2) at bf2; e3 (p2) in its Base."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, owner in (("bl", "p1"), ("e1", "p2"), ("e2", "p2"), ("e3", "p2")):
        state["objects"][oid] = unit(owner)
    state["battlefields"]["bf1"]["objects"] = ["bl", "e2"]
    if all_here:
        state["battlefields"]["bf1"]["objects"] += ["e1", "e3"]
        state["players"]["p2"]["zones"]["base"].remove("u2")
        state["battlefields"]["bf1"]["objects"].append("u2")
    else:
        state["battlefields"]["bf2"]["objects"] = ["e1"]
        state["players"]["p2"]["zones"]["base"].append("e3")
    return settle_contested(state)


PROGRAM = program("bl-fx", [copy.deepcopy(MOVE)], source_object="bl")
REGISTRY = {"bl-fx": PROGRAM}


def pending(state):
    descriptor = {"trigger_id": "bl-play", "controller": "p1", "source_object": "bl", "controller_order": 0,
                  "effect_program_id": "bl-fx", "optional_at_finalize": True, "trigger_kind": "triggered",
                  "batch_sequence": 0, "batch_id": "play:unit-1", "source_identity": object_identity(state, "bl")}
    return schedule_triggered_items(fixture(), [descriptor])["next_state"]


def choose(state, unit_id, place):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [unit_id], "selection_identities": {unit_id: object_identity(state, unit_id)}},
        {"decision_id": "dest", "stage": "trigger_finalization", "kind": "location_selection", "controller": "p1",
         "value": place}]}


def finalize(state, unit_id=None, place=None, perform=True):
    decisions = choose(state, unit_id, place) if unit_id else None
    return finalize_trigger(pending(state), state, REGISTRY, decisions, perform_optional_trigger=perform)


def resolve(finalized, between=None):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    if between is not None:
        effect = between(effect)
    return resolve_with_program(timing, "bl-play", effect, PROGRAM)


def at(state, oid):
    loc = find_location(state, oid)
    return None if loc is None else (f"battlefield:{loc[1]}" if loc[0] == "battlefield" else f"{loc[1]}:{loc[2]}")


def relocate(state, oid, where):
    s = copy.deepcopy(state)
    loc = find_location(s, oid)
    (s["battlefields"][loc[1]]["objects"] if loc[0] == "battlefield" else s["players"][loc[1]]["zones"][loc[2]]).remove(oid)
    if where == "base":
        s["players"][s["objects"][oid]["controller"]]["zones"]["base"].append(oid)
    else:
        s["battlefields"][where]["objects"].append(oid)
    return settle_contested(s)


def part_b() -> None:
    s = move_board()
    if validate_state(s):
        return fail("board", validate_state(s)[:2])
    ok = finalize(s, "e1", "battlefield:bf1")
    if not ok.get("committed") or ok.get("removed"):
        fail("B1 here", f"not finalized: {ok.get('reason')} {ok.get('message')}")
    else:
        got = resolve(ok)
        if not got.get("committed") or at(got["next_effect_state"], "e1") != "battlefield:bf1":
            fail("B1 here", f"{got.get('reason') or got.get('reason_code')} e1 at {at(got.get('next_effect_state') or s, 'e1')}")
        for label, between, where in (("B4 source to base", lambda st: relocate(st, "bl", "base"), "battlefield:bf2"),
                                      ("B5 source moved", lambda st: relocate(st, "bl", "bf2"), "battlefield:bf2")):
            got = resolve(ok, between)
            step = next((e for e in (got.get("trace") or {}).get("effect", []) if e.get("effect_id") == "mv"), {}) \
                if isinstance(got.get("trace"), dict) else {}
            if not got.get("committed") or at(got["next_effect_state"], "e1") != where \
                    or step.get("outcome") != "skipped_illegal_destination":
                fail(label, f"{got.get('reason') or got.get('reason_code')} e1 at "
                            f"{at(got.get('next_effect_state') or s, 'e1')} ({step.get('outcome')})")
    for label, unit_id, place in (("B2 not here", "e1", "base:p2"), ("B2 not here", "e3", "battlefield:bf2"),
                                  ("B3 already here", "e2", "battlefield:bf1")):
        refused = finalize(s, unit_id, place)
        if refused.get("committed") or refused.get("reason") != "move_destination_illegal":
            fail(label, f"{unit_id} to {place}: {refused.get('committed')} {refused.get('reason')}")
    crowded = move_board(all_here=True)
    left = finalize(crowded)
    if not left.get("removed") or (left.get("transition") or {}).get("type") != "no_legal_choices":
        fail("B6 nobody to move", f"{left.get('reason')} {left.get('transition')}")
    declined = finalize(s, perform=False)
    if declined.get("committed") and not declined.get("removed"):
        got = resolve(declined)
        if got.get("committed") and at(got["next_effect_state"], "e1") != "battlefield:bf2":
            fail("B7 declined", "a declined trigger moved the unit")
    elif not declined.get("committed"):
        fail("B7 declined", f"{declined.get('reason')}")
    bad = copy.deepcopy(PROGRAM)
    bad["effects"][0]["destination"]["here_battlefield"] = "bf2"
    if not validate_program(bad):
        fail("V validation", "a program carrying its own here_battlefield validated")
    bad = copy.deepcopy(PROGRAM)
    bad["effects"][0]["destination"] = {"kind": "battlefield", "restriction": "here"}
    if not validate_program(bad):
        fail("V validation", "'here' on a destination that is not chosen validated")
    direct = apply_program(s, {**copy.deepcopy(PROGRAM), "source_identity": object_identity(s, "bl")})
    if direct.get("committed") and at(direct["next_state"], "e1") == "battlefield:bf1":
        fail("V validation", "a Move to here ran with nothing chosen")


def main() -> int:
    part_a()
    part_b()
    if errors:
        print("FAILED: play to a battlefield / move to here")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'When you play me to a battlefield' triggers only on a play to a Battlefield; the Move 'to here' chooses only "
          "the source's Battlefield at finalization, refuses a unit already there, and is not carried out once the source has "
          "left it - never re-chosen, never its Base; nobody to move: the trigger leaves; declined: nothing (A1-A4, B1-B7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
