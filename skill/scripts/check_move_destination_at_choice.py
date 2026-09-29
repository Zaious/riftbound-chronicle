#!/usr/bin/env python3
"""
Regression gate (GPT 2026-09-29, blockers 1 and 2 of the package-5 review).

1. Core 355.4 / 355.15: a Move's destination is chosen where the spell or ability makes its choices - as
   the card is played, or as a triggered ability is finalized - recorded on its Chain entry with the
   targets, and never re-chosen at resolution. Through a real play and a real Chain:
     - "Move an enemy unit." played with no destination is refused (move_destination_required); with a
       resolution-stage destination at play, refused (decision_stage_mismatch); with the unit's own
       location, refused (move_destination_illegal, 355.4.a);
     - played with bf2, the destination is recorded (played_targets) and the unit resolves to bf2 with
       nothing supplied; a different destination supplied at resolution is refused
       (destination_changed_after_play), the same one accepted;
     - after a response moves the unit to bf2 itself, bf2 is no longer a legal destination: that Move is
       not executed (skipped_illegal_destination, 359.3.e.9) - never re-chosen - and the rest resolves;
     - a triggered ability's Move: finalized with no destination, refused; with one, it is in
       finalized_targets; a different one at resolution is refused (destination_changed_after_finalization).
2. Core 402.4: a triggered ability performed without enough legal options for a required choice leaves the
   Chain, never Finalized and not countered (402.4.a); with options, its controller must choose (402.4.b):
     - Hallowed Tomb's return, performed with no Chosen Champion in the trash: removed (no_legal_choices);
       declined: removed as before; with one in the trash: target_selection_required;
     - a mandatory "Deal 2 to an enemy unit in its base" with no enemy unit anywhere: removed.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import find_location, hash_value, object_identity  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
MOVE = {"op": "move_board_object", "effect_id": "mv",
        "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"},
        "destination": {"decision_ref": "d"}}
DRAW = {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}


def board() -> dict:
    """p1's spell c1 in hand; p2's u2 at bf1; an empty bf2."""
    state = base_state()
    p1 = state["players"]["p1"]["zones"]
    p1["main_deck"].remove("c1")
    p1["hand"].append("c1")
    for zone in state["players"]["p2"]["zones"].values():
        if "u2" in zone:
            zone.remove("u2")
    state["battlefields"]["bf1"]["objects"].append("u2")
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return settle_contested(state)


def envelope(state: dict, entries: list[dict]) -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": entries}


def target(state: dict, stage: str, ref: str = "t", obj: str = "u2") -> dict:
    return {"decision_id": ref, "stage": stage, "kind": "target_selection", "controller": "p1", "value": [obj],
            "selection_identities": {obj: object_identity(state, obj)}}


def place(value: str, stage: str, ref: str = "d") -> dict:
    return {"decision_id": ref, "stage": stage, "kind": "location_selection", "controller": "p1", "value": value}


def spell(effects: list[dict]) -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": "c1-effects",
            "controller": "p1", "effects": copy.deepcopy(effects)}


def play(state: dict, effects: list[dict], entries: list[dict]) -> dict:
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
                   "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "c1-effects",
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return play_card(fixture(), state, declaration, engine_decisions=envelope(state, entries), effect_program=spell(effects))


def resolve(effect_state: dict, effects: list[dict], entries: list[dict] | None = None) -> dict:
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "spell-1", effect_state, spell(effects),
                                engine_decisions=envelope(effect_state, entries) if entries else None)


def where(state: dict, obj: str) -> tuple | None:
    loc = find_location(state, obj)
    return loc[:2] if loc else None


def trigger_board(program: dict, *, optional: bool) -> tuple[dict, dict]:
    """c1, a unit with a play trigger running `program`, played into p1's Base; the trigger Pending."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2})
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    state["objects"]["c1"]["play_triggers"] = [{"trigger_id": "c1-on-play", "controller": "p1", "source_object": "c1",
                                                "controller_order": 0, "effect_program_id": program["program_id"],
                                                "optional_at_finalize": optional,
                                                "effect_program_hash": program_hash(program)}]
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                   "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    played = play_card(fixture(), settle_contested(state), declaration)
    assert played.get("committed"), played.get("reason")
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    entered = resolve_with_program(timing, "unit-1", played["next_effect_state"], None)
    assert entered.get("committed"), entered.get("reason")
    return entered["next_timing_state"], entered["next_effect_state"]


def trig_program(effects: list[dict], pid: str) -> dict:
    return {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": pid, "controller": "p1",
            "source_object": "c1", "effects": copy.deepcopy(effects)}


def main() -> int:
    errors: list[str] = []
    start = board()

    # --- 1. a spell's Move: chosen at play, recorded, never re-chosen --------------------------------
    for label, entries, reason in (
            ("no destination", [target(start, "play_declaration")], "move_destination_required"),
            ("a resolution-stage destination", [target(start, "play_declaration"), place("battlefield:bf2", "resolution")],
             "invalid_input"),
            ("the unit's own battlefield", [target(start, "play_declaration"), place("battlefield:bf1", "play_declaration")],
             "move_destination_illegal")):
        got = play(start, [MOVE], entries)
        if got.get("committed") or got.get("reason_code") != reason:
            errors.append(f"played with {label}: expected {reason}, got {got.get('committed')} {got.get('reason_code')} {got.get('reason')}")
    played = play(start, [MOVE, DRAW], [target(start, "play_declaration"), place("battlefield:bf2", "play_declaration")])
    if not played.get("committed"):
        errors.append(f"a Move played with a legal destination was refused: {played.get('reason')}")
        return report(errors)
    after_play = played["next_effect_state"]
    recorded = (after_play.get("chain_items") or {}).get("spell-1", {}).get("played_targets") or []
    if not any(e.get("kind") == "location_selection" and e.get("value") == "battlefield:bf2" for e in recorded):
        errors.append(f"the destination was not recorded on the Chain entry: {recorded}")
    done = resolve(after_play, [MOVE, DRAW])
    if not done.get("committed") or where(done["next_effect_state"], "u2") != ("battlefield", "bf2"):
        errors.append(f"the recorded destination did not carry the Move: {done.get('reason')} "
                      f"{where((done.get('next_effect_state') or after_play), 'u2')}")
    swapped = resolve(after_play, [MOVE, DRAW], [place("base:p2", "resolution")])
    if swapped.get("committed") or swapped.get("reason") != "destination_changed_after_play":
        errors.append(f"a destination changed at resolution was not refused: {swapped.get('committed')} {swapped.get('reason')}")
    same = resolve(after_play, [MOVE, DRAW], [place("battlefield:bf2", "resolution")])
    if not same.get("committed"):
        errors.append(f"the recorded destination supplied again at resolution was refused: {same.get('reason')}")
    # a response moves u2 to bf2 before the spell resolves: bf2 is no longer a legal destination for it
    responded = copy.deepcopy(after_play)
    responded["battlefields"]["bf1"]["objects"].remove("u2")
    responded["battlefields"]["bf2"]["objects"].append("u2")
    responded["battlefields"]["bf2"]["controller"] = "p2"
    responded["battlefields"]["bf1"].pop("contested", None)
    responded["battlefields"]["bf1"].pop("contested_by", None)
    late = resolve(responded, [MOVE, DRAW])
    moved = next((t for t in (late.get("trace") or {}).get("effect") or [] if t.get("op") == "move_board_object"), {})
    hand = (late.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("hand") or []
    if not late.get("committed") or moved.get("outcome") != "skipped_illegal_destination" \
            or where(late["next_effect_state"], "u2") != ("battlefield", "bf2") or len(hand) != len(responded["players"]["p1"]["zones"]["hand"]) + 1:
        errors.append(f"a destination made illegal by a response did not leave that Move unexecuted with the rest "
                      f"resolving: {late.get('reason') or late.get('errors')} {moved.get('outcome')} {where((late.get('next_effect_state') or responded), 'u2')}")

    # --- 1b. a triggered ability's Move: chosen at finalization ------------------------------------
    move_mine = [{**MOVE, "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                     "controller_relation": "enemy"}}]
    prog = trig_program(move_mine, "c1-move")
    registry = {prog["program_id"]: prog}
    timing, effect = trigger_board(prog, optional=False)
    enemy = next(o for o, obj in effect["objects"].items() if obj.get("controller") == "p2" and obj.get("kind") == "unit"
                 and (find_location(effect, o) or ("", "", ""))[0] in ("battlefield", "player") and find_location(effect, o)[2] in (None, "base"))
    dest = next(c for c in ("battlefield:bf2", "battlefield:bf1") if (("battlefield", c.split(":")[1]) != where(effect, enemy)))
    none = finalize_trigger(timing, effect, registry, envelope(effect, [target(effect, "trigger_finalization", obj=enemy)]))
    if none.get("committed") or none.get("reason") != "move_destination_required":
        errors.append(f"a triggered Move finalized with no destination: {none.get('committed')} {none.get('reason')}")
    fin = finalize_trigger(timing, effect, registry, envelope(effect, [target(effect, "trigger_finalization", obj=enemy),
                                                                      place(dest, "trigger_finalization")]))
    if not fin.get("committed") or not any(e.get("kind") == "location_selection" and e.get("value") == dest
                                           for e in fin.get("finalized_targets") or []):
        errors.append(f"a triggered Move's destination was not recorded at finalization: {fin.get('reason')} {fin.get('finalized_targets')}")
    else:
        t2 = fin["next_timing_state"]
        for actor in ("p1", "p2"):
            t2 = pass_priority(t2, actor).get("next_state") or t2
        trig_id = next(i["id"] for i in t2["chain"]["items"] if i.get("timing") == "triggered")
        other = "base:p2" if dest != "base:p2" else "battlefield:bf1"
        swap = resolve_with_program(t2, trig_id, fin["next_effect_state"], prog,
                                    engine_decisions=envelope(fin["next_effect_state"], [place(other, "resolution")]))
        if swap.get("committed") or swap.get("reason") != "destination_changed_after_finalization":
            errors.append(f"a triggered Move's destination changed at resolution was not refused: {swap.get('reason')}")

    # --- 2. Core 402.4: not enough options, the Pending ability leaves the Chain ------------------------
    tomb = trig_program([{"op": "return_to_champion_zone", "effect_id": "rt",
                          "target": {"decision_ref": "t", "chosen_zone_class": "non_board", "kind": "unit", "location": "trash",
                                     "zone_owner_relation": "own", "chosen_champion": True}}], "c1-tomb")
    t_timing, t_effect = trigger_board(tomb, optional=True)
    t_effect["players"]["p1"]["chosen_champion"] = "Probe Champion"
    t_effect["players"]["p1"]["zones"]["champion_zone"] = []
    reg = {tomb["program_id"]: tomb}
    empty = finalize_trigger(t_timing, t_effect, reg, None, perform_optional_trigger=True)
    left = [i for i in (empty.get("next_timing_state") or {}).get("chain", {}).get("items", []) if i.get("timing") == "triggered"]
    if not empty.get("committed") or not empty.get("removed") or (empty.get("transition") or {}).get("type") != "no_legal_choices" \
            or (empty.get("transition") or {}).get("countered") is not False or left:
        errors.append(f"performed with no Chosen Champion in the trash, the trigger did not leave the Chain (402.4): "
                      f"{empty.get('committed')} {empty.get('reason')} {empty.get('transition')} {len(left)} left")
    declined = finalize_trigger(t_timing, t_effect, reg, None, perform_optional_trigger=False)
    if not declined.get("committed"):
        errors.append(f"declining the optional trigger was refused: {declined.get('reason')}")
    with_one = copy.deepcopy(t_effect)
    with_one["objects"]["j1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4, "might_modifiers": [],
                                 "damage": 0, "exhausted": False, "name": "Probe Champion", "champion_unit": True}
    with_one["players"]["p1"]["zones"]["trash"].append("j1")
    must = finalize_trigger(t_timing, with_one, reg, None, perform_optional_trigger=True)
    if must.get("committed") or must.get("reason") != "target_selection_required":
        errors.append(f"with a Chosen Champion in the trash its controller was not asked to choose (402.4.b): {must.get('reason')}")
    hit = trig_program([{"op": "deal_damage", "effect_id": "dmg", "amount": 2,
                         "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                    "controller_relation": "enemy", "location": "base"}}], "c1-hit")
    h_timing, h_effect = trigger_board(hit, optional=False)
    for obj in [o for o, v in h_effect["objects"].items() if v.get("controller") == "p2" and v.get("kind") == "unit"]:
        loc = find_location(h_effect, obj)
        if loc and loc[0] == "player":
            h_effect["players"][loc[1]]["zones"][loc[2]].remove(obj)
        elif loc:
            h_effect["battlefields"][loc[1]]["objects"].remove(obj)
        h_effect["players"]["p2"]["zones"]["trash"].append(obj)
    gone = finalize_trigger(h_timing, h_effect, {hit["program_id"]: hit}, None)
    if not gone.get("committed") or (gone.get("transition") or {}).get("type") != "no_legal_choices":
        errors.append(f"a mandatory trigger with no legal target did not leave the Chain (402.4): {gone.get('reason')}")
    return report(errors)


def report(errors: list[str]) -> int:
    if errors:
        print("FAILED: Move destinations at the choice step; Core 402.4")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a Move's destination is chosen as the card is played or the ability finalized (355.4), recorded with "
          "its targets, refused if missing, early-staged or illegal, never changed at resolution (355.15), and a Move "
          "whose destination a response made illegal is not executed while the rest resolves; a performed trigger "
          "with no legal option leaves the Chain uncountered (402.4, 402.4.a), and with one its controller must choose")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
