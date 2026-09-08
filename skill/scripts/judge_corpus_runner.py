#!/usr/bin/env python3
"""Run corpus questions through the consultation command and compare the result to the contract.

A corpus question says what an answer must be shaped like. This runs the real
pipeline for it and checks what came back against that — the tier, the claim
templates, the classes, the locators those claims were bound to, and the answer
scope. Not the tier alone: a tier-B run that cites the right rule and explains
nothing passes a tier check and fails this one, which is the whole reason the
answer contract exists.

The run inputs live apart from the corpus. A question is a specification and
should read as one; the position to build, the action to test and the templates
to offer are what a runner needs to exercise it, and mixing the two would make
the corpus unreadable and tie its questions to one pipeline's argument shapes.

A question with no `consultation_entry` is not runnable here and is reported as
such. That is not a gap: a question the service declines by policy never reaches
an engine entry, and pretending to route it would be inventing a path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import judge_corpus
import legal_action
import rule_consult_command as rcc
import state_builder


SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS_PATH = SKILL_DIR / "data" / "judge_corpus.json"
RUNS_PATH = SKILL_DIR / "data" / "judge_corpus_runs.json"

SCOPE_OF_CLASSES = {
    "position_conclusion": "full_position_conclusion",
    "conditional_rule": "conditional_rule_explanation",
    "source_statement": "source_boundary_only",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_retriever(table: dict[str, Any]) -> rcc.TableRetriever:
    return rcc.TableRetriever(table, {})


def observed_scope(run: dict[str, Any]) -> str:
    """The scope the run actually delivered, read off its claims."""
    if run["status"] == "not_attempted" or not run["claims"]:
        return "explicit_abstention"
    classes = {claim["claim_class"] for claim in run["claims"]}
    if "position_conclusion" in classes:
        return "full_position_conclusion"
    if "conditional_rule" in classes:
        return "conditional_rule_explanation"
    return "source_boundary_only"


def compare(question: dict[str, Any], run: dict[str, Any]) -> list[str]:
    """Every way this run failed to be the answer the question specified."""
    contract = question["expected_answer_contract"]
    problems: list[str] = []

    if run["tier"] != question["expected_tier"]:
        problems.append(f"tier {run['tier']!r}, contract says {question['expected_tier']!r}")

    scope = observed_scope(run)
    if scope != contract["answer_scope"]:
        problems.append(f"answer scope {scope!r}, contract says {contract['answer_scope']!r}")

    templates = [claim["template"] for claim in run["claims"]]
    for required in contract["required_templates"]:
        if required in contract["template_coverage_debt"]:
            continue
        if required not in templates:
            problems.append(f"the contract requires the template {required!r}; "
                            f"the run carried {templates or 'none'}")

    forbidden = set(contract["forbidden_claim_classes"])
    for claim in run["claims"]:
        if claim["claim_class"] in forbidden:
            problems.append(f"claim {claim['claim_id']} is class {claim['claim_class']!r}, "
                            f"which this contract forbids")

    # The locators the contract names must be what the source claims were bound
    # to, not merely mentioned somewhere in the run.
    bound = {claim["source"].split(":", 1)[1] for claim in run["claims"]
             if claim["source"].startswith("official_text:")}
    for locator in contract["required_source_locators"]:
        if locator not in bound:
            problems.append(f"the contract requires a claim bound to {locator!r}; "
                            f"the run bound {sorted(bound) or 'nothing'}")

    if contract["answer_scope"] != "explicit_abstention":
        if run["status"] != "answered":
            problems.append(f"the contract expects an answer; the run was {run['status']!r}"
                            + (f" ({run['not_attempted_reason']})" if run["not_attempted_reason"] else ""))
    elif run["status"] == "answered":
        problems.append("the contract expects an abstention; the run answered")

    # A tier-B answer must say in the artifact that it concluded nothing here.
    if run["tier"] == "B" and run["position_statement"] != rcc.POSITION_STATEMENT:
        problems.append("a tier-B answer must carry the position statement")
    return problems


def _observation(inputs: dict[str, Any]) -> dict[str, Any]:
    """A legal-action observation over the same states the run builds.

    The runs file asks for one rather than carrying one: an observation is a
    large object with the states inside it, and a copy in the fixture would
    drift from the drafts beside it the first time either changed.
    """
    timing = state_builder.build_state_assumption(
        question="observation", question_kind=inputs.get("question_kind", "timing_priority"),
        draft=inputs["draft"])
    effect = state_builder.build_state_assumption(
        question="observation", question_kind="unit_damage", draft=inputs["effect_draft"])
    return legal_action.build_observation(
        perspective="player1", source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": "2026-07-16", "faq_as_of": "2026-07-16",
                 "format": "standard", "card_data_version": "r3a1"},
        timing_state=timing["state"], effect_state=effect["state"], facts={},
        pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete",
                      "pending_decisions": "complete"})


def run_question(question: dict[str, Any], inputs: dict[str, Any],
                 retriever: rcc.TableRetriever) -> dict[str, Any]:
    entry_inputs = dict(inputs["entry_inputs"])
    if entry_inputs.get("observation") == "$build":
        entry_inputs["observation"] = _observation(inputs)
    inputs = {**inputs, "entry_inputs": entry_inputs}
    return rcc.run_consultation(
        question=question["question"], entry=inputs["entry"], draft=inputs["draft"],
        question_kind=inputs.get("question_kind", "timing_priority"),
        effect_draft=inputs.get("effect_draft"),
        entry_inputs=inputs["entry_inputs"], claims=inputs["claims"],
        source_retriever=retriever)


def run_corpus(corpus: dict[str, Any], runs: dict[str, Any]) -> dict[str, Any]:
    retriever = build_retriever(runs["sources"])
    inputs_by_id = runs["runs"]
    results = []
    for question in corpus["questions"]:
        entry = question["consultation_entry"]
        inputs = inputs_by_id.get(question["question_id"])
        if entry is None:
            results.append({"question_id": question["question_id"], "outcome": "not_routable",
                            "reason": "the question has no consultation entry; the service "
                                      "declines it before any engine is reached"})
            continue
        if inputs is None:
            results.append({"question_id": question["question_id"], "outcome": "no_run_inputs",
                            "reason": "no run inputs are recorded for this question"})
            continue
        run = run_question(question, inputs, retriever)
        problems = compare(question, run)
        contract = question["expected_answer_contract"]
        if contract["template_coverage_debt"]:
            # The contract names a template the answer surface does not have, so
            # the answer it specifies cannot be given yet. That is the debt doing
            # its job, not a disagreement about behaviour.
            outcome = "blocked_by_template_debt"
        elif not problems:
            outcome = "matches_contract"
        elif question.get("correction_record"):
            # A difference that has been looked at and written down. It stays
            # visible in the count; what it stops being is a surprise.
            outcome = "differs_recorded"
        else:
            outcome = "differs"
        results.append({
            "question_id": question["question_id"],
            "outcome": outcome,
            "tier": run["tier"], "status": run["status"],
            "scope": observed_scope(run),
            "templates": [claim["template"] for claim in run["claims"]],
            "problems": problems,
        })
    counts: dict[str, int] = {}
    for item in results:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    return {"results": results, "counts": counts, "questions": len(corpus["questions"])}


def undeclared_differences(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Differences nobody has looked at. These are the ones that must not stand."""
    return [item for item in report["results"] if item["outcome"] == "differs"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--runs", type=Path, default=RUNS_PATH)
    args = parser.parse_args(argv)
    report = run_corpus(load(args.corpus), load(args.runs))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if not report["counts"].get("differs") else 1


if __name__ == "__main__":
    raise SystemExit(main())
