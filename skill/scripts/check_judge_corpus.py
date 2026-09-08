#!/usr/bin/env python3
"""Executable checks for judge-corpus.v1, the S-04 corpus contract.

This package delivers the contract and its validator, not the sixty questions,
and the gate's first job is to make that distinction hold rather than assert it:
the coverage report says how much exists, and the gate fails if it ever reports
complete on a corpus that is not.

The rest holds the checks the contract turns on — a question without a tier, a
tier-A or tier-B question without locators, a tier-C question without a named
abstention, a tier a family cannot produce, a quota satisfied by piling
questions into one family — and then the part that makes the answer contract
mean something: every routable question is run through the real consultation
command and compared to what its contract specified, not just to its tier.

A difference between the contract and the pipeline is a failure here unless the
question carries a correction record saying what came back, what was decided,
and what is left. Recording one is not a way to pass; it is a way to say the
difference was looked at.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import fact_ledger
import judge_corpus_runner
import rule_consult_command
import state_builder
from judge_corpus import (
    ABSTENTION_CONTRACTS,
    ANSWER_SCOPES,
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
    abstaining_contract = next(q for q in corpus["questions"]
                               if q["expected_tier"] == "C")["expected_answer_contract"]
    filled = {**corpus, "questions": [
        dict(good, question_id=f"JC-FILL-{name}-{index}", family=name,
             expected_tier="C" if name == "tournament_policy" else "A",
             locators=[] if name == "tournament_policy" else good["locators"],
             abstention_contract="tournament_policy_red_line" if name == "tournament_policy" else None,
             expected_answer_contract=(abstaining_contract if name == "tournament_policy"
                                       else good["expected_answer_contract"]),
             bounded_note=True if FAMILIES[name].get("requires_bounded_note") else None)
        for name, spec in FAMILIES.items() for index in range(spec["quota"])]}
    filled_coverage = corpus_coverage(filled)
    if not filled_coverage["complete"]:
        failures.append(f"a corpus meeting every quota must report complete: {filled_coverage}")
    if problems := validate_corpus(filled):
        failures.append(f"the filled corpus should be valid: {problems[:3]}")

    # --- the answer contract ------------------------------------------------
    # A tier is not an answer. These check the rules that say so.
    def with_contract(base, **changes):
        candidate = copy.deepcopy(base)
        candidate["expected_answer_contract"] = {**candidate["expected_answer_contract"], **changes}
        return candidate

    conclusion = copy.deepcopy(next(q for q in corpus["questions"]
                                    if q["expected_answer_contract"]["answer_scope"]
                                    == "full_position_conclusion"))
    explanation = copy.deepcopy(next(q for q in corpus["questions"]
                                     if q["expected_answer_contract"]["answer_scope"]
                                     == "conditional_rule_explanation"
                                     and not q["expected_answer_contract"]["template_coverage_debt"]))
    abstention = copy.deepcopy(next(q for q in corpus["questions"]
                                    if q["expected_answer_contract"]["answer_scope"]
                                    == "explicit_abstention"))

    contract_cases = [
        ("a tier-A question scoped as a rule explanation",
         with_contract(conclusion, answer_scope="conditional_rule_explanation"),
         "a tier-A answer is scoped"),
        ("a full position conclusion with no position template",
         with_contract(conclusion, required_templates=["official_text_recorded"],
                       required_source_locators=["Core 312"]),
         "requires at least one position_conclusion template"),
        # The rule the JC-TPC-012 measurement produced: reporting that a locator
        # came back is not explaining what it says.
        ("a rule explanation that only reports a locator was retrieved",
         with_contract(explanation, required_templates=["official_text_recorded"]),
         "requires a conditional_rule template"),
        ("a rule explanation that also concludes about the position",
         with_contract(explanation,
                       required_templates=explanation["expected_answer_contract"]
                       ["required_templates"] + ["timing_play_refused"]),
         "draws no conclusion about the position"),
        ("a rule explanation naming no locator",
         with_contract(explanation, required_source_locators=[]),
         "names the locators it explains"),
        ("an abstention that requires templates",
         with_contract(abstention, required_templates=["official_text_recorded"]),
         "carries no claims"),
        ("an abstention that cites locators",
         with_contract(abstention, required_source_locators=["Core 312"]),
         "cites nothing"),
        ("a contract that requires and forbids the same class",
         with_contract(conclusion, forbidden_claim_classes=["position_conclusion"]),
         "which it also forbids"),
        ("a contract forbidding a class that does not exist",
         with_contract(conclusion, forbidden_claim_classes=["vibes"]),
         "unknown classes"),
        ("an unknown answer scope",
         with_contract(conclusion, answer_scope="probably_right"),
         "answer_scope must be one of"),
        # Debt is declared or it is a typo; the two must not look the same.
        ("a template that does not exist and is not declared as debt",
         with_contract(conclusion,
                       required_templates=conclusion["expected_answer_contract"]
                       ["required_templates"] + ["rule_invented_here"]),
         "must be the same set"),
        ("debt declared for a template that exists",
         with_contract(conclusion, template_coverage_debt=["official_text_recorded"]),
         "must be the same set"),
    ]
    for label, candidate, expected in contract_cases:
        problems = validate_question(candidate)
        if not problems:
            failures.append(f"the validator accepts {label}")
        elif not any(expected in problem for problem in problems):
            failures.append(f"{label} was refused, but not by the rule that should have "
                            f"caught it: {problems}")

    # A declared debt is a real gap, so it is reported where gaps are read.
    declared = {name for question in corpus["questions"]
                for name in question["expected_answer_contract"]["template_coverage_debt"]}
    if set(coverage["template_coverage_debt"]) != declared:
        failures.append(f"coverage reports debt {coverage['template_coverage_debt']}, "
                        f"the questions declare {sorted(declared)}")
    for name in declared:
        if name in rule_consult_command.CLAIM_TEMPLATES:
            failures.append(f"{name} is declared as debt but the answer surface has it")

    # Every scope is exercised, or the contract has parts nothing has tried.
    used = {question["expected_answer_contract"]["answer_scope"] for question in corpus["questions"]}
    if missing_scopes := sorted(set(ANSWER_SCOPES) - used - {"source_boundary_only"}):
        failures.append(f"no question uses the answer scopes {missing_scopes}")

    # --- every routable question is run, and compared to its contract -------
    runs = judge_corpus_runner.load(judge_corpus_runner.RUNS_PATH)
    report = judge_corpus_runner.run_corpus(corpus, runs)
    counts = report["counts"]

    undeclared = judge_corpus_runner.undeclared_differences(report)
    for item in undeclared:
        failures.append(f"{item['question_id']} differs from its contract and nothing records "
                        f"why: {item['problems']}")

    routable = [q for q in corpus["questions"] if q["consultation_entry"]]
    if counts.get("no_run_inputs"):
        missing = [i["question_id"] for i in report["results"] if i["outcome"] == "no_run_inputs"]
        failures.append(f"every routable question needs run inputs; {missing} have none")
    if len(routable) != sum(counts.get(key, 0) for key in
                            ("matches_contract", "differs", "differs_recorded",
                             "blocked_by_template_debt", "no_run_inputs")):
        failures.append("the run report does not account for every routable question")
    if not counts.get("matches_contract"):
        failures.append("no question matched its contract, so the comparison proves nothing")

    # A recorded difference must actually differ, or the record is describing
    # something that is not happening.
    for item in report["results"]:
        question = next(q for q in corpus["questions"] if q["question_id"] == item["question_id"])
        if question.get("correction_record") and item["outcome"] == "matches_contract":
            failures.append(f"{item['question_id']} carries a correction record but now matches "
                            f"its contract; the record is stale")

    # And a question blocked by declared debt must be blocked by that debt
    # rather than by something else that happens to also stop it.
    for item in report["results"]:
        if item["outcome"] != "blocked_by_template_debt":
            continue
        question = next(q for q in corpus["questions"] if q["question_id"] == item["question_id"])
        if not question["expected_answer_contract"]["template_coverage_debt"]:
            failures.append(f"{item['question_id']} is reported as blocked by debt it does not declare")

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
    print(f"answer scopes used: {sorted(used)}; "
          f"template coverage debt: {sorted(declared) or 'none'}")
    print(f"contract mutations refused: {len(mutations) + len(c_mutations) + len(contract_cases) + 4}")
    print(f"run against the real consultation command: "
          + ", ".join(f"{value} {key}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
