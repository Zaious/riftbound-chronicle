#!/usr/bin/env python3
"""A reflexive trigger after a Move, its target chosen as it is finalized (package 11, Dragon's Rage: "Move an enemy unit.
Then do this: Choose another enemy unit at its destination. They deal damage equal to their Mights to each other.").

"Then do this:" is a Reflexive Trigger with no condition (Core 387.1, 387.2): once the Move is done it is added to the
Chain as its own Pending item (388.1) - not a choice inside the spell's resolution (GPT 2026-10-12, PACKAGE11 ruling 4).
The spell's conditional trigger {kind: unconditional, effect_id: <the Move>} is always held; the descriptor carries what
the Move did - the moved unit as trigger_event (the identity it had once moved) and where it went as noted_location - and
the program reads them: the unit as {object_ref: trigger_event_object} in one slot of the pair, the destination as
{location_ref: trigger_event_destination}, "another" as exclude_trigger_event_object. The second unit is chosen as the
trigger is finalized (Core 402, 355.5), Deflect paid then (809.1.c, 404.1), and the trigger has its own window before it
resolves.

  R1 exchange      e1 moved bf1 -> bf2; the trigger carries e1 and bf2; finalized choosing e2 there, it resolves: each
                   is dealt the other's Might, read at resolution
  R2 illegal       at finalization the moved unit itself, an enemy unit at another battlefield, and a friendly unit at
                   the destination are each refused as targets
  R3 window        finalized, then e1 is killed before the trigger resolves: the pair is ignored (the referent is gone),
                   e2 is dealt nothing
  R4 nobody there  no other enemy unit at the destination: at finalization the trigger leaves the Chain (Core 402.4),
                   never finalized, nothing dealt
  R5 not moved     the Move is ignored (bf1 forbids moving to a Base): the trigger is still added (387.2) with nothing bound, and leaves
                   at finalization (402.4)
  R6 Deflect       choosing an enemy unit with Deflect costs the trigger's controller 1 Power of any domain: asked for,
                   declined -> the trigger leaves (404.2); paid -> the receipt carries the Deflect component and the
                   pair resolves; a trigger choosing no Deflect unit is asked for nothing
  R7 base          e1 moved from bf1 to its controller's Base: every enemy unit in that Base is a legal choice, one at bf1
                   is not; it resolves
  R8 shape         the unconditional kind validates; an unknown kind does not; a selector excluding the referent in a
                   program with no event makes every target illegal by name

    python skill/scripts/check_reflexive_move.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from play_transaction import legal_target_options  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

errors: list[str] = []
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
TRIGGER = "rage-reflexive"
REFLEXIVE = "rage-reflexive-fx"


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(*, deflect=False, nobody=False, restricted=False, base_target=False):
    """bf1: e1 (p2, 5), e3 (p2, 2); bf2: e2 (p2, 4), a1 (p1, 3). The spell spell-1 is on the Chain."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, owner, might in (("e1", "p2", 5), ("e3", "p2", 2), ("e2", "p2", 4), ("a1", "p1", 3)):
        state["objects"][oid] = unit(owner, might)
    state["battlefields"]["bf1"]["objects"] = ["e1", "e3"]
    state["battlefields"]["bf2"]["objects"] = [] if nobody else ["e2", "a1"]
    if base_target:
        state["players"]["p2"]["zones"]["base"].append("e2")
        state["battlefields"]["bf2"]["objects"] = ["a1"]
    if nobody:
        state["players"]["p1"]["zones"]["base"].append("a1")
        state["players"]["p2"]["zones"]["base"].append("e2")
    if deflect:
        state["objects"]["e2"]["keywords"] = ["deflect"]
    if restricted:
        state["battlefields"]["bf1"]["move_restrictions"] = [{"affected_kind": "unit", "source_location": "here",
                                                             "destination_kind": "base"}]
    state["players"]["p1"]["resources"] = {"energy": 0, "power": {"fury": 1}}
    return settle_contested(state)


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "spell-1", "effects": effects, **extra}


def spell(destination):
    return program("spell-1-effects", [{"op": "move_board_object", "effect_id": "mv", "object_id": "e1",
                                        "destination": destination}],
                   conditional_triggers=[{"trigger_id": TRIGGER, "controller": "p1", "source_object": "spell-1",
                                          "controller_order": 0, "effect_program_id": REFLEXIVE, "optional_at_finalize": False,
                                          "condition": {"kind": "unconditional", "effect_id": "mv"}}])


SECOND = {"decision_ref": "e2", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy",
          "location_ref": {"kind": "trigger_event_destination"}, "exclude_trigger_event_object": True}
REGISTRY = {REFLEXIVE: program(REFLEXIVE, [{"op": "mutual_damage_current_might", "effect_id": "they", "units": [
    {"object_id": {"object_ref": "trigger_event_object"}, "chosen_zone_class": "board", "kind": "unit"}, dict(SECOND)]}])}
BF2 = {"kind": "battlefield", "battlefield": "bf2"}


def resolve_spell(state, destination=BF2):
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "spell-1", state, spell(destination))


def choose(state, value, ref="e2"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": ref, "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1", "value": [value],
         "selection_identities": {value: object_identity(state, value)}}]}


def pending(done):
    return [i for i in done["next_timing_state"]["chain"]["items"] if i.get("trigger_kind") == "reflexive"]


def resolve_trigger(finalized, *, between=None):
    timing, effect = finalized["next_timing_state"], finalized["next_effect_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    if between is not None:
        effect = between(effect)
    return resolve_with_program(timing, TRIGGER, effect, REGISTRY[REFLEXIVE])


def kill(state, oid):
    done = apply_program(state, {**program("k", [{"op": "kill", "effect_id": "k", "object_id": oid}]), "controller": "p2"})
    return done["next_state"]


def where(state, oid):
    for player, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if oid in ids:
                return f"{player}:{zone}"
    for bf, data in state["battlefields"].items():
        if oid in data["objects"]:
            return bf
    return None


def main() -> int:
    # R1 exchange
    done = resolve_spell(board())
    items = pending(done) if done.get("committed") else []
    if len(items) != 1 or items[0].get("noted_location") != BF2 or (items[0].get("trigger_event") or {}).get("object") != "e1":
        fail("R1 exchange", f"the trigger was not added carrying e1 and bf2: {done.get('reason') or [(i.get('trigger_event'), i.get('noted_location')) for i in items]}")
        return report()
    after = done["next_effect_state"]
    if where(after, "e1") != "bf2":
        fail("R1 exchange", f"e1 is at {where(after, 'e1')}")
    finalized = finalize_trigger(done["next_timing_state"], after, REGISTRY, choose(after, "e2"))
    if not finalized.get("committed") or finalized.get("removed"):
        fail("R1 exchange", f"not finalized choosing e2: {finalized.get('reason')} {finalized.get('message')}")
    else:
        got = resolve_trigger(finalized)
        s = got.get("next_effect_state") or {}
        if not got.get("committed") or s["objects"]["e1"]["damage"] != 4 or where(s, "e2") != "p2:trash":
            fail("R1 exchange", f"{got.get('reason') or got.get('reason_code')} e1 damage "
                                f"{(s.get('objects') or {}).get('e1', {}).get('damage')}, e2 at {where(s, 'e2') if s else None}")
    # R2 illegal choices
    for label, value in (("the moved unit itself", "e1"), ("an enemy unit elsewhere", "e3"), ("a friendly unit there", "a1")):
        refused = finalize_trigger(done["next_timing_state"], after, REGISTRY, choose(after, value))
        if refused.get("committed") or refused.get("reason") != "target_illegal_at_play":
            fail("R2 illegal", f"{label} ({value}): {refused.get('committed')} {refused.get('reason')}")
    # R3 window: killed between finalization and resolution
    if finalized.get("committed"):
        got = resolve_trigger(finalized, between=lambda s: kill(s, "e1"))
        step = next((e for e in got.get("trace", {}).get("effect", []) or [] if e.get("effect_id") == "they"), {}) \
            if isinstance(got.get("trace"), dict) else {}
        s = got.get("next_effect_state") or {}
        if not got.get("committed") or (s.get("objects") or {}).get("e2", {}).get("damage") != 0:
            fail("R3 window", f"{got.get('reason') or got.get('reason_code')} {step.get('outcome')} "
                              f"e2 damage {(s.get('objects') or {}).get('e2', {}).get('damage')}")
    # R4 nobody there
    alone = resolve_spell(board(nobody=True))
    left = finalize_trigger(alone["next_timing_state"], alone["next_effect_state"], REGISTRY, None) if alone.get("committed") else {}
    if not left.get("removed") or (left.get("transition") or {}).get("type") != "no_legal_choices":
        fail("R4 nobody there", f"{alone.get('reason')} {left.get('reason')} {left.get('transition')}")
    # R5 not moved
    held = resolve_spell(board(restricted=True), {"kind": "base", "player": "p2"})
    items = pending(held) if held.get("committed") else []
    if len(items) != 1 or items[0].get("trigger_event") or items[0].get("noted_location") \
            or where(held.get("next_effect_state") or {}, "e1") != "bf1":
        fail("R5 not moved", f"{held.get('reason')} {[(i.get('trigger_event'), i.get('noted_location')) for i in items]}")
    else:
        left = finalize_trigger(held["next_timing_state"], held["next_effect_state"], REGISTRY, None)
        if not left.get("removed"):
            fail("R5 not moved", f"the trigger did not leave at finalization: {left.get('reason')} {left.get('transition')}")
    # R6 Deflect
    shielded = resolve_spell(board(deflect=True))
    s6 = shielded["next_effect_state"]
    asked = finalize_trigger(shielded["next_timing_state"], s6, REGISTRY, choose(s6, "e2"))
    if asked.get("committed") or asked.get("reason") != "trigger_cost_choice_required" \
            or [c.get("payment") for c in asked.get("deflect_costs") or []] != [{"kind": "power_any", "amount": 1}]:
        fail("R6 Deflect", f"not asked for the Deflect cost: {asked.get('reason')} {asked.get('deflect_costs')}")
    declined = finalize_trigger(shielded["next_timing_state"], s6, REGISTRY, choose(s6, "e2"), pay_trigger_cost=False)
    if not declined.get("removed") or declined["next_effect_state"]["players"]["p1"]["resources"]["power"].get("fury") != 1:
        fail("R6 Deflect", f"declined, the trigger did not leave unpaid: {declined.get('reason')} {declined.get('transition')}")
    paid = finalize_trigger(shielded["next_timing_state"], s6, REGISTRY, choose(s6, "e2"), pay_trigger_cost=True,
                            payment_context=CLOSED)
    if not paid.get("committed") or paid.get("removed") \
            or paid["next_effect_state"]["players"]["p1"]["resources"]["power"].get("fury") != 0 \
            or not any(str(c.get("cost_id", "")).startswith("deflect:e2") for c in (paid.get("cost_receipt") or {}).get("components") or []):
        fail("R6 Deflect", f"paid, not finalized with the Deflect component: {paid.get('reason')} {paid.get('message')}")
    else:
        got = resolve_trigger(paid)
        if not got.get("committed") or got["next_effect_state"]["objects"]["e1"]["damage"] != 4:
            fail("R6 Deflect", f"paid, the pair did not resolve: {got.get('reason') or got.get('reason_code')}")
    if finalized.get("committed") and (finalized.get("trigger_cost") or finalized.get("cost_receipt")):
        fail("R6 Deflect", "a choice with no Deflect was charged")
    # R7 a Base destination
    home = resolve_spell(board(base_target=True), {"kind": "base", "player": "p2"})
    items = pending(home) if home.get("committed") else []
    if len(items) != 1 or items[0].get("noted_location") != {"kind": "base", "player": "p2"}:
        fail("R7 base", f"{home.get('reason')} {[i.get('noted_location') for i in items]}")
    else:
        s7 = home["next_effect_state"]
        bound = {**REGISTRY[REFLEXIVE], "trigger_event": items[0]["trigger_event"], "noted_location": items[0]["noted_location"]}
        options = legal_target_options(s7, "p1", bound, SECOND)
        if sorted(options) != ["e2", "u2"]:
            fail("R7 base", f"the legal choices at p2's Base are {options}, not e2 and u2 (both there; e3 at bf1 is not)")
        f7 = finalize_trigger(home["next_timing_state"], s7, REGISTRY, choose(s7, "e2"))
        got = resolve_trigger(f7) if f7.get("committed") else {}
        if not got.get("committed") or got["next_effect_state"]["objects"]["e1"]["damage"] != 4:
            fail("R7 base", f"{f7.get('reason')} {got.get('reason') or got.get('reason_code')}")
    # R8 shape
    if validate_program(spell(BF2)):
        fail("R8 shape", f"the unconditional kind did not validate: {validate_program(spell(BF2))}")
    wrong = spell(BF2)
    wrong["conditional_triggers"][0]["condition"]["kind"] = "whenever"
    if not validate_program(wrong):
        fail("R8 shape", "an unknown condition kind validated")
    if validate_program(REGISTRY[REFLEXIVE]):
        fail("R8 shape", f"the reflexive program did not validate: {validate_program(REGISTRY[REFLEXIVE])}")
    unbound = {**REGISTRY[REFLEXIVE], "noted_location": BF2}
    if legal_target_options(after, "p1", unbound, SECOND):
        fail("R8 shape", "with no event, 'another' than the referent still admitted a target")
    return report()


def report() -> int:
    if errors:
        print("FAILED: reflexive trigger after a Move")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'Then do this:' after a Move is its own Chain item, always added (387.2), carrying the moved unit and its "
          "destination; its second unit is chosen at finalization - not the moved one, not elsewhere, not friendly - Deflect "
          "paid then or declined; nobody there or nothing moved: it leaves (402.4); the moved unit gone before it resolves: "
          "ignored; a Base destination reads that Base (R1-R8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
