#!/usr/bin/env python3
"""The Deck Coach regression corpus contract: two claims, kept apart.

The coach makes two different claims about two different things, and the whole
point of this corpus is that they never get filed together.

  general_primer   Any decklist gets a structural and strategic primer. This
                   claim is about shape and plan. It carries no engine
                   evidence, and a case in this class may not carry an engine
                   evidence field anywhere inside it — not in a binding, not in
                   a note, not in an expectation. The check is a deep scan, not
                   a top-level field list, because the cheap way to break this
                   rule is to bury the field one level down.

  engine_closed    Only a deck whose every slot carries an active program and
                   an evidence receipt. The case binds the closure: its deck,
                   its input hash, its engine identity, its grammar version,
                   the hash of the closure itself, and the per-card program and
                   receipt hashes. `verify_case` re-derives all of that from a
                   closure handed to it now, so a case survives exactly as long
                   as the closure it was written against.

What neither class may claim
----------------------------
Win rate, Tier, keep rules, matchup or simulation results. Those are not weak
claims the coach makes carefully; they are claims it does not make, and a
corpus that admits one has moved the product's boundary by writing a fixture.
The ban is enforced twice: as a field name, and as a lexical scan over every
string in the case, because a field ban alone is escaped by writing "about a
60% win rate" into a note.

Two checks, as everywhere else here
-----------------------------------
  validate_case(case)              structural. Shape, class rules, the claim
                                   ban. Reads no closure.
  verify_case(case, closure=...)   bound. Re-derives every hash the case binds
                                   from the closure supplied now.

The public repository carries this contract, its validator, and synthetic
cases. The engine-closed cases for real decks live in the licensed overlay
along with the closures they bind, and are not part of a public clone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from engine_check import canonical_hash


SCHEMA_VERSION = "deck-coach-corpus.v1"

CASE_CLASSES = ("general_primer", "engine_closed")

COMMON_FIELDS = {"case_id", "case_class", "deck_id", "sections", "expectations", "notes"}
GENERAL_FIELDS = COMMON_FIELDS
CLOSED_FIELDS = COMMON_FIELDS | {"closure_binding"}

BINDING_FIELDS = {"deck", "deck_input_hash", "closure_hash", "engine", "grammar_version",
                  "all_slots_ready", "program_hashes", "receipt_hashes"}

# Evidence a general-primer case may not carry, at any depth. These are the
# keys the closure and the engine-check artifacts use; seeing one inside a
# primer case means the case is claiming something the primer does not.
ENGINE_EVIDENCE_KEYS = frozenset({
    "closure_binding", "closure_hash", "deck_input_hash", "program_hashes",
    "receipt_hashes", "engine_check", "engine_checks", "evidence_pack",
    "capability_set_id", "implementation_identity", "grammar_version",
    "all_slots_ready", "program_hash", "receipt_hash",
})

# Claims the coach does not make. Banned as field names ...
FORBIDDEN_CLAIM_KEYS = frozenset({
    "win_rate", "winrate", "win_percentage", "tier", "tier_list", "keep_rule",
    "keep_rules", "mulligan_rule", "matchup", "matchups", "matchup_win_rate",
    "meta_share", "placement", "simulated_games", "simulation", "ladder_rank",
})

# ... and as text, because a field ban alone is escaped by prose.
FORBIDDEN_CLAIM_PATTERNS = (
    ("win rate", re.compile(r"(?<!\w)win\s?rates?(?!\w)")),
    ("win percentage", re.compile(r"(?<!\w)wins?\s+\d{1,3}\s?%|(?<!\w)\d{1,3}\s?%\s+of\s+games(?!\w)")),
    ("tier placement", re.compile(r"(?<!\w)tier\s+(?:list|[0-9]|s|a|b|c|d)(?!\w)")),
    ("keep rule", re.compile(r"(?<!\w)keep\s+rules?(?!\w)")),
    ("matchup result", re.compile(r"(?<!\w)matchups?\s+(?:win|loss|record|result)")),
    ("simulation", re.compile(r"(?<!\w)simulat(?:e|ed|es|ion|ions)(?!\w)")),
    ("meta share", re.compile(r"(?<!\w)meta\s+share(?!\w)")),
)


class DeckCoachCorpusError(ValueError):
    pass


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _walk(value: Any, path: str = "$"):
    """Every (path, key, value) in a nested structure, keys included."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", key, child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield f"{path}[{index}]", None, child
            yield from _walk(child, f"{path}[{index}]")


def forbidden_claims(case: Any) -> list[str]:
    """Every place this case makes a claim the coach does not make."""
    hits: list[str] = []
    for path, key, child in _walk(case):
        if key is not None and key.casefold() in FORBIDDEN_CLAIM_KEYS:
            hits.append(f"{path}: {key!r} is a claim the coach does not make")
        if isinstance(child, str):
            folded = child.casefold()
            for label, pattern in FORBIDDEN_CLAIM_PATTERNS:
                if pattern.search(folded):
                    hits.append(f"{path}: the text makes a {label} claim")
    return hits


def engine_evidence_in(case: Any) -> list[str]:
    return [f"{path}: {key!r}" for path, key, _ in _walk(case)
            if key is not None and key in ENGINE_EVIDENCE_KEYS]


def program_hashes_of(closure: dict[str, Any]) -> dict[str, str]:
    """The per-card program hashes a closure carries, derived rather than read."""
    return {slot["card"]: slot["program_hash"]
            for slot in closure.get("slots", []) if slot.get("ready")}


def receipt_hashes_of(closure: dict[str, Any]) -> dict[str, str]:
    return {slot["card"]: slot["receipt_hash"]
            for slot in closure.get("slots", []) if slot.get("ready")}


def binding_for(closure: dict[str, Any]) -> dict[str, Any]:
    """The binding a case must carry to name this closure."""
    return {
        "deck": closure["deck"],
        "deck_input_hash": closure["deck_input_hash"],
        "closure_hash": canonical_hash(closure),
        "engine": dict(closure["engine"]),
        "grammar_version": closure["grammar_version"],
        "all_slots_ready": closure["all_slots_ready"],
        "program_hashes": program_hashes_of(closure),
        "receipt_hashes": receipt_hashes_of(closure),
    }


def validate_case(case: Any) -> list[str]:
    """Structural validation: shape, class rules, the claim ban. Reads no closure."""
    errors: list[str] = []
    if not isinstance(case, dict):
        return ["a case must be a JSON object"]
    case_class = case.get("case_class")
    if case_class not in CASE_CLASSES:
        return [f"case_class must be one of {list(CASE_CLASSES)}"]

    expected = GENERAL_FIELDS if case_class == "general_primer" else CLOSED_FIELDS
    if missing := expected - set(case):
        errors.append(f"missing fields: {sorted(missing)}")
    if unknown := set(case) - expected:
        errors.append(f"unknown fields: {sorted(unknown)}")
    if missing:
        return errors

    label = case["case_id"] if _nonempty(case["case_id"]) else "<unnamed>"
    for field in ("case_id", "deck_id"):
        if not _nonempty(case[field]):
            errors.append(f"{label}: {field} must be a non-empty string")
    sections = case["sections"]
    if not isinstance(sections, dict) or not sections or \
            any(not _nonempty(k) or not isinstance(v, int) or isinstance(v, bool) or v < 0
                for k, v in sections.items()):
        errors.append(f"{label}: sections must map section names to non-negative counts")
    expectations = case["expectations"]
    if not isinstance(expectations, list) or not expectations or \
            any(not _nonempty(v) for v in expectations):
        errors.append(f"{label}: expectations must be a non-empty array of non-empty strings")
    if case["notes"] is not None and not _nonempty(case["notes"]):
        errors.append(f"{label}: notes must be null or a non-empty string")

    # Neither class may make these claims.
    errors.extend(f"{label}: {hit}" for hit in forbidden_claims(case))

    if case_class == "general_primer":
        # The deep scan, not the field list: burying the field one level down
        # is the cheap way to break this rule.
        for hit in engine_evidence_in(case):
            errors.append(f"{label}: a general-primer case carries engine evidence at {hit}; "
                          f"this class claims structure and plan, not coverage")
        return errors

    binding = case["closure_binding"]
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
        errors.append(f"{label}: closure_binding must carry exactly {sorted(BINDING_FIELDS)}")
        return errors
    for field in ("deck", "deck_input_hash", "closure_hash", "grammar_version"):
        if not _nonempty(binding[field]):
            errors.append(f"{label}: closure_binding.{field} must be a non-empty string")
    if not isinstance(binding["engine"], dict) or not binding["engine"]:
        errors.append(f"{label}: closure_binding.engine must carry the engine identity")
    if not isinstance(binding["all_slots_ready"], bool):
        errors.append(f"{label}: closure_binding.all_slots_ready must be boolean")
    if binding["all_slots_ready"] is not True:
        errors.append(f"{label}: an engine-closed case binds a closure whose every slot is "
                      f"ready; a deck that is not closed is a general-primer case")
    for field in ("program_hashes", "receipt_hashes"):
        table = binding[field]
        if not isinstance(table, dict) or not table or \
                any(not _nonempty(k) or not _nonempty(v) for k, v in table.items()):
            errors.append(f"{label}: closure_binding.{field} must map cards to hashes")
    if isinstance(binding["program_hashes"], dict) and isinstance(binding["receipt_hashes"], dict) \
            and set(binding["program_hashes"]) != set(binding["receipt_hashes"]):
        errors.append(f"{label}: every bound card carries both a program hash and a receipt hash")
    return errors


def verify_case(case: Any, *, closure: Any) -> list[str]:
    """Bound verification: re-derive everything the case binds from this closure."""
    errors = validate_case(case)
    if errors:
        return [f"structural: {error}" for error in errors]
    if case["case_class"] != "engine_closed":
        return ["only an engine-closed case binds a closure"]
    if not isinstance(closure, dict):
        return ["a closure is required to verify an engine-closed case"]

    claimed = case["closure_binding"]
    actual = binding_for(closure)
    for field in sorted(BINDING_FIELDS):
        if claimed[field] != actual[field]:
            errors.append(f"closure_binding.{field} claims {claimed[field]!r}; "
                          f"this closure gives {actual[field]!r}")
    return errors


REQUIRED_TOP = {"schema_version", "corpus_id", "description", "general_primer_cases",
                "engine_closed_cases"}


def validate_corpus(corpus: Any) -> list[str]:
    """Check the envelope and both case classes, which are stored apart."""
    errors: list[str] = []
    if not isinstance(corpus, dict):
        return ["corpus must be a JSON object"]
    if missing := REQUIRED_TOP - set(corpus):
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown := set(corpus) - REQUIRED_TOP:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    if missing:
        return errors
    if corpus["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    for field in ("corpus_id", "description"):
        if not _nonempty(corpus[field]):
            errors.append(f"{field} must be a non-empty string")

    seen: set[str] = set()
    for field, expected_class in (("general_primer_cases", "general_primer"),
                                  ("engine_closed_cases", "engine_closed")):
        cases = corpus[field]
        if not isinstance(cases, list):
            errors.append(f"{field} must be an array")
            continue
        for index, case in enumerate(cases):
            where = f"{field}[{index}]"
            if isinstance(case, dict) and case.get("case_class") != expected_class:
                # The two classes are stored apart so that a case cannot be
                # verified under the rules of the other one.
                errors.append(f"{where}: a {expected_class} case belongs in {field}, "
                              f"and this one says {case.get('case_class')!r}")
                continue
            errors.extend(f"{where}: {e}" for e in validate_case(case))
            if isinstance(case, dict) and _nonempty(case.get("case_id")):
                if case["case_id"] in seen:
                    errors.append(f"{where}: case_id is used more than once")
                seen.add(case["case_id"])
    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or verify a Deck Coach regression corpus.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("validate", help="structural validation; this is not verification")
    check.add_argument("corpus")

    verify = sub.add_parser("verify", help="verify one engine-closed case against a closure")
    verify.add_argument("case")
    verify.add_argument("--closure", required=True)

    sub.add_parser("contract", help="print the two classes and what neither may claim")
    args = parser.parse_args(argv)

    if args.command == "contract":
        json.dump({"schema_version": SCHEMA_VERSION, "case_classes": list(CASE_CLASSES),
                   "closure_binding_fields": sorted(BINDING_FIELDS),
                   "engine_evidence_keys_barred_from_primers": sorted(ENGINE_EVIDENCE_KEYS),
                   "claims_the_coach_does_not_make": {
                       "fields": sorted(FORBIDDEN_CLAIM_KEYS),
                       "text": [label for label, _ in FORBIDDEN_CLAIM_PATTERNS]}},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    if args.command == "verify":
        problems = verify_case(_load(args.case), closure=_load(args.closure))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("verified against that closure" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    problems = validate_corpus(_load(args.corpus))
    for problem in problems:
        print(problem, file=sys.stderr)
    print("structurally valid (not verified)" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
