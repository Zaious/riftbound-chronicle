#!/usr/bin/env python3
"""Regression gate for modal clauses — "X or Y" (Round H, Core 402.2).

Qiyana, Victorious: "When I conquer, draw 1 or channel 1 rune exhausted."

The engine has had modal programs since ADR-0011; what was missing was the
grammar. So the danger here is not a missing feature, it is a wrong reading:
"or" sitting one character away from the sequence connectives DP-86 added. A
sequence performs both parts. Reading "or" as one would silently do twice
what the card says to do once, and nothing downstream would notice.

Codex's contract, checked below:

  - an unchosen mode is `decision_required`. The engine never picks one,
    however obvious the better mode looks;
  - a mode the program does not have is refused by name;
  - an empty or single-option modal is refused - a "choice" of one is not a
    choice, and a choice of none is a program that can never run.

And the grammar's own boundary: both halves must be instructions it already
reads. A half it cannot read, a half that is a passive, and a clause with two
"or"s all abstain rather than being compiled into a guess.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import apply_program, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402
from effect_ir import PROGRAM_VERSION  # noqa: E402

QIYANA = "When I conquer, draw 1 or channel 1 rune exhausted."


def modal_program(modal):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "qiyana-conquer", "controller": "p1", "modal": copy.deepcopy(modal)}


def bind(value, bindings):
    if isinstance(value, dict):
        return {k: bind(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    return bindings.get(value, value) if isinstance(value, str) else value


def decisions(state, option_id):
    from effect_ir import hash_value
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": "mode", "kind": "mode_selection", "stage": "trigger_finalization",
                           "controller": "p1", "value": option_id}]}


def main() -> int:
    errors: list[str] = []
    grammar = cg.load_grammar()

    # --- the clause compiles to a mode, not to a sequence -----------------------------------------
    compiled = cg.compile_clause(QIYANA, grammar)
    if compiled.get("unsupported") or compiled.get("production_id") != "when_i_conquer":
        errors.append(f"Qiyana's clause did not compile: {compiled}")
        modal = None
    else:
        modal = compiled.get("modal")
        if modal is None:
            errors.append("the clause compiled without a modal; 'or' was read as something else")
        elif compiled.get("program_effects"):
            errors.append(f"a modal clause also emitted unconditional instructions: {compiled['program_effects']}; "
                          "both modes would happen")
        elif len(modal["options"]) != 2 or modal["choose"] != 1:
            errors.append(f"the modes were not two choices of one: {modal}")
        elif modal["timing"] != "trigger_finalization":
            errors.append(f"a triggered ability chose its mode at {modal['timing']!r}, not at finalization (402.2)")
        trigger = (compiled.get("passive") or {}).get("object_fields", {}).get("conquer_triggers")
        if not trigger or trigger[0].get("scope") != "unit_here":
            errors.append(f"the conquer trigger did not name the unit at the Battlefield scored: {trigger}")

    # --- the engine will not choose for the player ------------------------------------------------
    if modal is not None:
        state = base_state()
        bindings = {"$controller": "p1", "$source_object": "u1", "$clause_id": "qiyana"}
        program = modal_program(bind(modal, bindings))
        if validate_program(program):
            errors.append(f"the compiled modal program is not valid: {validate_program(program)}")
        unchosen = apply_program(state, program)
        if unchosen.get("committed"):
            errors.append("an unchosen mode was resolved anyway; the engine picked one")
        if unchosen.get("reason_code") != "mode_selection_required" or unchosen.get("decision_ids") != ["mode"]:
            errors.append(f"the required decision was not reported as one: {unchosen.get('reason_code')} "
                          f"{unchosen.get('decision_ids')}")
        if sorted(unchosen.get("mode_options") or []) != ["mode-0", "mode-1"]:
            errors.append(f"the refusal did not say which modes were available: {unchosen.get('mode_options')}")
        if unchosen.get("trace"):
            errors.append("an unchosen modal program still did something")
        # each mode does its own thing, and only its own
        drawn = apply_program(state, program, decisions=decisions(state, "mode-0"))
        channelled = apply_program(state, program, decisions=decisions(state, "mode-1"))
        ops = ([t.get("op") for t in drawn.get("trace", [])], [t.get("op") for t in channelled.get("trace", [])])
        if ops[0] != ["draw"] or ops[1] != ["channel_rune"]:
            errors.append(f"the modes did not run exactly one instruction each: {ops}")
        # a mode the program does not have is refused by name
        unknown = apply_program(state, program, decisions=decisions(state, "mode-9"))
        if unknown.get("committed"):
            errors.append("a mode the program does not have was accepted")
        if "mode-9" not in str(unknown.get("errors") or unknown.get("reason") or ""):
            errors.append(f"the unknown mode was not named in the refusal: "
                          f"{unknown.get('errors') or unknown.get('reason')}")
        # and a "choice" of one is refused
        one = modal_program({**bind(modal, bindings), "options": bind(modal, bindings)["options"][:1]})
        if not validate_program(one):
            errors.append("a modal program with a single option was accepted; that is not a choice")
        none = modal_program({**bind(modal, bindings), "options": []})
        if not validate_program(none):
            errors.append("a modal program with no options was accepted")

    # --- the grammar's boundary --------------------------------------------------------------------
    for text, why in (
        ("Draw 1 or summon a dragon.", "a half the grammar cannot read"),
        ("[Tank] or draw 1.", "a half that is a passive, not an instruction"),
        ("Draw 1 or draw 2 or draw 3.", "two connectives, so which binds tighter is a guess"),
    ):
        result = cg.compile_clause(text, grammar)
        if not result.get("unsupported"):
            errors.append(f"{text!r} was compiled despite {why}: {result.get('production_id')}")

    # --- "or" is never read as a sequence ----------------------------------------------------------
    both = cg.compile_clause("Draw 1 and channel 1 rune exhausted.", grammar)
    either = cg.compile_clause("Draw 1 or channel 1 rune exhausted.", grammar)
    if both.get("production_id") != "sequence" or len(both.get("program_effects", [])) != 2:
        errors.append(f"the 'and' form stopped being a sequence: {both.get('production_id')}")
    if either.get("production_id") != "modal_choice" or either.get("program_effects"):
        errors.append(f"the 'or' form did not stay a choice: {either.get('production_id')} "
                      f"{either.get('program_effects')}")

    if errors:
        print("FAILED: modal clause checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("modal clause checks passed: 'or' compiles to a mode chosen at trigger finalization, the engine "
          "never chooses one, an unknown or empty option set is refused, and 'and' is still a sequence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
