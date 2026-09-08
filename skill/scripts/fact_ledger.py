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

Neither is a source's status. Two checks read a ledger, and they are not the
same check:

  validate_ledger(ledger)              structural. Shape, markers re-derived
                                       from the text, verdict re-derived from
                                       the records, hash. It reads no context,
                                       so it cannot know whether a record that
                                       says "verified" is telling the truth.
  verify_ledger(ledger, ...context)    bound. Rebuilds the ledger from its own
                                       sentences against the engine checks,
                                       index, snapshots and assumption artifact
                                       handed to it now, and compares every
                                       derived field. A record's status is
                                       what the context says it is, never what
                                       the ledger wrote.

Only the second is fact-ledger verification. The first is what a ledger has to
pass to be read at all.

Sources that can change under a ledger are content-addressed. A card snapshot
record binds the snapshot's text hash; an assumption record binds the hash of
the state-assumption artifact together with the assumption entry it named; an
engine record binds the hash of the check as supplied. A snapshot rewritten
under the same id, an assumption whose value moved, or a check swapped in the
bundle under its own check_id each fail verification, because the ledger was
built on something that is no longer there.

An official-text record binds whatever the locator index can tell it. A bare
container or callable answers membership and nothing else, so the record
carries no binding and the module does not pretend to see text it cannot read.
A *retriever* — anything with a `retrieve(locator)` returning
`{"status", "record"}` — is asked instead, and a retrieved record's document
id, document version, locator and text hash are bound together. Then a source
whose document was revised under the same locator fails verification the same
way a rewritten card snapshot does. `not_found` is `locator_not_in_index`;
`conflict` and `superseded` are `source_not_retrievable`, which is a different
thing from absence and is named differently.

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
from typing import Any, Container, Iterable

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
    "source_not_retrievable",
})

SOURCE_STATUSES = frozenset({
    "verified", "malformed", "unknown_engine_check", "invalid_engine_check",
    "engine_check_did_not_decide", "locator_not_in_index", "unknown_card_snapshot",
    "unknown_assumption", "source_not_retrievable",
})

# What a retriever must return about one locator. `retrieved` is the only
# status that can back a claim; the rest say why the locator is not a source
# right now, which is not the same as saying it never was.
RETRIEVAL_STATUSES = frozenset({"retrieved", "not_found", "conflict", "superseded"})
RETRIEVAL_RECORD_FIELDS = {"document_id", "document_version", "locator", "text_hash"}

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


def _is_retriever(index: Any) -> bool:
    return hasattr(index, "retrieve") and callable(index.retrieve)


def _retrieve(index: Any, locator: str) -> tuple[str, str | None]:
    """Ask the locator index about one locator: the status it earns, and its binding."""
    if index is None:
        return "locator_not_in_index", None
    if _is_retriever(index):
        answer = index.retrieve(locator)
        if not isinstance(answer, dict) or answer.get("status") not in RETRIEVAL_STATUSES:
            raise FactLedgerError(
                f"a retriever must answer with a status in {sorted(RETRIEVAL_STATUSES)}")
        status = answer["status"]
        if status == "not_found":
            return "locator_not_in_index", None
        if status != "retrieved":
            return "source_not_retrievable", None
        record = answer.get("record")
        if not isinstance(record, dict) or set(record) != RETRIEVAL_RECORD_FIELDS or \
                not all(isinstance(record[f], str) and record[f] for f in RETRIEVAL_RECORD_FIELDS):
            raise FactLedgerError(
                f"a retrieved source must carry exactly {sorted(RETRIEVAL_RECORD_FIELDS)}")
        if record["locator"] != locator:
            raise FactLedgerError(
                f"the retriever answered about {record['locator']!r}, not {locator!r}")
        return "verified", canonical_hash(record)
    if callable(index):
        return ("verified" if index(locator) else "locator_not_in_index"), None
    if isinstance(index, Container):
        return ("verified" if locator in index else "locator_not_in_index"), None
    raise FactLedgerError("locator_index must be a container, a callable, or a retriever")


class _Context:
    """The four things a source can be checked against, indexed once."""

    def __init__(self, engine_checks: Iterable[Any], locator_index: Any,
                 card_snapshots: dict[str, Any] | None, assumption_artifact: Any) -> None:
        self.checks: dict[str, Any] = {}
        for check in engine_checks:
            if not isinstance(check, dict) or not isinstance(check.get("check_id"), str):
                raise FactLedgerError("every supplied engine check must carry a check_id")
            self.checks[check["check_id"]] = check
        self.index = locator_index
        self.snapshots = dict(card_snapshots or {})
        self.artifact_hash: str | None = None
        self.assumptions: dict[str, Any] = {}
        if isinstance(assumption_artifact, dict):
            self.artifact_hash = canonical_hash(assumption_artifact)
            for entry in assumption_artifact.get("assumptions", []):
                if isinstance(entry, dict) and isinstance(entry.get("slot"), str):
                    self.assumptions[entry["slot"]] = entry

    def check_source(self, kind: str, ref: str) -> tuple[str, str | None]:
        """The status a source earns now, and the hash the record binds to."""
        if kind == "engine":
            check = self.checks.get(ref)
            if check is None:
                return "unknown_engine_check", None
            if validate_engine_check(check):
                return "invalid_engine_check", None
            if check.get("outcome") not in DECIDING_OUTCOMES:
                return "engine_check_did_not_decide", None
            return "verified", canonical_hash(check)
        if kind == "official_text":
            return _retrieve(self.index, ref)
        if kind == "card_text":
            snapshot = self.snapshots.get(ref)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("text_hash"), str) \
                    or not snapshot["text_hash"]:
                return "unknown_card_snapshot", None
            return "verified", snapshot["text_hash"]
        entry = self.assumptions.get(ref)
        if entry is None or self.artifact_hash is None:
            return "unknown_assumption", None
        return "verified", canonical_hash({"artifact_hash": self.artifact_hash, "entry": entry})


_STATUS_TO_VIOLATION = {
    "unknown_engine_check": "unknown_engine_check",
    "invalid_engine_check": "invalid_engine_check",
    "engine_check_did_not_decide": "engine_check_did_not_decide",
    "locator_not_in_index": "locator_not_in_index",
    "unknown_card_snapshot": "unknown_card_snapshot",
    "unknown_assumption": "unknown_assumption",
    "source_not_retrievable": "source_not_retrievable",
}


def build_ledger(*, question: str, sentences: Iterable[Any], engine_checks: Iterable[Any] = (),
                 locator_index: Any = None, card_snapshots: dict[str, Any] | None = None,
                 assumption_artifact: Any = None) -> dict[str, Any]:
    """Check every sentence of an answer against what it claims to stand on."""
    if not isinstance(question, str) or not question.strip():
        raise FactLedgerError("question must be a non-empty string")
    sentences = list(sentences)
    context = _Context(engine_checks, locator_index, card_snapshots, assumption_artifact)

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

        source_records: list[dict[str, Any]] = []
        for source in sentence["sources"]:
            parsed = parse_source(source)
            if parsed is None:
                source_records.append({"kind": "", "ref": str(source), "status": "malformed", "bound_hash": None})
                if mechanical:
                    violations.append({
                        "entry": index, "code": "malformed_source",
                        "detail": f"{source!r} is not '<kind>:<ref>' over {list(SOURCE_KINDS)}",
                    })
                continue
            kind, ref = parsed
            status, bound = context.check_source(kind, ref)
            source_records.append({"kind": kind, "ref": ref, "status": status, "bound_hash": bound})
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
SOURCE_FIELDS = {"kind", "ref", "status", "bound_hash"}
VIOLATION_FIELDS = {"entry", "code", "detail"}


def validate_ledger(value: Any) -> list[str]:
    """Structural validation only: shape, markers re-derived, verdict re-derived, hash.

    This reads no context. It can tell that a ledger is internally consistent;
    it cannot tell whether a record marked "verified" was ever verified against
    anything. That is verify_ledger's job, and a ledger that only passed this
    check has not been verified.
    """
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
            if not isinstance(record, dict) or set(record) != SOURCE_FIELDS:
                errors.append(f"{s_label} must carry exactly {sorted(SOURCE_FIELDS)}")
                continue
            if record["status"] not in SOURCE_STATUSES:
                errors.append(f"{s_label}.status must be one of {sorted(SOURCE_STATUSES)}")
            if record["status"] != "malformed" and record["kind"] not in SOURCE_KINDS:
                errors.append(f"{s_label}.kind must be one of {list(SOURCE_KINDS)}")
            if record["bound_hash"] is not None and (not isinstance(record["bound_hash"], str) or not record["bound_hash"]):
                errors.append(f"{s_label}.bound_hash must be a hash or null")
            if record["status"] == "verified" and record["kind"] in {"engine", "card_text", "assumption"} \
                    and record["bound_hash"] is None:
                errors.append(f"{s_label} is a verified {record['kind']} source and must carry its binding")

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


def _sentences_of(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """The producer's input, read back out of a ledger's entries."""
    sentences = []
    for entry in ledger["entries"]:
        sources = []
        for record in entry["sources"]:
            sources.append(record["ref"] if record["status"] == "malformed" else f"{record['kind']}:{record['ref']}")
        sentences.append({"text": entry["text"], "mechanical": entry["declared_mechanical"], "sources": sources})
    return sentences


def verify_ledger(ledger: Any, engine_checks: Iterable[Any] = (), locator_index: Any = None,
                  card_snapshots: dict[str, Any] | None = None, assumption_artifact: Any = None) -> list[str]:
    """Fact-ledger verification: rebuild from the ledger's own sentences against this context, and compare.

    Nothing the ledger wrote about a source is believed. Its sentences and
    their declared sources are read back, a fresh ledger is built against the
    engine checks, index, snapshots and assumption artifact supplied now, and
    every derived field — each source's status and binding, the violations,
    admissibility, tier, the cited checks, the hash — is compared to what the
    ledger claims. A mismatch is named by field.
    """
    errors = validate_ledger(ledger)
    if errors:
        return [f"structural: {error}" for error in errors]

    rebuilt = build_ledger(question=ledger["question"], sentences=_sentences_of(ledger),
                           engine_checks=engine_checks, locator_index=locator_index,
                           card_snapshots=card_snapshots, assumption_artifact=assumption_artifact)

    for position, (claimed, actual) in enumerate(zip(ledger["entries"], rebuilt["entries"])):
        for s_index, (c_rec, a_rec) in enumerate(zip(claimed["sources"], actual["sources"])):
            label = f"entries[{position}].sources[{s_index}] ({c_rec['kind']}:{c_rec['ref']})"
            if c_rec["status"] != a_rec["status"]:
                errors.append(f"{label} claims status {c_rec['status']!r}; against this context it is {a_rec['status']!r}")
            elif c_rec["bound_hash"] != a_rec["bound_hash"]:
                errors.append(f"{label} is bound to content that is no longer what the context holds")
        if claimed["mechanical"] != actual["mechanical"]:
            errors.append(f"entries[{position}].mechanical claims {claimed['mechanical']}, rebuilt as {actual['mechanical']}")

    claimed_codes = [(v["entry"], v["code"]) for v in ledger["violations"]]
    actual_codes = [(v["entry"], v["code"]) for v in rebuilt["violations"]]
    if claimed_codes != actual_codes:
        errors.append(f"violations claimed {claimed_codes}; rebuilt {actual_codes}")
    if ledger["admissible"] != rebuilt["admissible"]:
        errors.append(f"admissible claims {ledger['admissible']}; rebuilt {rebuilt['admissible']}")
    if ledger["admissible_tier"] != rebuilt["admissible_tier"]:
        errors.append(f"admissible_tier claims {ledger['admissible_tier']!r}; rebuilt {rebuilt['admissible_tier']!r}")
    if ledger["cited_engine_checks"] != rebuilt["cited_engine_checks"]:
        errors.append(f"cited_engine_checks claims {ledger['cited_engine_checks']}; rebuilt {rebuilt['cited_engine_checks']}")
    if ledger["ledger_hash"] != rebuilt["ledger_hash"]:
        errors.append("ledger_hash differs from the hash of the ledger rebuilt against this context")
    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _add_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine-checks", help="path to an array of engine-check.v1 artifacts")
    parser.add_argument("--index", help="path to a JSON array of admissible locators")
    parser.add_argument("--card-snapshots", help="path to a snapshot map")
    parser.add_argument("--assumptions", help="path to a state-assumption.v1 artifact")


def _context_from(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "engine_checks": _load(args.engine_checks) if args.engine_checks else (),
        "locator_index": set(_load(args.index)) if args.index else None,
        "card_snapshots": _load(args.card_snapshots) if args.card_snapshots else None,
        "assumption_artifact": _load(args.assumptions) if args.assumptions else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build, validate, or verify a fact-ledger.v1.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="check an answer's sentences against their sources")
    build.add_argument("--question", required=True)
    build.add_argument("--sentences", required=True, help="path to the tagged sentences")
    _add_context_arguments(build)

    check = sub.add_parser("validate", help="structural validation only; this is not verification")
    check.add_argument("ledger")

    verify = sub.add_parser("verify", help="fact-ledger verification: rebuild against the given context and compare")
    verify.add_argument("ledger")
    _add_context_arguments(verify)

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
        print("structurally valid (not verified)" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1
    if args.command == "verify":
        problems = verify_ledger(_load(args.ledger), **_context_from(args))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("verified against the given context" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    ledger = build_ledger(question=args.question, sentences=_load(args.sentences), **_context_from(args))
    json.dump(ledger, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if ledger["admissible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
