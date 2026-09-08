#!/usr/bin/env python3
"""Make every mechanical claim in an answer point at what it stands on.

An answer reaches this module as a list of sentences, each tagged mechanical or
not and each carrying its sources. Four source kinds are admissible and no
others:

    engine:<check_id>        a verified engine-check.v1 that actually decided
    official_text:<locator>  a locator that hits the rules index
    card_text:<snapshot>     a card text snapshot that is present and hashed
    assumption:<slot>        an assumption the state-assumption artifact carries

A mechanical sentence with no admissible source does not cost that sentence its
backing — it costs the whole answer its tier. That is what "no D layer" means
mechanically: an answer that is nine-tenths sourced reads exactly as
authoritative as one that is fully sourced, so the tenth part has to be able to
stop the whole thing.

The tagging is not taken on trust. A producer that wanted to escape the ledger
would simply mark its conclusions non-mechanical, so the marker vocabulary is
re-derived from the sentence text here and in the validator: a sentence a
marker fires on cannot be tagged non-mechanical, whoever wrote the ledger.

The marker set errs toward firing. A marker that fires on an ordinary sentence
costs one source, which is cheap; a marker that fails to fire on a real
conclusion is the failure this set exists to prevent. So it is added to, and
trimmed only with a case — the fixtures hold every marker that any labelled
conclusion depends on, and the gate fails if one stops firing.

What this module does not solve, and does not pretend to: two claims written
into one sentence share one set of sources. Splitting prose into claims is not
something a lexical rule can do honestly. What it does do is refuse an entry
that is visibly more than one sentence, which closes the cheap version of that.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Container, Iterable

from engine_check import canonical_hash, validate_engine_check
import rules_core


SCHEMA_VERSION = "fact-ledger.v1"
CORE_RULESET = rules_core.CORE_RULESET
FAQ_AS_OF = rules_core.FAQ_AS_OF

SOURCE_KINDS = ("engine", "official_text", "card_text", "assumption")

# An engine check that reached a verdict. The other three engine-check outcomes
# — unsupported, decision_required, invalid_input — are the engine declining to
# rule, and a declined ruling cited as the basis of a conclusion is the exact
# shape of an answer that sounds engine-backed and is not.
DECIDING_OUTCOMES = frozenset({"supported", "illegal"})

TIERS = ("A", "B", "C")

VIOLATION_CODES = frozenset({
    "untagged_mechanical_sentence",
    "multi_sentence_entry",
    "unsourced_conclusion",
    "malformed_source",
    "unknown_engine_check",
    "invalid_engine_check",
    "engine_check_did_not_decide",
    "locator_not_in_index",
    "unknown_card_snapshot",
    "unknown_assumption",
})

SOURCE_STATUSES = frozenset({
    "verified", "malformed", "unknown_engine_check", "invalid_engine_check",
    "engine_check_did_not_decide", "locator_not_in_index", "unknown_card_snapshot",
    "unknown_assumption",
})

# Lexical markers of a mechanical claim. Phrases are matched on word
# boundaries over the casefolded sentence.
MECHANICAL_MARKERS: tuple[str, ...] = (
    # legality and obligation
    "must", "must not", "cannot", "can not", "can't", "may", "may not",
    "is legal", "is not legal", "is illegal", "illegal", "is allowed",
    "is not allowed", "is required", "is optional", "you can", "you may",
    "is able to", "has to", "have to",
    # what happens. Both the base form and the inflected one: a marker set
    # that reads "draws" and not "draw" misses "you draw a card", which is a
    # conclusion in every sense that matters.
    "resolve", "resolves", "does not resolve", "counter", "counters",
    "is countered", "trigger", "triggers", "does not trigger",
    "destroy", "destroys", "destroyed", "die", "dies", "kill", "kills",
    "killed", "survive", "survives", "banish", "banishes", "banished",
    "stun", "stuns", "stunned", "exhaust", "exhausts", "exhausted",
    "ready", "readies", "readied", "take damage", "takes damage",
    "deal damage", "deals damage", "draw", "draws", "discard", "discards",
    "win", "wins", "lose", "loses", "is put", "put into", "go to", "goes to",
    "return to", "returns to", "enter", "enters", "leave", "leaves",
    # priority, focus, and the chain
    "priority", "focus", "pass", "passes", "the chain",
    # values
    "become", "becomes", "is set to", "is reduced", "is increased",
    "remain", "remains", "is treated as", "count as", "counts as",
)

_MARKER_PATTERNS = tuple(
    (marker, re.compile(r"(?<!\w)" + re.escape(marker).replace(r"\ ", r"\s+") + r"(?!\w)"))
    for marker in MECHANICAL_MARKERS
)

# A period, question mark, or exclamation mark followed by whitespace and more
# words. "3.1" and "Core 312." do not match; "It resolves. You draw." does.
_MULTI_SENTENCE = re.compile(r"[.!?][\"')\]]?\s+(?=[A-Z(\"'])")


class FactLedgerError(ValueError):
    pass


def markers_in(text: str) -> list[str]:
    """Every mechanical marker the sentence fires, in vocabulary order."""
    if not isinstance(text, str):
        return []
    folded = text.casefold()
    return [marker for marker, pattern in _MARKER_PATTERNS if pattern.search(folded)]


def is_multi_sentence(text: str) -> bool:
    return bool(isinstance(text, str) and _MULTI_SENTENCE.search(text.strip()))


def parse_source(source: Any) -> tuple[str, str] | None:
    """Split "<kind>:<ref>" into its parts, or None if it is not one."""
    if not isinstance(source, str) or ":" not in source:
        return None
    kind, ref = source.split(":", 1)
    if kind not in SOURCE_KINDS or not ref.strip():
        return None
    return kind, ref.strip()


def _index_contains(index: Any, locator: str) -> bool:
    if index is None:
        return False
    if callable(index):
        return bool(index(locator))
    if isinstance(index, Container):
        return locator in index
    raise FactLedgerError("locator_index must be a container or a callable")


def _assumption_slots(artifact: Any) -> set[str]:
    if not isinstance(artifact, dict):
        return set()
    return {entry["slot"] for entry in artifact.get("assumptions", [])
            if isinstance(entry, dict) and isinstance(entry.get("slot"), str)}


def _check_source(kind: str, ref: str, *, engine_checks: dict[str, Any],
                  locator_index: Any, card_snapshots: dict[str, Any],
                  assumption_slots: set[str]) -> str:
    if kind == "engine":
        check = engine_checks.get(ref)
        if check is None:
            return "unknown_engine_check"
        if validate_engine_check(check):
            return "invalid_engine_check"
        if check.get("outcome") not in DECIDING_OUTCOMES:
            return "engine_check_did_not_decide"
        return "verified"
    if kind == "official_text":
        return "verified" if _index_contains(locator_index, ref) else "locator_not_in_index"
    if kind == "card_text":
        snapshot = card_snapshots.get(ref)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("text_hash"), str) or not snapshot["text_hash"]:
            return "unknown_card_snapshot"
        return "verified"
    return "verified" if ref in assumption_slots else "unknown_assumption"


_STATUS_TO_VIOLATION = {
    "unknown_engine_check": "unknown_engine_check",
    "invalid_engine_check": "invalid_engine_check",
    "engine_check_did_not_decide": "engine_check_did_not_decide",
    "locator_not_in_index": "locator_not_in_index",
    "unknown_card_snapshot": "unknown_card_snapshot",
    "unknown_assumption": "unknown_assumption",
}


def build_ledger(*, question: str, sentences: Iterable[Any], engine_checks: Iterable[Any] = (),
                 locator_index: Any = None, card_snapshots: dict[str, Any] | None = None,
                 assumption_artifact: Any = None) -> dict[str, Any]:
    """Check every sentence of an answer against what it claims to stand on."""
    if not isinstance(question, str) or not question.strip():
        raise FactLedgerError("question must be a non-empty string")
    sentences = list(sentences)
    checks_by_id: dict[str, Any] = {}
    for check in engine_checks:
        if not isinstance(check, dict) or not isinstance(check.get("check_id"), str):
            raise FactLedgerError("every supplied engine check must carry a check_id")
        checks_by_id[check["check_id"]] = check
    card_snapshots = dict(card_snapshots or {})
    assumption_slots = _assumption_slots(assumption_artifact)

    entries: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    cited_engine_ids: list[str] = []

    for index, sentence in enumerate(sentences):
        if not isinstance(sentence, dict) or set(sentence) - {"text", "mechanical", "sources"} or \
                {"text", "mechanical", "sources"} - set(sentence):
            raise FactLedgerError(f"sentences[{index}] must carry exactly text, mechanical, sources")
        text = sentence["text"]
        if not isinstance(text, str) or not text.strip():
            raise FactLedgerError(f"sentences[{index}].text must be a non-empty string")
        if not isinstance(sentence["mechanical"], bool):
            raise FactLedgerError(f"sentences[{index}].mechanical must be boolean")
        if not isinstance(sentence["sources"], list):
            raise FactLedgerError(f"sentences[{index}].sources must be an array")

        markers = markers_in(text)
        declared = sentence["mechanical"]
        # Over-tagging is allowed: a producer may call an ordinary sentence
        # mechanical and pay for it with a source. Under-tagging is not.
        mechanical = declared or bool(markers)
        if markers and not declared:
            violations.append({
                "entry": index, "code": "untagged_mechanical_sentence",
                "detail": f"the sentence fires the mechanical markers {markers} but was tagged non-mechanical",
            })
        if is_multi_sentence(text):
            violations.append({
                "entry": index, "code": "multi_sentence_entry",
                "detail": "an entry is one sentence; several claims in one entry would share one set of sources",
            })

        source_records: list[dict[str, str]] = []
        for source in sentence["sources"]:
            parsed = parse_source(source)
            if parsed is None:
                source_records.append({"kind": "", "ref": str(source), "status": "malformed"})
                if mechanical:
                    violations.append({
                        "entry": index, "code": "malformed_source",
                        "detail": f"{source!r} is not '<kind>:<ref>' over {list(SOURCE_KINDS)}",
                    })
                continue
            kind, ref = parsed
            status = _check_source(kind, ref, engine_checks=checks_by_id, locator_index=locator_index,
                                   card_snapshots=card_snapshots, assumption_slots=assumption_slots)
            source_records.append({"kind": kind, "ref": ref, "status": status})
            if status == "verified" and kind == "engine":
                cited_engine_ids.append(ref)
            elif status != "verified" and mechanical:
                violations.append({
                    "entry": index, "code": _STATUS_TO_VIOLATION[status],
                    "detail": f"{kind}:{ref} is not an admissible source ({status})",
                })

        if mechanical and not any(record["status"] == "verified" for record in source_records):
            violations.append({
                "entry": index, "code": "unsourced_conclusion",
                "detail": "a mechanical conclusion with no admissible source; the answer cannot stand on it",
            })

        entries.append({
            "index": index, "text": text, "mechanical": mechanical,
            "declared_mechanical": declared, "markers": markers, "sources": source_records,
        })

    tier = verdict_tier(entries, violations)
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "question": question,
        "admissible": not violations,
        "admissible_tier": tier,
        "entries": entries,
        "violations": violations,
        "cited_engine_checks": sorted(set(cited_engine_ids)),
    }
    ledger["ledger_hash"] = canonical_hash({k: v for k, v in ledger.items() if k != "ledger_hash"})
    return ledger


def verdict_tier(entries: list[dict[str, Any]], violations: list[dict[str, Any]]) -> str:
    """A on a clean ledger that cites the engine, B on a clean one that does not, C otherwise.

    C is not "a worse A". It is the explicit abstention: the answer does not go
    out as a mechanical claim at all.
    """
    if violations:
        return "C"
    for entry in entries:
        if entry["mechanical"] and any(r["kind"] == "engine" and r["status"] == "verified" for r in entry["sources"]):
            return "A"
    return "B"


REQUIRED_TOP = {"schema_version", "ruleset", "question", "admissible", "admissible_tier",
                "entries", "violations", "cited_engine_checks", "ledger_hash"}
ENTRY_FIELDS = {"index", "text", "mechanical", "declared_mechanical", "markers", "sources"}
VIOLATION_FIELDS = {"entry", "code", "detail"}


def validate_ledger(value: Any) -> list[str]:
    """Check a ledger, re-deriving the markers rather than believing them."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["ledger must be a JSON object"]
    if missing := REQUIRED_TOP - set(value):
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown := set(value) - REQUIRED_TOP:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    if missing:
        return errors

    if value["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if value["ruleset"] != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("ruleset must match the kernel baseline")
    if not isinstance(value["question"], str) or not value["question"].strip():
        errors.append("question must be a non-empty string")
    if not isinstance(value["admissible"], bool):
        errors.append("admissible must be boolean")
    if value["admissible_tier"] not in TIERS:
        errors.append(f"admissible_tier must be one of {list(TIERS)}")

    entries = value["entries"]
    if not isinstance(entries, list):
        errors.append("entries must be an array")
        return errors
    for position, entry in enumerate(entries):
        label = f"entries[{position}]"
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            errors.append(f"{label} must carry exactly {sorted(ENTRY_FIELDS)}")
            continue
        if entry["index"] != position:
            errors.append(f"{label}.index must be {position}")
        if not isinstance(entry["text"], str) or not entry["text"].strip():
            errors.append(f"{label}.text must be a non-empty string")
            continue
        for field in ("mechanical", "declared_mechanical"):
            if not isinstance(entry[field], bool):
                errors.append(f"{label}.{field} must be boolean")
        # The claim that this sentence carries no mechanical marker is checked
        # against the sentence, not accepted from the ledger.
        expected = markers_in(entry["text"])
        if entry["markers"] != expected:
            errors.append(f"{label}.markers is {entry['markers']}, but the sentence fires {expected}")
        if expected and entry.get("declared_mechanical") is False and entry.get("mechanical") is not True:
            errors.append(f"{label} fires markers and cannot be treated as non-mechanical")
        if entry.get("mechanical") is False and entry.get("declared_mechanical") is True:
            errors.append(f"{label} was declared mechanical, so it stays mechanical")
        if not isinstance(entry["sources"], list):
            errors.append(f"{label}.sources must be an array")
            continue
        for s_index, record in enumerate(entry["sources"]):
            s_label = f"{label}.sources[{s_index}]"
            if not isinstance(record, dict) or set(record) != {"kind", "ref", "status"}:
                errors.append(f"{s_label} must carry kind, ref, status")
                continue
            if record["status"] not in SOURCE_STATUSES:
                errors.append(f"{s_label}.status must be one of {sorted(SOURCE_STATUSES)}")
            if record["status"] != "malformed" and record["kind"] not in SOURCE_KINDS:
                errors.append(f"{s_label}.kind must be one of {list(SOURCE_KINDS)}")

    violations = value["violations"]
    if not isinstance(violations, list):
        errors.append("violations must be an array")
        return errors
    for position, violation in enumerate(violations):
        label = f"violations[{position}]"
        if not isinstance(violation, dict) or set(violation) != VIOLATION_FIELDS:
            errors.append(f"{label} must carry exactly {sorted(VIOLATION_FIELDS)}")
            continue
        if violation["code"] not in VIOLATION_CODES:
            errors.append(f"{label}.code must be one of {sorted(VIOLATION_CODES)}")
        if not isinstance(violation["entry"], int) or not 0 <= violation["entry"] < len(entries):
            errors.append(f"{label}.entry must index an entry")
        if not isinstance(violation["detail"], str) or not violation["detail"].strip():
            errors.append(f"{label}.detail must say what is wrong")

    # The verdict is re-derived. A ledger cannot carry violations and an
    # admissible tier, nor claim A without a verified engine citation.
    if errors:
        return errors
    if value["admissible"] is not (not violations):
        errors.append("admissible is true exactly when there are no violations")
    expected_tier = verdict_tier(entries, violations)
    if value["admissible_tier"] != expected_tier:
        errors.append(f"admissible_tier is {value['admissible_tier']!r} but this ledger earns {expected_tier!r}")
    cited = sorted({r["ref"] for entry in entries for r in entry["sources"]
                    if r["kind"] == "engine" and r["status"] == "verified"})
    if value["cited_engine_checks"] != cited:
        errors.append(f"cited_engine_checks is {value['cited_engine_checks']}, expected {cited}")
    expected_hash = canonical_hash({k: v for k, v in value.items() if k != "ledger_hash"})
    if value["ledger_hash"] != expected_hash:
        errors.append("ledger_hash is not the hash of this ledger")
    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate a fact-ledger.v1.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="check an answer's sentences against their sources")
    build.add_argument("--question", required=True)
    build.add_argument("--sentences", required=True, help="path to the tagged sentences")
    build.add_argument("--engine-checks", help="path to an array of engine-check.v1 artifacts")
    build.add_argument("--index", help="path to a JSON array of admissible locators")
    build.add_argument("--card-snapshots", help="path to a snapshot map")
    build.add_argument("--assumptions", help="path to a state-assumption.v1 artifact")

    check = sub.add_parser("validate", help="validate a ledger, re-deriving its markers")
    check.add_argument("ledger")

    markers = sub.add_parser("markers", help="show which markers a sentence fires")
    markers.add_argument("text")

    args = parser.parse_args(argv)
    if args.command == "markers":
        found = markers_in(args.text)
        print(json.dumps({"text": args.text, "markers": found, "mechanical": bool(found)},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        problems = validate_ledger(_load(args.ledger))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("valid" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    ledger = build_ledger(
        question=args.question,
        sentences=_load(args.sentences),
        engine_checks=_load(args.engine_checks) if args.engine_checks else (),
        locator_index=set(_load(args.index)) if args.index else None,
        card_snapshots=_load(args.card_snapshots) if args.card_snapshots else None,
        assumption_artifact=_load(args.assumptions) if args.assumptions else None,
    )
    json.dump(ledger, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if ledger["admissible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
