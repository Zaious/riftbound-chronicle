#!/usr/bin/env python3
"""Executable checks for consultation-run.v1, the S-03 unified command.

Nothing here is stubbed. Every case runs the real pipeline — S-01 builds the
state, one of the five engine entries runs, the evidence pack is built and
re-run, retrieval answers, the claims bind, and S-02's ledger is built and
verified — so a case that passes has been through the same path a caller takes.

The sections after the cases hold the properties the contract turns on:

  * every entry has a path that answers and a path that does not, and the ones
    that do not name a reason from a closed vocabulary rather than writing prose;
  * all three tiers come out of the one path: A carries a position conclusion,
    B carries only source statements, C is an abstention;
  * a declined engine ruling puts every position conclusion out of reach and
    cannot be answered around with a locator;
  * the answer surface admits no free text, in any slot, of any template, and
    no source-statement template can be bent into a legality answer;
  * one claim is exactly one ledger entry;
  * the evidence pack re-runs to an equal hash, for all five kinds.

Then the forgeries. validate_run reads no context, so a run that rewrites what
its sources were worth and reseals its hash passes it. Each forgery below is
first shown to pass structural validation — that is the point being made, not
a defect being tolerated — and then refused by verify_run, which re-runs the
consultation from the run's own request and compares.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import effect_ir
import fact_ledger
import legal_action
import rule_consult_command as rcc
import state_builder
import verify_evidence_pack as evidence
from rule_consult_command import (
    CLAIM_TEMPLATES,
    COVERAGE_STATEMENT,
    ENTRIES,
    LEGALITY_VOCABULARY,
    NOT_ATTEMPTED_REASONS,
    SLOT_TYPES,
    TableRetriever,
    render,
    run_consultation,
    template_slot_types,
    validate_run,
    verify_run,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
CASES = SKILL_DIR / "data" / "rule_consult_command_cases.json"

TARGET = {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit",
          "location": "base", "controller_relation": "enemy"}


def programs() -> dict[str, dict]:
    base = {"schema_version": effect_ir.PROGRAM_VERSION,
            "ruleset": {"core": effect_ir.CORE_RULESET, "faq_as_of": effect_ir.FAQ_AS_OF},
            "controller": "p1"}
    return {
        "@applying_program": {**base, "program_id": "burn-1",
                              "effects": [{"op": "deal_damage", "target": TARGET, "amount": 1,
                                           "source_object": "u1"}]},
        # Recognized but not evaluated in a program, and the draw behind it runs
        # into the empty deck S-01 flagged as material. The engine stops.
        "@declining_program": {**base, "program_id": "kill-then-draw",
                               "effects": [{"op": "draw", "player": "p1", "count": 1,
                                            "condition": {"kind": "caused_kill", "effect_id": "e1"}}]},
    }


def observation(timing_state, effect_state):
    return legal_action.build_observation(
        perspective="player1", source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": "2026-07-16", "faq_as_of": "2026-07-16",
                 "format": "standard", "card_data_version": "r3a1"},
        timing_state=timing_state, effect_state=effect_state, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete",
                      "pending_decisions": "complete"})


def main() -> int:
    failures: list[str] = []
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = payload["cases"]
    retriever = TableRetriever(payload["sources"]["table"], payload["sources"]["surfaced"])
    snapshots = payload["card_snapshots"]
    timing_draft, effect_draft = payload["timing_draft"], payload["effect_draft"]

    timing_state = state_builder.build_state_assumption(
        question="probe", question_kind="timing_priority", draft=timing_draft)["state"]
    effect_state = state_builder.build_state_assumption(
        question="probe", question_kind="unit_damage", draft=effect_draft)["state"]
    substitutions = {**programs(), "@observation": observation(timing_state, effect_state)}
    context = {"source_retriever": retriever, "card_snapshots": snapshots}

    def resolve(value):
        if isinstance(value, str) and value.startswith("@"):
            return substitutions[value]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    ran: dict[str, dict] = {}
    seen_reasons: set[str] = set()
    entry_paths: dict[str, set[str]] = {entry: set() for entry in ENTRIES}
    tier_cases: set[str] = set()

    for case in cases:
        case_id = case["case_id"]
        expected = case["expected"]
        result = run_consultation(
            question=case["question"], entry=case["entry"],
            draft=case.get("draft_override", timing_draft),
            effect_draft=None if case.get("omit_effect_draft") else effect_draft,
            entry_inputs=resolve(case["entry_inputs"]),
            claims=case["claims"], **context)
        ran[case_id] = result

        if problems := validate_run(result):
            failures.append(f"{case_id}: its own run does not validate: {problems}")
        if problems := verify_run(result, **context):
            failures.append(f"{case_id}: its own run does not verify against the context "
                            f"it was built on: {problems}")
        if result["status"] != expected["status"]:
            failures.append(f"{case_id}: status {result['status']!r}, expected {expected['status']!r} "
                            f"({result['not_attempted_reason']}: {result['detail'][:120]})")
            continue
        if result["tier"] != expected["tier"]:
            failures.append(f"{case_id}: tier {result['tier']!r}, expected {expected['tier']!r}")
        if "engine_declined" in expected and result["engine_declined"] is not expected["engine_declined"]:
            failures.append(f"{case_id}: engine_declined {result['engine_declined']}, "
                            f"expected {expected['engine_declined']}")
        if case["entry"] in entry_paths:
            entry_paths[case["entry"]].add(case["path"])
        if "tier_case" in case:
            tier_cases.add(case["tier_case"])

        if result["status"] == "not_attempted":
            seen_reasons.add(result["not_attempted_reason"])
            if result["not_attempted_reason"] != expected["reason"]:
                failures.append(f"{case_id}: reason {result['not_attempted_reason']!r}, "
                                f"expected {expected['reason']!r} ({result['detail'][:120]})")
            if result["claims"] or result["ledger"] is not None:
                failures.append(f"{case_id}: a run that was not attempted must carry no answer")
            continue

        if len(result["claims"]) != expected["claims"]:
            failures.append(f"{case_id}: {len(result['claims'])} claims, expected {expected['claims']}")
        # One claim, one ledger entry. Not "about the same number".
        if len(result["ledger"]["entries"]) != len(result["claims"]):
            failures.append(f"{case_id}: {len(result['claims'])} claims produced "
                            f"{len(result['ledger']['entries'])} ledger entries")
        for position, (claim, entry) in enumerate(zip(result["claims"], result["ledger"]["entries"])):
            if entry["text"] != claim["text"]:
                failures.append(f"{case_id}: ledger entry {position} is not claim {position}")
            if entry["mechanical"] is not True:
                failures.append(f"{case_id}: a claim reached the ledger as non-mechanical")
        if "violations" in expected:
            codes = sorted({v["code"] for v in result["ledger"]["violations"]})
            if codes != sorted(set(expected["violations"])):
                failures.append(f"{case_id}: violations {codes}, expected "
                                f"{sorted(set(expected['violations']))}")
        # A tier-B run must not be carrying a position conclusion, and a tier-A
        # run must be.
        classes = {claim["claim_class"] for claim in result["claims"]}
        if result["tier"] == "A" and "position_conclusion" not in classes:
            failures.append(f"{case_id}: tier A without a position conclusion")
        if result["tier"] == "B" and "position_conclusion" in classes:
            failures.append(f"{case_id}: tier B while carrying a position conclusion")

    for entry, paths in entry_paths.items():
        if paths != {"happy", "failure"}:
            failures.append(f"the {entry} entry needs a path that answers and one that does not; "
                            f"saw {sorted(paths)}")
    if tier_cases != {"A", "B", "C"}:
        failures.append(f"all three tiers must come out of this path; cases cover {sorted(tier_cases)}")

    # --- the declined ruling, and the B route it leaves ----------------------
    declined = ran["CR-004"]
    if not declined["engine_declined"] or declined["coverage_statement"] != COVERAGE_STATEMENT:
        failures.append("a declined ruling must be named and carry the coverage statement")
    if declined["engine_check"]["outcome"] in fact_ledger.DECIDING_OUTCOMES:
        failures.append("CR-004 needs an engine check that did not decide")
    if declined["claims"]:
        failures.append("a declined ruling produced a position conclusion anyway")

    # The B route after a decline: text is reported, and nothing is concluded
    # about the position.
    boundary = ran["CR-005"]
    if boundary["tier"] != "B" or boundary["status"] != "answered":
        failures.append(f"a declined ruling with a source statement is a tier-B answer; "
                        f"got {boundary['status']}/{boundary['tier']}")
    if any(c["claim_class"] == "position_conclusion" for c in boundary["claims"]):
        failures.append("the B route produced a position conclusion")
    if boundary["coverage_statement"] != COVERAGE_STATEMENT:
        failures.append("a tier-B answer after a decline must carry the coverage statement")

    # And the B route is not a second way to answer the mechanical question:
    # adding a locator claim to a position claim does not rescue it.
    if ran["CR-006"]["status"] != "not_attempted":
        failures.append("a locator does not license a position conclusion the engine declined")

    # A declined run carries the coverage statement even when it carries
    # nothing else. It is derived from the engine's outcome, not attached
    # alongside a successful answer.
    bare = run_consultation(
        question="If my spell kills their unit, do I draw a card?", entry="effect",
        draft=timing_draft, effect_draft=effect_draft,
        entry_inputs={"program": substitutions["@declining_program"]}, claims=[], **context)
    if bare["not_attempted_reason"] != "no_claims_offered":
        failures.append(f"a declined run with no claims stops at no_claims_offered; "
                        f"got {bare['not_attempted_reason']!r}")
    if not bare["engine_declined"] or bare["coverage_statement"] != COVERAGE_STATEMENT:
        failures.append("a declined run carries the coverage statement even with no claims")

    # There is no template that lets a source basis make a position claim. This
    # runs before the cases below that render templates, so a malformed table is
    # reported rather than raised.
    for template_id, template in CLAIM_TEMPLATES.items():
        if template["class"] == "position_conclusion" and template["basis"]["kind"] != "engine":
            failures.append(f"{template_id} concludes about the position without an engine basis")
        if template["class"] == "source_statement":
            if template["basis"]["kind"] == "engine":
                failures.append(f"{template_id} is a source statement resting on the engine")
            if "player" in template["slots"].values():
                failures.append(f"{template_id} is a source statement that names a player")
            # A source statement carries one slot, and that slot is the source
            # it names. More than one and its `source` would be a choice among
            # them, which is a claim doing two jobs.
            if len(template["slots"]) != 1:
                failures.append(f"{template_id} is a source statement with "
                                f"{len(template['slots'])} slots; it names one source")
            folded = template["text"].casefold()
            for word in LEGALITY_VOCABULARY:
                if fact_ledger.markers_in(template["text"]) and word in folded:
                    failures.append(f"{template_id} is a source statement using the legality "
                                    f"vocabulary ({word!r})")

    # --- the answer surface admits no free text -----------------------------
    if unknown := sorted(template_slot_types() - set(SLOT_TYPES)):
        failures.append(f"templates use slot types with no closed rule behind them: {unknown}")
    prose = "You may play a spell, and your opponent cannot respond."
    slot_context = {"timing_state": timing_state, "retriever": retriever,
                    "assumption_slots": {"chain_items", "priority"}, "card_snapshots": snapshots}
    for slot_type, spec in SLOT_TYPES.items():
        if spec["admits"](slot_context, prose):
            failures.append(f"slot type {slot_type!r} admits a sentence")
        if not spec["samples"](slot_context):
            failures.append(f"slot type {slot_type!r} offers no value, so nothing can be said with it")
    free_text = ran["CR-015"]
    if free_text["not_attempted_reason"] != "claim_binding_invalid" or "free text" not in free_text["detail"]:
        failures.append(f"free text in a slot must be refused as such: {free_text['detail'][:120]}")

    for template_id, template in CLAIM_TEMPLATES.items():
        for joiner in (", and ", "; ", " then ", ", but "):
            if joiner in template["text"]:
                failures.append(f"template {template_id!r} joins two claims with {joiner!r}")
        sample = {}
        for slot, slot_type in template["slots"].items():
            values = SLOT_TYPES[slot_type]["samples"](slot_context)
            if not values:
                failures.append(f"template {template_id!r} has no value to render slot {slot!r}")
                sample = None
                break
            sample[slot] = values[0]
        if sample is None:
            continue
        text = render(template_id, sample)
        if fact_ledger.is_multi_sentence(text):
            failures.append(f"template {template_id!r} renders more than one sentence: {text!r}")
        if not text.strip().endswith("."):
            failures.append(f"template {template_id!r} does not render a sentence: {text!r}")

    # A producer cannot author text on the way in: the binding schema takes
    # template and slots and nothing else, so a sentence has no field to arrive
    # in. Without this case a module that quietly preferred a supplied `text`
    # would pass every other check here, because nothing else sends one.
    for extra in ({"text": "p1 may play a spell, and nothing can stop it."},
                  {"ref": "engine-check:0000000000000000000000ff"}):
        smuggled = run_consultation(
            question="May I play a spell?", entry="timing", draft=timing_draft,
            entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                     "timing": "default"}},
            claims=[{"template": "timing_play_permitted",
                     "slots": {"actor": "p1", "object_kind": "spell"}, **extra}],
            **context)
        if smuggled["not_attempted_reason"] != "claim_binding_invalid":
            failures.append(f"a claim binding carrying {sorted(extra)} must be refused; got "
                            f"{smuggled['status']}/{smuggled['not_attempted_reason']}")
        if any("nothing can stop it" in claim["text"] for claim in smuggled["claims"]):
            failures.append("supplied text reached a claim")

    # --- the evidence pack re-runs, for all five kinds ----------------------
    reproduced = {}
    for case_id in ("CR-001", "CR-003", "CR-007", "CR-009", "CR-011"):
        result = ran[case_id]
        pack = result["evidence_pack"]
        verification = evidence.verify_pack(pack)
        reproduced[pack["check_kind"]] = verification["verified"]
        if not verification["verified"]:
            failures.append(f"{case_id}: the pack does not re-run: {verification['reason_code']}")
        if not result["evidence_verification"]["verified"]:
            failures.append(f"{case_id}: the run shipped a pack it had not verified")
    if sorted(reproduced) != sorted({ENTRIES[e]["check_kind"] for e in ENTRIES}):
        failures.append(f"the five entries did not produce five pack kinds: {sorted(reproduced)}")

    # Re-running the same consultation reproduces the same run, hash included.
    first = ran["CR-001"]
    again = run_consultation(
        question=first["question"], entry="timing", draft=timing_draft,
        entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                 "timing": "default"}},
        claims=first["request"]["claim_bindings"], **context)
    for field in ("run_hash", "tier", "status"):
        if again[field] != first[field]:
            failures.append(f"a re-run changed {field}: {first[field]!r} -> {again[field]!r}")
    if again["evidence_pack"]["pack_hash"] != first["evidence_pack"]["pack_hash"]:
        failures.append("a re-run produced a different evidence pack hash")
    if again["ledger"]["ledger_hash"] != first["ledger"]["ledger_hash"]:
        failures.append("a re-run produced a different ledger hash")

    # --- a pack that will not re-run stops the run --------------------------
    original_verify = evidence.verify_pack
    try:
        evidence.verify_pack = lambda pack: {"schema_version": "evidence-verification.v1",
                                             "verified": False, "reason_code": "result_not_reproduced"}
        stopped = run_consultation(
            question="May I play a spell?", entry="timing", draft=timing_draft,
            entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                     "timing": "default"}},
            claims=[{"template": "timing_play_permitted", "slots": {"actor": "p1", "object_kind": "spell"}}],
            **context)
    finally:
        evidence.verify_pack = original_verify
    if stopped["not_attempted_reason"] != "evidence_not_reproducible":
        failures.append(f"a pack that does not re-run must stop the run; got "
                        f"{stopped['not_attempted_reason']!r}")
    seen_reasons.add(stopped["not_attempted_reason"])
    if missing := sorted(NOT_ATTEMPTED_REASONS - seen_reasons):
        failures.append(f"no case exercises the not_attempted reasons {missing}")

    # --- forgeries: structural first, then refused by verify_run ------------
    # Each one is built from a run the cases above produced, edited, and
    # resealed. Each passes validate_run — that is the point being made, not a
    # defect being tolerated — and verify_run refuses it for a named reason.
    def reseal(run):
        run["run_hash"] = rcc.canonical_hash({k: v for k, v in run.items() if k != "run_hash"})
        return run

    def reseal_ledger(run):
        run["ledger"]["ledger_hash"] = rcc.canonical_hash(
            {k: v for k, v in run["ledger"].items() if k != "ledger_hash"})
        return run

    def forge(label, case_id, edit, *, ctx=None, expect, needs_ledger=True):
        """Edit a run from `case_id`, or name what stopped the forgery.

        A forgery whose source run did not come out in the shape it needs is a
        failure to report, not a None to trip over: a gate that dies without
        saying what broke is a worse gate even when its exit code is right.
        """
        run = ran.get(case_id)
        if run is None:
            failures.append(f"forgery {label!r} needs {case_id}, which did not run")
            return
        if needs_ledger and not isinstance(run.get("ledger"), dict):
            failures.append(f"forgery {label!r} needs {case_id} to have produced a ledger; "
                            f"it stopped at {run['status']}/{run['not_attempted_reason']}")
            return
        candidate = copy.deepcopy(run)
        edit(candidate)
        structural = validate_run(candidate)
        if structural:
            failures.append(f"forgery {label!r} should pass structural validation "
                            f"(that is the hole being demonstrated), but got {structural}")
        problems = verify_run(candidate, **(ctx or context))
        if not problems:
            failures.append(f"verify_run accepts the forgery {label!r}")
        elif not any(expect in problem for problem in problems):
            failures.append(f"forgery {label!r} was refused, but not for the right reason: {problems}")

    # G1. A ledger source status rewritten to verified, and the run's verdict
    # rewritten to match. Nothing inside contradicts anything else.
    def _g1(run):
        record = run["ledger"]["entries"][0]["sources"][0]
        record["status"] = "verified"
        record["bound_hash"] = "sha256:" + "aa" * 32
        run["ledger"]["violations"] = []
        run["ledger"]["admissible"] = True
        run["ledger"]["admissible_tier"] = "B"
        reseal_ledger(run)
        run["status"], run["tier"], run["detail"] = "answered", "B", ""
        run["position_statement"] = rcc.POSITION_STATEMENT
        reseal(run)

    forge("ledger source status rewritten to verified", "CR-018", _g1,
          expect="claims status 'verified'; against this context it is 'locator_not_in_index'")

    # G2. The engine check swapped in the pack for one with the same id and a
    # flipped outcome, still structurally a valid engine check.
    def _g2(run):
        run["engine_check"]["outcome"] = "illegal"
        run["evidence_pack"]["engine_check"]["outcome"] = "illegal"
        run["evidence_pack"]["pack_hash"] = rcc.canonical_hash(
            {k: v for k, v in run["evidence_pack"].items() if k != "pack_hash"})
        reseal(run)

    forge("engine check swapped under its own id", "CR-001", _g2,
          expect="evidence pack does not re-run")

    # G3. The locator index moved: the document was revised under the same
    # locator the answer cites.
    revised = copy.deepcopy(payload["sources"]["table"])
    revised["Core 312"]["record"]["text_hash"] = "sha256:" + "ff" * 32
    forge("official text revised under the same locator", "CR-001", lambda run: None,
          ctx={**context, "source_retriever": TableRetriever(revised, {})},
          expect="bound to content that is no longer what the context holds")

    # G4. The card snapshot rewritten under its own id.
    rewritten = copy.deepcopy(snapshots)
    rewritten["synthetic-unit-a"]["text_hash"] = "sha256:" + "ee" * 32
    forge("card snapshot rewritten under the same id", "CR-017", lambda run: None,
          ctx={**context, "card_snapshots": rewritten},
          expect="bound to content that is no longer what the context holds")

    # G5. The state-assumption artifact edited under the run: the answer claims
    # a position that its own request does not build.
    forge("state assumption edited beneath the run", "CR-001",
          lambda run: reseal(run["state_assumptions"][0]["input_draft"].__setitem__("priority", "p2") or run),
          expect="the state this run was built on is not the state its request builds now")

    # G6. The B-tier source binding rewritten in place, with the ledger resealed.
    forge("B-tier source binding rewritten", "CR-017",
          lambda run: reseal(reseal_ledger(
              run["ledger"]["entries"][0]["sources"][0].__setitem__("bound_hash", "sha256:" + "cc" * 32) or run)),
          expect="bound to content that is no longer what the context holds")

    # G7. Nothing about the sources touched: an abstention is simply relabelled
    # an answer, tier and all, and resealed.
    def _g7(run):
        run["status"], run["tier"], run["detail"] = "answered", "B", ""
        run["position_statement"] = rcc.POSITION_STATEMENT
        reseal(run)

    forge("abstention relabelled as a tier-B answer", "CR-019", _g7,
          expect="status claims 'answered'")

    # G8. The claim's slot changed so it says something else, with the ledger
    # and every hash brought into line — but the request it was built from is
    # still in the run.
    def _g8(run):
        run["claims"][0]["slots"]["actor"] = "p2"
        run["claims"][0]["text"] = render("timing_play_permitted",
                                          {"actor": "p2", "object_kind": "spell"})
        run["ledger"]["entries"][0]["text"] = run["claims"][0]["text"]
        run["ledger"]["entries"][0]["markers"] = fact_ledger.markers_in(run["claims"][0]["text"])
        reseal_ledger(run)
        reseal(run)

    forge("a claim's slot changed to say something else", "CR-001", _g8,
          expect="claims[0].slots claims")

    # G9. Everything derived still agrees; only a field no other comparison
    # reads has been rewritten, and the hash resealed. If verify_run stopped
    # comparing the hash, this is what would walk through.
    forge("a field nothing else compares, rewritten and resealed", "CR-019",
          lambda run: reseal(run.__setitem__("detail", "reviewed and found fine") or run),
          expect="run_hash differs")

    forgeries = 9

    # --- the validator refuses the runs a hand-written one would be ---------
    good = copy.deepcopy(ran["CR-001"])
    mutations = [
        ("a claim added without a ledger entry",
         lambda r: r["claims"].append(dict(r["claims"][0], claim_id="claim-3"))),
        ("an answered run at tier C", lambda r: r.__setitem__("tier", "C")),
        ("an abstention that is not tier C", lambda r: r.__setitem__("status", "abstained")),
        ("a not_attempted run that still carries claims",
         lambda r: (r.__setitem__("status", "not_attempted"),
                    r.__setitem__("not_attempted_reason", "no_claims_offered"),
                    r.__setitem__("detail", "x"))),
        ("tier A on a run carrying only source statements",
         lambda r: r["claims"].__setitem__(0, dict(r["claims"][1], claim_id="claim-1"))),
        ("a coverage statement on a run whose engine ruled",
         lambda r: r.__setitem__("coverage_statement", COVERAGE_STATEMENT)),
        ("a claim naming an unknown template",
         lambda r: r["claims"][0].__setitem__("template", "timing_play_whenever")),
        ("a claim whose class is not its template's",
         lambda r: r["claims"][0].__setitem__("claim_class", "source_statement")),
        ("a claim whose slots do not match its template",
         lambda r: r["claims"][0]["slots"].__setitem__("extra", "p1")),
        ("a source that is not one source",
         lambda r: r["claims"][0].__setitem__("source", "Core 312")),
        ("a request that is not this run's",
         lambda r: r["request"].__setitem__("entry", "effect")),
        ("an unknown top-level field", lambda r: r.__setitem__("reviewed_by", "nobody")),
        ("a stale run hash", lambda r: r.__setitem__("question", "something else")),
    ]
    for label, mutate in mutations:
        candidate = copy.deepcopy(good)
        mutate(candidate)
        if not validate_run(candidate):
            failures.append(f"the validator accepts {label}")

    # Two of those turn on a specific rule, so the guard checks which rule
    # fired. Without this a mutation that removed the rule would still be
    # caught — by something else — and the rule would be dead.
    for label, mutate, expected in (
        ("tier A on a run carrying only source statements",
         lambda r: (r["claims"].__setitem__(0, dict(r["claims"][1], claim_id="claim-1")),
                    r["ledger"]["entries"].__setitem__(
                        0, dict(r["ledger"]["entries"][0], text=r["claims"][1]["text"],
                                markers=fact_ledger.markers_in(r["claims"][1]["text"])))),
         "tier A requires a position conclusion"),
        ("a claim whose class is not its template's",
         lambda r: r["claims"][0].__setitem__("claim_class", "source_statement"),
         "is a 'source_statement' claim, but"),
    ):
        candidate = copy.deepcopy(good)
        mutate(candidate)
        problems = validate_run(candidate)
        if not problems:
            failures.append(f"the validator accepts {label}")
        elif not any(expected in problem for problem in problems):
            failures.append(f"{label} was refused, but not by the rule that should have "
                            f"caught it: {problems}")

    # A tier-B run's position statement is derived too, so it cannot be dropped
    # and cannot be attached to a run at another tier.
    for label, case_id, edit in (
        ("a tier-B answer with its position statement removed", "CR-017",
         lambda r: r.__setitem__("position_statement", None)),
        ("a tier-A answer carrying the position statement", "CR-001",
         lambda r: r.__setitem__("position_statement", rcc.POSITION_STATEMENT)),
    ):
        candidate = copy.deepcopy(ran[case_id])
        edit(candidate)
        reseal(candidate)
        if not validate_run(candidate):
            failures.append(f"the validator accepts {label}")

    # A conditional rule is neither a position conclusion nor a bare source
    # statement: it says what the text says without naming anyone here. The
    # template table is what holds that, so it is checked there.
    for template_id, template in CLAIM_TEMPLATES.items():
        if template["class"] != "conditional_rule":
            continue
        if template["basis"]["kind"] == "engine":
            failures.append(f"{template_id} is a conditional rule resting on the engine")
        if "player" in template["slots"].values():
            failures.append(f"{template_id} is a conditional rule that names a player in "
                            f"this position")
        if "locator" not in template["slots"].values():
            failures.append(f"{template_id} states a rule without binding the rule it states")
        if not template["text"].startswith("Under {locator},"):
            failures.append(f"{template_id} must attribute the rule it states to its locator")

    # The declined run's coverage statement is derived, so it cannot be dropped.
    dropped = copy.deepcopy(ran["CR-005"])
    dropped["coverage_statement"] = None
    dropped = reseal(dropped)
    if not validate_run(dropped):
        failures.append("the validator accepts a declined run with its coverage statement removed")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across {len(cases)} consultation cases")
        return 1

    by_status = {s: sum(1 for r in ran.values() if r["status"] == s)
                 for s in ("answered", "abstained", "not_attempted")}
    by_tier = {t: sum(1 for r in ran.values() if r["tier"] == t) for t in ("A", "B", "C")}
    print(f"consultation-run.v1: {len(cases)} cases — {by_status['answered']} answered, "
          f"{by_status['abstained']} abstained, {by_status['not_attempted']} not attempted")
    print(f"tiers A/B/C: {by_tier['A']}/{by_tier['B']}/{by_tier['C']} (all three out of the one path); "
          f"not_attempted reasons exercised: {len(seen_reasons)}/{len(NOT_ATTEMPTED_REASONS)}")
    print(f"claim templates: {len(CLAIM_TEMPLATES)} over {len(SLOT_TYPES)} closed slot types, "
          f"no free-text slot type")
    print(f"evidence packs re-run: {sorted(reproduced)}")
    print(f"structural mutations refused: {len(mutations) + 1}; "
          f"forgeries refused by verify_run: {forgeries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
