#!/usr/bin/env python3
"""Regression gate (set 2 package A3: Rell - Magnetic, errata'd 2026-01-14: "When I attack, you may play an Equipment with
Energy cost no more than [2], ignoring its cost. If you do, then do this: Attach it to me."): a play an ability makes from
the hand (limited_play, choice from the hand - a private zone, no target), then a Reflexive Trigger whose condition is "If
you do" (conditional_triggers kind performed, Core 388.2-388.3) attaching the card that play put on the board to the
ability's source. The play is the older Pending item, finalized first; a Gear resolves immediately once finalized (Core
337.2, 337.1.b), into its base (152.2); only then is the Reflexive Trigger finalized and resolved. "it" is the played card in
the identity its play gives it on the board (Core 124).

  R1 played, attached  p1's Equipment eq (printed Energy 2, a Power cost) chosen from hand: Chain = the play, then the
                       Reflexive Trigger; the play completes at no cost (Core 356.1.b.1) and eq is in p1's base; the
                       trigger finalizes and resolves: eq is attached to rell
  R2 declined          no card chosen: the play is not performed, no Reflexive Trigger is added (the trace names why)
  R3 not eligible      a 3-Energy Equipment, or a 2-Energy Gear without the Equipment tag, is not offered: choosing it is
                       refused
  R4 it left           eq killed after its play resolved and before the trigger resolves: the attach is ignored (a new
                       object at its id, Core 124, 359.3.e.6), nothing attached
  R5 me gone           rell killed before the trigger resolves: the attach is ignored, eq stays unattached in the base
  V  validation        a performed condition naming an instruction that is not a limited_play, or an attach of the
                       referent carrying another field, does not validate

    python skill/scripts/check_reflexive_after_play.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from check_limited_play import CLOSED, card, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import find_location, hash_value, object_identity, validate_program  # noqa: E402
from resolution_bridge import complete_limited_play, finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

errors: list[str] = []
PLAY = {"op": "limited_play", "effect_id": "lp", "decision_ref": "c",
        "choice": {"from": "hand", "selection_kind": "unordered_set", "count": {"up_to": 1}, "by": "controller",
                   "visibility": "private_to_chooser"},
        "card_filter": {"kind": "gear", "with_tag": "Equipment", "printed_energy_at_most": 2},
        "cost_basis": {"kind": "ignore_all"}}
ATTACH = program("rell-attach", "rell", [{"op": "attach", "effect_id": "at",
                                          "object_id": {"object_ref": "trigger_event_object"},
                                          "to": {"object_ref": "program_source"}}])
REGISTRY = {ATTACH["program_id"]: ATTACH}


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def attack_program() -> dict:
    prog = program("rell-attack", "rell", [copy.deepcopy(PLAY)])
    prog["conditional_triggers"] = [{"trigger_id": "rell-reflexive", "controller": "p1", "source_object": "rell",
                                     "controller_order": 0, "effect_program_id": "rell-attach",
                                     "optional_at_finalize": False, "condition": {"kind": "performed", "effect_id": "lp"}}]
    return prog


def board() -> dict:
    s = base_state()
    s["objects"]["rell"] = card("p1", "unit", {"energy": 4, "power": {}}, might=4)
    s["players"]["p1"]["zones"]["base"].append("rell")
    s["objects"]["eq"] = card("p1", "gear", {"energy": 2, "power": {"order": 1}}, tags=["Equipment"])
    s["objects"]["eq3"] = card("p1", "gear", {"energy": 3, "power": {}}, tags=["Equipment"])
    s["objects"]["plain"] = card("p1", "gear", {"energy": 1, "power": {}})
    s["players"]["p1"]["zones"]["hand"] += ["eq", "eq3", "plain"]
    s["players"]["p1"]["resources"] = {"energy": 0, "power": {}}
    return s


def resolve_trigger(s: dict, chosen: list[str]) -> dict:
    timing = fixture(priority="p2", items=[item("rell-attack", "p1", "ability", "default", "finalized")], passes=["p1", "p2"])
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": "c", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": list(chosen),
         "selection_identities": {c: object_identity(s, c) for c in chosen}}]}
    return resolve_with_program(timing, "rell-attack", s, attack_program(), engine_decisions=decisions)


def resolve_reflexive(timing: dict, effect: dict) -> dict:
    fin = finalize_trigger(timing, effect, REGISTRY, None)
    if not fin.get("committed"):
        return fin
    t, e = fin["next_timing_state"], fin.get("next_effect_state") or effect
    while next_procedure(t).get("procedure") != "resolve_newest_finalized":
        holder = t.get("priority")
        passed = pass_priority(t, holder) if holder else {}
        if not passed.get("next_state"):
            break
        t = passed["next_state"]
    return resolve_with_program(t, "rell-reflexive", e, ATTACH)


def played_then(s: dict):
    """The trigger resolved choosing eq, and the play completed: (timing, effect) with the Reflexive Trigger Pending."""
    done = resolve_trigger(s, ["eq"])
    assert done.get("committed"), (done.get("reason"), done.get("reason_code"))
    lp = complete_limited_play(done["next_timing_state"], done["next_effect_state"], None, payment_context=CLOSED)
    assert lp.get("committed"), (lp.get("reason"), lp.get("message"))
    return done, lp["next_timing_state"], lp["next_effect_state"]


def main() -> int:
    s = board()
    done, t, e = played_then(s)
    order = [(i["id"], i["status"]) for i in done["next_timing_state"]["chain"]["items"]]
    if order != [("limited-play:rell-attack:lp", "pending"), ("rell-reflexive", "pending")]:
        fail("R1 order", f"{order}")
    if find_location(e, "eq") != ("player", "p1", "base") or e["players"]["p1"]["resources"] != {"energy": 0, "power": {}}:
        fail("R1 play", f"eq at {find_location(e, 'eq')}, resources {e['players']['p1']['resources']}")
    attached = resolve_reflexive(t, e)
    after = attached.get("next_effect_state") or {}
    if not attached.get("committed") or (after.get("objects", {}).get("eq") or {}).get("attached_to") != "rell":
        fail("R1 attached", f"{attached.get('reason_code') or attached.get('reason')} "
                            f"{(after.get('objects', {}).get('eq') or {}).get('attached_to')}")
    declined = resolve_trigger(board(), [])
    items = [i["id"] for i in (declined.get("next_timing_state") or {}).get("chain", {}).get("items", [])]
    if not declined.get("committed") or "rell-reflexive" in items:
        fail("R2 declined", f"{declined.get('reason')} chain {items}")
    for label, bad in (("R3 three Energy", "eq3"), ("R3 not an Equipment", "plain")):
        refused = resolve_trigger(board(), [bad])
        if refused.get("committed"):
            fail(label, f"{bad} was played")
    _, t4, e4 = played_then(board())
    e4 = copy.deepcopy(e4)
    e4["players"]["p1"]["zones"]["base"].remove("eq")
    e4["players"]["p1"]["zones"]["trash"].append("eq")
    e4["objects"]["eq"]["identity"] = "eq@3"
    gone = resolve_reflexive(t4, e4)
    if not gone.get("committed") or (gone["next_effect_state"]["objects"]["eq"].get("attached_to")):
        fail("R4 it left", f"{gone.get('reason_code') or gone.get('reason')}")
    _, t5, e5 = played_then(board())
    e5 = copy.deepcopy(e5)
    e5["players"]["p1"]["zones"]["base"].remove("rell")
    e5["players"]["p1"]["zones"]["trash"].append("rell")
    e5["objects"]["rell"]["identity"] = "rell@1"
    no_host = resolve_reflexive(t5, e5)
    if not no_host.get("committed") or no_host["next_effect_state"]["objects"]["eq"].get("attached_to") \
            or find_location(no_host["next_effect_state"], "eq") != ("player", "p1", "base"):
        fail("R5 me gone", f"{no_host.get('reason_code') or no_host.get('reason')}")
    bad = attack_program()
    bad["effects"].append({"op": "draw", "effect_id": "dr", "player": "p1", "amount": 1})
    bad["conditional_triggers"][0]["condition"]["effect_id"] = "dr"
    if not validate_program(bad):
        fail("V performed", "a performed condition on a draw validated")
    extra = copy.deepcopy(ATTACH)
    extra["effects"][0]["target"] = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}
    if not validate_program(extra):
        fail("V attach", "an attach of the referent carrying a target validated")
    if errors:
        print("reflexive-after-play checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("reflexive-after-play checks passed: the play from hand (an Equipment of printed Energy 2 or less, no cost) "
          "resolves first, then 'If you do, then do this' attaches it to the source; declined, nothing is added; an "
          "ineligible card is refused; it gone or the source gone, the attach is ignored; validated (R1-R5, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
