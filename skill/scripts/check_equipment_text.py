#!/usr/bin/env python3
"""ADR-0017 §1-§2: an Equipment's Effect Text is an ability bundle about its Top-Most card, and its own printed rules
text is Inactive while it is attached.

  T1  an attached card's printed triggers do not work (Core 435.1.e, 721.2); they do again once it detaches
  T2  an attached card is not an active source for its printed passives (721.2)
  T3  an attached Temporary card does not trigger (722.2's example) but still has the keyword (722.1)
  T4  an Effect Text's keywords are granted to the Top-Most card, with their values ([Shield 2]); [Deflect] counts
  T5  an Effect Text's continuous effects apply to the Top-Most card (+2 Might), besides the Might Bonus
  T6  an Effect Text's triggers are the Top-Most card's: their source and controller are the host's (435.1.c)
  T7  attaching to a new host takes the Effect Text off the old one (435.1.f, 436.1.d)
  T8  detaching one of two Equipment leaves the other's Effect Text on the host (it used to go too)
  T9  the activate-conquer op reads the host's appended conquer triggers
  V1  a malformed bundle is refused: an ungrantable keyword, an effect that names its own id, an empty bundle
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import (apply_program, effective_might, has_keyword, keyword_values, object_triggers,  # noqa: E402
                       source_active, temporary_triggers, validate_state)

FAILS: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + str(detail)) if detail != '' and not ok else ''}")
    if not ok:
        FAILS.append(name)


def trigger(trigger_id, source, controller="p1"):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False}


def gear(**fields):
    return {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, "tags": ["Equipment"], **fields}


def scene():
    """u1 and u3 (p1) at bf1; g1, g2, g3 Equipment in p1's Base."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"]["objects"].append("u1")
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["battlefields"]["bf1"]["objects"].append("u3")
    state["objects"]["g1"] = gear(might_bonus=1, conquer_triggers=[trigger("own", "g1")], keywords=["temporary"],
                                  effect_text={"keywords": [{"keyword": "shield", "value": 2}],
                                               "effects": [{"kind": "might_arithmetic", "value": {"amount": 2, "mode": "delta"}}],
                                               "triggers": {"conquer_triggers": [trigger("text", "g1")]}})
    state["objects"]["g2"] = gear(might_bonus=0, effect_text={"keywords": [{"keyword": "tank"}]})
    state["objects"]["g3"] = gear(might_bonus=0)
    state["objects"]["g4"] = gear(might_bonus=1, effect_text={"keywords": [{"keyword": "deflect"}]})
    state["players"]["p1"]["zones"]["base"] += ["g1", "g2", "g3", "g4"]
    return settle_contested(state)


def attach(state, gear_id, host):
    result = apply_program(state, program("eq", {"op": "attach", "effect_id": "a", "object_id": gear_id, "to": host}))
    if not result.get("committed"):
        raise SystemExit(f"attach {gear_id} -> {host} failed: {result.get('reason_code')} {result.get('reason')}")
    return result["next_state"]


def ids(rows):
    return [r["trigger_id"] for r in rows]


def main() -> int:
    state = scene()
    check("the scene is valid", not validate_state(state), validate_state(state))
    on = attach(state, "g1", "u1")
    check("the attached scene is valid", not validate_state(on), validate_state(on))

    check("T1 a gear's printed trigger works while it is not attached", ids(object_triggers(state, "g1", "conquer_triggers")) == ["own"])
    check("T1 and not while attached", ids(object_triggers(on, "g1", "conquer_triggers")) == [])
    off = apply_program(on, program("de", {"op": "detach", "effect_id": "d", "object_id": "g1"}))["next_state"]
    check("T1 and again once detached", ids(object_triggers(off, "g1", "conquer_triggers")) == ["own"])
    check("T2 an attached card is no active source", source_active(state, "g1") and not source_active(on, "g1"))
    check("T3 an attached Temporary gear does not trigger", temporary_triggers(state, "g1", "p1") != []
          and temporary_triggers(on, "g1", "p1") == [])
    check("T3 but still has the keyword", has_keyword(on, "g1", "temporary"))

    check("T4 the host gets [Shield 2] from the Effect Text", keyword_values(on, "u1").get("shield") == 2,
          keyword_values(on, "u1"))
    check("T4 not before the attach", not has_keyword(state, "u1", "shield"))
    from effect_ir import deflect_total
    hex_on = attach(state, "g4", "u1")
    check("T4 [Deflect] from an Effect Text counts as the host's Deflect (Hexdrinker)",
          deflect_total(state, "u1") == 0 and deflect_total(hex_on, "u1") == 1, deflect_total(hex_on, "u1"))
    check("T5 Might: printed 3, Might Bonus +1, Effect Text +2", effective_might(on, "u1") == effective_might(state, "u1") + 3,
          (effective_might(state, "u1"), effective_might(on, "u1")))
    text = [t for t in object_triggers(on, "u1", "conquer_triggers") if t["trigger_id"] == "text"]
    check("T6 the appended trigger is the host's", len(text) == 1 and text[0]["source_object"] == "u1"
          and text[0]["controller"] == "p1", text)

    moved = attach(on, "g1", "u3")
    check("T7 the old host loses the Effect Text", not has_keyword(moved, "u1", "shield")
          and ids(object_triggers(moved, "u1", "conquer_triggers")) == []
          and effective_might(moved, "u1") == effective_might(state, "u1"),
          (keyword_values(moved, "u1"), effective_might(moved, "u1")))
    check("T7 and the new host has it", keyword_values(moved, "u3").get("shield") == 2
          and effective_might(moved, "u3") == effective_might(state, "u3") + 3)

    both = attach(on, "g2", "u1")
    one = apply_program(both, program("de", {"op": "detach", "effect_id": "d", "object_id": "g2"}))["next_state"]
    check("T8 two attached: shield and tank", has_keyword(both, "u1", "shield") and has_keyword(both, "u1", "tank"))
    check("T8 detaching g2 keeps g1's Effect Text", has_keyword(one, "u1", "shield") and not has_keyword(one, "u1", "tank")
          and effective_might(one, "u1") == effective_might(state, "u1") + 3, keyword_values(one, "u1"))
    check("T8 and the state is valid", not validate_state(one), validate_state(one))

    from effect_ir import PROGRAM_VERSION, CORE_RULESET, FAQ_AS_OF, battlefield_identity
    arena = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
             "program_id": "arena", "controller": "p1", "source_object": "bf1", "source_identity": battlefield_identity(on, "bf1"),
             "effects": [{"op": "activate_conquer_effects", "effect_id": "act",
                          "location_ref": {"kind": "program_source_current_battlefield"}}]}
    conquer = apply_program(on, arena)
    found = [t.get("trigger_id") for t in conquer.get("pending_triggers", [])] if conquer.get("committed") else None
    check("T9 activate-conquer reads the host's appended conquer trigger", found is not None and "text" in found,
          conquer.get("reason") if found is None else found)

    for name, text_value in (("an ungrantable keyword", {"keywords": [{"keyword": "flying"}]}),
                             ("an effect naming its own id", {"effects": [{"kind": "might_arithmetic", "effect_id": "x",
                                                                           "value": {"amount": 1, "mode": "delta"}}]}),
                             ("an empty bundle", {"keywords": []})):
        bad = scene()
        bad["objects"]["g3"]["effect_text"] = text_value
        check(f"V1 refused: {name}", any("effect_text" in e for e in validate_state(bad)), validate_state(bad))
    print(f"check_equipment_text: {'FAILED ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
