#!/usr/bin/env python3
"""
Bounded legal-action service, Phase A only (ADR-0003, package C-10).

Three artifacts and one classifier:

  observation.v1          what is known, from whose perspective, and how
                          completely — facts are split into confirmed public,
                          own private, inferred, later-revealed, unknown and
                          contradictory sets, and completeness is reported per
                          field group rather than as one boolean.
  action-query.v1         the caller's candidates, bound to one observation
                          hash. Phase A has exactly one candidate source:
                          `user_supplied`. The engine generates nothing.
  legal-action-result.v1  one verdict per candidate — legal, illegal,
                          indeterminate, unsupported, decision_required — with
                          the reason, the official locators, what is missing,
                          and the constant admission that no enumeration was
                          attempted and the action set is not complete.

The classifier only ever consults *structured* facts. A candidate that arrives
as prose, or an observation whose timing-state group is not complete, comes
back `indeterminate` with the missing facts named. It never reads the prose
summary and guesses. That is the whole point of ADR-0003: a confident list
called "legal actions" built from a summary that omitted things would be the
most dangerous artifact this project could emit.

Two boundaries are enforced structurally, not by convention:

  perspective  a `player2` query is refused if any Player 1 private key appears
               anywhere in the observation or candidates, using the same
               forbidden-key list P2-A already enforces;
  hindsight    `later_revealed` and `contradictory` facts are carried for
               Match Analyst but are never an input to a verdict — the result
               hash of an observation with them equals the hash without them.

Usage:
    python3 skill/scripts/legal_action.py classify observation.json query.json [--output result.json]
    python3 skill/scripts/legal_action.py validate <observation|query|result>.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import rules_core  # noqa: E402
from p2a_session import FORBIDDEN_HIDDEN_KEYS, _find_forbidden_keys  # noqa: E402

OBSERVATION_VERSION = "observation.v1"
QUERY_VERSION = "action-query.v1"
RESULT_VERSION = "legal-action-result.v1"

PERSPECTIVES = ("player1", "player2", "public_observer", "omniscient_replay")
FACT_SETS = ("confirmed_public", "own_private", "inferred", "later_revealed", "unknown", "contradictory")
# Only these two feed a verdict. The other four exist so that what was *not*
# known is recorded, never so that it can be used.
DECISION_TIME_FACT_SETS = ("confirmed_public", "own_private")
COMPLETENESS_GROUPS = ("timing_state", "board", "hands", "resources", "pending_decisions")
COMPLETENESS_VALUES = ("complete", "partial", "absent")
CANDIDATE_SOURCE_MODES = ("user_supplied",)  # Phase B adds engine_enumerated; not here
VERDICTS = ("legal", "illegal", "indeterminate", "unsupported", "decision_required")
ACTION_FAMILIES = ("play_card", "activate_ability", "pass_priority", "pass_focus")
# What a candidate may ask to have checked. Phase A implements timing only;
# asking for anything else is answered `unsupported`, by name, rather than by
# a timing-only verdict that silently pretends the other checks ran.
CHECK_KINDS = ("timing", "cost", "targets", "effect_prerequisites")
IMPLEMENTED_CHECKS = ("timing",)
PROVENANCE_KINDS = ("human_confirmed", "engine_state", "normalizer_proposed", "replay_log", "unknown")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71


def _str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# --------------------------------------------------------------------------
# observation.v1
# --------------------------------------------------------------------------

def _decision_time_view(observation: dict[str, Any]) -> dict[str, Any]:
    """Everything a verdict may depend on. Hindsight sets are stripped here, once."""
    facts = observation.get("facts", {})
    return {
        "perspective": observation.get("perspective"),
        "source": observation.get("source"),
        "component_states": observation.get("component_states"),
        "facts": {name: facts.get(name, []) for name in DECISION_TIME_FACT_SETS},
        "pending_decisions": observation.get("pending_decisions", []),
        "completeness": observation.get("completeness"),
        "context": observation.get("context"),
    }


def observation_hash(observation: dict[str, Any]) -> str:
    return canonical_hash(_decision_time_view(observation))


def build_observation(
    *,
    perspective: str,
    source: dict[str, Any],
    context: dict[str, Any],
    timing_state: dict[str, Any] | None = None,
    facts: dict[str, list[dict[str, Any]]] | None = None,
    pending_decisions: list[dict[str, Any]] | None = None,
    completeness: dict[str, str] | None = None,
) -> dict[str, Any]:
    fact_sets = {name: list((facts or {}).get(name, [])) for name in FACT_SETS}
    component_states: dict[str, Any] = {}
    if timing_state is not None:
        component_states["timing_state"] = {
            "schema_version": timing_state.get("schema_version"),
            "hash": rules_core.state_hash(timing_state),
            "state": copy.deepcopy(timing_state),
        }
    derived_completeness = {group: "absent" for group in COMPLETENESS_GROUPS}
    if timing_state is not None:
        derived_completeness["timing_state"] = "complete" if not rules_core.validate_state(timing_state) else "partial"
    derived_completeness["pending_decisions"] = "complete" if pending_decisions is not None else "absent"
    derived_completeness.update(completeness or {})
    observation = {
        "schema_version": OBSERVATION_VERSION,
        "perspective": perspective,
        "source": copy.deepcopy(source),
        "context": copy.deepcopy(context),
        "component_states": component_states,
        "facts": fact_sets,
        "pending_decisions": list(pending_decisions or []),
        "completeness": derived_completeness,
    }
    observation["observation_hash"] = observation_hash(observation)
    return observation


def validate_observation(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["observation must be an object"]
    required = {"schema_version", "perspective", "source", "context", "component_states", "facts", "pending_decisions", "completeness", "observation_hash"}
    errors: list[str] = []
    if set(value) != required:
        errors.append("observation top-level fields are invalid")
    if value.get("schema_version") != OBSERVATION_VERSION:
        errors.append(f"schema_version must be {OBSERVATION_VERSION}")
    if value.get("perspective") not in PERSPECTIVES:
        errors.append("perspective is invalid")
    source = value.get("source")
    if not isinstance(source, dict) or not _str(source.get("kind")) or not isinstance(source.get("state_seq"), int) or source["state_seq"] < 0:
        errors.append("source must carry a kind and a non-negative state_seq")
    context = value.get("context")
    if not isinstance(context, dict) or not all(_str(context.get(k)) for k in ("ruleset_core", "faq_as_of", "format", "card_data_version")):
        errors.append("context must carry ruleset_core, faq_as_of, format, card_data_version")
    elif "region" in context and not _str(context["region"]):
        errors.append("context.region must be a non-empty string when present")
    states = value.get("component_states")
    if not isinstance(states, dict) or set(states) - {"timing_state"}:
        errors.append("component_states may only contain timing_state in Phase A")
    elif "timing_state" in states:
        ts = states["timing_state"]
        if not isinstance(ts, dict) or set(ts) != {"schema_version", "hash", "state"} or not isinstance(ts.get("state"), dict):
            errors.append("component_states.timing_state must carry schema_version, hash, state")
        elif ts["hash"] != rules_core.state_hash(ts["state"]):
            errors.append("component_states.timing_state.hash does not match its state")
    facts = value.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(FACT_SETS):
        errors.append("facts must contain exactly the six fact sets")
    else:
        seen: set[str] = set()
        for name, items in facts.items():
            if not isinstance(items, list):
                errors.append(f"facts.{name} must be an array")
                continue
            for item in items:
                if not isinstance(item, dict) or set(item) != {"fact_id", "text", "provenance"}:
                    errors.append(f"facts.{name} entries must carry fact_id, text, provenance")
                    break
                if not _str(item["fact_id"]) or item["fact_id"] in seen:
                    errors.append(f"facts.{name} fact_id must be unique and non-empty")
                    break
                seen.add(item["fact_id"])
                if not _str(item["text"]) or item["provenance"] not in PROVENANCE_KINDS:
                    errors.append(f"facts.{name} entries need text and a known provenance")
                    break
    pending = value.get("pending_decisions")
    if not isinstance(pending, list) or any(not isinstance(d, dict) or not _str(d.get("decision_id")) or not _str(d.get("owner")) or not _str(d.get("kind")) for d in pending):
        errors.append("pending_decisions entries must carry decision_id, owner, kind")
    completeness = value.get("completeness")
    if not isinstance(completeness, dict) or set(completeness) != set(COMPLETENESS_GROUPS) or any(v not in COMPLETENESS_VALUES for v in completeness.values()):
        errors.append("completeness must rate every field group as complete, partial, or absent")
    elif isinstance(states, dict) and "timing_state" not in states and completeness.get("timing_state") == "complete":
        errors.append("completeness.timing_state cannot be complete without a structured timing_state")
    hidden = _find_forbidden_keys(value)
    if value.get("perspective") == "player2" and hidden:
        errors.append("player2 observation carries Player 1 private information: " + ", ".join(hidden))
    if not errors and value.get("observation_hash") != observation_hash(value):
        errors.append("observation_hash does not match the decision-time view")
    return errors


# --------------------------------------------------------------------------
# action-query.v1
# --------------------------------------------------------------------------

def build_query(
    *,
    observation: dict[str, Any],
    acting_player: str,
    candidates: list[dict[str, Any]],
    requested_action_families: list[str] | None = None,
) -> dict[str, Any]:
    query = {
        "schema_version": QUERY_VERSION,
        "observation_hash": observation["observation_hash"],
        "candidate_source_mode": "user_supplied",
        "acting_player": acting_player,
        "requested_action_families": sorted(set(requested_action_families or ACTION_FAMILIES)),
        "candidates": sorted((copy.deepcopy(c) for c in candidates), key=lambda c: c["candidate_id"]),
    }
    query["query_hash"] = canonical_hash({k: v for k, v in query.items() if k != "query_hash"})
    return query


def validate_query(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["query must be an object"]
    required = {"schema_version", "observation_hash", "candidate_source_mode", "acting_player", "requested_action_families", "candidates", "query_hash"}
    errors: list[str] = []
    if set(value) != required:
        errors.append("query top-level fields are invalid")
    if value.get("schema_version") != QUERY_VERSION:
        errors.append(f"schema_version must be {QUERY_VERSION}")
    if not _is_hash(value.get("observation_hash")):
        errors.append("observation_hash must be a sha256 hash")
    if value.get("candidate_source_mode") not in CANDIDATE_SOURCE_MODES:
        errors.append("candidate_source_mode must be user_supplied in Phase A")
    if not _str(value.get("acting_player")):
        errors.append("acting_player is required")
    families = value.get("requested_action_families")
    if not isinstance(families, list) or not families or any(f not in ACTION_FAMILIES for f in families) or families != sorted(set(families)):
        errors.append("requested_action_families must be a sorted, unique subset of the known families")
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append("candidates must be a non-empty array")
    else:
        ids = []
        for c in candidates:
            if not isinstance(c, dict) or not {"candidate_id", "description"} <= set(c) or set(c) - {"candidate_id", "description", "action", "requires_decision_id"}:
                errors.append("candidate fields are invalid")
                break
            if not _str(c["candidate_id"]) or not _str(c["description"]):
                errors.append("candidate_id and description must be non-empty")
                break
            ids.append(c["candidate_id"])
            if "action" in c and (not isinstance(c["action"], dict) or c["action"].get("kind") not in ACTION_FAMILIES):
                errors.append(f"candidate {c['candidate_id']} action.kind must be a known family")
            elif "action" in c and "checks" in c["action"]:
                checks = c["action"]["checks"]
                if not isinstance(checks, list) or not checks or any(k not in CHECK_KINDS for k in checks) or checks != sorted(set(checks)):
                    errors.append(f"candidate {c['candidate_id']} action.checks must be a sorted, unique subset of {CHECK_KINDS}")
            if "requires_decision_id" in c and not _str(c["requires_decision_id"]):
                errors.append(f"candidate {c['candidate_id']} requires_decision_id must be non-empty")
        if len(set(ids)) != len(ids):
            errors.append("candidate_id values must be unique")
        if ids != sorted(ids):
            errors.append("candidates must be sorted by candidate_id for deterministic hashing")
    hidden = _find_forbidden_keys(value.get("candidates"))
    if value.get("acting_player") == "p2" and hidden:
        errors.append("player2 query carries Player 1 private information: " + ", ".join(hidden))
    if not errors and value.get("query_hash") != canonical_hash({k: v for k, v in value.items() if k != "query_hash"}):
        errors.append("query_hash does not match the query")
    return errors


# --------------------------------------------------------------------------
# classifier (Phase A)
# --------------------------------------------------------------------------

def _classify_one(observation: dict[str, Any], query: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    base = {
        "candidate_id": candidate["candidate_id"],
        "verdict": "indeterminate",
        "reason_code": "",
        "explanation": "",
        "rule_locators": [],
        "required_capabilities": ["timing_permission_v1"],
        "missing_information": [],
        "decision_id": None,
    }
    pending = {d["decision_id"]: d for d in observation.get("pending_decisions", [])}
    needs = candidate.get("requires_decision_id")
    if needs is not None:
        if needs in pending:
            return {**base, "verdict": "decision_required", "reason_code": "controller_decision_pending",
                    "explanation": f"Candidate depends on pending decision {needs!r} owned by {pending[needs]['owner']}.",
                    "decision_id": needs}
        return {**base, "reason_code": "unknown_decision_reference",
                "explanation": "Candidate references a decision the observation does not list.",
                "missing_information": [f"pending decision {needs!r}"]}

    action = candidate.get("action")
    if action is None:
        return {**base, "reason_code": "candidate_not_structured",
                "explanation": "Candidate has no structured action; prose is not classified.",
                "missing_information": ["structured action (kind, actor, timing, object_kind)"]}

    ts = observation.get("component_states", {}).get("timing_state")
    if ts is None or observation.get("completeness", {}).get("timing_state") != "complete":
        return {**base, "reason_code": "observation_incomplete:timing_state",
                "explanation": "No complete structured timing state; timing legality cannot be determined.",
                "missing_information": ["complete timing_state component"]}

    requested = list(action.get("checks", ["timing"]))
    beyond = [k for k in requested if k not in IMPLEMENTED_CHECKS]
    if beyond:
        return {**base, "verdict": "unsupported", "reason_code": "unsupported_check:" + ",".join(beyond),
                "explanation": "Phase A classifies timing only; the requested checks are not implemented.",
                "required_capabilities": ["timing_permission_v1"] + [f"{k}_v1" for k in beyond]}

    actor = action.get("actor", query["acting_player"])
    if actor != query["acting_player"]:
        # Not illegal: the kernel was never asked. The missing fact is a query
        # from that actor's perspective, which this query is not.
        return {**base, "reason_code": "actor_mismatch",
                "explanation": "Candidate actor differs from the query's acting player; not classified from this perspective.",
                "missing_information": [f"a query whose acting_player is {actor!r}"]}

    result = rules_core.validate_timing(ts["state"], {**action, "actor": actor})
    locators = list(result.get("rule_locators", []))
    code = str(result.get("reason_code", "") or "")
    if result.get("valid") is False:
        return {**base, "reason_code": "timing_state_invalid", "explanation": "; ".join(map(str, result.get("errors", []))),
                "missing_information": ["valid timing_state component"]}
    if code.startswith("unsupported"):
        return {**base, "verdict": "unsupported", "reason_code": code, "explanation": result.get("explanation", ""), "rule_locators": locators}
    if result.get("legal") is True:
        return {**base, "verdict": "legal", "reason_code": code or "ok", "explanation": result.get("explanation", ""), "rule_locators": locators}
    if result.get("legal") is False:
        return {**base, "verdict": "illegal", "reason_code": code, "explanation": result.get("explanation", ""), "rule_locators": locators}
    return {**base, "reason_code": "timing_result_indeterminate", "explanation": "Timing kernel returned no legality.",
            "missing_information": ["timing legality"]}


def classify_candidates(observation: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    """Phase A. Returns a legal-action-result.v1; never enumerates."""
    obs_errors = validate_observation(observation)
    q_errors = validate_query(query)
    valid = not obs_errors and not q_errors and query.get("observation_hash") == observation.get("observation_hash")
    if valid and observation["perspective"] in ("player1", "player2"):
        expected = {"player1": "p1", "player2": "p2"}[observation["perspective"]]
        if query["acting_player"] != expected:
            valid = False
            q_errors = q_errors + [f"acting_player must be {expected} for perspective {observation['perspective']}"]
    if valid and query.get("observation_hash") != observation.get("observation_hash"):
        valid = False
    errors = obs_errors + q_errors
    if valid is False and query.get("observation_hash") != observation.get("observation_hash") and not errors:
        errors = ["query.observation_hash does not match the observation"]

    per_candidate = [] if not valid else [_classify_one(observation, query, c) for c in query["candidates"]]
    verdicts = [c["verdict"] for c in per_candidate]
    result = {
        "schema_version": RESULT_VERSION,
        "valid": valid,
        "errors": errors,
        "observation_hash": observation.get("observation_hash"),
        "query_hash": query.get("query_hash"),
        "perspective": observation.get("perspective"),
        "acting_player": query.get("acting_player"),
        "candidate_source_mode": query.get("candidate_source_mode"),
        "enumeration_attempted": False,
        "complete_action_set": False,
        "proof_scope": None,
        "candidates": per_candidate,
        "summary": {v: verdicts.count(v) for v in VERDICTS},
        "rule_locators": sorted({loc for c in per_candidate for loc in c["rule_locators"]}),
        "reason_code": (
            "invalid_input" if not valid
            else "legal_action_decision_required" if "decision_required" in verdicts
            else "unsupported_all_candidates" if per_candidate and all(v == "unsupported" for v in verdicts)
            else "ok"
        ),
    }
    result["result_hash"] = canonical_hash({k: v for k, v in result.items() if k != "result_hash"})
    return result


def validate_result(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["result must be an object"]
    required = {"schema_version", "valid", "errors", "observation_hash", "query_hash", "perspective", "acting_player",
                "candidate_source_mode", "enumeration_attempted", "complete_action_set", "proof_scope", "candidates",
                "summary", "rule_locators", "reason_code", "result_hash"}
    errors: list[str] = []
    if set(value) != required:
        errors.append("result top-level fields are invalid")
    if value.get("schema_version") != RESULT_VERSION:
        errors.append(f"schema_version must be {RESULT_VERSION}")
    if value.get("enumeration_attempted") is not False or value.get("complete_action_set") is not False or value.get("proof_scope") is not None:
        errors.append("Phase A results must not attempt enumeration or claim a complete action set")
    if value.get("candidate_source_mode") not in CANDIDATE_SOURCE_MODES:
        errors.append("candidate_source_mode is invalid")
    cands = value.get("candidates")
    if not isinstance(cands, list):
        errors.append("candidates must be an array")
    else:
        ids = []
        for c in cands:
            if not isinstance(c, dict) or set(c) != {"candidate_id", "verdict", "reason_code", "explanation", "rule_locators", "required_capabilities", "missing_information", "decision_id"}:
                errors.append("candidate result fields are invalid")
                break
            ids.append(c["candidate_id"])
            if c["verdict"] not in VERDICTS:
                errors.append(f"candidate {c['candidate_id']} verdict is invalid")
            if (c["verdict"] == "decision_required") != (c["decision_id"] is not None):
                errors.append(f"candidate {c['candidate_id']} decision_id must exist only for decision_required")
            if c["verdict"] == "indeterminate" and not c["missing_information"]:
                errors.append(f"candidate {c['candidate_id']} indeterminate must name what is missing")
            if not _str(c["reason_code"]):
                errors.append(f"candidate {c['candidate_id']} reason_code is required")
        if ids != sorted(ids):
            errors.append("candidate results must be in candidate_id order")
        if isinstance(value.get("summary"), dict) and value["summary"] != {v: [c.get("verdict") for c in cands].count(v) for v in VERDICTS}:
            errors.append("summary does not match candidate verdicts")
    if value.get("valid") is True and value.get("errors"):
        errors.append("a valid result cannot carry errors")
    if value.get("valid") is False and not value.get("errors"):
        errors.append("an invalid result must say why")
    if not errors and value.get("result_hash") != canonical_hash({k: v for k, v in value.items() if k != "result_hash"}):
        errors.append("result_hash does not match the result")
    return errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit(f"{path} is not an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("classify")
    c.add_argument("observation", type=Path)
    c.add_argument("query", type=Path)
    c.add_argument("--output", type=Path)
    v = sub.add_parser("validate")
    v.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)

    if args.command == "validate":
        value = _load(args.artifact)
        kind = value.get("schema_version")
        fn = {OBSERVATION_VERSION: validate_observation, QUERY_VERSION: validate_query, RESULT_VERSION: validate_result}.get(kind)
        if fn is None:
            print(f"FAILED: unknown schema_version {kind!r}", file=sys.stderr)
            return 1
        errors = fn(value)
        if errors:
            print(f"FAILED: validate {args.artifact}:\n  - " + "\n  - ".join(errors), file=sys.stderr)
            return 1
        print(f"OK: validate {args.artifact} ({kind})")
        return 0

    result = classify_candidates(_load(args.observation), _load(args.query))
    if not result["valid"]:
        print("FAILED: classify:\n  - " + "\n  - ".join(result["errors"]), file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output} ({result['summary']})")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
