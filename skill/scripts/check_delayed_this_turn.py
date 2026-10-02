#!/usr/bin/env python3
"""
Regression gate: a delayed trigger "at the end of this turn" that carries its own program (2026-09-27).

"When you conquer here, ready up to 2 runes at the end of this turn." (Targon's Peak) creates a
Delayed Trigger (Core 390.2) whose window is the turn it is created in. The creating instruction is
create_delayed_trigger with `waits_for {kind: turn, moment: end_of_turn, turn: this_turn}` and the
delayed trigger's own instructions in `effects`. The engine binds the turn and the program's content
hash as it creates the trigger; the Ending Step fires it (begin_ending_step); its choices are made as
IT is finalized, not as the ability that made it was (Core 355.5.b, whose example is this card); and
if this turn's Ending Step had already begun when the instruction ran, the delayed trigger is not
generated and the instruction is ignored (Core 359.3.e.16, whose example is this card too).

Must hold, through the engine's own procedures:
  - created: the delayed entry is bound to this turn, to its source, to the hash of the program the
    instruction carried, and to the chain item that made it (its id carries the trigger instance - GPT
    2026-10-02: two Conquers of one Targon's Peak in one turn make two delayed triggers, never one id twice);
  - the Ending Step fires it once, with that hash on the chain item; it is disarmed;
  - finalized with two of p1's exhausted runes chosen and resolved: those two are ready, p1's
    third rune and p2's rune stay exhausted; nothing was chosen when it was created;
  - zero runes chosen: nothing readies (355.13); three chosen: refused at finalization;
  - a registry that offers different instructions under the same id is refused
    (effect_program_hash_mismatch);
  - an opponent's rune chosen: it readies ("ready up to 2 runes" names no controller - GPT 2026-10-02);
  - two creations in one turn (two chain items): two delayed triggers, both fire at the end of the turn;
  - resolved during this turn's Ending Phase after the Ending Step began: not generated, nothing
    armed, the instruction ignored (359.3.e.16); resolved in the Main Phase it is generated;
  - a delayed trigger of this turn does not fire at the end of another turn;
  - invalid: a nested create_delayed_trigger, empty effects, 'turn: next_turn', an
    instruction-supplied program hash;
  - mutations caught: an engine that does not bind the hash; one that ignores 359.3.e.16.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from resolution_bridge import begin_ending_step, finalize_trigger, program_hash, resolve_with_program  # noqa: E402

RULESET = {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF}
READY_UP_TO_TWO = [{"op": "ready", "effect_id": "rd", "targets": {
    "min": 0, "max": 2, "decision_ref": "t",
    "restrictions": {"chosen_zone_class": "board", "kind": "rune"}}}]
FIRED = "peak-end@spell-1"     # the delayed_id with the creating chain item's id (GPT 2026-10-02)
CREATE = {"op": "create_delayed_trigger", "effect_id": "dt",
          "delayed": {"delayed_id": "peak-end", "controller": "p1", "source_object": "bf1",
                      "waits_for": {"kind": "turn", "moment": "end_of_turn", "turn": "this_turn"},
                      "effect_program_id": "peak-end-effects", "optional_at_finalize": False, "controller_order": 0},
          "effects": copy.deepcopy(READY_UP_TO_TWO)}
NESTED = {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "peak-end-effects",
          "controller": "p1", "effects": copy.deepcopy(READY_UP_TO_TWO)}


def board():
    """p1 controls bf1 (the source); p1's exhausted runes pr1-pr3 and p2's exhausted qr1 in their Bases."""
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": []}
    for rune, owner in (("pr1", "p1"), ("pr2", "p1"), ("pr3", "p1"), ("qr1", "p2")):
        state["objects"][rune] = {"owner": owner, "controller": owner, "kind": "rune", "domain": "calm", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": True}
        state["players"][owner]["zones"]["base"].append(rune)
    return state


def creating_program(effect=None):
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "peak-conquer", "controller": "p1",
            "effects": [copy.deepcopy(effect or CREATE)]}


def resolve_creation(state, *, ending=False, effect=None, item_id="spell-1"):
    """The creating instruction resolves as a finalized chain item - in the Main Phase, or during this
    turn's Ending Phase after begin_ending_step (its `ending_step` record for this turn)."""
    timing = fixture(priority="p2", items=[item(item_id, "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    if ending:
        timing = {**timing, "phase": "ending",
                  "ending_step": {"status": "triggers_scheduled", "turn_id": state.get("turn_id", IR.DEFAULT_TURN_ID)}}
    return resolve_with_program(timing, item_id, state, creating_program(effect))


def choose(state, value):
    return {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(state),
            "decisions": [{"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection",
                           "controller": "p1", "value": list(value),
                           "selection_identities": {o: IR.object_identity(state, o) for o in value}}]}


def end_of_turn(state, runes, registry=None):
    """begin_ending_step, finalize the delayed trigger with `runes` chosen, pass, resolve.
    Returns (label, final effect state or None)."""
    began = begin_ending_step(fixture(), state)
    if not began.get("committed"):
        return f"ending refused: {began.get('reason')}", None
    items = began["next_timing_state"]["chain"]["items"]
    if [i["id"] for i in items] != [FIRED]:
        return f"fired {[i['id'] for i in items]}", None
    timing, effects = began["next_timing_state"], began["next_effect_state"]
    finalized = finalize_trigger(timing, effects, registry or {"peak-end-effects": NESTED}, choose(effects, runes))
    if not finalized.get("committed"):
        return f"finalize refused: {finalized.get('reason')}", None
    timing = finalized["next_timing_state"]
    for _ in range(4):
        if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
            break
        timing = RC.pass_priority(timing, timing["priority"])["next_state"]
    done = resolve_with_program(timing, FIRED, finalized["next_effect_state"], NESTED)
    if not done.get("committed"):
        return f"resolve refused: {done.get('reason') or done.get('reason_code')}", None
    return "resolved", done["next_effect_state"]


def exhausted(state):
    return {r: bool(state["objects"][r]["exhausted"]) for r in ("pr1", "pr2", "pr3", "qr1")}


def run_cases():
    """{label: observed} - each from a fresh board."""
    out = {}
    created = resolve_creation(board())
    if not created.get("committed"):
        return {"created": f"refused: {created.get('reason') or created.get('errors')}"}
    armed = created["next_effect_state"]
    entry = (armed.get("delayed_triggers") or [{}])[0]
    out["created"] = {k: entry.get(k) for k in ("delayed_id", "source_object", "created_turn", "waits_for", "effect_program_hash")}
    began = begin_ending_step(fixture(), armed)
    out["fired"] = ([(i["id"], i.get("effect_program_hash")) for i in began["next_timing_state"]["chain"]["items"]],
                    bool(began["next_effect_state"].get("delayed_triggers"))) if began.get("committed") else began.get("reason")
    label, after = end_of_turn(armed, ["pr1", "pr2"])
    out["two_chosen"] = exhausted(after) if after else label
    label, after = end_of_turn(armed, [])
    out["none_chosen"] = exhausted(after) if after else label
    out["three_chosen"] = end_of_turn(armed, ["pr1", "pr2", "pr3"])[0]
    label, after = end_of_turn(armed, ["qr1"])
    out["an_opponents_rune"] = exhausted(after) if after else label
    # two Conquers in one turn: two chain items resolve, each making its own delayed trigger
    second = resolve_creation(armed, item_id="spell-2")
    if second.get("committed"):
        # both armed (the Ending Step then asks p1 to order the two, Core 383.3.d)
        out["two_creations"] = sorted(d["delayed_id"] for d in second["next_effect_state"].get("delayed_triggers") or [])
    else:
        out["two_creations"] = f"refused: {second.get('reason') or second.get('errors')}"
    other = {**NESTED, "effects": [{"op": "ready", "effect_id": "rd", "targets": {
        "min": 0, "max": 3, "decision_ref": "t", "restrictions": {"chosen_zone_class": "board", "kind": "rune"}}}]}
    out["other_instructions_registered"] = end_of_turn(armed, ["pr1"], registry={"peak-end-effects": other})[0]
    late = resolve_creation(board(), ending=True)
    out["created_in_the_ending_step"] = ((late["next_effect_state"].get("delayed_triggers") or [],
                                          [t.get("outcome") for t in (late.get("trace") or {}).get("effect") or []
                                           if isinstance(t, dict) and t.get("op") == "create_delayed_trigger"])
                                         if late.get("committed") else late.get("reason"))
    next_turn = copy.deepcopy(armed)
    next_turn["turn_id"] = "turn-other"
    began = begin_ending_step(fixture(), next_turn)
    out["another_turns_end"] = [i["id"] for i in began["next_timing_state"]["chain"]["items"]] if began.get("committed") else began.get("reason")
    return out


def expected(turn):
    return {
        "created": {"delayed_id": FIRED, "source_object": "bf1", "created_turn": turn,
                    "waits_for": {"kind": "turn", "moment": "end_of_turn", "turn_id": turn},
                    "effect_program_hash": program_hash(NESTED)},
        "fired": ([(FIRED, program_hash(NESTED))], False),
        "two_chosen": {"pr1": False, "pr2": False, "pr3": True, "qr1": True},
        "none_chosen": {"pr1": True, "pr2": True, "pr3": True, "qr1": True},
        "three_chosen": "finalize refused: target_count_out_of_range",
        "an_opponents_rune": {"pr1": True, "pr2": True, "pr3": True, "qr1": False},
        "two_creations": ["peak-end@spell-1", "peak-end@spell-2"],
        "other_instructions_registered": "finalize refused: effect_program_hash_mismatch",
        "created_in_the_ending_step": ([], ["no_op"]),
        "another_turns_end": [],
    }


def main() -> int:
    errors: list[str] = []
    turn = board().get("turn_id", IR.DEFAULT_TURN_ID)
    got, want = run_cases(), expected(turn)
    for label, value in want.items():
        if got.get(label) != value:
            errors.append(f"{label}: {got.get(label)!r}, expected {value!r}")
    for label, bad in (("a nested create_delayed_trigger", {**CREATE, "effects": [copy.deepcopy(CREATE)]}),
                       ("empty effects", {**CREATE, "effects": []}),
                       ("turn: next_turn", {**CREATE, "delayed": {**CREATE["delayed"], "waits_for": {
                           "kind": "turn", "moment": "end_of_turn", "turn": "next_turn"}}}),
                       ("an instruction-supplied program hash", {**CREATE, "delayed": {**CREATE["delayed"],
                                                                                      "effect_program_hash": program_hash(NESTED)}})):
        if not IR.validate_program(creating_program(bad)):
            errors.append(f"an invalid creating instruction validated: {label}")
    # mutations: the hash not bound; 359.3.e.16 ignored - each must move a case
    real = IR._apply_one

    def no_hash(state, effect, *args, **kwargs):
        new_state, trace = real(state, effect, *args, **kwargs)
        for entry in new_state.get("delayed_triggers") or []:
            entry.pop("effect_program_hash", None)
        return new_state, trace

    def ignores_ending(state, effect, *args, **kwargs):
        return real(state, {k: v for k, v in effect.items() if k != "ending_step_context"}, *args, **kwargs)

    for label, replacement in (("an engine that does not bind the program hash", no_hash),
                               ("an engine that ignores 359.3.e.16", ignores_ending)):
        IR._apply_one = replacement
        try:
            moved = [k for k, v in run_cases().items() if v != want.get(k)]
        finally:
            IR._apply_one = real
        if not moved:
            errors.append(f"mutation not caught: {label}")
    if errors:
        print("FAILED: delayed trigger at the end of this turn")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a delayed trigger 'at the end of this turn' is bound to its turn and to the hash of the program its "
          "instruction carried; the Ending Step fires it once; its up-to-2 rune targets are chosen as it is finalized "
          "(355.5.b), any player's runes; its id carries the chain item that made it (two in one turn are two); other "
          "instructions under its id are refused; made after the Ending Step "
          "began it is not generated (359.3.e.16); two engine mutations are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
