#!/usr/bin/env python3
"""
Gate: two instructions joined by "and" are two steps in the card's order, and a step
that does nothing does not stop the other (Core 422.4 reads "then" the same way; neither
carries a backward reference, so neither is a Core 359.3.e.14 linked instruction).

Must hold, for "Channel 2 runes exhausted and draw 1." and "Draw 1 and channel 1 rune
exhausted.":
  - the clause grammar emits exactly two instructions, in the sentence's order, and
    neither carries a predicate;
  - run on a board with runes in the Rune Deck, both steps happen: the channelled runes
    are in the controller's Base exhausted and the hand grew by the draw;
  - run with an empty Rune Deck, the channel is a no_op and the draw still happens,
    whichever of the two comes first;
  - the trace lists the steps in the sentence's order.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program  # noqa: E402

SENTENCES = {
    "Channel 2 runes exhausted and draw 1.": ["channel_rune", "draw"],
    "Draw 1 and channel 1 rune exhausted.": ["draw", "channel_rune"],
}


def board(runes: int) -> dict:
    state = base_state()
    p1 = state["players"]["p1"]["zones"]
    template = copy.deepcopy(state["objects"][p1["rune_deck"][0]])
    ids = []
    for index in range(runes):
        oid = f"rq{index}"
        state["objects"][oid] = {**copy.deepcopy(template), "object_id": oid} if "object_id" in template \
            else copy.deepcopy(template)
        ids.append(oid)
    for old in p1["rune_deck"]:
        state["objects"].pop(old, None)
    p1["rune_deck"] = ids
    return state


def run(state: dict, effects: list[dict]) -> dict:
    return apply_program(state, {"schema_version": PROGRAM_VERSION, "ruleset": state["ruleset"],
                                 "program_id": "sequence-steps", "controller": "p1", "effects": effects})


def main() -> int:
    errors: list[str] = []
    grammar = cg.load_grammar()
    for sentence, ops in SENTENCES.items():
        out = cg.compile_clause(sentence, grammar)
        if out.get("unsupported"):
            errors.append(f"{sentence!r} did not compile: {out.get('reason') or out}")
            continue
        emitted = out["program_effects"]
        if [e["op"] for e in emitted] != ops:
            errors.append(f"{sentence!r} emitted {[e['op'] for e in emitted]}, not {ops} in the sentence's order")
            continue
        if any("predicate" in e for e in emitted):
            errors.append(f"{sentence!r}: a step carries a predicate; 'and' is being read as a condition")
        effects = [{k: v for k, v in copy.deepcopy(e).items() if k != "order"} for e in emitted]
        for e in effects:
            e["player"] = "p1"
        channel = next(e for e in effects if e["op"] == "channel_rune")
        draw = next(e for e in effects if e["op"] == "draw")

        before = board(channel["count"])
        hand = len(before["players"]["p1"]["zones"]["hand"])
        base = set(before["players"]["p1"]["zones"]["base"])
        both = run(before, effects)
        if not both.get("committed"):
            errors.append(f"{sentence!r} did not commit: {both.get('reason') or both.get('errors')}")
            continue
        after = both["next_state"]
        new = [o for o in after["players"]["p1"]["zones"]["base"] if o not in base]
        if len(new) != channel["count"] or not all(after["objects"][o].get("exhausted") is True for o in new):
            errors.append(f"{sentence!r}: {len(new)} rune(s) reached the Base, exhausted "
                          f"{[after['objects'][o].get('exhausted') for o in new]}; expected {channel['count']} exhausted")
        if len(after["players"]["p1"]["zones"]["hand"]) != hand + draw["count"]:
            errors.append(f"{sentence!r}: the hand went {hand} -> {len(after['players']['p1']['zones']['hand'])}, "
                          f"not +{draw['count']}")
        if [t.get("op") for t in both["trace"]] != ops:
            errors.append(f"{sentence!r}: the trace ran {[t.get('op') for t in both['trace']]}, not {ops}")

        dry = run(board(0), effects)
        if not dry.get("committed"):
            errors.append(f"{sentence!r} with an empty Rune Deck did not commit: {dry.get('reason') or dry.get('errors')}")
            continue
        outcomes = {t.get("op"): t.get("outcome") for t in dry["trace"]}
        if outcomes.get("channel_rune") != "no_op" or outcomes.get("draw") != "applied" \
                or len(dry["next_state"]["players"]["p1"]["zones"]["hand"]) != hand + draw["count"]:
            errors.append(f"{sentence!r}: with an empty Rune Deck the channel did not stop at no_op while the draw "
                          f"still happened: {outcomes}")

    if errors:
        print("FAILED: sequence steps" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'X and Y' compiles to two unconditional steps in the sentence's order; with runes both happen "
          "(runes in the Base exhausted, the hand grows by the draw); with an empty Rune Deck the channel is a "
          "no_op and the draw still happens, whichever comes first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
