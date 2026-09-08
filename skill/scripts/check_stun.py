#!/usr/bin/env python3
"""Regression gate for stun.v1 (DP-94; Core 423).

Rune Prison: "Stun a unit."

The `stunned` field and its one reader existed before this op did, which is
what makes the gate worth writing: the danger is not that Stun does nothing,
it is that it does slightly too much and never stops.

Codex's contract, and what each line here is trying to break:

  - **it never comes off.** A bare boolean with nothing to clear it leaves a
    Unit Stunned for the rest of the game. The status is owned by a
    `turn_effects` entry, the Expiration Step's 3d clears both together, and
    the state validator rejects a Stunned object with no owner - so the shape
    that never expires cannot even be written down.
  - **it becomes a Might change.** Core 423.1.b zeroes what a Stunned Unit
    *contributes to Combat Damage*. It does not set the Unit's Might to 0.
    A Unit with 3 Might that is Stunned still has 3 Might, still dies to 3
    damage and not to 1, and still reads as 3 to every other effect. This
    gate asserts all three, because an implementation that zeroed Might would
    pass a naive combat test and quietly change lethal damage.
  - **it stacks.** Stunning an already Stunned Unit is a legal choice and a
    no-op: no refreshed duration, no second entry, and no event - so a
    "when you stun" trigger cannot be made to fire twice by stunning twice.

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
from combat import available_combat_damage  # noqa: E402
from effect_ir import apply_program, effective_might, validate_state  # noqa: E402


def board_state():
    """u1 (p1) and u2 (p2) both at bf1, so a Stun has somewhere to land and
    somewhere it must not."""
    state = base_state()
    state["turn_id"] = "turn-3"
    state["players"]["p1"]["zones"]["base"] = []
    state["players"]["p2"]["zones"]["base"] = []
    state["battlefields"]["bf1"]["objects"] = ["u1", "u2"]
    state["objects"]["u1"]["damage"] = 0
    return state


def stun_program(object_id="u2"):
    prog = program("rune-prison", {"op": "stun", "effect_id": "st", "object_id": object_id})
    prog["source_object"] = "u1"
    return prog


def main() -> int:
    errors: list[str] = []
    state = board_state()

    # --- it applies, and it names what will end it --------------------------------------------------
    result = apply_program(state, stun_program())
    if not result.get("committed"):
        errors.append(f"a Stun on a board Unit did not commit: {result.get('reason') or result.get('errors')}")
        print("FAILED: stun checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    stunned_state = result["next_state"]
    if stunned_state["objects"]["u2"].get("stunned") is not True:
        errors.append("the chosen Unit is not Stunned")
    if stunned_state["objects"]["u1"].get("stunned"):
        errors.append("a Unit nobody chose was Stunned")
    owners = [e for e in stunned_state.get("turn_effects", []) if e.get("kind") == "stunned_unit"]
    if len(owners) != 1 or owners[0].get("object_id") != "u2" or owners[0].get("turn_id") != "turn-3":
        errors.append(f"the Stun has no turn-scoped owner: {owners}")
    if validate_state(stunned_state):
        errors.append(f"the Stunned state is not valid: {validate_state(stunned_state)}")
    events = [e for e in result.get("events", []) if e.get("kind") == "stunned"]
    if len(events) != 1:
        errors.append(f"a Stun that happened did not emit exactly one event: {len(events)}")

    # --- a status with nothing to expire it cannot be written down ---------------------------------
    orphan = copy.deepcopy(stunned_state)
    orphan.pop("turn_effects", None)
    if not any("no turn_effects entry to expire it" in problem for problem in validate_state(orphan)):
        errors.append("a Stunned Unit with nothing to clear it was accepted; that Stun never ends")
    lying = copy.deepcopy(stunned_state)
    lying["objects"]["u2"]["stunned"] = False
    if not validate_state(lying):
        errors.append("an owner entry naming a Unit that is not Stunned was accepted")

    # --- 423.1.b: Combat contribution only. Might, lethal threshold and every -----------------------
    #     other reader are untouched.
    if effective_might(stunned_state, "u2") != effective_might(state, "u2"):
        errors.append("Stun changed the Unit's Might; 423.1.b is about Combat Damage, not Might")
    total, parts = available_combat_damage(stunned_state, ["u2"])
    if total != 0 or parts[0]["contributed"] != 0:
        errors.append(f"a Stunned Unit still contributed Combat Damage: {parts}")
    if parts[0]["might"] != effective_might(state, "u2"):
        errors.append(f"the assignment read a reduced Might rather than a reduced contribution: {parts}")
    # lethal still needs its full Might: damage one short does not kill it
    might = effective_might(stunned_state, "u2")
    survives = apply_program(stunned_state, program("chip", {"op": "deal_damage", "effect_id": "d",
                                                             "object_id": "u2", "amount": might - 1}))
    if "u2" not in survives["next_state"]["objects"]:
        errors.append(f"a Stunned Unit died to {might - 1} damage; its lethal threshold was lowered to 0")
    kills = apply_program(stunned_state, program("lethal", {"op": "deal_damage", "effect_id": "d",
                                                            "object_id": "u2", "amount": might}))
    if "u2" in kills["next_state"]["objects"] and kills["next_state"]["objects"]["u2"].get("damage", 0) < might:
        errors.append("a Stunned Unit did not take its full damage")

    # --- 423.2: stunning again is legal and does nothing --------------------------------------------
    again = apply_program(stunned_state, stun_program())
    step = again["trace"][0]
    if not again.get("committed"):
        errors.append(f"choosing an already Stunned Unit was illegal: {again.get('reason')}")
    if step.get("outcome") != "no_op" or not step.get("already_stunned"):
        errors.append(f"stunning an already Stunned Unit was not a no-op: {step}")
    after = again["next_state"]
    if [e for e in after.get("turn_effects", []) if e.get("kind") == "stunned_unit"] != owners:
        errors.append("a second Stun added or refreshed an owner entry; the duration was extended")
    if [e for e in again.get("events", []) if e.get("kind") == "stunned"]:
        errors.append("a no-op Stun emitted an event; a 'when you stun' trigger would fire twice")

    # --- 317.2.d: and 3d is where it ends ------------------------------------------------------------
    from check_rules_core import fixture  # noqa: E402
    from resolution_bridge import run_expiration_step  # noqa: E402
    timing = fixture()
    timing["phase"] = "ending"
    timing["ending_step"] = {"status": "triggers_scheduled", "turn_id": "turn-3"}
    timing["priority"] = None
    expired = run_expiration_step(timing, stunned_state)
    if not expired.get("committed"):
        errors.append(f"the Expiration Step refused a state carrying a Stun: {expired.get('reason')}")
    else:
        if expired["next_effect_state"]["objects"]["u2"].get("stunned"):
            errors.append("the Stun survived the Expiration Step")
        if expired["trace"]["expire_this_turn"].get("unstunned") != ["u2"]:
            errors.append(f"the step did not record what it unstunned: {expired['trace']['expire_this_turn']}")
        if validate_state(expired["next_effect_state"]):
            errors.append(f"the state after expiry is invalid: {validate_state(expired['next_effect_state'])}")
    # before 3d it is still there
    if stunned_state["objects"]["u2"].get("stunned") is not True:
        errors.append("the Stun was cleared before the Expiration Step")

    # --- what cannot be Stunned ----------------------------------------------------------------------
    for object_id, why in (("c1", "a card in a deck, not a Unit on the board"),
                           ("r1", "a Rune, not a Unit"),
                           ("u3", "an object this state does not have")):
        refused = apply_program(state, stun_program(object_id))
        if refused.get("committed"):
            errors.append(f"Stun applied to {why}: {object_id!r}")
    # a Unit that left the board is a different object (359.3.e.4)
    left = copy.deepcopy(state)
    left["battlefields"]["bf1"]["objects"] = ["u1"]
    left["players"]["p2"]["zones"]["trash"].append("u2")
    left["objects"]["u2"]["identity"] = "u2@1"
    gone = apply_program(left, stun_program())
    if gone.get("committed"):
        errors.append("a Unit that had left the board was Stunned in its new zone")

    # --- the clause, and the five shapes that stay out of this wave -----------------------------------
    grammar = cg.load_grammar()
    compiled = cg.compile_clause("Stun a unit.", grammar)
    if compiled.get("unsupported") or compiled["program_effects"][0]["op"] != "stun":
        errors.append(f"Rune Prison's clause did not compile: {compiled}")
    for text, family in (
        ("When you stun one or more enemy units, buff a friendly unit.", "stun_trigger"),
        ("While there's a stunned enemy unit here, I have +2 :rb_might:.", "stun_state_condition"),
        ("Stunned enemy units here have -8 :rb_might:, to a minimum of 1 :rb_might:.", "stun_aura"),
        ("If a spell or ability that chooses me would stun me, give me -2 :rb_might: instead.", "stun_replacement"),
        ("If an opponent controls a stunned unit, I cost :rb_energy_2: less and enter ready.", "stun_cost_condition"),
    ):
        if not cg.compile_clause(text, grammar).get("unsupported"):
            errors.append(f"{family} was compiled; only direct Stun is in this wave: {text!r}")

    if errors:
        print("FAILED: stun checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("stun checks passed: the status is owned by a turn effect and cleared at Expiration 3d, a "
          "Stunned Unit contributes no Combat Damage while keeping its Might and its lethal threshold, "
          "stunning again is a legal no-op with no event, and the five other Stun shapes stay unparsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
