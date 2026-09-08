#!/usr/bin/env python3
"""Executable checks for judge-corpus.v1, the S-04 corpus contract.

This package delivers the contract and its validator, not the sixty questions,
and the gate's first job is to make that distinction hold rather than assert
it: the shipped corpus is seven exemplars, the coverage report says 7/60, and
the gate fails if anything starts claiming otherwise.

The rest of the gate holds the checks the contract turns on: a question without
a tier, a tier-A or tier-B question without locators, a tier-C question without
a named abstention, a tier a family cannot produce, and a quota that has been
satisfied by piling questions into one family.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import fact_ledger
import rule_consult_command
import state_builder
from judge_corpus import (
    ABSTENTION_CONTRACTS,
    FAMILIES,
    PIPELINE_ABSTENTIONS,
    POLICY_ABSTENTIONS,
    TOTAL_QUOTA,
    corpus_coverage,
    validate_corpus,
    validate_question,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS = SKILL_DIR / "data" / "judge_corpus.json"


def main() -> int:
    failures: list[str] = []
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

    if problems := validate_corpus(corpus):
        failures.append(f"the shipped corpus does not validate: {problems}")

    coverage = corpus_coverage(corpus)
    # The point of this package is the contract. A corpus that reported itself
    # complete on seven questions would be the exact failure the delivery
    # discipline names: a batch declared finished.
    if coverage["complete"]:
        failures.append("the shipped corpus reports itself complete; it is seven exemplars")
    if coverage["total_required"] != 60:
        failures.append(f"the quotas must sum to 60; they sum to {coverage['total_required']}")
    if coverage["total_present"] != len(corpus["questions"]):
        failures.append("coverage undercounts the questions in the corpus")
    if coverage["total_missing"] != coverage["total_required"] - coverage["total_present"]:
        failures.append("the shortfall does not account for the whole gap")

    # Every family is exercised by an exemplar, so the shape of every family is
    # shown rather than described.
    for name, report in coverage["families"].items():
        if report["present"] < 1:
            failures.append(f"the {name} family has no exemplar showing its shape")
        if report["missing"] != report["required"] - report["present"]:
            failures.append(f"the {name} shortfall is miscounted")

    # --- the contract's own checks -----------------------------------------
    good = copy.deepcopy(corpus["questions"][0])
    if validate_question(good):
        failures.append("the first exemplar must be valid, or the mutations below prove nothing")

    mutations = [
        ("a question with no tier", lambda q: q.__setitem__("expected_tier", None),
         "expected_tier must be one of"),
        ("a tier-A question with no locators", lambda q: q.__setitem__("locators", []),
         "names the locators its answer must cite"),
        ("a tier-A question carrying an abstention contract",
         lambda q: q.__setitem__("abstention_contract", "state_not_built"),
         "does not abstain"),
        ("a tier that this family cannot produce",
         lambda q: (q.__setitem__("family", "tournament_policy"),
                    q.__setitem__("expected_tier", "A")),
         "family expects"),
        ("an unknown family", lambda q: q.__setitem__("family", "deck_building"),
         "family must be one of"),
        ("a question in another language",
         lambda q: q.__setitem__("language", "zh-Hant"), "language must be one of"),
        ("a consultation entry the command does not have",
         lambda q: q.__setitem__("consultation_entry", "mulligan"),
         "consultation_entry must be null or one of"),
        ("an unknown field", lambda q: q.__setitem__("difficulty", "hard"), "unknown fields"),
        ("a zh_hant rendering that is not one",
         lambda q: q.__setitem__("zh_hant", {"question": "  "}), "zh_hant must be null"),
    ]
    for label, mutate, expected in mutations:
        candidate = copy.deepcopy(good)
        mutate(candidate)
        problems = validate_question(candidate)
        if not problems:
            failures.append(f"the validator accepts {label}")
        elif not any(expected in problem for problem in problems):
            failures.append(f"{label} was refused, but not by the rule that should have "
                            f"caught it: {problems}")

    # A tier-C question, and the checks that only apply to one.
    abstaining = copy.deepcopy(next(q for q in corpus["questions"] if q["expected_tier"] == "C"
                                    and q["family"] != "tournament_policy"))
    c_mutations = [
        ("a tier-C question with no abstention contract",
         lambda q: q.__setitem__("abstention_contract", None),
         "names the reason it must abstain with"),
        ("an abstention this pipeline cannot produce",
         lambda q: q.__setitem__("abstention_contract", "the model was unsure"),
         "is not a reason this pipeline can produce"),
        ("a tier-C question that cites locators",
         lambda q: q.__setitem__("locators", ["Core 312"]),
         "cites nothing, because it does not answer"),
        ("the policy red line used outside the policy family",
         lambda q: q.__setitem__("abstention_contract", "tournament_policy_red_line"),
         "does not apply to the"),
    ]
    for label, mutate, expected in c_mutations:
        candidate = copy.deepcopy(abstaining)
        mutate(candidate)
        problems = validate_question(candidate)
        if not problems:
            failures.append(f"the validator accepts {label}")
        elif not any(expected in problem for problem in problems):
            failures.append(f"{label} was refused, but not by the rule that should have "
                            f"caught it: {problems}")

    # The tournament-policy family abstains by policy, not by mechanism.
    policy = copy.deepcopy(next(q for q in corpus["questions"] if q["family"] == "tournament_policy"))
    swapped = dict(policy, abstention_contract="state_not_built")
    problems = validate_question(swapped)
    if not any("abstains by policy" in problem for problem in problems):
        failures.append(f"a tournament-policy question abstaining by mechanism must be "
                        f"refused as such: {problems}")

    # The available-actions family must acknowledge the bounded enumeration.
    actions = copy.deepcopy(next(q for q in corpus["questions"] if q["family"] == "available_actions"))
    without_note = dict(actions, bounded_note=False)
    if not any("bounded_note true" in p for p in validate_question(without_note)):
        failures.append("an available-actions question without the bounded note must be refused")
    elsewhere = dict(good, bounded_note=True)
    if not any("for the available-actions family" in p for p in validate_question(elsewhere)):
        failures.append("the bounded note outside its family must be refused")

    # --- quotas are not satisfiable by piling into one family ---------------
    stuffed = {**corpus, "questions": [
        dict(good, question_id=f"JC-STUFF-{index}") for index in range(TOTAL_QUOTA)]}
    stuffed_coverage = corpus_coverage(stuffed)
    if stuffed_coverage["complete"]:
        failures.append("sixty questions in one family reported the corpus complete")
    if stuffed_coverage["total_present"] != TOTAL_QUOTA:
        failures.append("the stuffed corpus should hold exactly the quota total")
    short = [name for name, report in stuffed_coverage["families"].items() if report["missing"] > 0]
    if len(short) != len(FAMILIES) - 1:
        failures.append(f"stuffing one family should leave every other family short; "
                        f"{len(short)} are")

    # A corpus that does meet every quota reports complete, so the check above
    # is about the distribution and not about the number being unreachable.
    filled = {**corpus, "questions": [
        dict(good, question_id=f"JC-FILL-{name}-{index}", family=name,
             expected_tier="C" if name == "tournament_policy" else "A",
             locators=[] if name == "tournament_policy" else ["Core 312"],
             abstention_contract="tournament_policy_red_line" if name == "tournament_policy" else None,
             bounded_note=True if FAMILIES[name].get("requires_bounded_note") else None)
        for name, spec in FAMILIES.items() for index in range(spec["quota"])]}
    filled_coverage = corpus_coverage(filled)
    if not filled_coverage["complete"]:
        failures.append(f"a corpus meeting every quota must report complete: {filled_coverage}")
    if problems := validate_corpus(filled):
        failures.append(f"the filled corpus should be valid: {problems[:3]}")

    # --- the abstention vocabulary is imported, not restated ----------------
    for module, name in ((state_builder, "DOWNGRADE_REASONS"),
                         (fact_ledger, "VIOLATION_CODES"),
                         (rule_consult_command, "NOT_ATTEMPTED_REASONS")):
        vocabulary = set(getattr(module, name))
        if not vocabulary <= PIPELINE_ABSTENTIONS:
            failures.append(f"{module.__name__}.{name} has grown reasons the corpus contract "
                            f"cannot name: {sorted(vocabulary - PIPELINE_ABSTENTIONS)}")
    if PIPELINE_ABSTENTIONS & POLICY_ABSTENTIONS:
        failures.append("a policy abstention must not also be a pipeline one; the distinction "
                        "is the point")
    for question in corpus["questions"]:
        contract = question["abstention_contract"]
        if contract is not None and contract not in ABSTENTION_CONTRACTS:
            failures.append(f"{question['question_id']} names an abstention outside the contract")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across the judge corpus contract")
        return 1

    by_family = ", ".join(f"{name} {report['present']}/{report['required']}"
                          for name, report in sorted(coverage["families"].items()))
    print(f"judge-corpus.v1: contract over {len(FAMILIES)} families, quota {TOTAL_QUOTA}")
    print(f"shipped: {coverage['total_present']} exemplars, "
          f"{coverage['total_missing']} questions still to write — {by_family}")
    print(f"abstention contracts: {len(PIPELINE_ABSTENTIONS)} from the pipeline, "
          f"{len(POLICY_ABSTENTIONS)} by policy")
    print(f"contract mutations refused: {len(mutations) + len(c_mutations) + 4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
