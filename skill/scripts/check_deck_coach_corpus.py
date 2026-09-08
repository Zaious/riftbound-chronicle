#!/usr/bin/env python3
"""Executable checks for deck-coach-corpus.v1, the S-05 regression contract.

Two claim classes that must not be filed together, and a list of claims neither
of them makes. The gate holds three things:

  * a general-primer case may not carry engine evidence anywhere inside it, and
    the check is a deep scan, because burying the field one level down is the
    cheap way to break the rule;
  * an engine-closed case binds its closure, and each of the five bindings —
    a program, a receipt, the engine identity, the grammar version, the deck
    input hash — breaks verification when it moves, naming which one did;
  * no case may claim a win rate, a Tier, a keep rule, a matchup result or a
    simulation, as a field or as prose.

The closure this gate binds is synthetic, built here in the shape
`deck-closure.v1` produces. That is deliberate: the contract and its damage
tests belong in the public repository, and the closures for real decks do not.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from deck_coach_corpus import (
    BINDING_FIELDS,
    CASE_CLASSES,
    ENGINE_EVIDENCE_KEYS,
    FORBIDDEN_CLAIM_KEYS,
    FORBIDDEN_CLAIM_PATTERNS,
    binding_for,
    forbidden_claims,
    validate_case,
    validate_corpus,
    verify_case,
)
from engine_check import canonical_hash


SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS = SKILL_DIR / "data" / "deck_coach_corpus.json"


def _rehash_program(slot):
    slot["program_hash"] = canonical_hash(slot["program"])
    slot["receipt"]["program_hash"] = slot["program_hash"]
    slot["receipt_hash"] = canonical_hash(slot["receipt"])


def _rehash_receipt(slot):
    slot["receipt_hash"] = canonical_hash(slot["receipt"])


def synthetic_closure() -> dict:
    """A closure in the shape deck-closure.v1 produces, with nothing licensed in it."""
    identity = {"capability_set_id": "capability-set:synthetic-0001",
                "implementation_identity": "implementation:synthetic-0001"}
    slots = []
    for index in range(1, 4):
        program = {"source": "grammar", "grammar_version": "clause-grammar.v1",
                   "schema_version": "card-program.v1",
                   "productions": [f"production-{index}"],
                   "program_effects": [{"op": "deal_damage", "amount": index}],
                   "passive": []}
        program_hash = canonical_hash(program)
        receipt = {"schema_version": "closure-receipt.v1", "card": f"synthetic-card-{index}",
                   "text_hash": canonical_hash(f"synthetic text {index}"),
                   "program_source": "grammar", "program_hash": program_hash,
                   "engine": identity, "grammar_version": "clause-grammar.v1"}
        slots.append({"card": f"synthetic-card-{index}", "ready": True, "program": program,
                      "program_hash": program_hash, "receipt": receipt,
                      "receipt_hash": canonical_hash(receipt)})
    return {
        "schema_version": "deck-closure.v1",
        "deck": "synthetic-closed-deck",
        "deck_input_hash": canonical_hash({"deck": "synthetic-closed-deck"}),
        "deck_snapshot_provenance": {"source": "synthetic"},
        "engine": identity,
        "grammar_version": "clause-grammar.v1",
        "sections_required": ["legend", "main", "battlefields", "runes"],
        "sections_present": ["legend", "main", "battlefields", "runes"],
        "missing_sections": [],
        "slot_count": len(slots),
        "card_slots": len(slots),
        "slots_by_section": {"main": len(slots)},
        "champion_slots": [],
        "all_slots_ready": True,
        "not_ready": [],
        "slots": slots,
    }


def closed_case(closure: dict) -> dict:
    return {
        "case_id": "DC-EC-SYNTH-1",
        "case_class": "engine_closed",
        "deck_id": closure["deck"],
        "sections": {"legend": 1, "main": 40, "battlefields": 3, "runes": 12},
        "expectations": [
            "Every slot carries an active program and an evidence receipt.",
            "The coverage claim names the engine build it was produced under.",
        ],
        "notes": "Synthetic closure; the real ones live in the licensed overlay.",
        "closure_binding": binding_for(closure),
    }


def main() -> int:
    failures: list[str] = []
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

    if problems := validate_corpus(corpus):
        failures.append(f"the shipped corpus does not validate: {problems}")
    if not corpus["general_primer_cases"]:
        failures.append("the corpus needs general-primer cases to show that class's shape")
    if corpus["engine_closed_cases"]:
        failures.append("the public corpus carries no engine-closed cases; the closures they "
                        "would bind are licensed overlay data")

    closure = synthetic_closure()
    case = closed_case(closure)
    if problems := validate_case(case):
        failures.append(f"the synthetic engine-closed case must validate: {problems}")
    if problems := verify_case(case, closure=closure):
        failures.append(f"the synthetic case must verify against its own closure: {problems}")

    # --- the five damage tests ---------------------------------------------
    # Each moves one binding and requires verification to fail naming it.
    damage = [
        ("a program",
         lambda c: (c["slots"][0]["program"]["program_effects"].append(
             {"op": "deal_damage", "amount": 99}), _rehash_program(c["slots"][0])),
         "program_hashes"),
        ("a receipt",
         lambda c: (c["slots"][1]["receipt"].__setitem__("text_hash", "sha256:0"),
                    _rehash_receipt(c["slots"][1])),
         "receipt_hashes"),
        ("the engine identity",
         lambda c: c["engine"].__setitem__("capability_set_id", "capability-set:moved"),
         "engine"),
        ("the grammar version",
         lambda c: c.__setitem__("grammar_version", "clause-grammar.v2"),
         "grammar_version"),
        ("the deck input hash",
         lambda c: c.__setitem__("deck_input_hash", "sha256:0"),
         "deck_input_hash"),
    ]
    for label, mutate, field in damage:
        moved = copy.deepcopy(closure)
        mutate(moved)
        problems = verify_case(case, closure=moved)
        if not problems:
            failures.append(f"a case survived {label} moving under it")
            continue
        if not any(f"closure_binding.{field}" in problem for problem in problems):
            failures.append(f"{label} moving was caught, but not as {field}: {problems}")
        # Every one of them also moves the closure hash, which is the binding of
        # last resort; the named field is what says which thing moved.
        if not any("closure_binding.closure_hash" in problem for problem in problems):
            failures.append(f"{label} moving did not change the closure hash")

    # A closure that did not move verifies, so the five above are about the
    # movement rather than about verification always failing.
    if verify_case(case, closure=synthetic_closure()):
        failures.append("an unchanged closure must still verify")

    # --- the two classes stay apart ----------------------------------------
    primer = copy.deepcopy(corpus["general_primer_cases"][0])
    smuggles = [
        ("a closure binding at the top level",
         lambda c: c.__setitem__("closure_binding", case["closure_binding"])),
        ("engine evidence buried one level down",
         lambda c: c.__setitem__("sections", {**c["sections"], "closure_hash": 1})),
    ]
    for label, mutate in smuggles:
        candidate = copy.deepcopy(primer)
        mutate(candidate)
        if not validate_case(candidate):
            failures.append(f"a general-primer case accepted {label}")

    # A general-primer case in the engine-closed list, and the reverse.
    mixed = {**corpus, "engine_closed_cases": [primer]}
    if not any("belongs in engine_closed_cases" in p for p in validate_corpus(mixed)):
        failures.append("a primer case filed as engine-closed must be refused as misfiled")
    mixed_back = {**corpus, "general_primer_cases": corpus["general_primer_cases"] + [case]}
    if not any("belongs in general_primer_cases" in p for p in validate_corpus(mixed_back)):
        failures.append("an engine-closed case filed as a primer must be refused as misfiled")

    # An engine-closed case whose closure is not closed is not one.
    unready = copy.deepcopy(case)
    unready["closure_binding"]["all_slots_ready"] = False
    if not any("every slot is ready" in p for p in validate_case(unready)):
        failures.append("an engine-closed case binding an unclosed deck must be refused")

    # --- claims the coach does not make ------------------------------------
    claim_cases = [
        ("a win rate field", lambda c: c.__setitem__("sections", {**c["sections"], "win_rate": 60})),
        ("a Tier field", lambda c: c.__setitem__("sections", {**c["sections"], "tier": 1})),
        ("a keep rule field", lambda c: c.__setitem__("sections", {**c["sections"], "keep_rule": 1})),
        ("a win rate in prose",
         lambda c: c["expectations"].append("The primer reports roughly a 60% win rate.")),
        ("a Tier claim in prose",
         lambda c: c["expectations"].append("The primer places the deck in Tier 2.")),
        ("a simulation claim in prose",
         lambda c: c["expectations"].append("The primer simulated a hundred games.")),
        ("a matchup result in prose",
         lambda c: c["expectations"].append("The primer gives the matchup win record.")),
        ("a keep rule in prose",
         lambda c: c.__setitem__("notes", "The primer gives keep rules for the opening hand.")),
    ]
    for label, mutate in claim_cases:
        for base, where in ((primer, "a general-primer case"), (case, "an engine-closed case")):
            candidate = copy.deepcopy(base)
            mutate(candidate)
            problems = validate_case(candidate)
            if not problems:
                failures.append(f"{where} accepted {label}")
            elif not any("does not make" in p or "claim" in p for p in problems):
                failures.append(f"{where} refused {label}, but not as a claim: {problems}")

    # The ban must not fire on anything shipped, or it is too wide to use.
    for field in ("general_primer_cases", "engine_closed_cases"):
        for shipped in corpus[field]:
            if hits := forbidden_claims(shipped):
                failures.append(f"the claim ban fires on the shipped case "
                                f"{shipped.get('case_id')}: {hits}")
    if hits := forbidden_claims(case):
        failures.append(f"the claim ban fires on the synthetic engine-closed case: {hits}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across the Deck Coach corpus contract")
        return 1

    print(f"deck-coach-corpus.v1: {len(CASE_CLASSES)} case classes kept apart — "
          f"{len(corpus['general_primer_cases'])} general-primer cases shipped, "
          f"{len(corpus['engine_closed_cases'])} engine-closed (the real ones are overlay data)")
    print(f"closure bindings: {len(BINDING_FIELDS)}; damage tests: {len(damage)}, "
          f"each naming the binding that moved")
    print(f"engine-evidence keys barred from primers: {len(ENGINE_EVIDENCE_KEYS)}; "
          f"claims refused: {len(FORBIDDEN_CLAIM_KEYS)} fields, "
          f"{len(FORBIDDEN_CLAIM_PATTERNS)} text patterns, over both classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
