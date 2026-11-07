#!/usr/bin/env python3
"""ADR-0017 §3: [Equip] - an activated ability of an Equipment whose one instruction attaches it to a chosen unit its
controller controls (Core 818.1.b, 818.1.b.1, 818.1.c.2).

On a synthetic catalogue (an Equipment "Sword": Might Bonus 2, Effect Text [Tank], [Equip] costing 1 Energy and one
any-domain Power; units of p1 in its Base and at a Battlefield, one of p2's):

  E1 targets     the legal actions list Sword's Equip once per unit p1 controls - in the Base and at the Battlefield
                 (no "same location": 818.1.c.2) - and never at p2's unit
  E2 cost        each listed Equip declares its any-domain Power as a resource payment, not as an object to name
  E3 resolves    the Equip program, with the target decision, attaches Sword to the chosen unit: the unit has the Might
                 Bonus and [Tank]
  E4 illegal     the program with p2's unit as the decision ignores the instruction as an illegal target (359.3.e)
  E5 inactive    an attached Sword offers no Equip (721.2): its printed abilities are not activated
  E6 not a unit  an instruction to attach a unit does nothing (435.1.h.1)
  E7 placed      an Equipment's Effect Text trigger is namespaced by its object, its program by its card
  E8 appended    attached, the host has that trigger as its own, and its program binds to the host
  V1 shape       attach with both `to` and `target`, or neither, does not validate; a row's keyword is only "equip"
  V2 catalogue   an Effect Text trigger running no program of its card is refused
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_space as A  # noqa: E402
import closed_environment as CE  # noqa: E402
import engine_decisions as ED  # noqa: E402
from check_play_space import enumerate_for, environment  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, RULE_NUMBERING, apply_program, effective_might,  # noqa: E402
                       has_keyword, hash_value, object_identity, validate_program, validate_state)
from effect_ir import object_triggers as IR_object_triggers  # noqa: E402

FAILS: list[str] = []
EQUIP = {"op": "attach", "effect_id": "eq", "object_id": "$source_object",
         "target": {"decision_ref": "host", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}}


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + str(detail)) if detail != '' and not ok else ''}")
    if not ok:
        FAILS.append(name)


def catalogue() -> dict:
    value = {
        "schema_version": CE.CATALOGUE_VERSION,
        "environment": {"format": "1v1", "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING,
                        "card_pool": "synthetic"},
        "cards": {
            "Sword": {"object": {"kind": "gear", "printed_cost": {"energy": 1, "power": {}}, "domains": ["fury"],
                                 "tags": ["Equipment"], "might_bonus": 2, "effect_text": {"keywords": [{"keyword": "tank"}]}},
                      "activated_abilities": {"equip": {"cost": {"energy": 1, "power": {}, "additional": [
                          {"cost_id": "equip:any", "mandatory": True, "payment": {"kind": "power_any", "amount": 1}}]},
                          "effect_program_id": "equip", "keyword": "equip"}},
                      "programs": {"equip": {"effects": [EQUIP]}}},
            "Pawn": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1, "domains": ["calm"]}},
            # an Equipment whose Effect Text is a trigger ("When I conquer, draw 1."): its program is the card's
            "Bow": {"object": {"kind": "gear", "printed_cost": {"energy": 1, "power": {}}, "domains": ["fury"],
                               "tags": ["Equipment"], "might_bonus": 0, "effect_text": {"triggers": {"conquer_triggers": [
                                   {"trigger_id": "text-conquer", "controller": "$controller", "source_object": "$source_object",
                                    "controller_order": 0, "effect_program_id": "conquer", "optional_at_finalize": False}]}}},
                    "programs": {"conquer": {"effects": [{"op": "draw", "effect_id": "d", "player": "$controller", "count": 1}]}}},
            "Field": {"object": {"kind": "battlefield"}},
        },
        "catalogue_hash": "",
    }
    value["catalogue_hash"] = CE.catalogue_hash(value)
    return value


def equip_actions(result):
    return [a for a in A.enumerated_actions(result, "activate_ability") if a["declaration"]["card"] == "s"]


def program_for(state):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "equip-s", "controller": "p1", "source_object": "s",
            "effects": [{**EQUIP, "object_id": "s"}]}


def chosen(state, unit):
    return {"schema_version": ED.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [
        {"decision_id": "host", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": [unit], "selection_identities": {unit: object_identity(state, unit) or f"{unit}@0"}}]}


def main() -> int:
    cat = catalogue()
    check("the catalogue validates", not CE.validate_catalogue(cat), CE.validate_catalogue(cat))
    placed = [("s", "Sword", "p1", "base"), ("a", "Pawn", "p1", "base"), ("f", "Pawn", "p1", "bf1"), ("e", "Pawn", "p2", "base")]
    state = environment(cat, placed)
    state["players"]["p1"]["resources"] = {"energy": 3, "power": {"fury": 1}}
    problems = validate_state(state) + CE.environment_problems(state, cat)
    check("the environment state is valid", not problems, problems[:3])

    got = enumerate_for(state, cat)
    hosts = sorted(tuple(d["value"]) for a in equip_actions(got) for d in A.canonical_action_key(a)["decisions"]
                   if d["kind"] == "target_selection")
    check("E1 Equip is listed once per unit p1 controls, wherever it is", hosts == [("a",), ("f",)], hosts)
    costs = [a["declaration"]["cost"].get("additional") or [] for a in equip_actions(got)]
    check("E2 the any-domain Power is a resource payment", bool(costs) and all(
        [c["payment"] for c in row] == [{"kind": "power_any", "amount": 1}] for row in costs), costs)

    done = apply_program(state, program_for(state), decisions=chosen(state, "f"))
    after = done.get("next_state")
    check("E3 the Equip attaches Sword to the chosen unit", done.get("committed") and after["objects"]["s"].get("attached_to") == "f",
          done.get("reason") or done.get("errors"))
    if after:
        check("E3 the unit has the Might Bonus and [Tank]",
              effective_might(after, "f") == effective_might(state, "f") + 2 and has_keyword(after, "f", "tank"))
    illegal = apply_program(state, program_for(state), decisions=chosen(state, "e"))
    outcome = (illegal.get("trace") or [{}])[0].get("outcome") if illegal.get("committed") else illegal.get("reason_code")
    check("E4 p2's unit is an illegal target: the instruction is ignored", outcome == "ignored_illegal_target", outcome)

    if after:
        after["players"]["p1"]["resources"] = {"energy": 3, "power": {"fury": 1}}
        check("E5 an attached Sword offers no Equip", equip_actions(enumerate_for(after, cat)) == [])
    unit = apply_program(state, {**program_for(state), "effects": [{"op": "attach", "effect_id": "u", "object_id": "a", "to": "f"}]})
    check("E6 attaching a unit does nothing", unit.get("committed") and unit["trace"][0].get("outcome") == "no_op"
          and unit["next_state"]["objects"]["a"].get("attached_to") is None, unit.get("reason") or unit.get("trace"))

    import closed_environment as CE_
    import game_loop as GL
    bow_state = environment(cat, placed + [("b", "Bow", "p1", "base")])
    placed_text = bow_state["objects"]["b"]["effect_text"]["triggers"]["conquer_triggers"][0]
    check("E7 placed: the Effect Text trigger is namespaced by the object and its program by the card",
          placed_text["trigger_id"] == "b:text-conquer" and placed_text["effect_program_id"] == "Bow#conquer", placed_text)
    on = apply_program(bow_state, {**program_for(bow_state), "effects": [{"op": "attach", "effect_id": "a", "object_id": "b", "to": "f"}]})
    host = [t for t in IR_object_triggers(on["next_state"], "f", "conquer_triggers")] if on.get("committed") else []
    check("E8 attached: the host has the trigger, its source and controller", len(host) == 1
          and host[0]["source_object"] == "f" and host[0]["controller"] == "p1", host)
    if host:
        bound = GL.item_program(cat, on["next_state"], {"id": "i1", "effect_program_id": host[0]["effect_program_id"],
                                                        "controller": "p1", "source_object": "f"})
        check("E8 its program binds to the host", bound is not None and bound["source_object"] == "f"
              and bound["effects"][0]["player"] == "p1", bound)
    broken = catalogue()
    broken["cards"]["Bow"]["object"]["effect_text"]["triggers"]["conquer_triggers"][0]["effect_program_id"] = "missing"
    broken["catalogue_hash"] = CE_.catalogue_hash(broken)
    check("V2 an Effect Text trigger running no program of the card is refused",
          any("effect_text" in e for e in CE_.validate_catalogue(broken)), CE_.validate_catalogue(broken))

    both = {**program_for(state), "effects": [{**EQUIP, "object_id": "s", "to": "f"}]}
    neither = {**program_for(state), "effects": [{"op": "attach", "effect_id": "eq", "object_id": "s"}]}
    check("V1 attach with both `to` and `target` is refused", bool(validate_program(both)))
    check("V1 attach with neither is refused", bool(validate_program(neither)))
    bad = environment(cat, placed)
    bad["objects"]["s"]["activated_abilities"]["s:equip"]["keyword"] = "weaponmaster"
    check("V1 a row's keyword is only equip", any("activated_abilities" in e for e in validate_state(bad)))
    print(f"check_equip: {'FAILED ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
