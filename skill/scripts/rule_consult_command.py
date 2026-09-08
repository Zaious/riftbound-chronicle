#!/usr/bin/env python3
"""One consultation command over the five engine entries, and one claim per ledger entry.

The pipeline is fixed and every stage is somebody else's module:

    state-assumption.v1  build the minimum state the question needs (S-01)
      -> engine entry     timing / effect / combat_step / control_step / legal_action
      -> evidence-pack.v1 the check, its inputs, and the engine identity, re-runnable
      -> claim surface    templates rendered from closed slots, never authored prose
      -> fact-ledger.v1   one claim, one entry, verified against this context (S-02)

The answer surface is the part worth reading twice. A producer here does not
write sentences. It picks a template from a closed table and fills that
template's slots, and every slot type is a closed set drawn from the run's own
context — a player in the state that was built, an object kind the timing
kernel knows, a step name the combat table holds, a locator the index holds, a
slot the assumption artifact carries. There is no free-text slot type, so there
is no way to put a sentence into a claim, so a claim cannot carry two of them.

That is the guarantee: one claim is one assertion because the producer never
composed it. The lexical marker layer in fact_ledger is a backstop against
hand-written ledgers arriving from elsewhere; it is not what holds atomicity
here, and it was never strong enough to.

Every claim becomes exactly one ledger entry, and every claim is mechanical.
Nothing on this surface can be tagged non-mechanical to avoid needing a source.

When the engine declines — unsupported, decision_required, invalid_input — the
run stops at `not_attempted` and names the decline. It does not fall back to
citing text at the reader. The question was routed to an engine entry because
it was a mechanical question about a position; an answer assembled from
locators after the engine refused to rule is a different answer to a different
question, and printing it here is how a service starts sounding certain about
things it did not decide.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import fact_ledger
import rules_core
import state_builder
import verify_evidence_pack as evidence
from battlefield_control import STEPS as CONTROL_STEPS
from combat import STEPS as COMBAT_STEPS
from engine_check import canonical_hash
from fact_ledger import build_ledger, verify_ledger
from legal_action import validate_observation


SCHEMA_VERSION = "consultation-run.v1"
CORE_RULESET = rules_core.CORE_RULESET
FAQ_AS_OF = rules_core.FAQ_AS_OF

# The five entries this command wraps. Each names the engine-check kind it
# produces and the extra inputs it needs beyond the state S-01 built.
ENTRIES = {
    "timing": {"check_kind": "timing", "needs_effect_state": False, "inputs": ("action",)},
    "effect": {"check_kind": "effect", "needs_effect_state": True, "inputs": ("program",)},
    "combat_step": {"check_kind": "combat_step", "needs_effect_state": True, "inputs": ("step",)},
    "control_step": {"check_kind": "control_step", "needs_effect_state": True, "inputs": ("step",)},
    "legal_action": {"check_kind": "legal_action", "needs_effect_state": True, "inputs": ("acting_player",)},
}

STATUSES = ("answered", "abstained", "not_attempted")

NOT_ATTEMPTED_REASONS = frozenset({
    "entry_not_covered",
    "state_not_built",
    "entry_inputs_missing",
    "engine_declined",
    "claim_binding_invalid",
    "no_claims_offered",
    "evidence_not_reproducible",
})

# An engine check that reached a verdict. Same line fact_ledger draws, and for
# the same reason.
DECIDING_OUTCOMES = fact_ledger.DECIDING_OUTCOMES


class ConsultationError(ValueError):
    pass


# --- the claim surface ------------------------------------------------------
#
# Every slot type resolves to a closed set built from the run's own context. A
# new slot type is a decision about what a producer may say, so adding one is a
# visible change here rather than a string that slipped through.

def _players(ctx: dict[str, Any]) -> set[str]:
    state = ctx.get("timing_state") or {}
    return set(state.get("players", []))


SLOT_TYPES = {
    "player": _players,
    "object_kind": lambda ctx: set(rules_core.OBJECT_KINDS),
    "phase": lambda ctx: set(rules_core.PHASES),
    "combat_step": lambda ctx: set(COMBAT_STEPS),
    "control_step": lambda ctx: set(CONTROL_STEPS),
    "locator": lambda ctx: set(ctx.get("locators") or ()),
    "assumption_slot": lambda ctx: set(ctx.get("assumption_slots") or ()),
}

CLAIM_TEMPLATES: dict[str, dict[str, Any]] = {
    "timing_play_permitted": {
        "text": "{actor} may play a {object_kind} in this position.",
        "slots": {"actor": "player", "object_kind": "object_kind"},
        "basis": {"kind": "engine", "check_kind": "timing", "outcomes": ("supported",)},
    },
    "timing_play_refused": {
        "text": "{actor} cannot play a {object_kind} in this position.",
        "slots": {"actor": "player", "object_kind": "object_kind"},
        "basis": {"kind": "engine", "check_kind": "timing", "outcomes": ("illegal",)},
    },
    "effect_program_applies": {
        "text": "The effect applies as written.",
        "slots": {},
        "basis": {"kind": "engine", "check_kind": "effect", "outcomes": ("supported",)},
    },
    "effect_program_refused": {
        "text": "The effect does not apply here.",
        "slots": {},
        "basis": {"kind": "engine", "check_kind": "effect", "outcomes": ("illegal",)},
    },
    "combat_step_completes": {
        "text": "The {step} step of Combat completes in this position.",
        "slots": {"step": "combat_step"},
        "basis": {"kind": "engine", "check_kind": "combat_step", "outcomes": ("supported",)},
    },
    "combat_step_refused": {
        "text": "The {step} step of Combat cannot be taken in this position.",
        "slots": {"step": "combat_step"},
        "basis": {"kind": "engine", "check_kind": "combat_step", "outcomes": ("illegal",)},
    },
    "control_step_completes": {
        "text": "The {step} control step completes in this position.",
        "slots": {"step": "control_step"},
        "basis": {"kind": "engine", "check_kind": "control_step", "outcomes": ("supported",)},
    },
    "control_step_refused": {
        "text": "The {step} control step cannot be taken in this position.",
        "slots": {"step": "control_step"},
        "basis": {"kind": "engine", "check_kind": "control_step", "outcomes": ("illegal",)},
    },
    "legal_action_available": {
        "text": "{actor} has at least one legal action in this position.",
        "slots": {"actor": "player"},
        "basis": {"kind": "engine", "check_kind": "legal_action", "outcomes": ("supported",)},
    },
    "official_text_governs": {
        "text": "{locator} governs this position.",
        "slots": {"locator": "locator"},
        "basis": {"kind": "official_text"},
    },
    "assumption_stands": {
        "text": "This answer assumes {assumption_slot}, which you can correct.",
        "slots": {"assumption_slot": "assumption_slot"},
        "basis": {"kind": "assumption"},
    },
}


def template_slot_types() -> set[str]:
    return {slot_type for template in CLAIM_TEMPLATES.values() for slot_type in template["slots"].values()}


def render(template_id: str, slots: dict[str, str]) -> str:
    """The claim's text. Producers do not have another way to make one."""
    template = CLAIM_TEMPLATES[template_id]
    if set(slots) != set(template["slots"]):
        raise ConsultationError(f"{template_id} takes exactly {sorted(template['slots'])}")
    return template["text"].format(**slots)


def _bind_claims(bindings: Iterable[Any], *, context: dict[str, Any], check: dict[str, Any] | None,
                 ) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn the producer's template choices into claims, or say why they do not bind."""
    claims: list[dict[str, Any]] = []
    problems: list[str] = []
    for position, binding in enumerate(bindings):
        label = f"claims[{position}]"
        if not isinstance(binding, dict) or set(binding) - {"template", "slots", "ref"} or \
                {"template", "slots"} - set(binding):
            problems.append(f"{label} must carry template and slots, and ref only for a "
                            f"non-engine basis")
            continue
        template_id = binding["template"]
        template = CLAIM_TEMPLATES.get(template_id)
        if template is None:
            problems.append(f"{label} names the unknown template {template_id!r}")
            continue
        slots = binding["slots"]
        if not isinstance(slots, dict) or set(slots) != set(template["slots"]):
            problems.append(f"{label} must fill exactly {sorted(template['slots'])} for {template_id}")
            continue
        bad = False
        for slot, value in slots.items():
            allowed = SLOT_TYPES[template["slots"][slot]](context)
            if value not in allowed:
                problems.append(f"{label}.slots.{slot}={value!r} is not one of this run's "
                                f"{template['slots'][slot]} values; a slot is a choice, not free text")
                bad = True
        if bad:
            continue

        basis = template["basis"]
        if basis["kind"] == "engine":
            # An engine claim's source is this run's check, and there is no way
            # to name a different one. The producer cannot supply it, both
            # because it could not know the id before the run and because
            # letting it choose is how a claim ends up citing a check that
            # answered some other question.
            if "ref" in binding:
                problems.append(f"{label} is an engine claim; its source is this run's check "
                                f"and cannot be supplied")
                continue
            if check is None:
                problems.append(f"{label} needs an engine check and this run has none")
                continue
            ref = check["check_id"]
            if check["check_kind"] != basis["check_kind"]:
                problems.append(f"{label} is a {basis['check_kind']} claim, but the check is "
                                f"a {check['check_kind']} one")
                continue
            if check["outcome"] not in basis["outcomes"]:
                problems.append(f"{label} needs an outcome in {list(basis['outcomes'])}; "
                                f"the engine returned {check['outcome']!r}")
                continue
        else:
            ref = binding.get("ref")
            if not isinstance(ref, str) or not ref.strip():
                problems.append(f"{label}.ref must name the {basis['kind']} source")
                continue

        claims.append({
            "claim_id": f"claim-{position + 1}",
            "template": template_id,
            "slots": dict(slots),
            "text": render(template_id, slots),
            "source": f"{basis['kind']}:{ref}",
        })
    return claims, problems


# --- the pipeline -----------------------------------------------------------

def _not_attempted(shell: dict[str, Any], reason: str, detail: str) -> dict[str, Any]:
    shell["status"] = "not_attempted"
    shell["not_attempted_reason"] = reason
    shell["detail"] = detail
    return _seal(shell)


def _seal(run: dict[str, Any]) -> dict[str, Any]:
    run["run_hash"] = canonical_hash({k: v for k, v in run.items() if k != "run_hash"})
    return run


def run_consultation(*, question: str, entry: str, draft: Any, question_kind: str = "timing_priority",
                     effect_draft: Any = None, effect_question_kind: str = "unit_damage",
                     entry_inputs: dict[str, Any] | None = None,
                     claims: Iterable[Any] = (), locator_index: Any = None,
                     card_snapshots: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one consultation end to end, or stop and say where."""
    if not isinstance(question, str) or not question.strip():
        raise ConsultationError("question must be a non-empty string")
    entry_inputs = dict(entry_inputs or {})
    claims = list(claims)

    run: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "question": question,
        "entry": entry,
        "status": "not_attempted",
        "not_attempted_reason": None,
        "detail": "",
        "tier": None,
        "engine_declined": False,
        "state_assumptions": [],
        "engine_check": None,
        "evidence_pack": None,
        "evidence_verification": None,
        "claims": [],
        "ledger": None,
    }

    profile = ENTRIES.get(entry)
    if profile is None:
        return _not_attempted(run, "entry_not_covered",
                              f"{entry!r} is not one of {sorted(ENTRIES)}")

    missing_inputs = [name for name in profile["inputs"] if name not in entry_inputs]
    if missing_inputs:
        return _not_attempted(run, "entry_inputs_missing",
                              f"the {entry} entry needs {missing_inputs}")

    # Stage 1: every state in this run comes through S-01, so every assumption
    # it rests on is one the reader can see and correct.
    timing_artifact = state_builder.build_state_assumption(
        question=question, question_kind=question_kind, draft=draft)
    run["state_assumptions"].append(timing_artifact)
    if not timing_artifact["buildable"]:
        return _not_attempted(run, "state_not_built",
                              f"the timing state could not be built: "
                              f"{timing_artifact['downgrade']['reason']} "
                              f"{timing_artifact['downgrade']['missing_fields'] or timing_artifact['downgrade']['rejected_fields']}")

    effect_artifact = None
    if profile["needs_effect_state"]:
        if effect_draft is None:
            return _not_attempted(run, "entry_inputs_missing",
                                  f"the {entry} entry needs an effect_draft as well as a timing draft")
        effect_artifact = state_builder.build_state_assumption(
            question=question, question_kind=effect_question_kind, draft=effect_draft)
        run["state_assumptions"].append(effect_artifact)
        if not effect_artifact["buildable"]:
            return _not_attempted(run, "state_not_built",
                                  f"the effect state could not be built: "
                                  f"{effect_artifact['downgrade']['reason']} "
                                  f"{effect_artifact['downgrade']['missing_fields'] or effect_artifact['downgrade']['rejected_fields']}")

    # Stage 2: the engine, wrapped in a pack that can be re-run by someone else.
    inputs: dict[str, Any] = {}
    if entry == "timing":
        inputs = {"timing_state": timing_artifact["state"], "timing_action": entry_inputs["action"]}
    elif entry == "effect":
        inputs = {"effect_state": effect_artifact["state"], "effect_program": entry_inputs["program"]}
    elif entry in {"combat_step", "control_step"}:
        inputs = {"timing_state": timing_artifact["state"], "effect_state": effect_artifact["state"],
                  "step": entry_inputs["step"]}
    else:
        observation = entry_inputs.get("observation")
        if observation is None:
            return _not_attempted(run, "entry_inputs_missing",
                                  "the legal_action entry needs an observation")
        if problems := validate_observation(observation):
            return _not_attempted(run, "entry_inputs_missing",
                                  f"the observation is not a legal-action observation: {problems}")
        inputs = {"observation": observation, "acting_player": entry_inputs["acting_player"]}
    if "decisions" in entry_inputs:
        inputs["engine_decisions"] = entry_inputs["decisions"]

    try:
        pack = evidence.build_pack(profile["check_kind"], inputs, note=f"consultation: {question}")
    except evidence.EvidencePackError as exc:
        return _not_attempted(run, "entry_inputs_missing", f"the engine refused the inputs: {exc}")
    check = pack["engine_check"]
    run["engine_check"] = check
    run["evidence_pack"] = pack

    verification = evidence.verify_pack(pack)
    run["evidence_verification"] = verification
    if not verification["verified"]:
        return _not_attempted(run, "evidence_not_reproducible",
                              f"the pack did not re-run on this engine: {verification['reason_code']}")

    if check["outcome"] not in DECIDING_OUTCOMES:
        run["engine_declined"] = True
        return _not_attempted(run, "engine_declined",
                              f"the engine returned {check['outcome']!r} ({check['reason']['code']}): "
                              f"{check['reason']['message']}")

    # Stage 3: the claim surface. Nothing here is authored.
    assumption_slots = {e["slot"] for artifact in run["state_assumptions"] for e in artifact["assumptions"]}
    context = {
        "timing_state": timing_artifact["state"],
        "locators": set(locator_index) if isinstance(locator_index, (set, frozenset, list, tuple)) else set(),
        "assumption_slots": assumption_slots,
    }
    bound, problems = _bind_claims(claims, context=context, check=check)
    if problems:
        return _not_attempted(run, "claim_binding_invalid", "; ".join(problems))
    if not bound:
        return _not_attempted(run, "no_claims_offered",
                              "the engine decided, but no claim was offered to carry the answer")
    run["claims"] = bound

    # Stage 4: one claim, one ledger entry. Every one of them mechanical.
    sentences = [{"text": claim["text"], "mechanical": True, "sources": [claim["source"]]}
                 for claim in bound]
    ledger_context = {
        "engine_checks": [check],
        "locator_index": locator_index,
        "card_snapshots": card_snapshots,
        "assumption_artifact": timing_artifact,
    }
    ledger = build_ledger(question=question, sentences=sentences, **ledger_context)
    run["ledger"] = ledger
    if problems := verify_ledger(ledger, **ledger_context):
        return _not_attempted(run, "claim_binding_invalid",
                              f"the ledger this run just built does not verify: {problems}")

    run["tier"] = ledger["admissible_tier"]
    run["status"] = "answered" if ledger["admissible"] else "abstained"
    if not ledger["admissible"]:
        run["detail"] = "; ".join(f"{v['code']} at claim {v['entry'] + 1}" for v in ledger["violations"])
    return _seal(run)


REQUIRED_TOP = {"schema_version", "ruleset", "question", "entry", "status", "not_attempted_reason",
                "detail", "tier", "engine_declined", "state_assumptions", "engine_check",
                "evidence_pack", "evidence_verification", "claims", "ledger", "run_hash"}


def validate_run(value: Any) -> list[str]:
    """Check a run, re-deriving every claim's text from its template and slots."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["run must be a JSON object"]
    if missing := REQUIRED_TOP - set(value):
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown := set(value) - REQUIRED_TOP:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    if missing:
        return errors

    if value["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if value["ruleset"] != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("ruleset must match the kernel baseline")
    if value["status"] not in STATUSES:
        errors.append(f"status must be one of {list(STATUSES)}")
    if value["entry"] not in ENTRIES and value["not_attempted_reason"] != "entry_not_covered":
        errors.append(f"entry must be one of {sorted(ENTRIES)}")

    if value["status"] == "not_attempted":
        if value["not_attempted_reason"] not in NOT_ATTEMPTED_REASONS:
            errors.append(f"not_attempted_reason must be one of {sorted(NOT_ATTEMPTED_REASONS)}")
        if not isinstance(value["detail"], str) or not value["detail"].strip():
            errors.append("a run that was not attempted says why")
        if value["claims"] or value["ledger"] is not None or value["tier"] is not None:
            errors.append("a run that was not attempted carries no claims, no ledger, and no tier")
    else:
        if value["not_attempted_reason"] is not None:
            errors.append("an attempted run carries no not_attempted_reason")
        if value["tier"] not in fact_ledger.TIERS:
            errors.append(f"tier must be one of {list(fact_ledger.TIERS)}")
        if not value["claims"]:
            errors.append("an attempted run carries at least one claim")
        if not isinstance(value["ledger"], dict):
            errors.append("an attempted run carries its ledger")
        else:
            errors.extend(f"ledger: {e}" for e in fact_ledger.validate_ledger(value["ledger"]))
            if len(value["ledger"]["entries"]) != len(value["claims"]):
                errors.append(f"one claim is one ledger entry: {len(value['claims'])} claims, "
                              f"{len(value['ledger']['entries'])} entries")
        if value["status"] == "answered" and value["tier"] == "C":
            errors.append("a run answered at tier C is an abstention, and must say so")
        if value["status"] == "abstained" and value["tier"] != "C":
            errors.append("an abstention is tier C")
        if value["engine_declined"]:
            errors.append("a declined engine ruling cannot produce an attempted run")

    for position, claim in enumerate(value["claims"]):
        label = f"claims[{position}]"
        if not isinstance(claim, dict) or set(claim) != {"claim_id", "template", "slots", "text", "source"}:
            errors.append(f"{label} must carry claim_id, template, slots, text, source")
            continue
        template = CLAIM_TEMPLATES.get(claim["template"])
        if template is None:
            errors.append(f"{label} names the unknown template {claim['template']!r}")
            continue
        if set(claim["slots"]) != set(template["slots"]):
            errors.append(f"{label} must fill exactly {sorted(template['slots'])}")
            continue
        # The text is re-rendered. A claim whose text was edited after the fact
        # is a claim someone wrote, which is the thing this surface exists to
        # make impossible.
        expected = render(claim["template"], claim["slots"])
        if claim["text"] != expected:
            errors.append(f"{label}.text is {claim['text']!r}, but its template renders {expected!r}")
        if fact_ledger.is_multi_sentence(claim["text"]):
            errors.append(f"{label} renders more than one sentence")
        if not isinstance(claim["source"], str) or fact_ledger.parse_source(claim["source"]) is None:
            errors.append(f"{label}.source must be one '<kind>:<ref>' source")

    if not errors:
        expected_hash = canonical_hash({k: v for k, v in value.items() if k != "run_hash"})
        if value["run_hash"] != expected_hash:
            errors.append("run_hash is not the hash of this run")
    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or validate one consultation over the five engine entries.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one consultation end to end")
    run.add_argument("--question", required=True)
    run.add_argument("--entry", required=True, choices=sorted(ENTRIES))
    run.add_argument("--request", required=True,
                     help="path to the request: draft, effect_draft, question_kind, entry_inputs, claims")
    run.add_argument("--index", help="path to a JSON array of admissible locators")

    check = sub.add_parser("validate", help="validate a run, re-rendering every claim")
    check.add_argument("run")

    templates = sub.add_parser("templates", help="list the claim templates and their slots")
    args = parser.parse_args(argv)

    if args.command == "templates":
        json.dump({name: {"text": t["text"], "slots": t["slots"], "basis": t["basis"]}
                   for name, t in sorted(CLAIM_TEMPLATES.items())}, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    if args.command == "validate":
        problems = validate_run(_load(args.run))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("valid" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    request = _load(args.request)
    result = run_consultation(
        question=args.question, entry=args.entry,
        draft=request.get("draft"), question_kind=request.get("question_kind", "timing_priority"),
        effect_draft=request.get("effect_draft"),
        effect_question_kind=request.get("effect_question_kind", "unit_damage"),
        entry_inputs=request.get("entry_inputs"), claims=request.get("claims", ()),
        locator_index=set(_load(args.index)) if args.index else None,
        card_snapshots=request.get("card_snapshots"))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if result["status"] == "answered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
