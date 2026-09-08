#!/usr/bin/env python3
"""Executable checks for consultation-run.v1, the S-03 unified command.

Nothing here is stubbed. Every case runs the real pipeline — S-01 builds the
state, one of the five engine entries runs, the evidence pack is built and
re-run, the claims bind, and S-02's ledger is built and verified — so a case
that passes has been through the same path a caller would take.

The sections after the cases hold the properties the contract turns on:

  * every entry has a path that answers and a path that does not, and the ones
    that do not name a reason from a closed vocabulary rather than writing
    prose;
  * a declined engine ruling stops the command, and no amount of citable text
    restarts it;
  * the answer surface admits no free text, in any slot, of any template — the
    guarantee that one claim is one assertion;
  * one claim is exactly one ledger entry;
  * the evidence pack re-runs to an equal hash, for all five kinds.
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
    ENTRIES,
    NOT_ATTEMPTED_REASONS,
    SLOT_TYPES,
    render,
    run_consultation,
    template_slot_types,
    validate_run,
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
        # Recognized but not evaluated in a program, and the draw behind it
        # runs into the empty deck S-01 flagged as material. The engine stops.
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
    index = set(payload["locator_index"])
    timing_draft, effect_draft = payload["timing_draft"], payload["effect_draft"]

    timing_state = state_builder.build_state_assumption(
        question="probe", question_kind="timing_priority", draft=timing_draft)["state"]
    effect_state = state_builder.build_state_assumption(
        question="probe", question_kind="unit_damage", draft=effect_draft)["state"]
    substitutions = {**programs(), "@observation": observation(timing_state, effect_state)}

    def resolve(value):
        if isinstance(value, str) and value.startswith("@"):
            return substitutions[value]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    ran: dict[str, dict] = {}
    seen_reasons: set[str] = set()
    entry_paths: dict[str, set[str]] = {entry: set() for entry in ENTRIES}

    for case in cases:
        case_id = case["case_id"]
        expected = case["expected"]
        result = run_consultation(
            question=case["question"], entry=case["entry"],
            draft=case.get("draft_override", timing_draft),
            effect_draft=None if case.get("omit_effect_draft") else effect_draft,
            entry_inputs=resolve(case["entry_inputs"]),
            claims=case["claims"], locator_index=index)
        ran[case_id] = result

        if problems := validate_run(result):
            failures.append(f"{case_id}: its own run does not validate: {problems}")
        if result["status"] != expected["status"]:
            failures.append(f"{case_id}: status {result['status']!r}, expected {expected['status']!r} "
                            f"({result['not_attempted_reason']}: {result['detail'][:120]})")
            continue
        if case["entry"] in entry_paths:
            entry_paths[case["entry"]].add(case["path"])

        if result["status"] == "not_attempted":
            seen_reasons.add(result["not_attempted_reason"])
            if result["not_attempted_reason"] != expected["reason"]:
                failures.append(f"{case_id}: reason {result['not_attempted_reason']!r}, "
                                f"expected {expected['reason']!r} ({result['detail'][:120]})")
            if result["claims"] or result["ledger"] is not None:
                failures.append(f"{case_id}: a run that was not attempted must carry no answer")
            continue

        if result["tier"] != expected["tier"]:
            failures.append(f"{case_id}: tier {result['tier']!r}, expected {expected['tier']!r}")
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
        if problems := fact_ledger.verify_ledger(
                result["ledger"], [result["engine_check"]], index, None, result["state_assumptions"][0]):
            failures.append(f"{case_id}: the run's ledger does not verify: {problems}")

    # Every entry needs both paths. An entry that only ever answers, or only
    # ever refuses, is one this corpus has not actually exercised.
    for entry, paths in entry_paths.items():
        if paths != {"happy", "failure"}:
            failures.append(f"the {entry} entry needs a path that answers and one that does not; saw {sorted(paths)}")

    # --- the declined ruling ------------------------------------------------
    declined = ran["CR-004"]
    if declined["not_attempted_reason"] != "engine_declined" or not declined["engine_declined"]:
        failures.append("a declined engine ruling must stop the command and be named")
    if declined["engine_check"]["outcome"] in fact_ledger.DECIDING_OUTCOMES:
        failures.append("CR-004 needs an engine check that did not decide")
    if declined["claims"]:
        failures.append("a declined ruling produced claims anyway")
    # And it does not restart by citing text at the reader: the same run with a
    # perfectly good locator claim still stops.
    with_text = run_consultation(
        question=ran["CR-004"]["question"], entry="effect", draft=timing_draft, effect_draft=effect_draft,
        entry_inputs={"program": substitutions["@declining_program"]},
        claims=[{"template": "official_text_governs", "slots": {"locator": "Core 312"}, "ref": "Core 312"}],
        locator_index=index)
    if with_text["status"] != "not_attempted" or with_text["not_attempted_reason"] != "engine_declined":
        failures.append("a declined ruling was papered over with a text citation: "
                        f"{with_text['status']}/{with_text['not_attempted_reason']}")

    # --- the answer surface admits no free text -----------------------------
    # Not a property of one case: every slot of every template resolves to a
    # closed set, so there is nowhere a sentence can be put.
    if unknown := sorted(template_slot_types() - set(SLOT_TYPES)):
        failures.append(f"templates use slot types with no closed set behind them: {unknown}")
    prose = "You may play a spell, and your opponent cannot respond."
    context = {"timing_state": timing_state, "locators": index,
               "assumption_slots": {"chain_items", "priority"}}
    for slot_type, resolver in SLOT_TYPES.items():
        allowed = resolver(context)
        if not isinstance(allowed, set):
            failures.append(f"slot type {slot_type!r} does not resolve to a set")
            continue
        if prose in allowed:
            failures.append(f"slot type {slot_type!r} admits a sentence")
        if not allowed and slot_type not in {"locator", "assumption_slot"}:
            failures.append(f"slot type {slot_type!r} resolved to nothing, so nothing can be said with it")
    free_text = ran["CR-013"]
    if free_text["not_attempted_reason"] != "claim_binding_invalid" or "free text" not in free_text["detail"]:
        failures.append(f"free text in a slot must be refused as such: {free_text['detail'][:120]}")

    # Every template renders one sentence, for every value its slots admit.
    for template_id, template in CLAIM_TEMPLATES.items():
        for joiner in (", and ", "; ", " then ", ", but "):
            if joiner in template["text"]:
                failures.append(f"template {template_id!r} joins two claims with {joiner!r}")
        sample = {}
        for slot, slot_type in template["slots"].items():
            allowed = sorted(SLOT_TYPES[slot_type](context))
            if not allowed:
                failures.append(f"template {template_id!r} has no value to render slot {slot!r}")
                sample = None
                break
            sample[slot] = allowed[0]
        if sample is None:
            continue
        text = render(template_id, sample)
        if fact_ledger.is_multi_sentence(text):
            failures.append(f"template {template_id!r} renders more than one sentence: {text!r}")
        if not text.strip().endswith("."):
            failures.append(f"template {template_id!r} does not render a sentence: {text!r}")

    # A producer cannot author text on the way in. The binding schema takes
    # template, slots and ref, and nothing else, so a sentence has no field to
    # arrive in. Without this case a module that quietly preferred a supplied
    # `text` would pass every other check here, because nothing else sends one.
    smuggled = run_consultation(
        question="May I play a spell?", entry="timing", draft=timing_draft,
        entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                 "timing": "default"}},
        claims=[{"template": "timing_play_permitted", "slots": {"actor": "p1", "object_kind": "spell"},
                 "text": "p1 may play a spell, and nothing can stop it."}],
        locator_index=index)
    if smuggled["status"] != "not_attempted" or smuggled["not_attempted_reason"] != "claim_binding_invalid":
        failures.append(f"a claim binding carrying its own text must be refused; got "
                        f"{smuggled['status']}/{smuggled['not_attempted_reason']}")
    if any("nothing can stop it" in claim["text"] for claim in smuggled["claims"]):
        failures.append("supplied text reached a claim")

    # A claim whose text was edited after the run is refused because the
    # validator re-renders it from the template and slots. The run hash is
    # resealed first: without that, the hash catches the edit and this case
    # would pass while proving nothing about re-rendering.
    edited = copy.deepcopy(ran["CR-001"])
    edited["claims"][0]["text"] = "p1 may play a spell, and nothing can stop it."
    edited["run_hash"] = rcc.canonical_hash({k: v for k, v in edited.items() if k != "run_hash"})
    problems = validate_run(edited)
    if not problems:
        failures.append("the validator accepts a resealed run whose claim text was rewritten")
    elif not any("renders" in problem for problem in problems):
        failures.append(f"the rewritten claim was refused, but not by re-rendering it: {problems}")

    # --- the evidence pack re-runs, for all five kinds ----------------------
    reproduced = {}
    for case_id in ("CR-001", "CR-003", "CR-005", "CR-007", "CR-009"):
        result = ran[case_id]
        pack = result["evidence_pack"]
        verification = evidence.verify_pack(pack)
        reproduced[pack["check_kind"]] = verification["verified"]
        if not verification["verified"]:
            failures.append(f"{case_id}: the pack does not re-run: {verification['reason_code']}")
        if not result["evidence_verification"]["verified"]:
            failures.append(f"{case_id}: the run shipped a pack it had not verified")
    if sorted(reproduced) != sorted({ENTRIES[e]['check_kind'] for e in ENTRIES}):
        failures.append(f"the five entries did not produce five pack kinds: {sorted(reproduced)}")
    for kind in sorted(evidence.VERIFIABLE_KINDS):
        if kind not in reproduced and kind != "effect":
            failures.append(f"{kind} is verifiable but no case builds one")

    # Re-running the same consultation reproduces the same run, hash included.
    first = ran["CR-001"]
    again = run_consultation(
        question=first["question"], entry="timing", draft=timing_draft,
        entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                 "timing": "default"}},
        claims=[{"template": "timing_play_permitted", "slots": {"actor": "p1", "object_kind": "spell"}},
                {"template": "official_text_governs", "slots": {"locator": "Core 312"}, "ref": "Core 312"}],
        locator_index=index)
    for field in ("run_hash", "tier", "status"):
        if again[field] != first[field]:
            failures.append(f"a re-run changed {field}: {first[field]!r} -> {again[field]!r}")
    if again["evidence_pack"]["pack_hash"] != first["evidence_pack"]["pack_hash"]:
        failures.append("a re-run produced a different evidence pack hash")
    if again["ledger"]["ledger_hash"] != first["ledger"]["ledger_hash"]:
        failures.append("a re-run produced a different ledger hash")

    # --- a pack that will not re-run stops the run --------------------------
    # Injected fault: the only way to reach this path without a broken engine.
    original_verify = evidence.verify_pack
    try:
        evidence.verify_pack = lambda pack: {"schema_version": "evidence-verification.v1",
                                             "verified": False, "reason_code": "result_not_reproduced"}
        stopped = run_consultation(
            question="May I play a spell?", entry="timing", draft=timing_draft,
            entry_inputs={"action": {"actor": "p1", "kind": "play_card", "object_kind": "spell",
                                     "timing": "default"}},
            claims=[{"template": "timing_play_permitted", "slots": {"actor": "p1", "object_kind": "spell"}}],
            locator_index=index)
    finally:
        evidence.verify_pack = original_verify
    if stopped["not_attempted_reason"] != "evidence_not_reproducible":
        failures.append(f"a pack that does not re-run must stop the run; got "
                        f"{stopped['not_attempted_reason']!r}")
    seen_reasons.add(stopped["not_attempted_reason"])
    if missing := sorted(NOT_ATTEMPTED_REASONS - seen_reasons):
        failures.append(f"no case exercises the not_attempted reasons {missing}")

    # --- the validator refuses the runs a hand-written one would be ---------
    good = copy.deepcopy(ran["CR-001"])
    mutations = [
        ("a claim added without a ledger entry",
         lambda r: r["claims"].append(dict(r["claims"][0], claim_id="claim-3"))),
        ("an answered run at tier C", lambda r: r.__setitem__("tier", "C")),
        ("an abstention that is not tier C", lambda r: r.__setitem__("status", "abstained")),
        ("a not_attempted run that still carries claims",
         lambda r: (r.__setitem__("status", "not_attempted"),
                    r.__setitem__("not_attempted_reason", "engine_declined"),
                    r.__setitem__("detail", "x"))),
        ("an attempted run flagged as a declined ruling",
         lambda r: r.__setitem__("engine_declined", True)),
        ("a claim naming an unknown template",
         lambda r: r["claims"][0].__setitem__("template", "timing_play_whenever")),
        ("a claim whose slots do not match its template",
         lambda r: r["claims"][0]["slots"].__setitem__("extra", "p1")),
        ("a source that is not one source",
         lambda r: r["claims"][0].__setitem__("source", "Core 312")),
        ("an unknown top-level field", lambda r: r.__setitem__("reviewed_by", "nobody")),
        ("a stale run hash", lambda r: r.__setitem__("question", "something else")),
    ]
    for label, mutate in mutations:
        candidate = copy.deepcopy(good)
        mutate(candidate)
        if not validate_run(candidate):
            failures.append(f"the validator accepts {label}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across {len(cases)} consultation cases")
        return 1

    answered = sum(1 for r in ran.values() if r["status"] == "answered")
    print(f"consultation-run.v1: {len(cases)} cases, {answered} answered, "
          f"{len(cases) - answered} not attempted")
    print(f"entries covered: {len(ENTRIES)} (each with an answering and a non-answering path); "
          f"not_attempted reasons exercised: {len(seen_reasons)}/{len(NOT_ATTEMPTED_REASONS)}")
    print(f"claim templates: {len(CLAIM_TEMPLATES)} over {len(SLOT_TYPES)} closed slot types, "
          f"no free-text slot type")
    print(f"evidence packs re-run: {sorted(reproduced)}")
    print(f"validator mutations refused: {len(mutations) + 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
