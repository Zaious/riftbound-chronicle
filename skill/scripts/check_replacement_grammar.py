#!/usr/bin/env python3
"""Regression gate for C-56 (ADR-0014 §3): the general replacement grammar and
the Core ordering law, with the rulebook's own examples as golden fixtures.

Must hold:
  - Core 370.2, the Zhonya's Hourglass pair: two Replacement Effects that each
    say "kill me instead" both apply — the first to the original death, the
    second to the death that replaced it — and then they stop. Whichever
    applied last dies. The sequence memory is what stops the first from
    applying again: the negative mutation asks the same engine for the
    applicable set without it and the first is back;
  - Core 374, the Soraka / Guardian Angel example: each Replacement Effect may
    be applied in only one sequence. Both orderings the rulebook describes are
    reproduced, and they save different Units — applying Soraka's first saves
    the Recruits at her Battlefield, applying Guardian Angel's first recalls
    her and leaves her replacement able to save only the Recruits in base;
  - Core 373.2: a replacement's own Game Actions are performed before any
    simultaneous unmodified event;
  - the ordering law is asked in three places, and each names the right
    player: the controller with several Replacement Effects orders its own
    sequences, a Replacement Effect's controller orders its qualifying events,
    and the controller of the object being acted on orders the Replacement
    Effects that apply to it. Across controllers the batch runs in Turn Order,
    and a batch that would need one without being given it fails closed;
  - Core 372: a "once each turn" Replacement Effect spends its use only when
    it is applied, and declining leaves the use for a later event that turn;
  - a Replacement Effect's instructions can say "it" and "me" (`$affected`,
    `$source`), and a binding the event cannot supply is refused.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import (  # noqa: E402
    _applicable_replacements,
    apply_program,
    apply_simultaneous_kill_batch,
    perform_lethal_cleanup,
    validate_state,
)

TURN = "turn-5"


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might,
            "might_modifiers": [], "damage": 0, "exhausted": False, **extra}


def hourglass_state():
    """Core 370.2: a Unit about to die and two "kill me instead" gear units."""
    state = base_state()
    state["turn_id"] = TURN
    for object_id in ("h1", "h2"):
        state["objects"][object_id] = unit("p1", 1)
        state["players"]["p1"]["zones"]["base"].append(object_id)
    state["replacement_effects"] = [
        {"replacement_id": f"hourglass-{n}", "controller": "p1", "source_object": f"h{n}",
         "mode": "replace_with", "event_op": "kill", "optional": False, "uses_remaining": None,
         "target_controller_relation": "friendly",
         "replacement_effects": [{"op": "kill", "effect_id": f"kill-h{n}", "object_id": f"h{n}"}]}
        for n in (1, 2)
    ]
    return state


def soraka_state():
    """Core 374: Soraka at a Battlefield with Guardian Angel attached, two
    1-Might Recruits there and two more in base, all dying together."""
    state = base_state()
    state["turn_id"] = TURN
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"]["objects"].append("u1")  # Soraka
    state["objects"]["u1"].update({"base_might": 4, "damage": 0})
    # Recruits, as cards rather than tokens, so a death leaves them in the
    # Trash where the fixture can see it instead of ceasing to exist (186.1).
    for object_id in ("r_here_1", "r_here_2"):
        state["objects"][object_id] = unit("p1", 1)
        state["battlefields"]["bf1"]["objects"].append(object_id)
    for object_id in ("r_base_1", "r_base_2"):
        state["objects"][object_id] = unit("p1", 1)
        state["players"]["p1"]["zones"]["base"].append(object_id)
    state["objects"]["ga"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False, "attached_to": "u1"}
    state["battlefields"]["bf1"]["objects"].append("ga")
    saved = [{"op": "heal_all_damage", "effect_id": "heal", "object_id": "$affected"},
             {"op": "exhaust", "effect_id": "exhaust", "object_id": "$affected"},
             {"op": "recall", "effect_id": "recall", "object_id": "$affected"}]
    state["replacement_effects"] = [
        # "If another unit you control here would die, if it has less Might
        # than me, instead heal it, exhaust it, and recall it."
        {"replacement_id": "soraka", "controller": "p1", "source_object": "u1",
         "mode": "replace_with", "event_op": "kill", "optional": False, "uses_remaining": None,
         "target_controller_relation": "friendly",
         "condition": {"kind": "and", "of": [{"kind": "object_kind", "value": "unit"},
                                             {"kind": "same_location_as", "as": "u1"},
                                             {"kind": "might_less_than", "than": "u1"}]},
         "replacement_effects": copy.deepcopy(saved)},
        # Guardian Angel appends: "If I would die, kill Guardian Angel
        # instead. Heal me, exhaust me, and recall me."
        {"replacement_id": "guardian-angel", "controller": "p1", "source_object": "u1",
         "mode": "replace_with", "event_op": "kill", "optional": False, "uses_remaining": None,
         "target_object_id": "u1",
         "replacement_effects": [{"op": "kill", "effect_id": "kill-ga", "object_id": "ga"}] + copy.deepcopy(saved)},
    ]
    return state


def location_of(state, object_id):
    for battlefield_id, battlefield in state["battlefields"].items():
        if object_id in battlefield["objects"]:
            return f"battlefield:{battlefield_id}"
    for player_id, player in state["players"].items():
        for zone, ids in player["zones"].items():
            if object_id in ids:
                return f"{player_id}.{zone}"
    return None


def main() -> int:
    errors: list[str] = []

    # --- Core 370.2: the Zhonya's Hourglass pair --------------------------------------------
    state = hourglass_state()
    if found := validate_state(state):
        errors.append(f"the Hourglass fixture is invalid: {found}")
    killed = apply_program(state, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1",
                                                 "replacement_order": ["hourglass-1", "hourglass-2"],
                                                 "replacement_decider": "p1"}))
    if not killed.get("committed"):
        print("FAILED: replacement grammar checks")
        print(f"  - the Hourglass fixture did not resolve: {killed.get('reason_code')} {killed.get('reason')}")
        return 1
    after = killed["next_state"]
    survivors = {object_id: location_of(after, object_id) for object_id in ("u1", "h1", "h2")}
    if survivors["u1"] != "p1.base" or survivors["h1"] != "p1.base":
        errors.append(f"the Unit or the first Hourglass did not survive: {survivors}")
    if survivors["h2"] != "p1.trash":
        errors.append(f"Core 370.2: the Hourglass that applied last did not die: {survivors}")
    # the memory is what stopped the first from applying again
    kill_h1 = {"op": "kill", "object_id": "h1"}
    intermediate = copy.deepcopy(state)
    with_memory = [item["replacement_id"] for item in _applicable_replacements(intermediate, kill_h1, frozenset({"hourglass-1"}))]
    without_memory = [item["replacement_id"] for item in _applicable_replacements(intermediate, kill_h1, frozenset())]
    if with_memory != ["hourglass-2"]:
        errors.append(f"the sequence memory did not exclude the applied Replacement Effect: {with_memory}")
    if sorted(without_memory) != ["hourglass-1", "hourglass-2"]:
        errors.append(f"negative mutation failed: without the memory the applied one is not back, so it is not "
                      f"the memory that excluded it: {without_memory}")

    # --- Core 374: the Soraka / Guardian Angel example --------------------------------------
    soraka = soraka_state()
    if found := validate_state(soraka):
        errors.append(f"the Soraka fixture is invalid: {found}")
    dying = ["u1", "r_here_1", "r_here_2", "r_base_1", "r_base_2"]
    # The qualifying set is read when each sequence starts, so the two
    # orderings ask for the order of different events — which is the example's
    # point: after Guardian Angel recalls her, "here" is the base.
    soraka_first = apply_simultaneous_kill_batch(
        soraka, dying, turn_order=["p1", "p2"],
        replacement_sequence_order={"p1": ["soraka", "guardian-angel"]},
        replacement_event_order={"soraka": ["r_here_1", "r_here_2"]})
    angel_first = apply_simultaneous_kill_batch(
        soraka, dying, turn_order=["p1", "p2"],
        replacement_sequence_order={"p1": ["guardian-angel", "soraka"]},
        replacement_event_order={"soraka": ["r_base_1", "r_base_2"]})
    for label, result in (("Soraka first", soraka_first), ("Guardian Angel first", angel_first)):
        if not result.get("committed"):
            errors.append(f"the Soraka batch ({label}) did not resolve: {result.get('reason_code')} {result.get('reason')}")
    if soraka_first.get("committed") and angel_first.get("committed"):
        saved_first = sorted(object_id for object_id in dying if location_of(soraka_first["next_state"], object_id) != "p1.trash")
        saved_second = sorted(object_id for object_id in dying if location_of(angel_first["next_state"], object_id) != "p1.trash")
        if saved_first != ["r_here_1", "r_here_2", "u1"]:
            errors.append(f"applying Soraka's Replacement Effect first did not save her Battlefield's Recruits and her: {saved_first}")
        if saved_second != ["r_base_1", "r_base_2", "u1"]:
            errors.append(f"applying Guardian Angel's first did not leave Soraka able to save only the Recruits in base: {saved_second}")
        if saved_first == saved_second:
            errors.append("the two orderings the rulebook distinguishes gave the same result")
        if location_of(soraka_first["next_state"], "ga") != "p1.trash":
            errors.append("Guardian Angel did not die in Soraka's place")
        # Core 374 in one sentence: each Replacement Effect appears in exactly
        # one sequence, however many events that sequence covered.
        for label, result in (("Soraka first", soraka_first), ("Guardian Angel first", angel_first)):
            applied = [rid for entry in result["trace"] for rid in entry.get("applied_replacements", [])]
            if sorted(set(applied)) != ["guardian-angel", "soraka"]:
                errors.append(f"({label}) not both Replacement Effects were applied: {applied}")
            spent_twice = [rid for rid in set(applied) if sum(
                1 for entry in result["trace"] if rid in (entry.get("applied_replacements") or []) and entry.get("object_id") == "u1") > 1]
            if spent_twice:
                errors.append(f"({label}) a Replacement Effect was applied in two sequences: {spent_twice}")

    # --- Core 373.2: replacement actions before the unmodified deaths -------------------------
    phases = [entry.get("phase") for entry in soraka_first.get("trace", [])]
    if "replacement_sequence" in phases and "unmodified_simultaneous_events" in phases:
        if phases.index("unmodified_simultaneous_events") < len(phases) - phases[::-1].index("replacement_sequence") - 1:
            errors.append(f"Core 373.2: an unmodified death was performed before a replacement's own actions: {phases}")
    else:
        errors.append(f"the Soraka batch did not produce both phases: {phases}")

    # --- the three ordering questions, each to the right player -------------------------------
    no_decisions = apply_simultaneous_kill_batch(soraka, dying, turn_order=["p1", "p2"])
    if no_decisions.get("committed") or no_decisions.get("decision_controller") != "p1" or \
            sorted(no_decisions.get("replacement_ids") or []) != ["guardian-angel", "soraka"]:
        errors.append(f"the controller with two Replacement Effects was not asked to order its sequences: {no_decisions.get('reason')}")
    no_event_order = apply_simultaneous_kill_batch(soraka, dying, turn_order=["p1", "p2"],
                                                   replacement_sequence_order={"p1": ["soraka", "guardian-angel"]})
    if no_event_order.get("committed") or no_event_order.get("replacement_ids") != ["soraka"]:
        errors.append(f"the Replacement Effect's controller was not asked to order its qualifying events: {no_event_order.get('reason')}")

    # two controllers, no Turn Order: the engine refuses rather than guessing
    two_sided = base_state()
    two_sided["objects"]["u1"]["damage"] = 9
    two_sided["objects"]["u2"]["damage"] = 9
    two_sided["objects"]["g1"] = unit("p1", 1)
    two_sided["objects"]["g2"] = unit("p2", 1)
    two_sided["players"]["p1"]["zones"]["base"].append("g1")
    two_sided["players"]["p2"]["zones"]["base"].append("g2")
    two_sided["replacement_effects"] = [
        {"replacement_id": "p1-guard", "controller": "p1", "source_object": "g1", "mode": "prevent_event",
         "event_op": "kill", "optional": False, "uses_remaining": None, "target_object_id": "u1"},
        {"replacement_id": "p2-guard", "controller": "p2", "source_object": "g2", "mode": "prevent_event",
         "event_op": "kill", "optional": False, "uses_remaining": None, "target_object_id": "u2"},
    ]
    blind = apply_simultaneous_kill_batch(two_sided, ["u1", "u2"])
    if blind.get("committed") or blind.get("reason_code") != "turn_order_unknown":
        errors.append(f"a two-controller batch without a Turn Order did not fail closed: {blind.get('reason_code')}")
    p1_first = apply_simultaneous_kill_batch(two_sided, ["u1", "u2"], turn_order=["p1", "p2"])
    p2_first = apply_simultaneous_kill_batch(two_sided, ["u1", "u2"], turn_order=["p2", "p1"])
    order_1 = [entry.get("object_id") for entry in p1_first.get("trace", []) if entry.get("phase") == "replacement_sequence"]
    order_2 = [entry.get("object_id") for entry in p2_first.get("trace", []) if entry.get("phase") == "replacement_sequence"]
    if order_1 != ["u1", "u2"] or order_2 != ["u2", "u1"]:
        errors.append(f"the sequences of different controllers did not execute in Turn Order: {order_1} / {order_2}")
    if not p1_first.get("committed") or sorted(p1_first.get("prevented_objects") or []) != ["u1", "u2"]:
        errors.append(f"both guards did not apply: {p1_first.get('prevented_objects')}")

    # --- Core 372: "once each turn" spends its use only when applied --------------------------
    limited = copy.deepcopy(two_sided)
    limited["turn_id"] = TURN
    limited["replacement_effects"] = [{
        "replacement_id": "once", "controller": "p1", "source_object": "g1", "mode": "prevent_event",
        "event_op": "kill", "optional": True, "uses_remaining": None, "uses_per_turn": 1,
        "target_controller_relation": "friendly",
    }]
    limited["objects"]["u3"] = unit("p1", 1, damage=9)
    limited["players"]["p1"]["zones"]["base"].append("u3")
    if found := validate_state(limited):
        errors.append(f"a once-each-turn Replacement Effect was rejected: {found}")
    declined = apply_simultaneous_kill_batch(
        limited, ["u1", "u3"], replacement_event_order={"once": ["u1", "u3"]},
        replacement_choices={"once": {"u1": False, "u3": True}}, turn_order=["p1", "p2"])
    if not declined.get("committed"):
        errors.append(f"the once-each-turn batch did not resolve: {declined.get('reason')}")
    else:
        spent = next(item for item in declined["next_state"]["replacement_effects"] if item["replacement_id"] == "once")
        if spent.get("applied_this_turn", {}).get(TURN) != 1:
            errors.append(f"declining and then applying did not spend exactly one use: {spent.get('applied_this_turn')}")
        if declined.get("prevented_objects") != ["u3"]:
            errors.append(f"the declined event was not left to die, or the applied one was not saved: {declined.get('prevented_objects')}")
        exhausted = copy.deepcopy(declined["next_state"])
        exhausted["objects"]["u4"] = unit("p1", 1, damage=9)
        exhausted["players"]["p1"]["zones"]["base"].append("u4")
        again = apply_simultaneous_kill_batch(exhausted, ["u4"], replacement_choices={"once": {"u4": True}}, turn_order=["p1", "p2"])
        if again.get("prevented_objects"):
            errors.append("a once-each-turn Replacement Effect applied twice in one turn (Core 372)")
        next_turn = copy.deepcopy(exhausted)
        next_turn["turn_id"] = "turn-6"
        renewed = apply_simultaneous_kill_batch(next_turn, ["u4"], replacement_choices={"once": {"u4": True}}, turn_order=["p1", "p2"])
        if not renewed.get("committed") or renewed.get("prevented_objects") != ["u4"]:
            errors.append(f"the per-turn allowance did not come back on the next turn: {renewed.get('reason')} {renewed.get('prevented_objects')}")

    # --- "it" and "me" ------------------------------------------------------------------------
    unbound = copy.deepcopy(hourglass_state())
    unbound["replacement_effects"] = [{
        "replacement_id": "self-kill", "controller": "p1", "source_object": "h1", "mode": "replace_with",
        "event_op": "draw", "optional": False, "uses_remaining": None,
        "replacement_effects": [{"op": "kill", "effect_id": "k", "object_id": "$affected"}],
    }]
    refused = apply_program(unbound, program("d", {"op": "draw", "effect_id": "d", "player": "p1", "count": 1}))
    if refused.get("committed") or "affected" not in str(refused.get("reason", "")):
        errors.append(f"a replacement naming $affected on an event that binds none was not refused: {refused.get('reason')}")
    bound = apply_program(hourglass_state(), program("k", {"op": "kill", "effect_id": "k", "object_id": "u1",
                                                            "replacement_order": ["hourglass-1", "hourglass-2"],
                                                            "replacement_decider": "p1"}))
    if bound != killed:
        errors.append("the replacement grammar is not deterministic")

    if errors:
        print("FAILED: replacement grammar checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("replacement grammar checks passed: Core 370.2, 372, 373.1, 373.2 and 374 with the rulebook's own examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
