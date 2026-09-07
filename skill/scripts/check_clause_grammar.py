#!/usr/bin/env python3
"""Regression gate for C-60 / C-61 (ADR-0016 §1–2): the clause grammar and
canonical dual-compilation agreement.

Must hold:
  - the contract validates, and every production carries both fixtures it is
    promoted on: each golden clause compiles to that production, and each
    near-miss does **not** match it. A pattern that swallows its own negative
    fixture is a failure, not a warning;
  - every production has a lowering and every lowering has a production;
  - the round trip closes against the corpus: for every clause the grammar
    parses, the program it compiles is canonically equal to the program a
    human wrote for that clause in the card pack. The corpus is the golden
    set, and the gate reports how much of it the grammar reproduces;
  - canonical equality is neither vacuous nor structural-only: renaming an
    instruction is closed automatically with an audit record, changing an
    amount is a semantic disagreement, and two programs of the same shape
    whose linked predicate points at a different instruction disagree;
  - a disagreement escalates once, however many rounds it appears in;
  - a clause outside the grammar is `clause_unparsed` carrying its own text,
    and never a guessed program; `complete_grammar` stays false;
  - compilation is deterministic.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from pack_locator import pack_files  # noqa: E402


def corpus_clauses():
    for pack in pack_files("r3a1_programs.json"):
        data = json.loads(pack.read_text(encoding="utf-8"))
        for card in data["cards"]:
            for clause in card["clauses"]:
                yield clause


def target_of(execution):
    return {
        "program_effects": (execution.get("program") or {}).get("effects", []),
        "passive": execution.get("passive"),
        "play_timing": (execution.get("declaration") or {}).get("chain_item", {}).get("timing")
        if execution.get("kind") == "play" else None,
    }


def compiled_of(result):
    return {"program_effects": result.get("program_effects", []), "passive": result.get("passive"),
            "play_timing": result.get("play_timing")}


def main() -> int:
    errors: list[str] = []
    grammar = cg.load_grammar()
    if found := cg.validate_grammar(grammar):
        errors.append(f"the grammar contract does not validate: {found}")
    if grammar.get("complete_grammar") is not False:
        errors.append("the grammar claims to be complete")

    # --- the two fixtures every production is promoted on -------------------------------------
    for production in grammar["productions"]:
        production_id = production["production_id"]
        for text in production["golden"]:
            result = cg.compile_clause(text, grammar)
            if result.get("production_id") != production_id or result.get("unsupported"):
                errors.append(f"{production_id} did not compile its own golden fixture {text!r}: "
                              f"{result.get('production_id')} {result.get('reason_code', '')}")
        for text in production["negative"]:
            result = cg.compile_clause(text, grammar)
            if result.get("production_id") == production_id and not result.get("unsupported"):
                errors.append(f"{production_id} matched its own near-miss {text!r}; the pattern is too wide")

    # --- the round trip against the corpus -----------------------------------------------------
    agree = disagree = unparsed = skipped = 0
    semantic: list[dict] = []
    for clause in corpus_clauses():
        result = cg.compile_clause(clause["text"], grammar)
        if result.get("unsupported"):
            unparsed += 1
            if result.get("reason_code") != "clause_unparsed" or result.get("text") != clause["text"]:
                errors.append(f"an unparsed clause did not carry its own text: {result}")
            if "program_effects" in result:
                errors.append(f"an unparsed clause produced a program anyway: {clause['text']!r}")
            continue
        execution = clause.get("execution")
        if execution is None:
            skipped += 1
            continue
        verdict = cg.compare_compilations(compiled_of(result), target_of(execution),
                                          label_left="grammar", label_right="corpus")
        if verdict["agree"]:
            agree += 1
        else:
            disagree += 1
            semantic.extend(verdict["escalate"])
    if disagree:
        errors.append(f"the grammar disagrees with the corpus on {disagree} clause(s): "
                      f"{[d['field'] for d in semantic][:4]}")
    if agree < 25:
        errors.append(f"the round trip reproduces only {agree} of the corpus's hand-written programs")

    # --- canonical equality has teeth -----------------------------------------------------------
    left = {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1}]}
    renamed = {"program_effects": [{"op": "draw", "effect_id": "draw-1", "player": "$controller", "count": 1}]}
    verdict = cg.compare_compilations(left, renamed)
    if not verdict["agree"] or not verdict["closed_automatically"]:
        errors.append(f"renaming an instruction was not closed as a naming difference: {verdict}")
    if verdict["closed_automatically"][0]["equivalence"] != "instruction_naming":
        errors.append("the audit record does not name the equivalence it closed on")
    changed = {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 2}]}
    verdict = cg.compare_compilations(left, changed)
    if verdict["agree"] or not verdict["escalate"]:
        errors.append("changing an amount was not a semantic disagreement")
    # the link a name carried survives the canonicalizer
    linked = {"program_effects": [
        {"op": "discard", "effect_id": "d", "player": "$controller", "count": 1},
        {"op": "draw", "effect_id": "then", "player": "$controller", "count": 1,
         "predicate": {"kind": "action_performed", "effect_id": "d"}}]}
    relinked = copy.deepcopy(linked)
    relinked["program_effects"][1]["predicate"]["effect_id"] = "then"
    if cg.compare_compilations(linked, relinked)["agree"]:
        errors.append("a predicate pointing at a different instruction was called equal; the link did not survive")
    renamed_link = copy.deepcopy(linked)
    renamed_link["program_effects"][0]["effect_id"] = "first"
    renamed_link["program_effects"][1]["predicate"]["effect_id"] = "first"
    if not cg.compare_compilations(linked, renamed_link)["agree"]:
        errors.append("renaming both ends of a link was called a disagreement")
    reordered = cg.compare_compilations({"required_capability": ["draw", "targeting"]},
                                        {"required_capability": ["targeting", "draw"]})
    if not reordered["agree"] or not reordered["closed_automatically"]:
        errors.append(f"an unordered set in a different order was escalated: {reordered}")

    # --- one signature, one escalation -----------------------------------------------------------
    once = cg.compare_compilations(left, changed)["escalate"]
    fresh, seen = cg.dedupe(once)
    again, _ = cg.dedupe(once, seen)
    if len(fresh) != 1 or again:
        errors.append(f"the same disagreement escalated twice: {len(fresh)} then {len(again)}")

    # --- a card, and what it will not compile ------------------------------------------------------
    card = cg.compile_card([{"text": "[Action]"}, {"text": "Draw 1."}, {"text": "Summon a dragon."}], grammar)
    if card["complete_grammar"] is not False:
        errors.append("compile_card claimed a complete grammar")
    if [c["text"] for c in card["unsupported_clauses"]] != ["Summon a dragon."]:
        errors.append(f"compile_card did not report exactly the clause it could not parse: {card['unsupported_clauses']}")
    if len(card["program_effects"]) != 1 or card["program_effects"][0]["op"] != "draw":
        errors.append(f"compile_card did not keep the clauses it could compile: {card['program_effects']}")
    wrapped = cg.compile_clause("When you play me, summon a dragon.", grammar)
    if not wrapped.get("unsupported") or wrapped.get("production_id") != "when_you_play_me":
        errors.append(f"a wrapper with an unparsed instruction was compiled anyway: {wrapped}")

    if cg.compile_clause("Draw 1.", grammar) != cg.compile_clause("Draw 1.", grammar):
        errors.append("compilation is not deterministic")
    if cg.normalize("Give a friendly unit +3 :rb_might: this turn.") != "give a friendly unit +3 [m] this turn":
        errors.append(f"normalization changed: {cg.normalize('Give a friendly unit +3 :rb_might: this turn.')!r}")

    if errors:
        print("FAILED: clause grammar checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"clause grammar checks passed: {len(grammar['productions'])} productions, corpus round trip "
          f"{agree} reproduced / {disagree} disagreed / {unparsed} unparsed / {skipped} without a program, "
          f"complete_grammar false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
