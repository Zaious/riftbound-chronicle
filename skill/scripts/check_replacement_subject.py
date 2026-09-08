#!/usr/bin/env python3
"""Regression gate for the replacement subject (Round H, Core 370.1.b).

Zhonya's Hourglass, current text:

    "If a friendly unit would die, kill this instead.
     Heal that unit, exhaust it, and recall it."

Two sentences, one Replacement Effect. The second is not something the Gear
does afterwards - it is the rest of what happens *instead of* the death, and
"that unit" is the unit that would have died.

Codex's contract:

    the subject is captured from the object that would have died, with its
    immutable identity, when the replacement applies; Heal / exhaust / recall
    read only that subject and may not be rebound to the Gear or to a fresh
    target.

Which gives this gate three things to disprove:

  - **the subject becomes the Gear.** "Kill this instead" names the source, so
    an implementation that reuses that binding for the following instructions
    would heal and recall the Gear. The unit would stay dead and the Gear
    would come home - the exact opposite of the card.
  - **the subject is re-chosen.** If "that unit" compiled to a fresh selector,
    a board with two damaged friendly units would let the healing land on the
    wrong one, and the card would still look like it worked.
  - **the identity is not pinned.** An id can be reused inside one resolution.
    An instruction that names only the id would then act on whatever holds it
    now; the capture has to carry the identity the object had when the
    replacement applied (359.3.e.4).

Every fixture here is synthetic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import (  # noqa: E402
    _bind_replacement_effects,
    apply_program,
    object_identity,
    validate_program,
    validate_state,
)

CLAUSES = [{"text": "If a friendly unit would die, kill this instead."},
           {"text": "Heal that unit, exhaust it, and recall it."}]


def bind(value, bindings):
    if isinstance(value, dict):
        return {k: bind(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    return bindings.get(value, value) if isinstance(value, str) else value


def hourglass_state():
    """g1 is the Gear; u1 and u3 are two damaged friendly Units at bf1, so a
    re-chosen subject would have somewhere wrong to land."""
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False}
    state["objects"]["u3"] = copy.deepcopy(state["objects"]["u1"])
    state["objects"]["u1"]["damage"] = 2
    state["objects"]["u3"]["damage"] = 2
    state["players"]["p1"]["zones"]["base"] = ["g1"]
    state["battlefields"]["bf1"]["objects"] = ["u1", "u3"]
    state["battlefields"]["bf1"]["controller"] = "p1"
    return state


def install(state, card):
    entries = copy.deepcopy(card["passive"]["state_lists"]["replacement_effects"])
    bindings = {"$clause_id": "hourglass", "$controller": "p1", "$source_object": "g1"}
    state["replacement_effects"] = bind(entries, bindings)
    return state


def kill_program(object_id="u1"):
    prog = program("kill-u1", {"op": "kill", "effect_id": "k", "object_id": object_id})
    prog["source_object"] = "u2"
    return prog


def main() -> int:
    errors: list[str] = []
    grammar = cg.load_grammar()

    # --- the two clauses compile into one replacement ---------------------------------------------
    card = cg.compile_card(CLAUSES, grammar)
    if any(c.get("unsupported") for c in card["clauses"]):
        print("FAILED: replacement subject checks")
        print(f"  - Zhonya's clauses did not compile: {card['unsupported_clauses']}")
        return 1
    if card["clauses"][1].get("absorbed_into") != "$clause_id":
        errors.append(f"the second clause was not absorbed into the replacement: {card['clauses'][1]}")
    if card["program_effects"]:
        errors.append(f"the card kept top-level instructions: {card['program_effects']}; "
                      "the heal would happen whether or not anything was replaced")
    entries = card["passive"]["state_lists"]["replacement_effects"]
    steps = entries[0]["replacement_effects"]
    if [s["op"] for s in steps] != ["kill", "heal_all_damage", "exhaust", "recall"]:
        errors.append(f"the replacement does not do what the card says, in order: {[s['op'] for s in steps]}")
    if steps[0].get("object_id") != "$source":
        errors.append(f"'kill this instead' did not name the source: {steps[0]}")
    for step in steps[1:]:
        if step.get("object_id") != "$affected":
            errors.append(f"a following instruction was rebound away from the subject: {step}")
        if step.get("subject_identity") != "$affected_identity":
            errors.append(f"a following instruction did not pin the subject's identity: {step}")
        if "target" in step or "targets" in step:
            errors.append(f"the subject was compiled as a chosen target: {step}; nobody chose it (355.10.a)")

    # --- and it runs: the unit that would have died is healed, exhausted and recalled --------------
    state = install(hourglass_state(), card)
    if validate_state(state):
        errors.append(f"the compiled replacement is not a valid state: {validate_state(state)}")
    result = apply_program(state, kill_program("u1"))
    if not result.get("committed"):
        errors.append(f"the replacement did not resolve: {result.get('reason') or result.get('errors')}")
    else:
        after = result["next_state"]
        if "g1" in after["players"]["p1"]["zones"]["base"]:
            errors.append("the Gear was not killed instead")
        if after["objects"]["u1"]["damage"] != 0:
            errors.append(f"the unit that would have died was not healed: damage {after['objects']['u1']['damage']}")
        if after["objects"]["u1"]["exhausted"] is not True:
            errors.append("the subject was not exhausted")
        if "u1" not in after["players"]["p1"]["zones"]["base"]:
            errors.append(f"the subject was not recalled to its controller's Base: "
                          f"{after['players']['p1']['zones']['base']}")
        # the *other* damaged friendly unit is untouched: the subject was not re-chosen
        if after["objects"]["u3"]["damage"] != 2 or after["objects"]["u3"]["exhausted"] is not False:
            errors.append("the second damaged friendly unit was affected; the subject was re-chosen "
                          "rather than captured")

    # --- the subject is the dying unit, never the source ------------------------------------------
    bound = _bind_replacement_effects(copy.deepcopy(steps), "u1", "g1", "u1@0")
    if bound[0]["object_id"] != "g1":
        errors.append(f"'this' stopped meaning the source: {bound[0]}")
    if any(step["object_id"] != "u1" for step in bound[1:]):
        errors.append(f"the subject was bound to something other than the dying unit: {bound[1:]}")

    # --- an unbindable subject is refused, not half-substituted -----------------------------------
    try:
        _bind_replacement_effects(copy.deepcopy(steps), None, "g1", None)
        errors.append("instructions naming a subject the event does not supply were bound anyway")
    except Exception as exc:  # IllegalOperation
        if "$affected" not in str(exc):
            errors.append(f"the unbindable subject was reported as something else: {exc}")

    # --- the identity is load-bearing: a different object at the same id is not the subject --------
    swapped = hourglass_state()
    swapped["objects"]["u1"]["identity"] = "u1@1"          # the object here now is a later generation
    swapped = install(swapped, card)
    pinned = [{"op": "heal_all_damage", "effect_id": "hl", "object_id": "u1", "subject_identity": "u1@0"}]
    prog = program("heal-subject", *pinned)
    if validate_program(prog):
        errors.append(f"a pinned subject failed validation: {validate_program(prog)}")
    result = apply_program(swapped, prog)
    step = result["trace"][0]
    if step["outcome"] != "ignored_subject_changed" or step.get("reason") != "subject_identity_changed":
        errors.append(f"an instruction acted on a different object holding the subject's id: {step}")
    if result["next_state"]["objects"]["u1"]["damage"] != 2:
        errors.append("the replaced-identity object was healed anyway")
    # and with the identity it actually has, the same instruction applies
    matching = program("heal-subject", {"op": "heal_all_damage", "effect_id": "hl",
                                        "object_id": "u1", "subject_identity": object_identity(swapped, "u1")})
    if apply_program(swapped, matching)["next_state"]["objects"]["u1"]["damage"] != 0:
        errors.append("a correctly pinned subject was refused; the identity check is too strict")

    if errors:
        print("FAILED: replacement subject checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("replacement subject checks passed: the two clauses form one replacement, the subject is the unit "
          "that would have died and not the Gear, the second damaged unit is untouched, and an instruction "
          "whose subject identity moved on applies nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
