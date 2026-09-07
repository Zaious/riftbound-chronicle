#!/usr/bin/env python3
"""
Regression gate for C-53 (ADR-0013 §6): the Effect Text of an attached card
appended in the Ability layer, and copy over the traits the engine models.

Must hold:
  - attaching a card that carries an Effect Text appends its abilities to the
    Top-Most card (477.2): the host's trigger list gains them while the host's
    own printed abilities stay, and the attached card keeps its own;
  - the append is a continuous effect with `until_detached` duration, so
    detaching removes it and the host's abilities go back to what they were —
    the same host with the card still attached keeps them (negative mutation);
  - a host that leaves the board takes the append with it;
  - every scheduler reads through `object_triggers`, so an appended death or
    play trigger really fires: killing a host with an appended death trigger
    schedules it, and the same host without the attachment schedules nothing;
  - copy applies the modelled copyable traits (477.1): the target's type and
    rules text become the source's, while its Might and damage do not change;
  - a copy that needs a trait the model does not carry — name, tags, printed
    cost, domain — is `unsupported: copy_unmodelled_traits` and changes
    nothing, while the same copy of the modelled traits commits (negative
    mutation);
  - the validator refuses an append naming a field that is not an ability list
    and a copy naming an unmodelled trait in the state;
  - the effect scope declares both and keeps the copy boundary.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, characteristics, object_triggers, validate_state  # noqa: E402
from engine_check import KIND_CONFIG  # noqa: E402


def trigger(trigger_id, source, kind="death_triggers", controller="p1"):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False}


def equipped():
    """u1 at a Battlefield with g1, a Gear whose Effect Text appends a death trigger."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"]["objects"].append("u1")
    state["objects"]["u1"]["death_triggers"] = [trigger("printed", "u1")]
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "might_bonus": 1,
                              "effect_text": {"death_triggers": [trigger("appended", "g1")]}}
    state["players"]["p1"]["zones"]["base"].append("g1")
    return state


def main() -> int:
    errors: list[str] = []
    state = equipped()
    if validate_state(state):
        errors.append(f"an object carrying an Effect Text is invalid: {validate_state(state)}")

    attach = program("eq", {"op": "attach", "effect_id": "a", "object_id": "g1", "to": "u1"})
    attached = apply_program(state, attach)
    if not attached.get("committed"):
        errors.append(f"attaching failed: {attached.get('reason_code')} {attached.get('reason')}")
        print("FAILED: effect text / copy checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    after = attached["next_state"]

    # --- the append -------------------------------------------------------------------------
    host = [t["trigger_id"] for t in object_triggers(after, "u1", "death_triggers")]
    if host != ["printed", "appended"]:
        errors.append(f"the Effect Text was not appended to the Top-Most card (477.2): {host}")
    if [t["trigger_id"] for t in object_triggers(after, "g1", "death_triggers")] != []:
        errors.append("the attached card's own death triggers changed")
    if attached["trace"][0].get("appended_effect_text") != "effect_text:g1:u1":
        errors.append(f"the attach trace does not name the append: {attached['trace'][0].get('appended_effect_text')}")
    appended = next((e for e in after["continuous_effects"] if e["kind"] == "ability_append"), None)
    if appended is None or appended["layer"] != "ability" or appended["duration"]["kind"] != "until_detached":
        errors.append(f"the append is not an Ability-layer effect that lasts until detached: {appended}")

    detached = apply_program(after, program("de", {"op": "detach", "effect_id": "d", "object_id": "g1"}))
    if not detached.get("committed"):
        errors.append(f"detaching failed: {detached.get('reason_code')} {detached.get('reason')}")
    elif [t["trigger_id"] for t in object_triggers(detached["next_state"], "u1", "death_triggers")] != ["printed"]:
        errors.append("the appended Effect Text survived the detach")
    elif [e for e in detached["next_state"].get("continuous_effects", []) if e["kind"] == "ability_append"]:
        errors.append("the append effect was left in the state after detaching")
    if [t["trigger_id"] for t in object_triggers(after, "u1", "death_triggers")] != ["printed", "appended"]:
        errors.append("negative mutation failed: the host lost the append while the card was still attached")

    # --- the schedulers read through it ------------------------------------------------------------
    killed = apply_program(after, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    scheduled = [t["trigger_id"] for t in killed.get("pending_triggers", [])]
    if scheduled != ["printed", "appended"]:
        errors.append(f"killing the host did not schedule the appended death trigger: {scheduled}")
    bare = apply_program(state, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    if [t["trigger_id"] for t in bare.get("pending_triggers", [])] != ["printed"]:
        errors.append("negative mutation failed: the same host schedules the appended trigger without the attachment")
    gone = apply_program(after, program("b", {"op": "banish", "effect_id": "b", "object_id": "u1"}))
    if not gone.get("committed") or [e for e in gone["next_state"].get("continuous_effects", []) if e["kind"] == "ability_append"]:
        errors.append("a host leaving the board did not take the append with it")

    # --- copy -------------------------------------------------------------------------------------------
    source = copy.deepcopy(state)
    source["objects"]["u2"]["play_triggers"] = [trigger("source-play", "u2", controller="p2")]
    copied = apply_program(source, program("cp", {"op": "copy_object", "effect_id": "c", "object_id": "c1", "source_object": "u2",
                                                  "request_id": "reflection-1"}))
    if not copied.get("committed"):
        errors.append(f"copying the modelled traits failed: {copied.get('reason_code')} {copied.get('reason')}")
    else:
        computed = characteristics(copied["next_state"], "c1")
        if computed["kind"] != "unit":
            errors.append(f"the copy did not take the source's type (477.1): {computed['kind']}")
        if [t["trigger_id"] for t in object_triggers(copied["next_state"], "c1", "play_triggers")] != ["source-play"]:
            errors.append("the copy did not take the source's rules text")
        if copied["next_state"]["objects"]["c1"]["base_might"] != source["objects"]["c1"]["base_might"]:
            errors.append("the copy changed a trait the rules do not copy")
        entry = next(e for e in copied["next_state"]["continuous_effects"] if e["kind"] == "copy_traits")
        if entry["layer"] != "trait" or entry["value"]["request_id"] != "reflection-1":
            errors.append(f"the copy is not a Trait-layer effect with its request: {entry}")
    unmodelled = apply_program(source, program("cp2", {"op": "copy_object", "effect_id": "c", "object_id": "c1", "source_object": "u2",
                                                       "request_id": "reflection-2", "traits": ["type", "domain"]}))
    if unmodelled.get("unsupported") is not True or "copy_unmodelled_traits" not in str(unmodelled.get("reason")):
        errors.append(f"a copy needing an unmodelled trait was not refused: {unmodelled.get('reason_code')} {unmodelled.get('reason')}")
    elif unmodelled.get("committed"):
        errors.append("the refused copy still changed the state")

    # --- validation and scope --------------------------------------------------------------------------------
    bad_field = copy.deepcopy(state)
    bad_field["objects"]["g1"]["effect_text"] = {"not_a_trigger_list": [trigger("x", "g1")]}
    if not any("effect_text" in e for e in validate_state(bad_field)):
        errors.append("an Effect Text naming a field that is not an ability list was accepted")
    bad_copy = copy.deepcopy(after)
    bad_copy["continuous_effects"].append({
        "effect_id": "bad-copy", "kind": "copy_traits", "source": {"object": "u2", "identity": None},
        "affects": {"scope": "object", "object": "c1", "identity": None}, "layer": "trait", "timestamp": 99,
        "value": {"source_object": "u2", "traits": ["cost"]}, "duration": {"kind": "permanent"},
    })
    if not any("not modelled" in e for e in validate_state(bad_copy)):
        errors.append("a copy effect naming an unmodelled trait was accepted by the validator")
    scope = KIND_CONFIG["effect"]
    if not {"effect_text_append", "copy_modelled_traits"} <= set(scope["supported"]) or "copy_unmodelled_traits" not in scope["unsupported"]:
        errors.append("the effect scope does not declare the append and the copy boundary")
    if apply_program(state, attach) != attached:
        errors.append("attaching with an Effect Text is not deterministic")

    if errors:
        print("FAILED: effect text / copy checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("effect text / copy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
