#!/usr/bin/env python3
"""Regression gate: "When you choose or ready me, ..." (set 2 package A2: Irelia - Fervent). One watch on two event kinds,
the card itself as the object and its controller as the actor (Core 383.4.b, 416): chosen by the controller's spell or
ability, or readied by the controller - each event its own trigger.

  R1  p1's spell chooses the watcher as it is played: its trigger is on the Chain, about the watcher
  R2  p1's spell readies the exhausted watcher as it resolves (no choice): its trigger is scheduled, kind readied
  R3  p1's spell chooses another unit (u1): no trigger from the watcher
  R4  p1's spell readies another exhausted unit (u1): no trigger
  R5  p2's spell readies the watcher: no trigger (scope actor)
  R6  already ready  p1's spell readies the watcher while it is Ready: its ready state does not change, no trigger
                     (Core 416.1.b, 416.1.c)
  R7  awaken         p1's Awaken step readies the exhausted watcher (and u1): one trigger, kind readied, about the
                     watcher; the watcher already Ready at the Awaken: none (Core 315.1.b, 416.3.a, 416.1.b)
  R8  enemy chooses  p2's spell chooses the watcher: no trigger - "you choose", and the choice is p2's (Core 383.4.b)
  R9  several        one spell of p1's chooses the watcher, u1 and u2: one trigger, about the watcher (Core 355.14.d,
                     383.4.b); the watcher chosen in two slots of one spell is one object targeted: one trigger
  R10 new choices    p2's "Deal 1 to a unit" (chose p1's a1), taken by p1's Mystic Reversal, its target remade by p1 to
                     the watcher: the item targets it again, so the watcher's Targeting Effect triggers (Core 754,
                     383.4.b.2); remade to e1: none
  G   the printed form lowers to the two-kind watch; near misses do not
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_spell_control as SC  # noqa: E402
import check_trigger_source_identity as TS  # noqa: E402
import clause_grammar as CG  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import program, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from check_turn_cycle import handled, setup_timing  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402
from turn_cycle import begin_turn, run_awaken_step  # noqa: E402

TEXT = "When you choose or ready me, draw 1."


def watch() -> dict:
    got = CG.compile_clause(TEXT, CG.load_grammar())
    return (((got.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or [None])[0]


def board(actor="p1") -> dict:
    """TS.board plus p1's watcher irelia (exhausted, in p1's Base); u1 exhausted; c1, a spell, in `actor`'s hand."""
    state = TS.board()
    state["objects"]["irelia"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                                  "damage": 0, "exhausted": True,
                                  "event_triggers": [{**copy.deepcopy(watch()), "controller": "p1",
                                                      "source_object": "irelia", "effect_program_id": "irelia-1"}]}
    state["players"]["p1"]["zones"]["base"].append("irelia")
    state["objects"]["u1"]["exhausted"] = True
    for p in ("p1", "p2"):
        if "c1" in state["players"][p]["zones"]["main_deck"]:
            state["players"][p]["zones"]["main_deck"].remove("c1")
    state["objects"]["c1"].update({"owner": actor, "controller": actor})
    state["players"][actor]["zones"]["hand"].append("c1")
    state["players"][actor]["resources"] = {"energy": 1, "power": {}}
    return state


def cast(state, effects, actor="p1"):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": actor, "card": "c1",
            "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "spell-1-effects",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    timing = fixture() if actor == "p1" else {**fixture(priority=actor), "turn_player": actor}
    return play_card(timing, state, decl, effect_program={**program("spell-1-effects", *effects), "controller": actor})


def resolve(played, effects, actor="p1"):
    timing = RC.finalize_oldest_pending(played["next_timing_state"]).get("next_state") or played["next_timing_state"]
    timing["chain"]["consecutive_passes"] = list(timing.get("turn_order") or ["p1", "p2"])
    return resolve_with_program(timing, "spell-1", played["next_effect_state"],
                                {**program("spell-1-effects", *effects), "controller": actor})


def woke(result, kind):
    items = (result.get("next_timing_state") or {}).get("chain", {}).get("items", [])
    return [i for i in items if i.get("source_object") == "irelia" and (i.get("trigger_event") or {}).get("kind") == kind]


def watcher(state, where="bf1", exhausted=False) -> None:
    """Puts p1's watcher irelia on `state` at `where` (a Battlefield)."""
    state["objects"]["irelia"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                                  "damage": 0, "exhausted": exhausted,
                                  "event_triggers": [{**copy.deepcopy(watch()), "controller": "p1",
                                                      "source_object": "irelia", "effect_program_id": "irelia-1"}]}
    state["battlefields"][where]["objects"].append("irelia")
    settle_contested(state)


def awaken(irelia_exhausted: bool) -> dict:
    """p1's turn begins and its Awaken step runs, the watcher exhausted (or Ready) in p1's Base, u1 exhausted."""
    state = board()
    state["mode"] = {"victory_score": 8, "id": "duel"}
    state["objects"]["irelia"]["exhausted"] = irelia_exhausted
    began = begin_turn(setup_timing(), state)
    if not began.get("committed"):
        return began
    return run_awaken_step(handled(began["next_timing_state"]), began["next_effect_state"])


# R10: a spell of p2's choosing any unit, so that p1's new choice may be p1's own watcher
ANY_UNIT = {**copy.deepcopy(SC.SHOT), "effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": 1,
                                                   "target": {"decision_ref": "t", "chosen_zone_class": "board",
                                                              "kind": "unit"}}]}


def main() -> int:
    errors: list[str] = []
    w = watch()
    if (w or {}).get("watch") != {"kinds": ["targeted", "readied"], "scope": "actor", "filter": {"is_source": True},
                                  "grouping": "each"}:
        errors.append(f"G: lowered to {w}")
    for near in ("When you choose me, draw 1.", "When an opponent chooses or readies me, draw 1."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == "when_you_choose_or_ready_me":
            errors.append(f"G: the near miss {near!r} lowered to the row")
    dmg = lambda t: [{"op": "deal_damage", "amount": 1, "effect_id": "dmg", "object_id": t,
                      "target": {"object_id": t, "chosen_zone_class": "board", "kind": "unit"}}]
    chose = cast(board(), dmg("irelia"))
    if not chose.get("committed") or len(woke(chose, "targeted")) != 1:
        errors.append(f"R1: {chose.get('reason_code')} {woke(chose, 'targeted')}")
    other = cast(board(), dmg("u1"))
    if not other.get("committed") or woke(other, "targeted"):
        errors.append(f"R3: {other.get('reason_code')} {woke(other, 'targeted')}")
    for label, who, actor, want in (("R2", "irelia", "p1", 1), ("R4", "u1", "p1", 0), ("R5", "irelia", "p2", 0)):
        effects = [{"op": "ready", "effect_id": "rd", "object_id": who}]
        played = cast(board(actor), effects, actor=actor)
        if not played.get("committed"):
            errors.append(f"{label}: the play was refused: {played.get('reason_code')} {played.get('reason')}")
            continue
        done = resolve(played, effects, actor)
        if not done.get("committed"):
            errors.append(f"{label}: resolution refused: {done.get('reason')}")
            continue
        if done["next_effect_state"]["objects"][who].get("exhausted"):
            errors.append(f"{label}: {who} was not readied")
        if len(woke(done, "readied")) != want:
            errors.append(f"{label}: {len(woke(done, 'readied'))} readied trigger(s), expected {want}")
    # R6: readied while already Ready - no Ready event, so no trigger (416.1.b, 416.1.c)
    effects = [{"op": "ready", "effect_id": "rd", "object_id": "irelia"}]
    ready_state = board()
    ready_state["objects"]["irelia"]["exhausted"] = False
    played = cast(ready_state, effects)
    done = resolve(played, effects) if played.get("committed") else played
    if not done.get("committed") or woke(done, "readied"):
        errors.append(f"R6 already ready: {done.get('reason_code')} {done.get('reason')} {woke(done, 'readied')}")
    # R7: the Awaken step's Ready is an actual Ready by the Turn Player
    for exhausted, want in ((True, 1), (False, 0)):
        got = awaken(exhausted)
        fired = [i for i in woke(got, "readied") if (i.get("trigger_event") or {}).get("object") == "irelia"]
        if not got.get("committed") or len(woke(got, "readied")) != want or len(fired) != want:
            errors.append(f"R7 awaken (irelia exhausted={exhausted}): {got.get('reason_code')} {got.get('reason')} "
                          f"{len(woke(got, 'readied'))} readied trigger(s), expected {want}")
    # R8: the enemy's spell chooses the watcher - not "you choose"
    enemy = cast(board("p2"), dmg("irelia"), actor="p2")
    if not enemy.get("committed") or woke(enemy, "targeted"):
        errors.append(f"R8 enemy chooses: {enemy.get('reason_code')} {enemy.get('reason')} {woke(enemy, 'targeted')}")
    # R9: one spell choosing several objects, the watcher among them - one trigger for the watcher
    several = [{"op": "deal_damage", "amount": 1, "effect_id": "dmg", "targets": {"selectors": [
        {"object_id": o, "chosen_zone_class": "board", "kind": "unit"} for o in ("irelia", "u1", "u2")], "min": 0, "max": 3}}]
    many = cast(board(), several)
    if not many.get("committed") or len(woke(many, "targeted")) != 1 \
            or (woke(many, "targeted")[0].get("trigger_event") or {}).get("object") != "irelia":
        errors.append(f"R9 several: {many.get('reason_code')} {many.get('reason')} {woke(many, 'targeted')}")
    two_slots = dmg("irelia") + [{"op": "exhaust", "effect_id": "ex", "object_id": "irelia",
                                  "target": {"object_id": "irelia", "chosen_zone_class": "board", "kind": "unit"}}]
    twice = cast(board(), two_slots)
    if not twice.get("committed") or len(woke(twice, "targeted")) != 1:
        errors.append(f"R9 two slots: {twice.get('reason_code')} {twice.get('reason')} {len(woke(twice, 'targeted'))} "
                      f"targeted trigger(s), expected 1")
    # R10: new choices for a Chain item (Core 750-755) - targeting the watcher again triggers it (754)
    taken = SC.board()
    watcher(taken)
    for target, want in ((["irelia"], 1), (["e1"], 0)):
        got = SC.reverse(taken, may=True, remake={"t": target}, spell=ANY_UNIT)
        items = [i for i in (got.get("next_timing_state") or {}).get("chain", {}).get("items", [])
                 if i.get("source_object") == "irelia"]
        remade = ((got.get("next_effect_state") or {}).get("chain_items", {}).get("spell-shot") or {}).get("played_targets")
        if not got.get("committed") or [p.get("value") for p in remade or []] != [target]:
            errors.append(f"R10 new choices ({target}): the Reversal did not remake the target: "
                          f"{got.get('reason_code')} {got.get('reason')} {remade}")
        elif len(items) != want:
            errors.append(f"R10 new choices ({target}): {len(items)} trigger(s) from the watcher, expected {want} "
                          f"(Core 754: the remade target is targeted, its Targeting Effects trigger) - "
                          f"effect_ir make_new_choices records the new played_targets but emits no targeted event")
    if errors:
        print("choose-or-ready checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("choose-or-ready checks passed: chosen by its controller's spell or readied by its controller, the card triggers; "
          "another unit, or the opponent's ready, does not; the Awaken's Ready triggers it, a Ready on a Ready card and the "
          "enemy's choice do not; one spell choosing it among several is one trigger; a remade target triggers it; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
