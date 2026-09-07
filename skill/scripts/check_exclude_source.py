#!/usr/bin/env python3
"""Regression gate for `exclude_source_identity` (Round H).

"Ready another unit" is one word away from "ready a unit", and the word is
load-bearing. Codex's contract for it:

    it excludes the trigger's own source object and nothing else, by
    identity; never by name, and never by quietly re-finding a substitute.

So the gate is written against the three ways that could go wrong:

  - **the source is not excluded.** A program whose chosen target is its own
    source must be refused with `target_excludes_source`. Same object, same
    everything, one word of text - it has to be the word that decides.
  - **something else is excluded too.** A second unit with the *same name and
    the same printed fields* as the source is a legal choice. If it were
    refused, the exclusion would be reading a name, and every card that says
    "another" would silently stop working on a board with two copies.
  - **the exclusion evaporates.** The sentinel is written by the grammar and
    bound by the engine. If it ever reaches the legality check unbound, the
    answer must be a refusal (`target_source_exclusion_unresolved`), not a
    pass - an unresolved exclusion that returns "legal" turns "another unit"
    into "any unit" with no error anywhere.

And one thing the engine must *not* do: when the chosen target is the source,
it may not substitute a legal object. The choice is the player's; the engine
reports the illegal target and applies nothing.
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
    SOURCE_IDENTITY_SENTINEL,
    apply_program,
    evaluate_target,
    object_identity,
    validate_program,
)


def board_state():
    """u1 and u3 on the same Battlefield, identical in every printed field and
    in name. Only their identity tells them apart."""
    state = base_state()
    state["objects"]["u3"] = copy.deepcopy(state["objects"]["u1"])
    state["objects"]["u1"]["name"] = state["objects"]["u3"]["name"] = "Pit Rookie"
    state["objects"]["u1"]["exhausted"] = state["objects"]["u3"]["exhausted"] = True
    state["players"]["p1"]["zones"]["base"] = []
    state["battlefields"]["bf1"]["objects"] = ["u1", "u3"]
    state["battlefields"]["bf1"]["controller"] = "p1"
    return state


def ready_program(object_id, *, source="u1", exclusion=SOURCE_IDENTITY_SENTINEL):
    target = {"object_id": object_id, "chosen_zone_class": "board", "kind": "unit"}
    if exclusion is not None:
        target["exclude_source_identity"] = exclusion
    prog = program("ready-another", {"op": "ready", "effect_id": "rd", "target": target})
    prog["source_object"] = source
    return prog


def main() -> int:
    errors: list[str] = []
    state = board_state()

    # --- 1. the source itself is refused ---------------------------------------------------------
    legal, reason = evaluate_target(
        state, {"object_id": "u1", "chosen_zone_class": "board", "kind": "unit",
                "exclude_source_identity": object_identity(state, "u1")}, "p1")
    if legal or reason != "target_excludes_source":
        errors.append(f"the source object was a legal choice for 'another unit': {legal} {reason}")

    # --- 2. an identical twin is not ------------------------------------------------------------
    legal, reason = evaluate_target(
        state, {"object_id": "u3", "chosen_zone_class": "board", "kind": "unit",
                "exclude_source_identity": object_identity(state, "u1")}, "p1")
    if not legal:
        errors.append(f"a second unit with the same name as the source was excluded too: {reason}; "
                      "the exclusion is reading something other than identity")
    if state["objects"]["u1"]["name"] != state["objects"]["u3"]["name"]:
        errors.append("the twin fixture stopped sharing a name, so it no longer tests the name path")

    # --- 3. an unresolved sentinel refuses rather than passes ------------------------------------
    legal, reason = evaluate_target(
        state, {"object_id": "u3", "chosen_zone_class": "board", "kind": "unit",
                "exclude_source_identity": SOURCE_IDENTITY_SENTINEL}, "p1")
    if legal or reason != "target_source_exclusion_unresolved":
        errors.append(f"an unbound exclusion sentinel was treated as no exclusion: {legal} {reason}")

    # --- 4. the whole program: chosen source refused, no substitute applied ----------------------
    result = apply_program(board_state(), ready_program("u1"))
    step = result["trace"][0]
    if step["outcome"] != "ignored_illegal_target" or step.get("reason") != "target_excludes_source":
        errors.append(f"a program that chose its own source did not report an illegal target: {step}")
    if result["next_state"]["objects"]["u3"]["exhausted"] is not True:
        errors.append("the engine readied a different unit instead of refusing the chosen one; "
                      "an illegal choice is not an invitation to re-choose")
    if result["next_state"]["objects"]["u1"]["exhausted"] is not True:
        errors.append("the refused target was readied anyway")

    # --- 5. and the legal twin does get readied --------------------------------------------------
    result = apply_program(board_state(), ready_program("u3"))
    if result["trace"][0]["outcome"] != "applied" or result["next_state"]["objects"]["u3"]["exhausted"] is not False:
        errors.append(f"the legal 'another unit' was not readied: {result['trace'][0]}")
    if result["next_state"]["objects"]["u1"]["exhausted"] is not True:
        errors.append("readying another unit also readied the source")

    # --- 6. the sentinel needs a source to bind to ----------------------------------------------
    orphan = ready_program("u3")
    del orphan["source_object"]
    result = apply_program(board_state(), orphan)
    if result["committed"] or result["valid"]:
        errors.append("a program excluding its source without naming one was committed anyway")
    if not any("source_object" in e for e in result.get("errors", [])):
        errors.append(f"the missing source was reported as something else: {result.get('errors')}")
    if "next_state" in result:
        errors.append("an invalid program still produced a next state")

    # --- 7. validation accepts the sentinel and an identity, and nothing else --------------------
    if validate_program(ready_program("u3")):
        errors.append(f"a well-formed exclusion failed validation: {validate_program(ready_program('u3'))}")
    if not validate_program(ready_program("u3", exclusion="Pit Rookie")):
        errors.append("a card *name* passed as an exclusion; only an identity token may")

    # --- 8. the grammar writes the sentinel, and only for 'another' ------------------------------
    grammar = cg.load_grammar()
    for text, expected in (("Ready another unit.", True), ("Ready a unit.", False),
                           ("Buff another friendly unit.", True), ("Buff a friendly unit.", False)):
        compiled = cg.compile_clause(text, grammar)
        if compiled.get("unsupported"):
            errors.append(f"{text!r} did not compile: {compiled}")
            continue
        written = compiled["program_effects"][0].get("target", {}).get("exclude_source_identity")
        if (written == SOURCE_IDENTITY_SENTINEL) != expected:
            errors.append(f"{text!r} wrote exclusion {written!r}; expected {'the sentinel' if expected else 'none'}")

    if errors:
        print("FAILED: exclude_source_identity checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("exclude_source_identity checks passed: the source is excluded by identity, an identically "
          "named twin is not, an unbound sentinel refuses, and a refused choice is never substituted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
