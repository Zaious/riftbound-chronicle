#!/usr/bin/env python3
"""Regression gate (set 2 package A2: The Zero Drive - "[Equip] ... :rb_energy_3::rb_rune_mind:, Banish this: Play all units
banished with this, ignoring their costs. (Use only if unattached.)", its Effect Text "[Deathknell] - Banish me.").

Core 396: abilities granted by the same source are linked - the Deathknell its Effect Text grants and its activated ability;
398: the activated ability plays only the units those linked abilities banished.

  Z1 granted    attached to h1, h1 has the Deathknell; its descriptor names the Zero Drive (granted_by)
  Z2 dies       h1 killed: the death trigger raised carries granted_by; finalized and resolved, "Banish me" moves h1 from
                p1's trash to its Banishment, and the Zero Drive records h1 (as the object it is there)
  Z3 plays      the activated ability's program (source the Zero Drive): one effect-driven play of h1 started, ignoring its
                cost; a unit banished by something else (u9) is not played
  Z4 gone       h1 left the Banishment (or is another object now): nothing is played
  Z5 not in trash  the trigger resolving after h1 left its trash: "Banish me" does nothing, nothing recorded
  V             banish self from another zone, link_to_granter without self, a linked_set of another shape do not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, object_identity, object_triggers,  # noqa: E402
                       validate_program)
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import pass_priority, schedule_triggered_items  # noqa: E402

DK_PROGRAM = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
              "program_id": "zd-dk-fx", "controller": "p1", "source_object": "h1",
              "effects": [{"op": "banish", "effect_id": "b", "self": {"from": "trash"},
                                                     "link_to_granter": True}]}
PLAY = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "program_id": "zd-ability", "controller": "p1", "source_object": "zd",
        "effects": [{"op": "limited_play", "effect_id": "lp", "linked_set": {"from": "banishment", "kind": "unit"},
                     "cost_basis": {"kind": "ignore_all"}}]}


def program(pid, effects, source):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": source, "effects": effects}


def board():
    s = base_state()
    s["objects"]["h1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "printed_cost": {"energy": 4, "power": {}}}
    s["objects"]["zd"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Equipment"],
                          "effect_text": {"triggers": {"death_triggers": [{
                              "trigger_id": "zd-dk", "controller": "p1", "source_object": "zd", "controller_order": 0,
                              "effect_program_id": "zd-dk-fx", "optional_at_finalize": False, "linked_to_source": True}]}}}
    s["objects"]["u9"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 1, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"] += ["h1", "zd"]
    s["players"]["p1"]["zones"]["banishment"].append("u9")
    attached = apply_program(s, program("eq", [{"op": "attach", "effect_id": "at", "object_id": "zd", "to": "h1"}], "zd"))
    return attached["next_state"]


def died(state):
    killed = apply_program(state, program("k", [{"op": "kill", "effect_id": "k", "object_id": "h1"}], "u1"))
    return killed["next_state"], killed.get("pending_triggers") or []


def resolve_trigger(state, descriptor):
    timing = schedule_triggered_items(fixture(), [{**descriptor, "trigger_kind": "triggered", "batch_sequence": 0,
                                                   "batch_id": "death:h1"}])["next_state"]
    fin = finalize_trigger(timing, state, {"zd-dk-fx": DK_PROGRAM}, None)
    if not fin.get("committed"):
        return fin
    t, e = fin["next_timing_state"], fin["next_effect_state"]
    for actor in ("p1", "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    return resolve_with_program(t, descriptor["trigger_id"], e, DK_PROGRAM)


def main() -> int:
    errors: list[str] = []
    for p in (DK_PROGRAM, PLAY):
        if validate_program(p):
            errors.append(f"V: {p['program_id']} {validate_program(p)[:2]}")
    s = board()
    granted = object_triggers(s, "h1", "death_triggers")
    if len(granted) != 1 or granted[0].get("granted_by") != "zd" or granted[0].get("source_object") != "h1":
        errors.append(f"Z1 granted: {granted}")
        return report(errors)
    after_death, pending = died(s)
    mine = [d for d in pending if d.get("granted_by") == "zd"]
    if len(mine) != 1 or "h1" not in after_death["players"]["p1"]["zones"]["trash"]:
        errors.append(f"Z2 dies: {pending}")
        return report(errors)
    done = resolve_trigger(after_death, mine[0])
    e = done.get("next_effect_state") or {}
    record = (e.get("objects") or {}).get("zd", {}).get("linked_banished")
    if not done.get("committed") or "h1" not in e["players"]["p1"]["zones"]["banishment"] \
            or record != [{"card": "h1", "identity": object_identity(e, "h1")}]:
        errors.append(f"Z2 dies: {done.get('reason') or done.get('reason_code')} {record}")
        return report(errors)
    played = apply_program(e, PLAY)
    starts = [ev for ev in played.get("trace") or [] if ev.get("op") == "limited_play" and ev.get("linked_card")]
    if not played.get("committed") or [ev["linked_card"] for ev in starts] != ["h1"]:
        errors.append(f"Z3 plays: {played.get('reason') or played.get('errors')} {[ev.get('outcome') for ev in played.get('trace') or []]}")
    # its cost banishes the Zero Drive itself first ("Banish this"): the record of what its linked ability banished is kept
    paid = apply_program(e, program("cost", [{"op": "banish", "effect_id": "b", "object_id": "zd"}], "zd"))
    after_cost = paid.get("next_state") or {}
    again = apply_program(after_cost, PLAY) if paid.get("committed") else {}
    if [ev.get("linked_card") for ev in again.get("trace") or [] if ev.get("linked_card")] != ["h1"]:
        errors.append(f"Z3 plays: after Banish this {again.get('reason') or again.get('errors')}")
    gone = copy.deepcopy(e)
    gone["players"]["p1"]["zones"]["banishment"].remove("h1")
    gone["players"]["p1"]["zones"]["hand"].append("h1")
    gone["objects"]["h1"]["identity"] = "h1@9"
    none = apply_program(gone, PLAY)
    if not none.get("committed") or [ev.get("outcome") for ev in none.get("trace") or []] != ["no_op"]:
        errors.append(f"Z4 gone: {[ev.get('outcome') for ev in none.get('trace') or []]}")
    moved = copy.deepcopy(after_death)
    moved["players"]["p1"]["zones"]["trash"].remove("h1")
    moved["players"]["p1"]["zones"]["hand"].append("h1")
    late = resolve_trigger(moved, mine[0])
    le = late.get("next_effect_state") or {}
    if not late.get("committed") or (le.get("objects") or {}).get("zd", {}).get("linked_banished"):
        errors.append(f"Z5 not in trash: {late.get('reason') or late.get('reason_code')}")
    for label, effect in (("self from hand", {"op": "banish", "effect_id": "b", "self": {"from": "hand"}}),
                          ("link without self", {"op": "banish", "effect_id": "b", "object_id": "u1", "link_to_granter": True}),
                          ("another linked set", {"op": "limited_play", "effect_id": "lp", "linked_set": {"from": "trash", "kind": "unit"},
                                                  "cost_basis": {"kind": "ignore_all"}})):
        if not validate_program(program("x", [effect], "zd")):
            errors.append(f"V: {label} validated")
    return report(errors)


def report(errors) -> int:
    if errors:
        print("zero-drive checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("zero-drive checks passed: the Effect Text's Deathknell, linked with its granting card (granted_by), banishes the "
          "dead unit from its trash and the Zero Drive records it; its activated ability plays exactly the units so banished "
          "(not another banished unit, not one gone); a source no longer in the trash banishes nothing; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
