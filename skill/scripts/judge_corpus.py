#!/usr/bin/env python3
"""The judge corpus contract: what a question must carry before it counts.

This module is the specification and its validator. It is not the sixty
questions, and it says so in the only way that means anything — the coverage
report it produces reads `complete: false` until the quotas are met, per
family, with the shortfall named. A corpus cannot be declared finished by
asserting that it is.

What a question owes
--------------------
Its family, from the seven the v0 baseline drew from what players actually ask.
Its expected tier, A, B or C. Then, depending on the tier:

  A and B   locators. An answer that cites the rules is checkable; one that
            does not is an opinion with a citation-shaped hole in it.
  C         an abstention contract: which named reason the service is expected
            to abstain with. "It should decline" is not a test — two different
            failures both decline, and only one of them is the right answer.

The abstention vocabulary is not written here. It is imported from the modules
that actually produce abstentions — the state builder's downgrades, the fact
ledger's violations, the consultation command's not-attempted reasons — so a C
question cannot name an outcome the pipeline has no way to reach, and a
vocabulary that changes upstream breaks the corpus rather than silently
outliving it.

The one exception is the tournament-policy family. Those questions abstain
because the project decided not to answer them, not because a mechanism ran
out; that abstention is a policy, so it is named here, where the policy is
visible, rather than borrowed from a module that never made it.

Quotas
------
Sixty questions across seven families, and the split is part of the contract
rather than an afterthought: a corpus where fifty questions are timing and ten
are everything else would pass any per-question check and would still tell us
almost nothing about the families it skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import fact_ledger
import rule_consult_command
import state_builder


SCHEMA_VERSION = "judge-corpus.v1"

# The abstention reasons the pipeline can actually reach, taken from the
# modules that reach them. Importing rather than restating is the point: a
# corpus that names a reason no longer produced should fail, not survive.
PIPELINE_ABSTENTIONS = frozenset(
    set(state_builder.DOWNGRADE_REASONS)
    | set(fact_ledger.VIOLATION_CODES)
    | set(rule_consult_command.NOT_ATTEMPTED_REASONS)
)

# The one abstention that is a decision rather than a mechanism. Tournament
# procedure and penalties are a policy red line: the service declines because
# it should not answer, not because something ran out.
POLICY_ABSTENTIONS = frozenset({"tournament_policy_red_line"})

ABSTENTION_CONTRACTS = PIPELINE_ABSTENTIONS | POLICY_ABSTENTIONS

TIERS = ("A", "B", "C")

# The seven families, their share of the sixty, and the tiers each may expect.
# `tiers` is not decoration: a tournament-policy question that expects an
# engine ruling is a question about a different service.
FAMILIES: dict[str, dict[str, Any]] = {
    "timing_priority_chain": {
        "quota": 12, "tiers": ("A", "B", "C"),
        "scope": "Timing, Priority, Focus, the chain, HOT and FEPR.",
    },
    "combat": {
        "quota": 10, "tiers": ("A", "B", "C"),
        "scope": "Assignment, Tank and Backline, Deal, result, closing. "
                 "Combat start and end effects sit at the boundary and expect B.",
    },
    "control_scoring": {
        "quota": 8, "tiers": ("A", "B", "C"),
        "scope": "Control, Conquer, Hold, scoring, Final Point.",
    },
    "turn_structure_endgame": {
        "quota": 8, "tiers": ("A", "B", "C"),
        "scope": "Turn structure, victory, draws, Burn Out, terminal states.",
    },
    "available_actions": {
        "quota": 8, "tiers": ("A", "B", "C"),
        "scope": "\"What can I do right now\". Every question here carries the "
                 "bounded-enumeration acknowledgement; the engine's action set "
                 "is not complete and an answer that does not say so is wrong "
                 "even when its list is right.",
        "requires_bounded_note": True,
    },
    "card_interaction": {
        "quota": 8, "tiers": ("A", "B", "C"),
        "scope": "Specific card interactions. A tier depends on whether the "
                 "card is compiled; the rest expect B.",
    },
    "tournament_policy": {
        "quota": 6, "tiers": ("C",),
        "scope": "Tournament procedure and penalties. Declined by policy.",
    },
}

TOTAL_QUOTA = sum(family["quota"] for family in FAMILIES.values())

QUESTION_FIELDS = {"question_id", "family", "language", "question", "expected_tier",
                   "locators", "abstention_contract", "consultation_entry", "bounded_note",
                   "zh_hant", "notes"}

LANGUAGES = ("en",)


class JudgeCorpusError(ValueError):
    pass


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_question(question: Any, *, seen: set[str] | None = None) -> list[str]:
    """Check one question against the contract."""
    errors: list[str] = []
    if not isinstance(question, dict):
        return ["a question must be a JSON object"]
    if missing := QUESTION_FIELDS - set(question):
        errors.append(f"missing fields: {sorted(missing)}")
    if unknown := set(question) - QUESTION_FIELDS:
        errors.append(f"unknown fields: {sorted(unknown)}")
    if missing:
        return errors

    label = question["question_id"] if _nonempty(question["question_id"]) else "<unnamed>"
    if not _nonempty(question["question_id"]):
        errors.append("question_id must be a non-empty string")
    elif seen is not None:
        if question["question_id"] in seen:
            errors.append(f"{label}: question_id is used more than once")
        seen.add(question["question_id"])
    if not _nonempty(question["question"]):
        errors.append(f"{label}: question must be a non-empty string")
    # English first: the agent host is the English surface, and a corpus that
    # begins in translation inherits the translation's ambiguities.
    if question["language"] not in LANGUAGES:
        errors.append(f"{label}: language must be one of {list(LANGUAGES)}; "
                      f"a Traditional Chinese rendering goes in zh_hant")

    family = FAMILIES.get(question["family"])
    if family is None:
        errors.append(f"{label}: family must be one of {sorted(FAMILIES)}")
        return errors

    tier = question["expected_tier"]
    if tier not in TIERS:
        errors.append(f"{label}: expected_tier must be one of {list(TIERS)}")
    elif tier not in family["tiers"]:
        errors.append(f"{label}: the {question['family']} family expects "
                      f"{list(family['tiers'])}, not {tier!r}")

    locators = question["locators"]
    if not isinstance(locators, list) or any(not _nonempty(v) for v in locators):
        errors.append(f"{label}: locators must be an array of non-empty strings")
        locators = []
    contract = question["abstention_contract"]

    if tier in {"A", "B"}:
        if not locators:
            errors.append(f"{label}: a tier-{tier} question names the locators its answer "
                          f"must cite; without them nothing distinguishes a right answer "
                          f"from a confident one")
        if contract is not None:
            errors.append(f"{label}: a tier-{tier} question does not abstain, so it carries "
                          f"no abstention contract")
    elif tier == "C":
        if not _nonempty(contract):
            errors.append(f"{label}: a tier-C question names the reason it must abstain with; "
                          f"'it should decline' is not a test, because two different failures "
                          f"both decline")
        elif contract not in ABSTENTION_CONTRACTS:
            errors.append(f"{label}: abstention_contract {contract!r} is not a reason this "
                          f"pipeline can produce")
        elif question["family"] == "tournament_policy" and contract not in POLICY_ABSTENTIONS:
            errors.append(f"{label}: a tournament-policy question abstains by policy "
                          f"({sorted(POLICY_ABSTENTIONS)}), not by a mechanism running out")
        elif question["family"] != "tournament_policy" and contract in POLICY_ABSTENTIONS:
            errors.append(f"{label}: {contract!r} is the tournament-policy red line and does "
                          f"not apply to the {question['family']} family")
        if locators:
            errors.append(f"{label}: a tier-C question cites nothing, because it does not answer")

    entry = question["consultation_entry"]
    if entry is not None and entry not in rule_consult_command.ENTRIES:
        errors.append(f"{label}: consultation_entry must be null or one of "
                      f"{sorted(rule_consult_command.ENTRIES)}")

    if family.get("requires_bounded_note"):
        if question["bounded_note"] is not True:
            errors.append(f"{label}: an available-actions question carries bounded_note true; "
                          f"the engine's action set is not complete and the answer must say so")
    elif question["bounded_note"] not in (False, None):
        errors.append(f"{label}: bounded_note is for the available-actions family")

    zh = question["zh_hant"]
    if zh is not None:
        if not isinstance(zh, dict) or set(zh) != {"question"} or not _nonempty(zh["question"]):
            errors.append(f"{label}: zh_hant must be null or {{question: <non-empty string>}}")

    if question["notes"] is not None and not _nonempty(question["notes"]):
        errors.append(f"{label}: notes must be null or a non-empty string")
    return errors


def corpus_coverage(corpus: dict[str, Any]) -> dict[str, Any]:
    """How much of the corpus exists, by family. Nothing here is asserted by hand."""
    present: dict[str, int] = {name: 0 for name in FAMILIES}
    for question in corpus.get("questions", []):
        if isinstance(question, dict) and question.get("family") in present:
            present[question["family"]] += 1
    families = {
        name: {"required": spec["quota"], "present": present[name],
               "missing": max(0, spec["quota"] - present[name])}
        for name, spec in FAMILIES.items()
    }
    total_present = sum(present.values())
    return {
        "families": families,
        "total_required": TOTAL_QUOTA,
        "total_present": total_present,
        "total_missing": sum(f["missing"] for f in families.values()),
        "complete": all(f["missing"] == 0 for f in families.values()),
    }


REQUIRED_TOP = {"schema_version", "corpus_id", "description", "questions"}


def validate_corpus(corpus: Any) -> list[str]:
    """Check the corpus envelope and every question in it.

    Being incomplete is not an error. A corpus with four questions is a valid
    corpus that is not finished, and `corpus_coverage` is where that shows.
    Declaring completeness is what this cannot be talked into.
    """
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
    if not isinstance(corpus["questions"], list):
        errors.append("questions must be an array")
        return errors
    seen: set[str] = set()
    for index, question in enumerate(corpus["questions"]):
        errors.extend(f"questions[{index}]: {e}" for e in validate_question(question, seen=seen))
    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a judge corpus and report its coverage.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("validate", help="validate a corpus against the contract")
    check.add_argument("corpus")

    cover = sub.add_parser("coverage", help="report how much of the corpus exists, by family")
    cover.add_argument("corpus")

    sub.add_parser("contract", help="print the families, quotas and abstention vocabulary")
    args = parser.parse_args(argv)

    if args.command == "contract":
        json.dump({
            "schema_version": SCHEMA_VERSION,
            "total_quota": TOTAL_QUOTA,
            "families": {name: {k: v for k, v in spec.items()} for name, spec in FAMILIES.items()},
            "abstention_contracts": {
                "from_pipeline": sorted(PIPELINE_ABSTENTIONS),
                "by_policy": sorted(POLICY_ABSTENTIONS),
            },
        }, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    corpus = _load(args.corpus)
    if args.command == "coverage":
        coverage = corpus_coverage(corpus)
        json.dump(coverage, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0 if coverage["complete"] else 2

    problems = validate_corpus(corpus)
    for problem in problems:
        print(problem, file=sys.stderr)
    coverage = corpus_coverage(corpus)
    print("valid" if not problems else f"{len(problems)} problem(s)")
    print(f"coverage: {coverage['total_present']}/{coverage['total_required']} "
          f"({'complete' if coverage['complete'] else 'incomplete'})")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
