#!/usr/bin/env python3
"""Executable checks for fact-ledger.v1, the S-02 no-D-layer gate.

The engine checks these cases cite are not fixtures. The gate runs the real
timing kernel and the real effect kernel over states the S-01 builder produced,
wraps the results with build_engine_check, and substitutes the resulting
check_ids into the cases. A ledger that passes here has been checked against
verdicts the engine actually reached.

The four counterexamples the S-02 contract names each get their own section
below: a question the engine declines to rule on, an answer with one source
removed, a citation to a locator the index does not hold, and a conclusion
tagged non-mechanical to slip past the ledger.

Then the forgeries. validate_ledger reads no context, so a ledger that writes
"verified" on a source that never was, and reseals its hash, passes it. Each
forgery below is first shown to pass structural validation — that is the
point, not a defect being tolerated — and then refused by verify_ledger, which
rebuilds the ledger against the context and does not read the status field.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import effect_ir
import fact_ledger
import rules_core
import state_builder
from engine_check import build_engine_check
from engine_check import validate_engine_check
from fact_ledger import (
    VIOLATION_CODES,
    build_ledger,
    markers_in,
    validate_ledger,
    verify_ledger,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
CASES = SKILL_DIR / "data" / "fact_ledger_cases.json"


class Retriever:
    """A source retriever standing in for the indexed rules corpus.

    The real service passes one backed by the rules index; this one is a table,
    because the public repository holds no licensed document text. What matters
    to the ledger is the shape of the answer, not where it came from.
    """

    def __init__(self, table):
        self.table = copy.deepcopy(table)

    def retrieve(self, locator):
        return copy.deepcopy(self.table.get(locator, {"status": "not_found", "record": None}))


def real_engine_checks() -> dict[str, dict]:
    """Three engine checks from real kernel runs on S-01-built states."""
    timing = state_builder.build_state_assumption(
        question="It is my main phase, the chain is empty, and I hold priority. May I play a spell?",
        question_kind="timing_priority",
        draft={"players": ["p1", "p2"], "turn_player": "p1", "phase": "main", "priority": "p1"})
    if not timing["buildable"]:
        raise SystemExit(f"the S-01 builder could not build the timing state: {timing['downgrade']}")
    state = timing["state"]
    state_hash = rules_core.state_hash(state)
    checks = {}
    for label, actor in (("@timing_supported", "p1"), ("@timing_illegal", "p2")):
        result = rules_core.validate_timing(
            state, {"actor": actor, "kind": "play_card", "object_kind": "spell", "timing": "default"})
        checks[label] = build_engine_check("timing", result, input_hashes={"timing_state": state_hash})

    # The declined ruling. The program asks the engine to draw on a condition
    # it recognizes but does not evaluate in a program; the draw then runs into
    # a deck the S-01 state says is empty — which S-01 flagged as a material
    # assumption — and the engine stops rather than deciding.
    effect_artifact = state_builder.build_state_assumption(
        question="If my spell kills their unit, do I draw a card from the follow-up effect?",
        question_kind="unit_damage",
        draft={"players": ["p1", "p2"],
               "units": [{"object_id": "u1", "controller": "p1", "might": 3},
                         {"object_id": "u2", "controller": "p2", "might": 2, "damage": 1}]})
    if not effect_artifact["buildable"]:
        raise SystemExit(f"the S-01 builder could not build the effect state: {effect_artifact['downgrade']}")
    effect_state = effect_artifact["state"]
    program = {
        "schema_version": effect_ir.PROGRAM_VERSION,
        "ruleset": {"core": effect_ir.CORE_RULESET, "faq_as_of": effect_ir.FAQ_AS_OF},
        "program_id": "kill-then-draw", "controller": "p1",
        "effects": [{"op": "draw", "player": "p1", "count": 1,
                     "condition": {"kind": "caused_kill", "effect_id": "e1"}}],
    }
    result = effect_ir.apply_program(effect_state, program)
    checks["@effect_unsupported"] = build_engine_check(
        "effect", result, input_hashes={"effect_state": effect_ir.hash_value(effect_state)})
    return checks, timing


def resolve(sources: list[str], checks: dict[str, dict]) -> list[str]:
    out = []
    for source in sources:
        if isinstance(source, str) and source.startswith("engine:@"):
            out.append("engine:" + checks[source.split(":", 1)[1]]["check_id"])
        else:
            out.append(source)
    return out


def main() -> int:
    failures: list[str] = []
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = payload["cases"]
    index = set(payload["locator_index"])
    retriever = Retriever(payload["retrievals"])
    snapshots = payload["card_snapshots"]
    checks, assumption_artifact = real_engine_checks()

    outcomes = {label: check["outcome"] for label, check in checks.items()}
    if outcomes.get("@timing_supported") != "supported" or outcomes.get("@timing_illegal") != "illegal":
        failures.append(f"the timing kernel no longer produces the verdicts these cases cite: {outcomes}")
    if outcomes.get("@effect_unsupported") in {"supported", "illegal"}:
        failures.append("the declined-ruling case needs an engine check that did not decide; "
                        f"this one is {outcomes.get('@effect_unsupported')!r}")

    built: dict[str, dict] = {}
    seen_codes: set[str] = set()

    for case in cases:
        case_id = case["case_id"]
        expected = case["expected"]
        sentences = [{**s, "sources": resolve(s["sources"], checks)} for s in case["sentences"]]
        case_index = retriever if case.get("use_retriever") else index
        ledger = build_ledger(question=case["question"], sentences=sentences,
                              engine_checks=list(checks.values()), locator_index=case_index,
                              card_snapshots=snapshots, assumption_artifact=assumption_artifact)
        built[case_id] = ledger

        if problems := validate_ledger(ledger):
            failures.append(f"{case_id}: its own ledger does not validate: {problems}")
        if problems := verify_ledger(ledger, list(checks.values()), case_index, snapshots, assumption_artifact):
            failures.append(f"{case_id}: its own ledger does not verify against the context it was built on: {problems}")
        if ledger["admissible"] is not expected["admissible"]:
            failures.append(f"{case_id}: admissible was {ledger['admissible']}, expected {expected['admissible']}")
        if ledger["admissible_tier"] != expected["tier"]:
            failures.append(f"{case_id}: tier was {ledger['admissible_tier']!r}, "
                            f"expected {expected['tier']!r} ({ledger['violations']})")
        codes = sorted({v["code"] for v in ledger["violations"]})
        seen_codes |= set(codes)
        if codes != sorted(set(expected["violations"])):
            failures.append(f"{case_id}: violations {codes}, expected {sorted(set(expected['violations']))}")

        # The fixture's own tagging has to be honest: a sentence the author
        # called non-mechanical may only fire markers in the case that exists
        # to demonstrate exactly that.
        allows_untagged = "untagged_mechanical_sentence" in expected["violations"]
        for position, sentence in enumerate(case["sentences"]):
            fired = markers_in(sentence["text"])
            if fired and not sentence["mechanical"] and not allows_untagged:
                failures.append(f"{case_id}.sentences[{position}] is tagged non-mechanical "
                                f"but fires {fired}; the fixture is wrong, not the module")

    # Counterexample 1, the question the engine declines. FL-003 looks like a
    # rules question and reads like one; the cited check did not decide, so the
    # answer may not go out as an engine-backed one.
    declined = built["FL-003"]
    if declined["admissible_tier"] != "C":
        failures.append("a conclusion resting on a declined engine ruling must abstain")
    if "engine_check_did_not_decide" not in {v["code"] for v in declined["violations"]}:
        failures.append("the declined ruling must be named as such, not folded into 'unsourced'")

    # Counterexample 2: take one source away from an answer that passed, and
    # the whole answer falls — not just the sentence that lost it.
    clean = next(c for c in cases if c["case_id"] == "FL-001")
    stripped = [{**s, "sources": resolve(s["sources"], checks)} for s in clean["sentences"]]
    stripped[1] = {**stripped[1], "sources": []}
    fallen = build_ledger(question=clean["question"], sentences=stripped,
                          engine_checks=list(checks.values()), locator_index=index,
                          card_snapshots=snapshots, assumption_artifact=assumption_artifact)
    if built["FL-001"]["admissible_tier"] != "A":
        failures.append("FL-001 must stand at A before the source is removed, or removing it proves nothing")
    if fallen["admissible_tier"] != "C" or fallen["admissible"]:
        failures.append("removing one source must take the whole answer down, not one sentence")
    if fallen["entries"][0]["sources"][0]["status"] != "verified":
        failures.append("the sentence that kept its source should still show it verified; "
                        "the answer falls because of the other one")

    # Counterexample 3: a locator outside the index is not a source.
    off_index = build_ledger(question="May I play a spell in my main phase?",
                             sentences=[{"text": "You may play a spell right now.", "mechanical": True,
                                         "sources": ["official_text:Core 999.9"]}],
                             engine_checks=list(checks.values()), locator_index=index,
                             card_snapshots=snapshots, assumption_artifact=assumption_artifact)
    if "locator_not_in_index" not in {v["code"] for v in off_index["violations"]}:
        failures.append("a locator the index does not hold must be refused")
    in_index = build_ledger(question="May I play a spell in my main phase?",
                            sentences=[{"text": "You may play a spell right now.", "mechanical": True,
                                        "sources": ["official_text:Core 312"]}],
                            engine_checks=list(checks.values()), locator_index=index,
                            card_snapshots=snapshots, assumption_artifact=assumption_artifact)
    if not in_index["admissible"]:
        failures.append("the same sentence with an in-index locator must pass; "
                        "otherwise the refusal above is not about the index")

    # Counterexample 4: the escape hatch. Tagging a conclusion non-mechanical
    # does not remove it from the ledger, because the markers are re-derived.
    escaped = built["FL-006"]
    if escaped["admissible"] or escaped["entries"][0]["mechanical"] is not True:
        failures.append("a conclusion tagged non-mechanical must still be treated as one")

    # An engine check that no longer validates cannot back anything, even
    # though its id is the one the answer cites. The tamper here is the one
    # that matters: a check rewritten to claim it is an official ruling. The
    # ledger does not read the boundary itself — it refuses the check because
    # engine_check.validate_engine_check refuses it, which is where that
    # judgment belongs.
    tampered = copy.deepcopy(checks["@timing_supported"])
    tampered["authority"]["role"] = "official_ruling"
    broken = build_ledger(question="May I play a spell?",
                          sentences=[{"text": "You may play a spell right now.", "mechanical": True,
                                      "sources": ["engine:" + tampered["check_id"]]}],
                          engine_checks=[tampered], locator_index=index,
                          card_snapshots=snapshots, assumption_artifact=assumption_artifact)
    broken_codes = {v["code"] for v in broken["violations"]}
    if "invalid_engine_check" not in broken_codes:
        failures.append(f"a tampered engine check must be refused; got {sorted(broken_codes)}")
    seen_codes |= broken_codes

    if missing := sorted(VIOLATION_CODES - seen_codes):
        failures.append(f"no case exercises the violation codes {missing}")

    # ---- Source-status forgeries -------------------------------------------
    # Each one passes validate_ledger. That is what these cases exist to show:
    # structural validation cannot see a lie about a source, because it has
    # nothing to check the source against. verify_ledger has, and refuses.
    context = dict(engine_checks=list(checks.values()), locator_index=index,
                   card_snapshots=snapshots, assumption_artifact=assumption_artifact)

    def reseal(ledger):
        ledger["ledger_hash"] = fact_ledger.canonical_hash(
            {k: v for k, v in ledger.items() if k != "ledger_hash"})
        return ledger

    def forgery(label, ledger, ctx, *, expect_in_reason):
        structural = validate_ledger(ledger)
        if structural:
            failures.append(f"forgery '{label}' should pass structural validation "
                            f"(that is the hole being demonstrated), but got {structural}")
        problems = verify_ledger(ledger, **ctx)
        if not problems:
            failures.append(f"verify_ledger accepts the forgery '{label}'")
        elif not any(expect_in_reason in problem for problem in problems):
            failures.append(f"forgery '{label}' was refused, but not for the right reason: {problems}")

    # F1. The bypass as reported: an off-index locator written up as verified.
    f1 = copy.deepcopy(built["FL-005"])
    f1["entries"][0]["sources"][0]["status"] = "verified"
    f1["violations"] = []
    f1["admissible"] = True
    f1["admissible_tier"] = "B"
    forgery("off-index locator marked verified", reseal(f1), context,
            expect_in_reason="against this context it is 'locator_not_in_index'")

    # F2. A declined engine ruling written up as a verdict, binding and all.
    # The forger can compute the check's hash — the bundle is not secret —
    # so the binding is right; the status is still not what the context says.
    f2 = copy.deepcopy(built["FL-003"])
    undecided = checks["@effect_unsupported"]
    f2["entries"][0]["sources"][0]["status"] = "verified"
    f2["entries"][0]["sources"][0]["bound_hash"] = fact_ledger.canonical_hash(undecided)
    f2["violations"] = []
    f2["admissible"] = True
    f2["admissible_tier"] = "A"
    f2["cited_engine_checks"] = [undecided["check_id"]]
    forgery("declined engine ruling marked verified", reseal(f2), context,
            expect_in_reason="against this context it is 'engine_check_did_not_decide'")

    # F3. The ledger is honest; the bundle is not. The check it cites has been
    # swapped for one with the same check_id and a flipped outcome, still a
    # structurally valid engine check. Only the binding tells them apart.
    swapped = copy.deepcopy(checks["@timing_illegal"])
    swapped["outcome"] = "supported"
    swapped["reason"] = {"code": "ok", "message": "ok"}
    if validate_engine_check(swapped):
        failures.append("the swapped check must still validate, or the binding is not what catches it")
    swapped_bundle = [c for c in checks.values() if c["check_id"] != swapped["check_id"]] + [swapped]
    forgery("engine check swapped in the bundle under its own id", copy.deepcopy(built["FL-016"]),
            {**context, "engine_checks": swapped_bundle},
            expect_in_reason="bound to content that is no longer what the context holds")

    # F4. Same snapshot id, different text behind it.
    rewritten = copy.deepcopy(snapshots)
    rewritten["synthetic-unit-a"]["text_hash"] = "sha256:" + "e" * 64
    forgery("card snapshot rewritten under the same id", copy.deepcopy(built["FL-009"]),
            {**context, "card_snapshots": rewritten},
            expect_in_reason="bound to content that is no longer what the context holds")

    # F5. The assumption artifact moved. The slot is still there with the same
    # value; the artifact it belongs to is a different one, and the answer was
    # built on the old one.
    moved = state_builder.build_state_assumption(
        question="A different question over the same position.",
        question_kind="timing_priority",
        draft=assumption_artifact["input_draft"])
    if "showdown_active" not in {e["slot"] for e in moved["assumptions"]}:
        failures.append("the moved artifact must still carry the cited slot, or this tests absence")
    forgery("assumption artifact replaced, slot still present", copy.deepcopy(built["FL-007"]),
            {**context, "assumption_artifact": moved},
            expect_in_reason="bound to content that is no longer what the context holds")

    # F6. The assumption's value moved. turn_order is derived from the order
    # the players were listed; reverse them and the slot survives with a
    # different value.
    order_ledger = build_ledger(
        question="Who takes the second turn?",
        sentences=[{"text": "Turn order follows the order the players were listed.", "mechanical": True,
                    "sources": ["assumption:turn_order"]}], **context)
    if not order_ledger["admissible"]:
        failures.append(f"the turn-order ledger must build clean first: {order_ledger['violations']}")
    reversed_draft = dict(assumption_artifact["input_draft"],
                          players=list(reversed(assumption_artifact["input_draft"]["players"])))
    reordered = state_builder.build_state_assumption(question=assumption_artifact["question"],
                                                     question_kind="timing_priority", draft=reversed_draft)
    new_value = next((e["value"] for e in reordered["assumptions"] if e["slot"] == "turn_order"), None)
    old_value = next((e["value"] for e in assumption_artifact["assumptions"] if e["slot"] == "turn_order"), None)
    if new_value is None or new_value == old_value:
        failures.append("the reordered artifact must carry turn_order with a different value")
    forgery("assumption value changed, slot still present", order_ledger,
            {**context, "assumption_artifact": reordered},
            expect_in_reason="bound to content that is no longer what the context holds")

    # F8. A retrieved official-text source binds its document. The document is
    # revised under the same locator, so the ledger still names a real source
    # and still cites it correctly — and the answer was built on text that is
    # no longer what that locator says.
    retrieved = built["FL-017"]["entries"][0]["sources"][0]
    if retrieved["status"] != "verified" or not retrieved["bound_hash"]:
        failures.append("a retrieved official-text source must carry its binding")
    revised = copy.deepcopy(payload["retrievals"])
    revised["Core 339.1"]["record"]["text_hash"] = "sha256:" + "ff" * 32
    forgery("official text revised under the same locator", copy.deepcopy(built["FL-017"]),
            {**context, "locator_index": Retriever(revised)},
            expect_in_reason="bound to content that is no longer what the context holds")

    # F9. The same ledger against a bare set instead of the retriever: the
    # source still passes membership, but the binding it claims is gone.
    forgery("retrieved source checked against an index that cannot bind",
            copy.deepcopy(built["FL-017"]), {**context, "locator_index": {"Core 339.1"}},
            expect_in_reason="bound to content that is no longer what the context holds")

    # F7. No status touched at all: the violations are simply deleted from a
    # ledger whose second sentence has no source.
    f7 = copy.deepcopy(fallen)
    f7["violations"] = []
    f7["admissible"] = True
    f7["admissible_tier"] = "A"
    forgery("violations deleted from an unsourced answer", reseal(f7), context,
            expect_in_reason="violations claimed []")

    forgeries = 9

    # The validator has to refuse the ledgers a hand-written one would be.
    good = copy.deepcopy(built["FL-001"])
    mutations = [
        ("a ledger that says its conclusion fires no markers",
         lambda l: l["entries"][0].__setitem__("markers", [])),
        ("a conclusion demoted to non-mechanical after the fact",
         lambda l: (l["entries"][0].__setitem__("mechanical", False),
                    l["entries"][0].__setitem__("declared_mechanical", False))),
        ("tier A on a ledger with a violation",
         lambda l: l["violations"].append({"entry": 0, "code": "unsourced_conclusion", "detail": "x"})),
        ("admissible with a violation",
         lambda l: (l["violations"].append({"entry": 0, "code": "unsourced_conclusion", "detail": "x"}),
                    l.__setitem__("admissible_tier", "C"))),
        ("tier A claimed without a verified engine citation",
         lambda l: l["entries"][0]["sources"].__setitem__(
             0, {**l["entries"][0]["sources"][0], "status": "locator_not_in_index"})),
        ("a cited-checks list that does not match the entries",
         lambda l: l["cited_engine_checks"].append("engine-check:deadbeef")),
        ("an unknown violation code",
         lambda l: l["violations"].append({"entry": 0, "code": "looks_fine", "detail": "x"})),
        ("a violation pointing past the entries",
         lambda l: l["violations"].append({"entry": 99, "code": "unsourced_conclusion", "detail": "x"})),
        ("an unknown top-level field", lambda l: l.__setitem__("reviewed_by", "nobody")),
        ("a stale ledger hash", lambda l: l["entries"][0].__setitem__("text", "You may not.")),
        ("a verified engine source with no binding",
         lambda l: l["entries"][0]["sources"][0].__setitem__("bound_hash", None)),
        ("a binding that is not a hash",
         lambda l: l["entries"][0]["sources"][0].__setitem__("bound_hash", 42)),
        ("a source record without the binding field",
         lambda l: l["entries"][0]["sources"][0].pop("bound_hash")),
    ]
    for label, mutate in mutations:
        candidate = copy.deepcopy(good)
        mutate(candidate)
        if not validate_ledger(candidate):
            failures.append(f"the validator accepts {label}")

    # A hand-written ledger that is internally consistent and still lying: a
    # sentence that plainly fires markers, declared clean, with the hash
    # recomputed so nothing else can catch it. Only re-deriving the markers
    # from the sentence itself refuses this one, which is the whole reason the
    # validator re-derives them rather than reading the field.
    forged = copy.deepcopy(built["FL-014"])
    forged["entries"][0] = {
        "index": 0, "text": "Your opponent cannot respond, and the spell resolves.",
        "mechanical": False, "declared_mechanical": False, "markers": [], "sources": [],
    }
    forged["ledger_hash"] = fact_ledger.canonical_hash(
        {k: v for k, v in forged.items() if k != "ledger_hash"})
    if not markers_in(forged["entries"][0]["text"]):
        failures.append("the forged sentence must fire markers, or it proves nothing")
    if not validate_ledger(forged):
        failures.append("the validator accepts a self-consistent ledger that lies about its markers")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across {len(cases)} fact-ledger cases")
        return 1

    admissible = sum(1 for ledger in built.values() if ledger["admissible"])
    tiers = {tier: sum(1 for l in built.values() if l["admissible_tier"] == tier) for tier in ("A", "B", "C")}
    print(f"fact-ledger.v1: {len(cases)} cases, {admissible} admissible, {len(cases) - admissible} refused")
    print(f"tiers A/B/C: {tiers['A']}/{tiers['B']}/{tiers['C']}; "
          f"violation codes exercised: {len(seen_codes)}/{len(VIOLATION_CODES)}")
    print(f"engine checks from real kernel runs: {len(checks)} "
          f"({', '.join(f'{k[1:]}={v}' for k, v in sorted(outcomes.items()))})")
    print(f"structural mutations refused: {len(mutations) + 1}; "
          f"source-status forgeries refused by verify_ledger: {forgeries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
