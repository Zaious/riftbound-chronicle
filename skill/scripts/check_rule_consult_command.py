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
import rule_consult_command as rcc_module
import source_semantic_bindings as ssb
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
    # T-02: the readings the fixture text admits. Bound to the fixture table's
    # own hashes, so a claim that pairs legal values the text does not say, or
    # reads text whose hash moved, has nothing to bind to.
    fixture_record = lambda loc: payload["sources"]["table"][loc]["record"]  # noqa: E731

    def fixture_binding(template, slots, review="human_reviewed"):
        record = fixture_record(slots["locator"])
        return {"binding_id": ssb.binding_id(record, template, slots), **record, "template": template,
                "slots": slots, "rendered_text_hash": ssb.rendered_hash(template, slots),
                "source_page": 1, "review_status": review,
                "reviewed_by": "fixture" if review == "human_reviewed" else None,
                "reviewed_at": "2026-09-09" if review == "human_reviewed" else None}

    fixture_registry = {"schema_version": ssb.SCHEMA_VERSION, "status": "fixture", "bindings": [
        fixture_binding("rule_role_holder", {"locator": "Core 312", "occasion": "when_showdown_begins",
                                             "role": "focus", "holder": "applied_contested"}),
        fixture_binding("rule_event_consequence", {"locator": "Core 312", "event": "a_chain_item_is_finalized",
                                                   "consequence": "priority_is_not_passed"}),
        fixture_binding("rule_point_source", {"locator": "Core 312", "source": "holding_a_battlefield"}),
        # Registered but not reviewed: carries no authority.
        fixture_binding("rule_point_source", {"locator": "Core 312", "source": "conquering_a_battlefield"},
                        review="proposed"),
    ]}
    registry = ssb.BindingRegistry(fixture_registry, allow_fixture=True)
    context = {"source_retriever": retriever, "card_snapshots": snapshots, "semantic_bindings": registry}

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

    # --- T-01: the rule families -------------------------------------------
    # Four families, closed lexicons. What is checked: the six literals they
    # absorbed are gone (one truth); a lexicon value outside the table, a
    # number written as a word, and a relation given a number it does not take
    # are each refused by name; a family claim answers at tier B and renders
    # the sentence its lexicons say.
    families = {"rule_action_permission", "rule_role_holder", "rule_step_order", "rule_quantity",
                "rule_event_consequence", "rule_point_source"}
    if missing_families := sorted(families - set(CLAIM_TEMPLATES)):
        failures.append(f"the approved rule families are missing: {missing_families}")
    for absorbed in ("rule_focus_on_showdown_start", "rule_focus_retained_on_pass",
                     "rule_no_priority_no_discretionary", "rule_limited_actions_regardless_of_priority",
                     "rule_no_focus_in_neutral_state", "rule_newest_item_resolves",
                     "rule_finalizing_does_not_pass_priority"):
        if absorbed in CLAIM_TEMPLATES:
            failures.append(f"{absorbed} was absorbed by a family and must not survive beside it")

    def family_run(binding):
        return run_consultation(
            question="What does the rule say?", entry="timing", draft=timing_draft,
            entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                     "timing": "default"}},
            claims=[binding], **context)

    good_family = family_run({"template": "rule_role_holder",
                              "slots": {"locator": "Core 312", "occasion": "when_showdown_begins",
                                        "role": "focus", "holder": "applied_contested"}})
    if good_family["status"] != "answered" or good_family["tier"] != "B":
        failures.append(f"a family claim must answer at tier B; got "
                        f"{good_family['status']}/{good_family['tier']}/{good_family['detail'][:100]}")
    elif good_family["claims"][0]["text"] != ("Under Core 312, as a Showdown begins, Focus is held "
                                              "by the player who applied Contested status to the "
                                              "Battlefield."):
        failures.append(f"a family claim renders its lexicons; got {good_family['claims'][0]['text']!r}")
    elif good_family["claims"][0]["source"] != "official_text:Core 312":
        failures.append(f"a family claim's source is its locator; got {good_family['claims'][0]['source']!r}")

    family_refusals = [
        ("a lexicon value outside the table",
         {"template": "rule_action_permission",
          "slots": {"locator": "Core 312", "actor": "p1", "modality": "may",
                    "action": "take_a_discretionary_action", "condition": "unconditionally"}},
         "not one of this run's rule_actor values"),
        ("a sentence in a lexicon slot",
         {"template": "rule_step_order",
          "slots": {"locator": "Core 312", "first": "assigning_combat_damage",
                    "relation": "the attacker wins and the defender loses",
                    "second": "dealing_combat_damage"}},
         "not one of this run's rule_order_relation values"),
        ("a number written as a word",
         {"template": "rule_quantity",
          "slots": {"locator": "Core 312", "quantity": "victory_score_by_default",
                    "relation": "is", "value": "eight"}},
         "not one of this run's rule_value values"),
        ("a relation that states a number, given none",
         {"template": "rule_quantity",
          "slots": {"locator": "Core 312", "quantity": "victory_score_by_default",
                    "relation": "is", "value": None}},
         "does not cohere"),
        ("a relation that takes no number, given one",
         {"template": "rule_quantity",
          "slots": {"locator": "Core 312", "quantity": "shield_value_from_several_sources",
                    "relation": "is_the_sum_of_the_values", "value": 4}},
         "does not cohere"),
        ("a boolean where a number goes",
         {"template": "rule_quantity",
          "slots": {"locator": "Core 312", "quantity": "victory_score_by_default",
                    "relation": "is", "value": True}},
         "not one of this run's rule_value values"),
    ]
    for label, binding, expected in family_refusals:
        refused = family_run(binding)
        if refused["not_attempted_reason"] != "claim_binding_invalid" or expected not in refused["detail"]:
            failures.append(f"{label} must be refused as claim_binding_invalid ({expected!r}); got "
                            f"{refused['status']}/{refused['not_attempted_reason']}: {refused['detail'][:120]}")

    # --- T-02: semantic binding ----------------------------------------------
    # Legal values in every slot, and still refused: the registry never
    # recorded this reading of this text. Then the same reading against text
    # whose hash moved, a T-01 family with the wrong slot pairing, a locator
    # that was not retrieved, and a run with no registry at all.
    event_ok = {"template": "rule_event_consequence",
                "slots": {"locator": "Core 312", "event": "a_chain_item_is_finalized",
                          "consequence": "priority_is_not_passed"}}
    good_event = family_run(event_ok)
    if good_event["status"] != "answered" or good_event["tier"] != "B":
        failures.append(f"a registered event reading must answer at tier B; got "
                        f"{good_event['status']}/{good_event['not_attempted_reason']}: {good_event['detail'][:120]}")
    elif good_event["claims"][0]["text"] != "Under Core 312, when a Chain Item is finalized, Priority is not passed.":
        failures.append(f"the event family renders its lexicons; got {good_event['claims'][0]['text']!r}")
    if verify_run(good_event, **context):
        failures.append("a registered reading must verify against the registry it was bound on")
    expected_id = ssb.binding_id(fixture_record("Core 312"), "rule_event_consequence", event_ok["slots"])
    if good_event["claims"][0]["binding_id"] != expected_id:
        failures.append(f"a rule claim records the reviewed binding it rests on; got "
                        f"{good_event['claims'][0]['binding_id']!r}")
    if good_family["claims"][0]["binding_id"] is None or good_family["claims"][1:] and any(
            c["binding_id"] is not None for c in good_family["claims"][1:]):
        failures.append("only rule claims carry a binding id")
    # A registry that is proposed, or a fixture outside its gate, carries no authority.
    for label, kwargs, status in (("a proposed registry", {}, "proposed"),
                                  ("a fixture registry outside its gate", {}, "fixture")):
        try:
            ssb.BindingRegistry({**fixture_registry, "status": status,
                                 "bindings": [dict(b, review_status="proposed", reviewed_by=None, reviewed_at=None)
                                              if status == "proposed" else b
                                              for b in fixture_registry["bindings"]]}, **kwargs)
        except ValueError:
            pass
        else:
            failures.append(f"{label} must carry no authority")
    # A run that bound a reading does not verify with a binding id swapped in.
    swapped = copy.deepcopy(good_event)
    swapped["claims"][0]["binding_id"] = "ssb-" + "0" * 24
    swapped["run_hash"] = rcc_module.canonical_hash({k: v for k, v in swapped.items() if k != "run_hash"})
    if not any("binding_id" in p for p in verify_run(swapped, **context)):
        failures.append("a swapped binding id must fail verification by name")

    semantic_refusals = [
        ("legal event and legal consequence the text does not pair",
         {"template": "rule_event_consequence",
          "slots": {"locator": "Core 312", "event": "a_player_wins",
                    "consequence": "priority_is_not_passed"}}, context,
         "not a reviewed reading"),
        ("a T-01 family with the wrong slot pairing for its locator",
         {"template": "rule_role_holder",
          "slots": {"locator": "Core 312", "occasion": "when_showdown_begins", "role": "focus",
                    "holder": "the_attacker"}}, context,
         "not a reviewed reading"),
        ("a registered reading of a locator the retriever does not have",
         {"template": "rule_event_consequence",
          "slots": {"locator": "Core 999", "event": "a_chain_item_is_finalized",
                    "consequence": "priority_is_not_passed"}}, context,
         "was not retrieved"),
        ("a rule claim in a run with no registry",
         event_ok, {**context, "semantic_bindings": None},
         "no semantic-binding registry"),
        ("a registered reading whose review status is not human_reviewed",
         {"template": "rule_point_source", "slots": {"locator": "Core 312", "source": "conquering_a_battlefield"}},
         context, "not a reviewed reading"),
    ]
    moved_table = copy.deepcopy(payload["sources"]["table"])
    moved_table["Core 312"]["record"]["text_hash"] = "sha256:" + "e" * 64
    moved = TableRetriever(moved_table, payload["sources"]["surfaced"])
    semantic_refusals.append(
        ("the registered reading, against the same locator whose text hash moved",
         event_ok, {**context, "source_retriever": moved}, "not a reviewed reading"))
    versioned_table = copy.deepcopy(payload["sources"]["table"])
    versioned_table["Core 312"]["record"]["document_version"] = "2027-01-01"
    versioned = TableRetriever(versioned_table, payload["sources"]["surfaced"])
    semantic_refusals.append(
        ("the registered reading, against a later document version",
         event_ok, {**context, "source_retriever": versioned}, "not a reviewed reading"))
    for label, binding, ctx, expected in semantic_refusals:
        refused = run_consultation(
            question="What does the rule say?", entry="timing", draft=timing_draft,
            entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                     "timing": "default"}},
            claims=[binding], **ctx)
        if refused["not_attempted_reason"] != "claim_binding_invalid" or expected not in refused["detail"]:
            failures.append(f"{label} must be refused as claim_binding_invalid ({expected!r}); got "
                            f"{refused['status']}/{refused['not_attempted_reason']}: {refused['detail'][:140]}")
    # A run bound on one registry does not verify against a context whose
    # text moved: verification re-runs, and the reading no longer binds.
    if not verify_run(good_event, **{**context, "source_retriever": moved}):
        failures.append("a rule claim must fail verification once its locator's text hash moved")
    for name, table in (("RULE_ACTORS", rcc_module.RULE_ACTORS), ("RULE_CONDITIONS", rcc_module.RULE_CONDITIONS),
                        ("RULE_EVENTS", rcc_module.RULE_EVENTS), ("RULE_CONSEQUENCES", rcc_module.RULE_CONSEQUENCES),
                        ("RULE_POINT_SOURCES", rcc_module.RULE_POINT_SOURCES),
                        ("RULE_OCCASIONS", rcc_module.RULE_OCCASIONS), ("RULE_ROLES", rcc_module.RULE_ROLES),
                        ("RULE_HOLDERS", rcc_module.RULE_HOLDERS), ("RULE_STEPS", rcc_module.RULE_STEPS),
                        ("RULE_QUANTITIES", rcc_module.RULE_QUANTITIES)):
        for value, phrase in table.items():
            if "." in phrase or "." in value:
                failures.append(f"{name}[{value!r}] would render a second sentence")

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
          f"forgeries refused by verify_run: {forgeries}; "
          f"rule-family bindings refused: {len(family_refusals)}; "
          f"semantic bindings refused: {len(semantic_refusals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
