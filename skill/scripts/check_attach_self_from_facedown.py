#!/usr/bin/env python3
"""Regression gate (set 2 package A2, Edge of Night: "When you play this from face down, attach it to a unit you control
(here)."): a Gear's play trigger met only by a play from facedown (condition played_from_facedown, Core 811.1.c.3), and
an attach whose attached card is the program's own source ({object_ref: program_source}) and whose Top-Most card is the
instruction's target - a unit its controller controls at the Battlefield the card was played from facedown at (location_ref
program_source_played_battlefield, noted as the trigger triggers; GPT A2 ruling 25; ADR-0017 §3, Core 435, 811.4).

  A1 facedown    the Gear played from facedown at bf1 enters bf1; its trigger is pending; finalized choosing u1 (p1's,
                 at bf1) it resolves: the Gear is attached to u1
  A2 not there   a unit of p1's in its Base is refused as the target ("here")
  A3 hand        the same Gear played from p1's hand: nothing triggers
  A4 gone        the Gear killed before the trigger resolves: nothing is attached (its source is gone)
  A5 recalled    (official FAQ) the Gear recalled to p1's Base before the trigger resolves: it is still attached to u1
                 at bf1, the unit chosen there - "(here)" is where it was played, not where it is now
  A6 noted       the trigger's chain item carries bf1 as its noted location
  V              attach's object_ref program_source validates; another object_ref shape does not
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

errors: list[str] = []
FX = "eon-fx"
ATTACH = {"op": "attach", "effect_id": "at", "object_id": {"object_ref": "program_source"},
          "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly",
                     "location_ref": {"kind": "program_source_played_battlefield"}}}


def program(pid, effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "eon", "effects": [copy.deepcopy(e) for e in effects]}


REGISTRY = {FX: program(FX, [ATTACH])}


def board(*, facedown=True):
    s = base_state()
    s["turn_id"] = "turn-2"
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"]}
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("u3")
    s["objects"]["eon"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                           "damage": 0, "exhausted": False, "tags": ["Equipment"],
                           "printed_cost": {"energy": 2, "power": {}},
                           "play_triggers": [{"trigger_id": "eon-on-play", "controller": "p1", "source_object": "eon",
                                              "controller_order": 0, "effect_program_id": FX,
                                              "optional_at_finalize": False,
                                              "condition": {"kind": "played_from_facedown"}}]}
    if facedown:
        s["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": [{"object_id": "eon", "controller": "p1",
                                                                          "hidden_on_turn": "turn-1"}]}
    else:
        s["players"]["p1"]["zones"]["hand"].append("eon")
        s["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return s


def played(s, *, facedown=True):
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-eon", "actor": "p1", "card": "eon",
            "chain_item": {"id": "gear-1", "object_kind": "gear", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}}
    if facedown:
        decl.update({"source": {"kind": "facedown", "battlefield": "bf1"},
                     "cost_override": {"kind": "ignore_base_cost", "source": "hidden"},
                     "entry_location": {"kind": "battlefield", "battlefield": "bf1"}})
    else:
        decl.update({"entry_location": {"kind": "base"}, "payment_context": {"add_window_closed": True, "confirmed_by": "human"}})
    got = PT.play_card(fixture(), s, decl)
    assert got.get("committed"), (got.get("reason_code"), got.get("reason"))
    timing = fixture(priority="p2", items=[item("gear-1", "p1", "gear", "default", "finalized")], passes=["p1", "p2"])
    done = resolve_with_program(timing, "gear-1", got["next_effect_state"], None)
    assert done.get("committed"), (done.get("reason"), done.get("stage"))
    return done


def pending(done):
    return [i for i in done["next_timing_state"]["chain"]["items"] if i.get("id") == "eon-on-play"]


def choose(state, target):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [target], "selection_identities": {target: object_identity(state, target)}}]}


def resolve_trigger(finalized, between=None):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    if between is not None:
        effect = between(effect)
    return resolve_with_program(timing, "eon-on-play", effect, REGISTRY[FX])


def kill_eon(state):
    return apply_program(state, {**program("k", [{"op": "kill", "effect_id": "k", "object_id": "eon"}]),
                                 "controller": "p2", "source_object": None})["next_state"]


def recall_eon(state):
    return apply_program(state, {**program("r", [{"op": "recall", "effect_id": "r", "object_id": "eon"}]),
                                 "controller": "p2", "source_object": None})["next_state"]


def main() -> int:
    done = played(board())
    after = done["next_effect_state"]
    if not pending(done) or "eon" not in after["battlefields"]["bf1"]["objects"]:
        errors.append(f"A1 facedown: trigger {bool(pending(done))}, eon at bf1 {'eon' in after['battlefields']['bf1']['objects']}")
    else:
        fin = finalize_trigger(done["next_timing_state"], after, REGISTRY, choose(after, "u1"))
        res = resolve_trigger(fin) if fin.get("committed") and not fin.get("removed") else {}
        if not res.get("committed") or res["next_effect_state"]["objects"]["eon"].get("attached_to") != "u1":
            errors.append(f"A1 facedown: {fin.get('reason')} {fin.get('message')} {res.get('reason')} "
                          f"{(res.get('next_effect_state') or {}).get('objects', {}).get('eon')}")
        base = finalize_trigger(done["next_timing_state"], after, REGISTRY, choose(after, "u3"))
        if base.get("committed") and not base.get("removed"):
            errors.append("A2 not there: a unit in p1's Base was accepted as the target")
        if [i.get("noted_location") for i in pending(done)] != [{"kind": "battlefield", "battlefield": "bf1"}]:
            errors.append(f"A6 noted: {[i.get('noted_location') for i in pending(done)]}")
        back = resolve_trigger(fin, between=recall_eon) if fin.get("committed") and not fin.get("removed") else {}
        st = back.get("next_effect_state") or {}
        if not back.get("committed") or (st.get("objects", {}).get("eon") or {}).get("attached_to") != "u1" \
                or "eon" not in st["battlefields"]["bf1"]["objects"]:
            errors.append(f"A5 recalled: {back.get('reason')} {back.get('reason_code')} {(st.get('objects') or {}).get('eon')}")
        gone = resolve_trigger(fin, between=kill_eon) if fin.get("committed") and not fin.get("removed") else {}
        if not gone.get("committed") or (gone["next_effect_state"]["objects"].get("eon") or {}).get("attached_to"):
            errors.append(f"A4 gone: {gone.get('reason')} {(gone.get('next_effect_state') or {}).get('objects', {}).get('eon')}")
    hand = played(board(facedown=False), facedown=False)
    if pending(hand):
        errors.append("A3 hand: the trigger was scheduled for a play from the hand")
    if validate_program(REGISTRY[FX]):
        errors.append(f"V: the attach program is invalid: {validate_program(REGISTRY[FX])}")
    bad = program(FX, [{**ATTACH, "object_id": {"object_ref": "program_targets"}}])
    if not validate_program(bad):
        errors.append("V: an attach of another object_ref validated")
    if errors:
        print("FAILED: attach this from facedown")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'When you play this from face down, attach it to a unit you control (here)' - triggers only from facedown, "
          "attaches the card itself to the unit chosen at its Battlefield; a Base unit refused; the card gone, nothing "
          "attached; recalled to its Base first, still attached to the unit chosen at the Battlefield it was played to "
          "(A1-A6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
