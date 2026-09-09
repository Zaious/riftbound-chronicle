#!/usr/bin/env python3
"""The judge corpus contract: what a question must carry before it counts.

This module is the specification and its validator. It is not the sixty
questions, and it says so in the only way that means anything — the coverage
report it produces reads `complete: false` until the quotas are met, per
family, with the shortfall named. A corpus cannot be declared finished by
asserting that it is.

What an answer owes
-------------------
A tier is not an answer. A run can reach tier B by citing the right rule and
saying nothing about what was asked — "Core 345 is official text retrieved for
this question" is true, bound, verifiable, and useless to the person who asked
which player gains Focus. A corpus that only checks tiers would pass a service
that never answered anything.

So every question also carries an `expected_answer_contract`: what the answer
must be shaped like, which claim templates must appear in it, which locators
those claims must be bound to, and which claim classes must not appear at all.

  full_position_conclusion       the answer rules on this position, and an
                                 engine check that reached a verdict backs it
  conditional_rule_explanation   the answer states what the rule says, in the
                                 rule's own terms, and explicitly draws no
                                 conclusion about this position
  source_boundary_only           the answer reports which text governs and
                                 nothing further
  explicit_abstention            the answer declines, for the named reason

The templates named have to exist. Where no template can state a rule, that is
a coverage debt — and never a licence to fall back to free text, which this
surface has no way to accept anyway.

Coverage debts
--------------
Every gap the corpus measured lives in one ledger, `coverage_debts[]` at the
top of the corpus, so gaps of different kinds can be counted and ordered
together instead of one kind sitting in a contract field and another in a
note:

  id           the debt's name; for class `template`, the template it names
  class        template | state_builder | engine | source | policy
  blocks       answer_contract | position_conclusion | source_explanation
  owner        the module or package that closes it
  observed_in  the questions that measured it — at least one
  trigger      the measured event that raised it, in the pipeline's own words
  status       open | closed

A question's `template_coverage_debt` is derived from this ledger — the open
template debts that observe the question — and a corpus that stores that
field is refused, so there is one truth about what is missing. An open
template debt must name a template the surface does not have; a closed one
must name a template it has. The tournament-policy red line is a decision,
not a gap: no debt may observe a question that abstains by policy.

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
import re
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
                   "expected_answer_contract", "correction_record", "zh_hant", "notes"}

CORRECTION_FIELDS = {"observed", "decided", "follow_up"}

DEBT_FIELDS = {"id", "class", "blocks", "owner", "observed_in", "trigger", "status", "review_by"}
DEBT_CLASSES = ("template", "state_builder", "engine", "source", "policy")
DEBT_BLOCKS = ("answer_contract", "position_conclusion", "source_explanation")
DEBT_STATUSES = ("open", "closed")
# owner: which track closes the debt, and under which package. Both closed. A
# package id names real work; a debt no package has been opened for carries
# package_id null, and then it must say when it is next looked at
# (review_by) and what would force that look sooner (a triage trigger).
OWNER_FIELDS = {"track", "package_id"}
DEBT_TRACKS = ("answer_surface", "state_builder", "engine", "rules_index", "policy")
PACKAGE_IDS = ("S-01", "S-01b", "S-01c", "S-01d", "S-02", "S-03", "S-04", "S-04d", "S-05", "I-01",
               "T-01", "T-02")
TRIAGE_KIND = "triage_required"
# What would pull an unscheduled debt into triage before its review date:
# the stop rules the loop already runs on the ledger, plus the date itself.
TRIAGE_THRESHOLDS = ("recurrence_at_3", "family_fully_blocked", "review_by_reached")
DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# trigger: the kind of measured event that raised the debt, fixed by class,
# and the condition — a template id, a slot name, a reason code, a retrieval
# status — checked by kind against the module that owns that vocabulary.
TRIGGER_FIELDS = {"kind", "threshold_or_condition"}
TRIGGER_KIND_BY_CLASS = {
    "template": "template_missing",
    "state_builder": "slot_missing",
    "engine": "engine_declined",
    "source": "source_not_retrievable",
    "policy": "policy_decision_pending",
}
CODE_SHAPE = re.compile(r"^[a-z][a-z0-9_]*$")
# Derived onto every contract from the ledger, never stored on the question.
DERIVED_DEBT_FIELD = "template_coverage_debt"

ANSWER_SCOPES = ("full_position_conclusion", "conditional_rule_explanation",
                 "source_boundary_only", "explicit_abstention")

STORED_CONTRACT_FIELDS = {"answer_scope", "required_claims", "required_source_locators",
                          "forbidden_claim_classes"}
# Derived onto every contract from required_claims, never stored.
DERIVED_TEMPLATES_FIELD = "required_templates"
# The in-memory contract: the stored fields plus the two derived lists.
CONTRACT_FIELDS = STORED_CONTRACT_FIELDS | {DERIVED_DEBT_FIELD, DERIVED_TEMPLATES_FIELD}
CLAIM_BINDING_FIELDS = {"template", "slots"}

# Which scopes each tier may take. A tier-A answer that only explains a rule has
# not used the engine verdict it claims to rest on; a tier-C answer that
# concludes about the position is not an abstention.
SCOPES_BY_TIER = {
    "A": ("full_position_conclusion",),
    "B": ("conditional_rule_explanation", "source_boundary_only"),
    "C": ("explicit_abstention",),
}

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

    errors.extend(f"{label}: {problem}" for problem in
                  _contract_errors(question["expected_answer_contract"], tier))

    record = question["correction_record"]
    if record is not None:
        # A recorded difference says what came back, what was decided about it,
        # and what is left to do. A record that only says "known issue" is how a
        # corpus stops being a test.
        if not isinstance(record, dict) or set(record) != CORRECTION_FIELDS:
            errors.append(f"{label}: correction_record must carry exactly "
                          f"{sorted(CORRECTION_FIELDS)}")
        else:
            for field in ("observed", "decided"):
                if not _nonempty(record[field]):
                    errors.append(f"{label}: correction_record.{field} must say what it says")
            if record["follow_up"] is not None and not _nonempty(record["follow_up"]):
                errors.append(f"{label}: correction_record.follow_up is null or a description")

    zh = question["zh_hant"]
    if zh is not None:
        if not isinstance(zh, dict) or set(zh) != {"question"} or not _nonempty(zh["question"]):
            errors.append(f"{label}: zh_hant must be null or {{question: <non-empty string>}}")

    if question["notes"] is not None and not _nonempty(question["notes"]):
        errors.append(f"{label}: notes must be null or a non-empty string")
    return errors


def _known_templates() -> dict[str, dict[str, Any]]:
    return rule_consult_command.CLAIM_TEMPLATES


def _slot_value_ok(slot_type: str, value: Any) -> bool:
    """Whether a pinned slot value is one the answer surface could bind.

    The corpus has no run context, so slots that are only checkable against a
    position (a player, an assumption, a snapshot) are checked for shape here
    and against the position by the run. Everything else — the closed
    lexicons, the step names, a number — is the surface's own admission rule.
    """
    if slot_type in ("player", "assumption_slot", "card_snapshot"):
        return _nonempty(value)
    if slot_type == "locator":
        return isinstance(value, str) and bool(rule_consult_command.LOCATOR_SHAPE.match(value))
    spec = rule_consult_command.SLOT_TYPES.get(slot_type)
    return bool(spec) and bool(spec["admits"]({}, value))


def _contract_errors(contract: Any, tier: Any) -> list[str]:
    """Check the answer contract: shape, scope against tier, and declared debt."""
    if not isinstance(contract, dict) or set(contract) != CONTRACT_FIELDS:
        return [f"expected_answer_contract must carry exactly {sorted(CONTRACT_FIELDS)}"]
    errors: list[str] = []
    scope = contract["answer_scope"]
    if scope not in ANSWER_SCOPES:
        errors.append(f"answer_scope must be one of {list(ANSWER_SCOPES)}")
    elif tier in SCOPES_BY_TIER and scope not in SCOPES_BY_TIER[tier]:
        errors.append(f"a tier-{tier} answer is scoped {list(SCOPES_BY_TIER[tier])}, not {scope!r}")

    for field in ("required_templates", "required_source_locators", "forbidden_claim_classes",
                  "template_coverage_debt"):
        if not isinstance(contract[field], list) or any(not _nonempty(v) for v in contract[field]):
            errors.append(f"{field} must be an array of non-empty strings")
            return errors

    known = _known_templates()
    # A required claim pins its slot values. The same template with other
    # values is a different claim, and a contract that named only the template
    # would be met by any of them.
    claims = contract["required_claims"]
    if not isinstance(claims, list):
        errors.append("required_claims must be an array of {template, slots}")
        return errors
    for index, claim in enumerate(claims):
        label = f"required_claims[{index}]"
        if not isinstance(claim, dict) or set(claim) != CLAIM_BINDING_FIELDS:
            errors.append(f"{label} carries exactly template and slots")
            continue
        if not _nonempty(claim["template"]) or not isinstance(claim["slots"], dict):
            errors.append(f"{label}: template is a name and slots is an object")
            continue
        template = known.get(claim["template"])
        if template is None:
            continue  # unknown: declared as debt, or refused below as a typo
        if set(claim["slots"]) != set(template["slots"]):
            errors.append(f"{label}: {claim['template']} takes exactly {sorted(template['slots'])}")
            continue
        for slot, value in claim["slots"].items():
            if not _slot_value_ok(template["slots"][slot], value):
                errors.append(f"{label}.slots.{slot}={value!r} is not a value of "
                              f"{template['slots'][slot]}; a slot is a choice, not free text")
        if (incoherent := template.get("coheres", lambda s: None)(claim["slots"])) is not None \
                and all(_slot_value_ok(template["slots"][s], v) for s, v in claim["slots"].items()):
            errors.append(f"{label} does not cohere: {incoherent}")
    if any(e.startswith("required_claims[") for e in errors):
        return errors
    derived_templates = [c["template"] for c in claims]
    if contract[DERIVED_TEMPLATES_FIELD] != derived_templates:
        errors.append(f"required_templates is derived from required_claims; it reads "
                      f"{contract[DERIVED_TEMPLATES_FIELD]} against {derived_templates}")
    debt = contract["template_coverage_debt"]
    missing = [name for name in contract["required_templates"] if name not in known]
    # Debt is declared, never inferred. A question may name a template that does
    # not exist yet, but it must say so and say exactly which - otherwise a
    # typo and an unwritten template look the same.
    if sorted(missing) != sorted(debt):
        errors.append(f"required_templates names {missing or 'no'} template(s) this build does "
                      f"not have, and template_coverage_debt declares {debt or 'none'}; they "
                      f"must be the same set")
    for name in debt:
        if name in known:
            errors.append(f"template_coverage_debt names {name!r}, which exists")

    classes = {known[name]["class"] for name in contract["required_templates"] if name in known}
    forbidden = set(contract["forbidden_claim_classes"])
    if unknown := sorted(forbidden - set(rule_consult_command.CLAIM_CLASSES)):
        errors.append(f"forbidden_claim_classes names unknown classes {unknown}")
    if overlap := sorted(classes & forbidden):
        errors.append(f"the contract requires templates of class {overlap}, which it also forbids")

    if scope == "full_position_conclusion":
        # The rule Codex named: a tier-A answer needs an engine-backed position
        # claim, not a citation that happens to be correct.
        if "position_conclusion" not in classes and not debt:
            errors.append("a full position conclusion requires at least one position_conclusion "
                          "template, backed by an engine check that reached a verdict")
        if not contract["required_templates"]:
            errors.append("a full position conclusion names the templates that must carry it")
    elif scope == "conditional_rule_explanation":
        # And the rule the JC-TPC-012 measurement produced: reporting that a
        # locator was retrieved is not explaining what it says.
        if "conditional_rule" not in classes and not debt:
            errors.append("a conditional rule explanation requires a conditional_rule template; "
                          "reporting that a locator was retrieved explains nothing")
        if "position_conclusion" in classes:
            errors.append("a conditional rule explanation draws no conclusion about the position")
        if not contract["required_source_locators"]:
            errors.append("a conditional rule explanation names the locators it explains")
    elif scope == "source_boundary_only":
        if "position_conclusion" in classes:
            errors.append("a source boundary answer draws no conclusion about the position")
        if not contract["required_source_locators"]:
            errors.append("a source boundary answer names the text it reports")
    elif scope == "explicit_abstention":
        if contract["required_templates"]:
            errors.append("an abstention carries no claims, so it requires no templates")
        if contract["required_source_locators"]:
            errors.append("an abstention cites nothing, because it does not answer")
    return errors


def _requires_unknown(question: dict[str, Any], template_id: str) -> bool:
    """Whether the question's contract asks for this template and the surface lacks it."""
    contract = question.get("expected_answer_contract") or {}
    return template_id not in _known_templates() and any(
        isinstance(c, dict) and c.get("template") == template_id
        for c in (contract.get("required_claims") or []))


def validate_debts(corpus: dict[str, Any]) -> list[str]:
    """Check the coverage-debt ledger: shape, vocabulary, and what it points at.

    A debt's status is not taken on trust. An open template debt must name a
    template the surface lacks and some observed question must still ask for
    it; a closed one may block nobody. An open state-builder debt names a slot
    the builder does not have; a closed one names a slot it has.
    """
    debts = corpus.get("coverage_debts")
    if not isinstance(debts, list):
        return ["coverage_debts must be an array"]
    questions = {q.get("question_id"): q for q in corpus.get("questions", []) if isinstance(q, dict)}
    by_policy = {qid for qid, q in questions.items() if q.get("abstention_contract") in POLICY_ABSTENTIONS}
    known = _known_templates()
    errors: list[str] = []
    seen: set[str] = set()
    for index, debt in enumerate(debts):
        label = f"coverage_debts[{index}]"
        if not isinstance(debt, dict) or set(debt) != DEBT_FIELDS:
            errors.append(f"{label}: a debt carries exactly {sorted(DEBT_FIELDS)}")
            continue
        if not _nonempty(debt["id"]):
            errors.append(f"{label}: id must be a non-empty string")
            continue
        label = f"coverage_debts[{debt['id']}]"
        if debt["id"] in seen:
            errors.append(f"{label}: id is used more than once")
        seen.add(debt["id"])
        cls = debt["class"]
        if cls not in DEBT_CLASSES:
            errors.append(f"{label}: class must be one of {list(DEBT_CLASSES)}")
            continue
        if debt["blocks"] not in DEBT_BLOCKS:
            errors.append(f"{label}: blocks must be one of {list(DEBT_BLOCKS)}")
        status = debt["status"]
        if status not in DEBT_STATUSES:
            errors.append(f"{label}: status must be one of {list(DEBT_STATUSES)}")

        owner = debt["owner"]
        scheduled = None
        if not isinstance(owner, dict) or set(owner) != OWNER_FIELDS:
            errors.append(f"{label}: owner carries exactly {sorted(OWNER_FIELDS)}; not a description")
        else:
            if owner["track"] not in DEBT_TRACKS:
                errors.append(f"{label}: owner.track must be one of {list(DEBT_TRACKS)}")
            if owner["package_id"] is None:
                scheduled = False
            elif owner["package_id"] in PACKAGE_IDS:
                scheduled = True
            else:
                errors.append(f"{label}: owner.package_id must be null or one of {list(PACKAGE_IDS)}")
        if scheduled is False and status == "closed":
            errors.append(f"{label}: a closed debt names the package that closed it")

        # review_by: only an unscheduled debt has one, and it must have one.
        review_by = debt["review_by"]
        if scheduled is False:
            if not (isinstance(review_by, str) and DATE_SHAPE.match(review_by)):
                errors.append(f"{label}: a debt with no package carries review_by as YYYY-MM-DD")
        elif scheduled is True and review_by is not None:
            errors.append(f"{label}: a debt with a package carries no review_by; the package "
                          f"is its review")

        trigger = debt["trigger"]
        if not isinstance(trigger, dict) or set(trigger) != TRIGGER_FIELDS:
            errors.append(f"{label}: trigger carries exactly {sorted(TRIGGER_FIELDS)}; not a description")
            trigger = None
        elif scheduled is False:
            # No package: the trigger is what forces triage, from the closed
            # list of things that do. The class-specific condition checks
            # below do not apply; nothing owns this debt yet.
            if trigger["kind"] != TRIAGE_KIND:
                errors.append(f"{label}: a debt with no package is triggered by {TRIAGE_KIND!r}, "
                              f"not {trigger['kind']!r}")
            elif trigger["threshold_or_condition"] not in TRIAGE_THRESHOLDS:
                errors.append(f"{label}: a triage threshold is one of {list(TRIAGE_THRESHOLDS)}")
            trigger = None
        elif scheduled and trigger["kind"] == TRIAGE_KIND:
            errors.append(f"{label}: {TRIAGE_KIND!r} is for a debt with no package; this one is "
                          f"owned by {owner['package_id']!r}")
            trigger = None
        elif trigger["kind"] != TRIGGER_KIND_BY_CLASS[cls]:
            errors.append(f"{label}: a {cls} debt is triggered by {TRIGGER_KIND_BY_CLASS[cls]!r}, "
                          f"not {trigger['kind']!r}")
            trigger = None

        observed = debt["observed_in"]
        if not isinstance(observed, list) or not observed or any(not _nonempty(v) for v in observed):
            errors.append(f"{label}: observed_in names at least one question; a debt nobody "
                          f"measured is a wish")
            observed = []
        for qid in observed:
            if qid not in questions:
                errors.append(f"{label}: observed_in names {qid!r}, which is not in the corpus")
            elif qid in by_policy:
                errors.append(f"{label}: observed_in names {qid!r}, which abstains by policy; "
                              f"the red line is a decision, not a debt")
        observers = [questions[qid] for qid in observed if qid in questions]

        condition = trigger["threshold_or_condition"] if trigger else None
        if cls == "template":
            if trigger and condition != debt["id"]:
                errors.append(f"{label}: a template debt's condition is the template it lacks, "
                              f"its own id; it reads {condition!r}")
            if status == "open" and debt["id"] in known:
                errors.append(f"{label}: an open template debt names {debt['id']!r}, which the "
                              f"answer surface has")
            if status == "open" and observers and not any(_requires_unknown(q, debt["id"]) for q in observers):
                errors.append(f"{label}: an open template debt must still be required by a question "
                              f"it observes; none asks for {debt['id']!r}")
            if status == "closed" and any(_requires_unknown(q, debt["id"]) for q in observers):
                errors.append(f"{label}: a closed template debt still blocks a question that "
                              f"requires {debt['id']!r}, which the answer surface does not have")
        elif cls == "state_builder" and trigger:
            if not (isinstance(condition, str) and CODE_SHAPE.match(condition)):
                errors.append(f"{label}: a state_builder debt's condition is the slot name it lacks")
            elif status == "open" and condition in state_builder.SLOTS:
                errors.append(f"{label}: an open state_builder debt names slot {condition!r}, "
                              f"which the builder has")
            elif status == "closed" and condition not in state_builder.SLOTS:
                errors.append(f"{label}: a closed state_builder debt names slot {condition!r}, "
                              f"which the builder does not have")
        elif cls == "source" and trigger:
            allowed = sorted(fact_ledger.RETRIEVAL_STATUSES - {"retrieved"})
            if condition not in allowed:
                errors.append(f"{label}: a source debt's condition is a retrieval status {allowed}")
        elif trigger and not (isinstance(condition, str) and CODE_SHAPE.match(condition)):
            errors.append(f"{label}: a {cls} debt's condition is a code, not a description")
    return errors


def derived_template_debt(corpus: dict[str, Any], question_id: str) -> list[str]:
    """The open template debts that observe one question, by template name."""
    return sorted(d["id"] for d in corpus.get("coverage_debts", []) if isinstance(d, dict)
                  and d.get("class") == "template" and d.get("status") == "open"
                  and question_id in (d.get("observed_in") or []))


def attach_debts(corpus: dict[str, Any]) -> dict[str, Any]:
    """The in-memory corpus: every contract carries its derived debt list.

    Recomputed from the ledger every time, so a stale copy cannot survive a
    change to the ledger. The stored file never carries the field.
    """
    out = json.loads(json.dumps(corpus))
    for question in out.get("questions", []):
        if not isinstance(question, dict):
            continue
        contract = question.get("expected_answer_contract")
        if isinstance(contract, dict):
            contract[DERIVED_DEBT_FIELD] = derived_template_debt(out, question.get("question_id"))
            claims = contract.get("required_claims")
            contract[DERIVED_TEMPLATES_FIELD] = [c.get("template") for c in claims
                                                 if isinstance(c, dict)] if isinstance(claims, list) else []
    return out


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
    debts = [d for d in corpus.get("coverage_debts", []) if isinstance(d, dict)]
    open_debts = [d for d in debts if d.get("status") == "open"]
    by_class: dict[str, int] = {}
    by_blocks: dict[str, int] = {}
    blocked: set[str] = set()
    for d in open_debts:
        by_class[d.get("class")] = by_class.get(d.get("class"), 0) + 1
        by_blocks[d.get("blocks")] = by_blocks.get(d.get("blocks"), 0) + 1
        blocked.update(d.get("observed_in") or [])
    return {
        "families": families,
        # Visible in the coverage report rather than buried in a question: a
        # rule the answer surface cannot state is a gap in the service, not a
        # note on one corpus entry. Derived from the ledger, like the contracts.
        "template_coverage_debt": sorted(d["id"] for d in open_debts if d.get("class") == "template"),
        "coverage_debts": {
            "open": len(open_debts), "closed": len(debts) - len(open_debts),
            "by_class": dict(sorted(by_class.items())),
            "by_blocks": dict(sorted(by_blocks.items())),
            "questions_blocked": len(blocked),
        },
        "total_required": TOTAL_QUOTA,
        "total_present": total_present,
        "total_missing": sum(f["missing"] for f in families.values()),
        "complete": all(f["missing"] == 0 for f in families.values()),
    }


REQUIRED_TOP = {"schema_version", "corpus_id", "description", "questions", "coverage_debts",
                "semantic_binding_status", "runtime_authority"}
# The public corpus states readings (template and slot values per locator) as
# expectations. They are proposed and unreviewed here, and the corpus carries
# no authority at run time: only an approved registry on the private pack
# paths can support a B-tier claim. Both are said on the corpus itself, and
# a corpus that claimed otherwise is refused.
SEMANTIC_BINDING_STATUSES = ("proposed_unreviewed",)
RUNTIME_AUTHORITIES = ("none",)


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
    if corpus["semantic_binding_status"] not in SEMANTIC_BINDING_STATUSES:
        errors.append(f"semantic_binding_status must be one of {list(SEMANTIC_BINDING_STATUSES)}; the "
                      f"readings this corpus states are not reviewed here")
    if corpus["runtime_authority"] not in RUNTIME_AUTHORITIES:
        errors.append(f"runtime_authority must be one of {list(RUNTIME_AUTHORITIES)}; a corpus supports no "
                      f"claim at run time, only an approved registry does")
    if not isinstance(corpus["questions"], list):
        errors.append("questions must be an array")
        return errors
    # The stored form carries no derived field. One truth: the ledger.
    for index, question in enumerate(corpus["questions"]):
        contract = question.get("expected_answer_contract") if isinstance(question, dict) else None
        if isinstance(contract, dict) and DERIVED_DEBT_FIELD in contract:
            errors.append(f"questions[{index}]: {DERIVED_DEBT_FIELD} is derived from "
                          f"coverage_debts; it is not stored on the question")
        if isinstance(contract, dict) and DERIVED_TEMPLATES_FIELD in contract:
            errors.append(f"questions[{index}]: {DERIVED_TEMPLATES_FIELD} is derived from "
                          f"required_claims; it is not stored on the question")
    errors.extend(validate_debts(corpus))
    if errors:
        return errors
    derived = attach_debts(corpus)
    seen: set[str] = set()
    for index, question in enumerate(derived["questions"]):
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
