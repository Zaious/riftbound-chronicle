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
import source_semantic_bindings as ssb
import state_builder
from judge_corpus import (
    DEBT_BLOCKS,
    DEBT_CLASSES,
    DERIVED_DEBT_FIELD,
    DERIVED_TEMPLATES_FIELD,
    attach_debts,
    validate_debts,
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
    stored = json.loads(CORPUS.read_text(encoding="utf-8"))

    if problems := validate_corpus(stored):
        failures.append(f"the shipped corpus does not validate: {problems}")
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    # Everything below reads the in-memory form: every contract carries the
    # debt list derived from the ledger.
    corpus = attach_debts(stored)

    coverage = corpus_coverage(corpus)
    # The corpus met every quota on 2026-09-09. The coverage report must say
    # so from the counts, and must not say so if a family falls short again:
    # completeness is read off the quotas, never declared.
    if coverage["complete"] != (coverage["total_missing"] == 0):
        failures.append("the coverage report's completeness disagrees with its own shortfall")
    if not coverage["complete"]:
        short = {n: r for n, r in coverage["families"].items() if r["missing"]}
        failures.append(f"the shipped corpus is short of quota: {short}")
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
    good_stored = copy.deepcopy(stored["questions"][0])
    stuffed = {**stored, "coverage_debts": [], "questions": [
        dict(good_stored, question_id=f"JC-STUFF-{index}") for index in range(TOTAL_QUOTA)]}
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
    abstaining_contract = next(q for q in stored["questions"]
                               if q["expected_tier"] == "C")["expected_answer_contract"]
    filled = {**stored, "coverage_debts": [], "questions": [
        dict(good_stored, question_id=f"JC-FILL-{name}-{index}", family=name,
             expected_tier="C" if name == "tournament_policy" else "A",
             locators=[] if name == "tournament_policy" else good_stored["locators"],
             abstention_contract="tournament_policy_red_line" if name == "tournament_policy" else None,
             expected_answer_contract=(abstaining_contract if name == "tournament_policy"
                                       else good_stored["expected_answer_contract"]),
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
         with_contract(conclusion, required_claims=[{"template": "official_text_recorded", "slots": {"locator": "Core 312"}}],
                       required_templates=["official_text_recorded"],
                       required_source_locators=["Core 312"]),
         "requires at least one position_conclusion template"),
        # The rule the JC-TPC-012 measurement produced: reporting that a locator
        # came back is not explaining what it says.
        ("a rule explanation that only reports a locator was retrieved",
         with_contract(explanation, required_claims=[{"template": "official_text_recorded", "slots": {"locator": "Core 312"}}],
                       required_templates=["official_text_recorded"]),
         "requires a conditional_rule template"),
        ("a rule explanation that also concludes about the position",
         with_contract(explanation,
                       required_claims=explanation["expected_answer_contract"]["required_claims"]
                       + [{"template": "timing_play_refused",
                           "slots": {"actor": "p1", "object_kind": "spell"}}],
                       required_templates=explanation["expected_answer_contract"]
                       ["required_templates"] + ["timing_play_refused"]),
         "draws no conclusion about the position"),
        ("a rule explanation naming no locator",
         with_contract(explanation, required_source_locators=[]),
         "names the locators it explains"),
        ("an abstention that requires templates",
         with_contract(abstention, required_claims=[{"template": "official_text_recorded", "slots": {"locator": "Core 312"}}],
                       required_templates=["official_text_recorded"]),
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
                       required_claims=conclusion["expected_answer_contract"]["required_claims"]
                       + [{"template": "rule_invented_here", "slots": {}}],
                       required_templates=conclusion["expected_answer_contract"]
                       ["required_templates"] + ["rule_invented_here"]),
         "must be the same set"),
        ("debt declared for a template that exists",
         with_contract(conclusion, template_coverage_debt=["official_text_recorded"]),
         "must be the same set"),
        # S-04d. A claim pins its slot values, and those values are choices.
        ("a required claim whose slot value is outside the lexicon",
         with_contract(explanation,
                       required_claims=[{"template": "rule_role_holder",
                                         "slots": {"locator": "Core 345", "occasion": "when_showdown_begins",
                                                   "role": "focus", "holder": "p1"}}],
                       required_templates=["rule_role_holder"]),
         "is not a value of rule_holder"),
        ("a required claim with a sentence in a slot",
         with_contract(explanation,
                       required_claims=[{"template": "rule_action_permission",
                                         "slots": {"locator": "Core 313.4", "actor": "any_player",
                                                   "modality": "may_not",
                                                   "action": "take a discretionary action whenever they like",
                                                   "condition": "unconditionally"}}],
                       required_templates=["rule_action_permission"]),
         "is not a value of rule_action"),
        ("a required claim missing a slot its template takes",
         with_contract(explanation,
                       required_claims=[{"template": "rule_role_holder",
                                         "slots": {"locator": "Core 345", "role": "focus"}}],
                       required_templates=["rule_role_holder"]),
         "takes exactly"),
        ("a required claim whose number is a word",
         with_contract(explanation,
                       required_claims=[{"template": "rule_quantity",
                                         "slots": {"locator": "Core 194.3", "quantity": "victory_score_by_default",
                                                   "relation": "is", "value": "eight"}}],
                       required_templates=["rule_quantity"]),
         "is not a value of rule_value"),
        ("a required claim whose relation and number disagree",
         with_contract(explanation,
                       required_claims=[{"template": "rule_quantity",
                                         "slots": {"locator": "Core 814.2",
                                                   "quantity": "shield_value_from_several_sources",
                                                   "relation": "is_the_sum_of_the_values", "value": 4}}],
                       required_templates=["rule_quantity"]),
         "does not cohere"),
        ("a derived template list that disagrees with the claims",
         with_contract(explanation, required_templates=["official_text_recorded"]),
         "is derived from required_claims"),
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
                        f"the questions derive {sorted(declared)}")
    for name in declared:
        if name in rule_consult_command.CLAIM_TEMPLATES:
            failures.append(f"{name} is declared as debt but the answer surface has it")

    # --- one ledger, one truth ---------------------------------------------
    # Each mutation of the stored corpus must be refused by the rule that names
    # it. A ledger that could be talked into any of these would be two truths
    # with a tidier shape.
    # Every template debt is closed now, so the ledger mutations run over a
    # probe: one copied question that requires a template the surface does
    # not have, and the open debt that observes it. The probe must validate
    # on its own, or the refusals below would be refusing the probe.
    def with_probe(candidate):
        source = next(q for q in candidate["questions"]
                      if q["expected_answer_contract"]["answer_scope"] == "conditional_rule_explanation")
        probe = copy.deepcopy(source)
        probe["question_id"] = "JC-PROBE-DEBT"
        probe["expected_answer_contract"]["required_claims"] = [{"template": "rule_probe_unwritten", "slots": {}}]
        candidate["questions"].append(probe)
        candidate["coverage_debts"].insert(0, {
            "id": "rule_probe_unwritten", "class": "template", "blocks": "source_explanation",
            "owner": {"track": "answer_surface", "package_id": None}, "observed_in": ["JC-PROBE-DEBT"],
            "trigger": {"kind": "triage_required", "threshold_or_condition": "recurrence_at_3"},
            "status": "open", "review_by": "2026-10-09"})
        return candidate

    if problems := validate_corpus(with_probe(copy.deepcopy(stored))):
        failures.append(f"the probe corpus must validate, or the ledger refusals prove nothing: {problems[:2]}")

    def stored_with(mutate):
        candidate = with_probe(copy.deepcopy(stored))
        mutate(candidate)
        return candidate

    def first_open(candidate, cls="template"):
        return next(d for d in candidate["coverage_debts"]
                    if d["class"] == cls and d["status"] == "open")

    def stun(candidate):
        return next(d for d in candidate["coverage_debts"] if d["class"] == "state_builder")

    def first_scheduled(candidate):
        return next(d for d in candidate["coverage_debts"] if d["owner"]["package_id"] is not None)

    policy_id = next(q["question_id"] for q in stored["questions"]
                     if q["family"] == "tournament_policy")
    ledger_cases = [
        ("a question storing the derived debt field",
         stored_with(lambda c: c["questions"][0]["expected_answer_contract"]
                     .__setitem__(DERIVED_DEBT_FIELD, [])),
         "is derived from coverage_debts; it is not stored"),
        ("a corpus with no ledger",
         stored_with(lambda c: c.pop("coverage_debts")), "missing top-level fields"),
        # The corpus says what its readings are and are not.
        ("a corpus that does not say its readings are unreviewed",
         stored_with(lambda c: c.pop("semantic_binding_status")), "missing top-level fields"),
        ("a corpus claiming its readings are approved",
         stored_with(lambda c: c.__setitem__("semantic_binding_status", "approved")),
         "are not reviewed here"),
        ("a corpus claiming run-time authority",
         stored_with(lambda c: c.__setitem__("runtime_authority", "approved_registry")),
         "only an approved registry does"),
        ("an open template debt the surface already has",
         stored_with(lambda c: first_open(c).__setitem__("id", "official_text_recorded")),
         "which the answer surface has"),
        ("a debt observed in no question",
         stored_with(lambda c: first_open(c).__setitem__("observed_in", [])),
         "a debt nobody measured is a wish"),
        ("a debt observed in a question the corpus does not have",
         stored_with(lambda c: first_open(c).__setitem__("observed_in", ["JC-NOWHERE-1"])),
         "which is not in the corpus"),
        ("a debt observed in the policy red line",
         stored_with(lambda c: first_open(c).__setitem__("observed_in", [policy_id])),
         "the red line is a decision, not a debt"),
        ("a debt of a class the ledger does not know",
         stored_with(lambda c: first_open(c).__setitem__("class", "vibes")),
         "class must be one of"),
        ("a debt blocking something the ledger does not know",
         stored_with(lambda c: first_open(c).__setitem__("blocks", "everything")),
         "blocks must be one of"),
        ("a debt with a status the ledger does not know",
         stored_with(lambda c: first_open(c).__setitem__("status", "someday")),
         "status must be one of"),
        ("two debts with one id",
         stored_with(lambda c: c["coverage_debts"].append(dict(first_open(c)))),
         "id is used more than once"),
        ("a debt whose owner is a description",
         stored_with(lambda c: first_open(c).__setitem__("owner", "the template-review package")),
         "owner carries exactly"),
        ("a debt owned by a track the loop does not run",
         stored_with(lambda c: first_open(c)["owner"].__setitem__("track", "vibes")),
         "owner.track must be one of"),
        ("a debt owned by a package that does not exist",
         stored_with(lambda c: first_open(c)["owner"].__setitem__("package_id", "T-99")),
         "owner.package_id must be null or one of"),
        # S-04e. No package is not a package: it is null, a review date, and a
        # triage trigger — each refused without the others.
        ("a debt parked under an invented 'unscheduled' package",
         stored_with(lambda c: first_open(c)["owner"].__setitem__("package_id", "unscheduled")),
         "owner.package_id must be null or one of"),
        ("a debt with no package and no review date",
         stored_with(lambda c: first_open(c).__setitem__("review_by", None)),
         "carries review_by as YYYY-MM-DD"),
        ("a debt with no package and a prose review date",
         stored_with(lambda c: first_open(c).__setitem__("review_by", "next sprint")),
         "carries review_by as YYYY-MM-DD"),
        ("a debt with no package triggered like an owned one",
         stored_with(lambda c: first_open(c)["trigger"].__setitem__("kind", "template_missing")),
         "is triggered by 'triage_required'"),
        ("a triage threshold outside the closed list",
         stored_with(lambda c: first_open(c)["trigger"]
                     .__setitem__("threshold_or_condition", "when someone has time")),
         "a triage threshold is one of"),
        ("an owned debt carrying a review date",
         stored_with(lambda c: first_scheduled(c).__setitem__("review_by", "2026-10-09")),
         "carries no review_by"),
        ("an owned debt triggered by triage",
         stored_with(lambda c: first_scheduled(c)["trigger"].__setitem__("kind", "triage_required")),
         "is for a debt with no package"),
        ("a closed debt with no package",
         stored_with(lambda c: (first_scheduled(c)["owner"].__setitem__("package_id", None),
                                first_scheduled(c).__setitem__("review_by", "2026-10-09"),
                                first_scheduled(c)["trigger"].__setitem__("kind", "triage_required"),
                                first_scheduled(c)["trigger"].__setitem__("threshold_or_condition",
                                                                          "review_by_reached"))),
         "names the package that closed it"),
        ("a debt whose trigger is a description",
         stored_with(lambda c: first_open(c).__setitem__("trigger", "the surface had no template")),
         "trigger carries exactly"),
        ("a template debt triggered like a state-builder one",
         stored_with(lambda c: first_scheduled(c)["trigger"].__setitem__("kind", "slot_missing")),
         "is triggered by 'template_missing'"),
        ("a template debt whose condition is not the template it lacks",
         stored_with(lambda c: first_scheduled(c)["trigger"].__setitem__("threshold_or_condition", "rule_other")),
         "its own id"),
        ("an open state-builder debt naming a slot the builder has",
         stored_with(lambda c: (stun(c).__setitem__("status", "open"),
                                stun(c)["trigger"].__setitem__("threshold_or_condition", "combat"))),
         "which the builder has"),
        ("a closed state-builder debt naming a slot the builder lacks",
         stored_with(lambda c: stun(c)["trigger"].__setitem__("threshold_or_condition", "stunned_context")),
         "which the builder does not have"),
        ("an open template debt no observed question still requires",
         stored_with(lambda c: c["questions"].__setitem__(
             next(i for i, q in enumerate(c["questions"])
                  if q["question_id"] == first_open(c)["observed_in"][0]),
             dict(next(q for q in c["questions"] if q["question_id"] == first_open(c)["observed_in"][0]),
                  expected_answer_contract=dict(
                      next(q for q in c["questions"] if q["question_id"] == first_open(c)["observed_in"][0])
                      ["expected_answer_contract"], required_claims=[])))),
         "none asks for"),
        ("a question storing the derived template list",
         stored_with(lambda c: c["questions"][0]["expected_answer_contract"]
                     .__setitem__(DERIVED_TEMPLATES_FIELD, [])),
         "is derived from required_claims"),
        # Closed is measured, not declared: a closed template debt whose
        # observed question still requires the missing template is not closed.
        ("a template debt closed while its question still requires it",
         stored_with(lambda c: first_open(c).__setitem__("status", "closed")),
         "still blocks a question"),
        # The derivation is what keeps a typo and an unwritten template apart:
        # drop the ledger entry and the question's unknown template is a typo.
        ("a required template whose debt was removed from the ledger",
         stored_with(lambda c: c["coverage_debts"].remove(first_open(c))),
         "must be the same set"),
    ]
    for label, candidate, expected in ledger_cases:
        problems = validate_corpus(candidate)
        if not problems:
            failures.append(f"the ledger accepts {label}")
        elif not any(expected in problem for problem in problems):
            failures.append(f"{label} was refused, but not by the rule that should have "
                            f"caught it: {problems[:3]}")
    if set(DEBT_CLASSES) != {"template", "state_builder", "engine", "source", "policy"}:
        failures.append("the debt classes are the five the ruling named")
    if set(DEBT_BLOCKS) != {"answer_contract", "position_conclusion", "source_explanation"}:
        failures.append("the debt blocks are the three the ruling named")
    if not any(d["class"] != "template" for d in stored["coverage_debts"]):
        failures.append("the ledger holds only template debts; the Stun gap is a state_builder "
                        "debt and must be entered as one")
    # T-01 closed debts by measurement: every closed template debt's observed
    # questions carry a family claim that the run actually binds, so "closed"
    # is read off the runs below, not off the status field.
    closed_template = [d for d in stored["coverage_debts"] if d["class"] == "template" and d["status"] == "closed"]
    parked = [d for d in stored["coverage_debts"] if d["owner"]["package_id"] is None]
    if any(d["owner"]["package_id"] == "unscheduled" for d in stored["coverage_debts"]):
        failures.append("'unscheduled' is not a package")
    if parked and not all(d["review_by"] for d in parked):
        failures.append("every debt with no package carries a review date")
    if not closed_template:
        failures.append("T-01 closed no template debt; the families absorbed nothing")

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
                             "blocked_by_template_debt", "no_run_inputs", "awaiting_approved_binding")):
        failures.append("the run report does not account for every routable question")
    if not counts.get("matches_contract"):
        failures.append("no question matched its contract, so the comparison proves nothing")

    # Semantic authority. With an approved registry on the pack paths every
    # rule question must match; without one, every question whose contract
    # requires a rule claim must be reported as awaiting its binding — not
    # matching, and not differing. The gate says which state it ran in.
    approved = ssb.approved_registry_paths()
    rule_questions = {q["question_id"] for q in corpus["questions"]
                      if any(rule_consult_command.CLAIM_TEMPLATES.get(c["template"], {}).get("class")
                             == "conditional_rule" for c in q["expected_answer_contract"]["required_claims"])}
    awaiting = {i["question_id"] for i in report["results"] if i["outcome"] == "awaiting_approved_binding"}
    if approved:
        authority = f"closed ({len(approved)} approved registry file(s) on the pack paths)"
        if awaiting:
            failures.append(f"an approved registry is present and {sorted(awaiting)} still await a binding")
    else:
        authority = "pending (no approved registry on the pack paths; rule questions await review)"
        if awaiting != rule_questions:
            failures.append(f"with no approved registry, exactly the rule questions await a binding; "
                            f"awaiting {sorted(awaiting)}, rule questions {sorted(rule_questions)}")

    for debt in closed_template:
        for qid in debt["observed_in"]:
            item = next(i for i in report["results"] if i["question_id"] == qid)
            # Closed means the question it observed now runs to its contract,
            # with every required claim matched template and slot for slot —
            # or, with no approved registry to bind against, awaits exactly that.
            if item["outcome"] != ("matches_contract" if approved else "awaiting_approved_binding"):
                failures.append(f"{debt['id']} is closed, but {qid} runs to {item['outcome']}: "
                                f"{item.get('problems') or item.get('reason')}")

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
        # And the debt must be the only thing in the way. A locator the run
        # never bound is a gap in the run inputs, and the debt was hiding it.
        for problem in item["problems"]:
            if "requires a claim bound to" in problem:
                failures.append(f"{item['question_id']} is blocked by debt, and also short of a "
                                f"source binding the debt does not explain: {problem}")

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
    print(f"contract mutations refused: {len(mutations) + len(c_mutations) + len(contract_cases) + 4}; "
          f"ledger mutations refused: {len(ledger_cases)}")
    ledger = coverage["coverage_debts"]
    print(f"coverage debts: {ledger['open']} open, {ledger['closed']} closed; by class {ledger['by_class']}; "
          f"by blocks {ledger['by_blocks']}; questions blocked {ledger['questions_blocked']}; "
          f"no package yet: {len(parked)} (review by {sorted({d['review_by'] for d in parked}) or '-'})")
    print(f"run against the real consultation command: "
          + ", ".join(f"{value} {key}" for key, value in sorted(counts.items())))
    print(f"semantic authority: {authority}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
