#!/usr/bin/env python3
"""
Regression gate: printed keyword auras (2026-09-27).

"Units here have [Ganking].", "Other friendly units here have [Assault].", "Other friendly units
here have [Shield]." and "Other friendly units have [Vision]." are passive abilities of a card on
the board (Core 365.1) that grant a keyword in the Ability layer (477.2, 477.2.b). The card
carries them as `static_auras` entries with a keyword
instead of a Might amount, read live (effect_ir.printed_aura_effects); every consumer reads the
keyword off the computed characteristics.

Must hold, each through the engine path that uses the keyword:
  - Ganking from a Battlefield's aura: a Unit at that Battlefield Standard Moves to another
    Battlefield (810.1.b, 144.4.c.1); the same Unit at the other Battlefield cannot move back;
    either side's Unit at it has Ganking; a Unit in a Base does not; without the aura the move
    is refused;
  - Assault / Shield "here": another friendly Unit at the source's Battlefield has the keyword,
    and its Might as the Attacker / Defender includes it (807.1.c, 814.1.c); values are summed
    with its own (807.2, 814.2); the source, a friendly Unit elsewhere, an enemy Unit there and
    a Unit in a Base do not; it stops when the source leaves the board;
  - Vision to the other friendly Units: a Unit without Vision played while the source is on the
    board schedules one Vision trigger; a Unit with its own Vision schedules two, each finalized
    and resolved with its own recycle choice (817.2, 817.2.a); the source played with no other
    such source on the board schedules one (its own - "other"), a second one played beside the
    first schedules two; an opponent's Unit schedules none; with the source gone, none;
  - invalid: an aura with a keyword the engine does not read, a value on a keyword whose values
    are not summed, a keyword aura over gear, and one carrying both a keyword and an amount;
  - mutations caught: a Vision count that ignores instances, and an aura read without "here".
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import engine_decisions as ed  # noqa: E402
import play_transaction as PT  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import STANDARD_MOVE_DECLARATION_VERSION, standard_move  # noqa: E402
from effect_ir import effective_might, has_keyword, hash_value, keyword_values, object_identity, validate_state  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

HERE = {"kind": "unit", "controller_relation": "friendly", "exclude_source": True, "at_source_battlefield": True}
OTHERS = {"kind": "unit", "controller_relation": "friendly", "exclude_source": True}


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False, **extra}


# ------------------------------------------------------------------ Ganking (a Battlefield's aura)
def hillock(*, aura=True):
    """bf1 carries "Units here have [Ganking]." with p1's m1 and p2's e1 there (contested); bf2 is
    empty and uncontrolled with nothing on it; p1's m2 waits at bf3 (p1's own)."""
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["m1", "e1"], "contested": True, "contested_by": "p2",
                                    **({"static_auras": [{"aura_id": "here-ganking", "keyword": "ganking",
                                                          "criteria": {"kind": "unit"}}]} if aura else {})}
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["battlefields"]["bf3"] = {"controller": "p1", "objects": ["m2"]}
    state["objects"]["m1"] = unit("p1", 2)
    state["objects"]["m2"] = unit("p1", 2)
    state["objects"]["e1"] = unit("p2", 2)
    return state


def move(state, mover, destination, actor="p1"):
    return standard_move(fixture(priority=actor) if actor == "p1" else {**fixture(priority=actor), "turn_player": actor}, state, {
        "schema_version": STANDARD_MOVE_DECLARATION_VERSION, "actor": actor, "units": [mover],
        "destination": {"kind": "battlefield", "battlefield": destination},
        "unit_identities": {mover: object_identity(state, mover) or f"{mover}@0"},
        "cost_confirmation": {"exhaust_confirmed": True}})


def check_ganking(errors):
    state = hillock()
    if found := validate_state(state):
        errors.append(f"a Battlefield with a keyword aura was invalid: {found}")
        return
    got = {o: has_keyword(state, o, "ganking") for o in ("m1", "e1", "m2", "u1", "u2")}
    if got != {"m1": True, "e1": True, "m2": False, "u1": False, "u2": False}:
        errors.append(f"'units here have [Ganking]' reached the wrong units: {got}")
    out = move(state, "m1", "bf2")
    if not out.get("committed") or "m1" not in out["next_effect_state"]["battlefields"]["bf2"]["objects"]:
        errors.append(f"a Unit at the Ganking Battlefield could not move to another Battlefield: {out.get('reason_code')} {out.get('reason')}")
    back = move(state, "m2", "bf1")
    if back.get("committed") or back.get("reason_code") != "ganking_required":
        errors.append(f"a Unit at another Battlefield moved to the Ganking Battlefield: {back.get('reason_code')}")
    plain = move(hillock(aura=False), "m1", "bf2")
    if plain.get("committed") or plain.get("reason_code") != "ganking_required":
        errors.append(f"without the aura the Battlefield-to-Battlefield move was not refused: {plain.get('reason_code')}")
    for bad in ({"aura_id": "x", "keyword": "ganking", "value": 2, "criteria": {"kind": "unit"}},
                {"aura_id": "x", "keyword": "ganking", "criteria": {"kind": "unit", "controller_relation": "friendly"}},
                {"aura_id": "x", "keyword": "legion", "criteria": {"kind": "unit"}}):
        broken = hillock()
        broken["battlefields"]["bf1"]["static_auras"] = [bad]
        if not validate_state(broken):
            errors.append(f"an invalid Battlefield keyword aura validated: {bad}")


# ------------------------------------------------------------------ Assault / Shield "here"
def captain(keyword, *, role, source_gone=False):
    """g1 carries "Other friendly units here have [<keyword>]." at bf1 (p1's), with p1's f1 (no
    keyword), p1's f3 (its own keyword, value 2) and p2's e1 there, in a Combat at bf1 in which p1
    is `role`; p1's f2 waits at bf2 (p1's)."""
    state = base_state()
    other = "defender" if role == "attacker" else "attacker"
    here = ["g1", "f1", "f3", "e1"]
    state["battlefields"]["bf1"] = {"controller": "p2" if role == "attacker" else "p1", "objects": here,
                                    "contested": True, "contested_by": "p1" if role == "attacker" else "p2"}
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": ["f2"]}
    state["objects"]["g1"] = unit("p1", 3, static_auras=[{"aura_id": f"here-{keyword}", "keyword": keyword, "criteria": dict(HERE)}])
    state["objects"]["f1"] = unit("p1", 2)
    state["objects"]["f2"] = unit("p1", 2)
    state["objects"]["f3"] = unit("p1", 2, keywords=[keyword], **{f"{keyword}_value": 2})
    state["objects"]["e1"] = unit("p2", 2)
    for oid in ("g1", "f1", "f3"):
        state["objects"][oid]["combat_designation"] = {"combat_id": "cb1", "role": role}
    state["objects"]["e1"]["combat_designation"] = {"combat_id": "cb1", "role": other}
    if source_gone:
        state["battlefields"]["bf1"]["objects"].remove("g1")
        state["objects"]["g1"].pop("combat_designation")
        state["players"]["p1"]["zones"]["trash"].append("g1")
    return state


def check_here(errors, keyword, role):
    state = captain(keyword, role=role)
    if found := validate_state(state):
        errors.append(f"a {keyword} aura board was invalid: {found}")
        return
    values = {o: keyword_values(state, o).get(keyword) for o in ("g1", "f1", "f2", "f3", "e1", "u1")}
    if values != {"g1": None, "f1": 1, "f2": None, "f3": 3, "e1": None, "u1": None}:
        errors.append(f"'other friendly units here have [{keyword}]' gave the wrong values (807.2 / 814.2 sum): {values}")
    mights = {o: effective_might(state, o) for o in ("g1", "f1", "f3", "e1")}
    if mights != {"g1": 3, "f1": 3, "f3": 5, "e1": 2}:
        errors.append(f"[{keyword}] from the aura did not count while the Unit is the {role}: {mights}")
    gone = captain(keyword, role=role, source_gone=True)
    after = {o: keyword_values(gone, o).get(keyword) for o in ("f1", "f3")}
    if after != {"f1": None, "f3": 2}:
        errors.append(f"the [{keyword}] aura outlived its source leaving the board: {after}")


# ------------------------------------------------------------------ Vision to the other friendly units
SEER = {"aura_id": "all-vision", "keyword": "vision", "criteria": dict(OTHERS)}


def seer_board(*, printed_vision=False, player="p1", seer_where="base", card_is_seer=False):
    state = base_state()
    zones = state["players"][player]["zones"]
    card = "c1" if player == "p1" else "c4"
    zones["main_deck"].remove(card)
    zones["hand"].append(card)
    state["objects"][card].update({"kind": "unit", "base_might": 2})
    if printed_vision or card_is_seer:
        state["objects"][card]["keywords"] = ["vision"]
    if card_is_seer:
        state["objects"][card]["static_auras"] = [copy.deepcopy(SEER)]
    state["objects"]["s1"] = unit("p1", 2, keywords=["vision"], static_auras=[copy.deepcopy(SEER)])
    state["players"]["p1"]["zones"]["base" if seer_where == "base" else "trash"].append("s1")
    state["players"][player]["resources"] = {"energy": 2, "power": {}}
    return state, card


def play_unit(state, card, actor):
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": actor, "card": card,
                "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    timing = fixture(priority=actor) if actor == "p1" else {**fixture(priority=actor), "turn_player": actor}
    played = PT.play_card(timing, state, declared)
    if not played.get("committed"):
        return None, played.get("reason")
    other = "p2" if actor == "p1" else "p1"
    resolving = {**fixture(priority=other, items=[item("unit-1", actor, "unit", "default", "finalized")], passes=["p1", "p2"]),
                 "turn_player": actor}
    return resolve_with_program(resolving, "unit-1", played["next_effect_state"], None), None


def scheduled(state, card, actor):
    done, why = play_unit(state, card, actor)
    if done is None or not done.get("committed"):
        return None
    return [i["id"] for i in done["next_timing_state"]["chain"]["items"]], done


def check_vision(errors):
    runs = {}
    for label, kwargs in (("plain", {}), ("own_vision", {"printed_vision": True}), ("the_seer_alone", {"card_is_seer": True, "seer_where": "trash"}),
                          ("a_second_seer", {"card_is_seer": True}),
                          ("opponents_unit", {"player": "p2"}), ("seer_in_trash", {"seer_where": "trash"})):
        state, card = seer_board(**kwargs)
        if found := validate_state(state):
            errors.append(f"the {label} Vision board was invalid: {found}")
            return
        got = scheduled(state, card, "p2" if kwargs.get("player") == "p2" else "p1")
        runs[label] = got[0] if got else None
    want = {"plain": ["c1:vision"], "own_vision": ["c1:vision", "c1:vision:2"], "the_seer_alone": ["c1:vision"],
            "a_second_seer": ["c1:vision", "c1:vision:2"],
            "opponents_unit": [], "seer_in_trash": []}
    if runs != want:
        errors.append(f"Vision instances under 'other friendly units have [Vision]' scheduled the wrong triggers (817.2): {runs}")
        return
    # both instances finalize and resolve, each with its own recycle choice (817.2.a)
    state, card = seer_board(printed_vision=True)
    _, done = scheduled(state, card, "p1")
    after = done["next_effect_state"]
    program = IR.vision_program(after, "c1", "p1")
    registry = {program["program_id"]: program}
    timing = done["next_timing_state"]
    for _ in range(2):
        finalized = finalize_trigger(timing, after, registry, None)
        if not finalized.get("committed"):
            errors.append(f"a Vision instance did not finalize: {finalized.get('reason')}")
            return
        timing = finalized["next_timing_state"]
    resolved = []
    for _ in range(2):
        for _pass in range(4):
            if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
                break
            timing = RC.pass_priority(timing, timing["priority"])["next_state"]
        newest = [i for i in timing["chain"]["items"] if i["status"] == "finalized"][-1]
        dispatched, refusal = dispatch_program(registry, newest)
        if refusal is not None:
            errors.append(f"a Vision instance was refused at dispatch: {refusal}")
            return
        top = after["players"]["p1"]["zones"]["main_deck"][0]
        keep = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(after), "decisions": [
            {"decision_id": "vision:recycle", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": [],
             "selection_identities": {}}]}
        out = resolve_with_program(timing, newest["id"], after, dispatched, engine_decisions=keep)
        if not out.get("committed"):
            errors.append(f"a Vision instance did not resolve: {out.get('reason_code')} {out.get('reason')}")
            return
        resolved.append((newest["id"], out["next_effect_state"]["players"]["p1"]["zones"]["main_deck"][0] == top))
        timing, after = out["next_timing_state"], out["next_effect_state"]
    if [r[0] for r in resolved] != ["c1:vision:2", "c1:vision"] or not all(r[1] for r in resolved):
        errors.append(f"the two Vision instances did not each resolve with their own choice: {resolved}")


def check_invalid(errors):
    for bad in ({"aura_id": "x", "keyword": "legion", "criteria": dict(HERE)},
                {"aura_id": "x", "keyword": "ganking", "value": 1, "criteria": dict(HERE)},
                {"aura_id": "x", "keyword": "assault", "value": 0, "criteria": dict(HERE)},
                {"aura_id": "x", "keyword": "assault", "criteria": {**HERE, "kind": "gear"}},
                {"aura_id": "x", "keyword": "assault", "amount": 1, "criteria": dict(HERE)}):
        broken = captain("assault", role="attacker")
        broken["objects"]["g1"]["static_auras"] = [bad]
        if not validate_state(broken):
            errors.append(f"an invalid keyword aura validated: {bad}")


def check_mutations(errors):
    saved = IR.keyword_instances
    try:
        IR.keyword_instances = lambda state, object_id, keyword: 1 if has_keyword(state, object_id, keyword) else 0
        state, card = seer_board(printed_vision=True)
        got = scheduled(state, card, "p1")
    finally:
        IR.keyword_instances = saved
    if got and got[0] == ["c1:vision", "c1:vision:2"]:
        errors.append("mutation not caught: a Vision count that ignores instances still scheduled two triggers")
    elif got is None or got[0] != ["c1:vision"]:
        errors.append(f"the instance mutation did not run as intended: {got and got[0]}")
    saved_applies = IR._printed_aura_applies
    try:
        IR._printed_aura_applies = lambda state, criteria, object_id: saved_applies(
            state, {k: v for k, v in criteria.items() if k != "at_source_battlefield"}, object_id)
        leaked = keyword_values(captain("assault", role="attacker"), "f2").get("assault")
    finally:
        IR._printed_aura_applies = saved_applies
    if leaked != 1:
        errors.append(f"mutation not caught: an aura read without 'here' must reach f2 at bf2 in this board ({leaked})")


def main() -> int:
    errors: list[str] = []
    check_ganking(errors)
    check_here(errors, "assault", "attacker")
    check_here(errors, "shield", "defender")
    check_vision(errors)
    check_invalid(errors)
    check_mutations(errors)
    if errors:
        print("FAILED: keyword aura checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a printed keyword aura grants Ganking to every Unit at its Battlefield (a real Battlefield-to-Battlefield "
          "Standard Move), Assault / Shield to the other friendly Units at its source's Battlefield (summed, counted in "
          "Combat, gone with the source), and Vision to the other friendly Units - each instance its own trigger "
          "(817.2); invalid auras are refused and two mutations are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
