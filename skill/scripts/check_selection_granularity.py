#!/usr/bin/env python3
"""
Standing gate: an empty choice costs its consumer, not the whole card.

"Choose a gear. Buff it. Draw 1." on a board with no gear used to draw nothing.
The choice correctly reported `no_op` - Core 359.3.e, there is nothing to choose
from - and then the Buff's `selection_origin_unbound` returned committed=False
for the entire program, so the Draw disappeared with it.

Core 359.3.e.6 ignores an instruction that cannot be followed. Core 359.3.e.10
lets a spell execute none of its instructions and still be considered played.
Core 359.3.e.14.a takes the LINKED later instruction down - the Buff, which
reads the choice - and says nothing about an instruction that reads nothing.

What is held here:

  * an empty choice is `no_op`, its consumer is `ignored_illegal_target`, and an
    unrelated later instruction still runs;
  * the program COMMITS - a card whose every instruction was ignored is still
    played (359.3.e.10);
  * the narrowness. A tampered decision artifact is not a game event, so every
    other unbound reference still refuses the whole program: an artifact naming
    another program, and one naming another effect, both still abort. Widening
    the per-instruction path to those would let a lying artifact through, which
    is the opposite failure and a worse one.

    python skill/scripts/check_selection_granularity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import effect_ir  # noqa: E402
import selection_binding as sb  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FAILURES: list[str] = []


def fail(label: str, detail: str) -> None:
    FAILURES.append(f"{label}: {detail}")


def state() -> dict:
    """Two friendly Units at a battlefield, cards in hand and deck, no gear."""
    return {
        "schema_version": "riftbound-effect-state.v1",
        "ruleset": {"core": effect_ir.CORE_RULESET, "faq_as_of": effect_ir.FAQ_AS_OF},
        "turn_id": "T1",
        "players": {
            "p1": {"zones": {"main_deck": ["c1", "c2"], "hand": ["h1"], "trash": [],
                             "banishment": [], "base": [], "rune_deck": []},
                   "resources": {"energy": 5, "power": {}}},
            "p2": {"zones": {"main_deck": [], "hand": [], "trash": [],
                             "banishment": [], "base": [], "rune_deck": []},
                   "resources": {"energy": 0, "power": {}}},
        },
        "battlefields": {"bf1": {"controller": None, "objects": ["u1", "u2"]}},
        "objects": {
            "u1": {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4,
                   "might_modifiers": [], "damage": 0, "exhausted": False},
            "u2": {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4,
                   "might_modifiers": [], "damage": 0, "exhausted": False},
            "c1": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                   "might_modifiers": [], "damage": 0, "exhausted": False},
            "c2": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                   "might_modifiers": [], "damage": 0, "exhausted": False},
            "h1": {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                   "might_modifiers": [], "damage": 0, "exhausted": False},
        },
        "replacement_effects": [],
    }


def program(effects: list[dict], program_id: str = "granularity") -> dict:
    return {"schema_version": effect_ir.PROGRAM_VERSION,
            "ruleset": {"core": effect_ir.CORE_RULESET, "faq_as_of": effect_ir.FAQ_AS_OF},
            "program_id": program_id, "controller": "p1", "source_object": "u1",
            "effects": effects}


# "Choose a gear." on a board with no gear.
EMPTY_CHOICE = {"op": "establish_selection", "effect_id": "ch", "selection_id": "s1",
                "decision_ref": "ch",
                "choice": {"selection_kind": "single", "from": "board",
                           "count": {"one": True}, "visibility": "public",
                           "criteria": {"kind": "gear"}}}
CONSUMER = {"op": "buff", "effect_id": "consume",
            "target": {"selection_ref": "s1", "chosen_zone_class": "board", "kind": "unit"}}
UNRELATED = {"op": "draw", "effect_id": "draw", "player": "p1", "count": 1}


def main() -> int:
    # 1. the empty choice costs the consumer and nothing else
    start = state()
    before = len(start["players"]["p1"]["zones"]["hand"])
    result = effect_ir.apply_program(start, program([EMPTY_CHOICE, CONSUMER, UNRELATED]))
    if result.get("committed") is not True:
        fail("empty choice", f"the program did not commit: {result.get('reason_code')} "
                             f"{result.get('reason') or result.get('errors')}. Core 359.3.e.10 "
                             f"has a spell execute none of its instructions and still be played.")
    else:
        outcomes = {e.get("effect_id"): e.get("outcome") for e in result.get("trace") or []}
        if outcomes.get("ch") != "no_op":
            fail("empty choice", f"the choice reported {outcomes.get('ch')!r}, not no_op")
        if outcomes.get("consume") != "ignored_illegal_target":
            fail("empty choice", f"the consumer reported {outcomes.get('consume')!r}; an "
                                 f"instruction that cannot be followed is ignored (359.3.e.6)")
        after = len(result["next_state"]["players"]["p1"]["zones"]["hand"])
        if after != before + 1:
            fail("empty choice", f"the unrelated Draw did not run (hand {before} -> {after}). "
                                 f"359.3.e.14.a takes the LINKED instruction, not the card.")

    # 2. the narrowness: a lying artifact still refuses the whole program
    import engine_decisions  # noqa: F401 - imported for its schema, used via the envelope
    real = {"op": "establish_selection", "effect_id": "ch", "selection_id": "s1",
            "decision_ref": "ch",
            "choice": {"selection_kind": "single", "from": "board", "count": {"one": True},
                       "visibility": "public", "criteria": {"kind": "unit"}}}
    start = state()
    candidates, identities = effect_ir.choice_candidates(start, real["choice"], "p1")
    good = {"selection_id": "s1",
            "candidate_set_hash": sb.candidate_set_hash(real["choice"], candidates, identities),
            "visibility": "public",
            "origin": {"program_id": "granularity", "effect_id": "ch"}}
    for label, tamper, expected in (
            ("another program", {"origin": {"program_id": "somebody-else", "effect_id": "ch"}},
             sb.ORIGIN_UNBOUND),
            ("another effect", {"origin": {"program_id": "granularity", "effect_id": "other"}},
             sb.ORIGIN_UNBOUND),
            ("another candidate set", {"candidate_set_hash": "sha256:" + "0" * 64},
             sb.CANDIDATES_CHANGED)):
        start = state()
        envelope = {"schema_version": "engine-decisions.v1",
                    "input_hash": effect_ir.hash_value(start),
                    "decisions": [{"decision_id": "ch", "stage": "resolution",
                                   "kind": "target_selection", "controller": "p1",
                                   "value": ["u1"],
                                   "selection_identities": {
                                       "u1": effect_ir.object_identity(start, "u1")},
                                   "binding": {**good, **tamper}}]}
        result = effect_ir.apply_program(start, program([real, CONSUMER, UNRELATED]),
                                         decisions=envelope)
        if result.get("committed") is not False:
            fail(f"tampered: {label}",
                 "the program committed. A lying decision artifact is not a game event and "
                 "may not take the per-instruction path an empty choice takes.")
        elif result.get("reason_code") != expected:
            fail(f"tampered: {label}",
                 f"refused as {result.get('reason_code')!r}, expected {expected!r}")

    print("selection granularity")
    print("  an empty choice: no_op, its consumer ignored, the unrelated Draw still runs, "
          "and the program commits (359.3.e, 359.3.e.6, 359.3.e.10)")
    print("  3 tampered artifacts still refuse the whole program by name")
    for failure in FAILURES:
        print("\nFAILED: " + failure)
    if FAILURES:
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
