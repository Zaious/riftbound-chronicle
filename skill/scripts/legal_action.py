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

import effect_ir  # noqa: E402
import play_transaction  # noqa: E402
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
CANDIDATE_SOURCE_MODES = ("user_supplied", "engine_enumerated")  # C-57 (ADR-0015 §1) adds the second
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
    effect_state: dict[str, Any] | None = None,
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
    if effect_state is not None:
        # C-57: the board, hands and resources an enumeration reads. The
        # completeness this derives is the *structural* one; whether this
        # perspective may see a hand is the caller's own `completeness`.
        component_states["effect_state"] = {
            "schema_version": effect_state.get("schema_version"),
            "hash": effect_ir.hash_value(effect_state),
            "state": copy.deepcopy(effect_state),
        }
    derived_completeness = {group: "absent" for group in COMPLETENESS_GROUPS}
    if timing_state is not None:
        derived_completeness["timing_state"] = "complete" if not rules_core.validate_state(timing_state) else "partial"
    if effect_state is not None:
        structural = "complete" if not effect_ir.validate_state(effect_state) else "partial"
        derived_completeness["board"] = structural
        derived_completeness["resources"] = structural
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
    if not isinstance(states, dict) or set(states) - {"timing_state", "effect_state"}:
        errors.append("component_states may only contain timing_state and effect_state")
    elif "effect_state" in states and (not isinstance(states["effect_state"], dict)
                                       or set(states["effect_state"]) != {"schema_version", "hash", "state"}
                                       or not isinstance(states["effect_state"].get("state"), dict)
                                       or states["effect_state"]["hash"] != effect_ir.hash_value(states["effect_state"]["state"])):
        errors.append("component_states.effect_state must carry schema_version, hash, state, and the hash must match")
    if isinstance(states, dict) and "timing_state" in states:
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


# --------------------------------------------------------------------------
# Phase B: bounded enumeration (C-57, ADR-0015 §1)
# --------------------------------------------------------------------------

# Families the engine can produce candidates for. A family absent from this
# tuple is not enumerated at all — the result says so rather than implying the
# player has no such action.
ENUMERABLE_FAMILIES = ("play_card", "activate_ability", "standard_move", "hide", "pass_priority", "pass_focus")
# What each family must be able to read before it may answer. A group that is
# not `complete` makes the family abstain by name.
FAMILY_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "play_card": ("timing_state", "hands", "resources"),
    "activate_ability": ("timing_state", "board", "resources"),
    "standard_move": ("timing_state", "board"),
    "hide": ("timing_state", "hands", "board"),
    "pass_priority": ("timing_state",),
    "pass_focus": ("timing_state",),
}
# What the enumeration is allowed to look at. `observation.facts` is prose
# with provenance, so it is never parsed for a conclusion; structured
# knowledge comes from the component states the observation carries.
ENUMERATION_SOURCES = ("component_states.timing_state", "component_states.effect_state")


def _abstain(family: str, reason_code: str, missing: list[str], locators: list[str] | None = None) -> dict[str, Any]:
    return {"family": family, "status": "abstained", "reason_code": reason_code,
            "missing_information": list(missing), "candidates": [], "rule_locators": list(locators or [])}


def _enumerated(family: str, candidates: list[str], locators: list[str], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    return {"family": family, "status": "enumerated", "reason_code": "ok", "missing_information": [],
            "candidates": list(candidates), "rule_locators": list(locators), "excluded": excluded}


def _timing_verdict(timing_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    return rules_core.validate_timing(timing_state, action)


def _cost_total(cost: Any, *, effect_state: dict[str, Any] | None = None, card_id: str | None = None,
                actor: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """The total of a printed cost the state carries, or why the enumeration
    will not compute one. A cost with modifications, additional components or
    intents is a decision the player makes, not one an enumeration makes for
    them — but a fixed Energy reduction the card's own text declares is not a
    decision, so the enumeration reads it through the same function the
    payment path uses (Round H)."""
    if not isinstance(cost, dict):
        return None, "printed_cost_not_observed"
    if set(cost) - {"base"}:
        return None, "cost_modelling_beyond_enumeration"
    base = cost.get("base")
    if not isinstance(base, dict) or not isinstance(base.get("energy"), int) or not isinstance(base.get("power"), dict):
        return None, "printed_cost_not_observed"
    cost = copy.deepcopy(cost)
    if effect_state is not None:
        own = play_transaction.self_cost_reductions(effect_state, card_id)
        kept = []
        for modification in own:
            if "condition" not in modification:
                kept.append({k: v for k, v in modification.items() if k != "self_card"})
                continue
            try:
                outcome = effect_ir.evaluate_cost_modification(effect_state, modification, actor)
            except effect_ir.ConditionUnsupported:
                return None, "cost_condition_not_observed"
            except ValueError:
                return None, "cost_modelling_beyond_enumeration"
            if outcome["applies"] and outcome["amount"] > 0:
                kept.append({k: v for k, v in modification.items() if k not in {"condition", "self_card"}}
                            | {"amount": outcome["amount"]})
        if kept:
            cost["discounts"] = kept
    try:
        skeleton = play_transaction.determine_total_cost(cost, {})
    except Exception:  # a shape the transaction itself will not read
        return None, "cost_modelling_beyond_enumeration"
    return skeleton["total"], None


def _enumerate_play_card(observation, timing_state, effect_state, actor):
    player = (effect_state.get("players") or {}).get(actor)
    resources = player.get("resources") if isinstance(player, dict) else None
    if not isinstance(resources, dict):
        return _abstain("play_card", "observation_incomplete:resources", [f"{actor}'s resource pool"]), []
    candidates, excluded = [], []
    # Only this player's own hand. An opponent's hand is in the observation
    # only when the observer may see it, and enumeration never reaches for it.
    for object_id in list(player["zones"]["hand"]):
        obj = effect_state["objects"].get(object_id) or {}
        object_kind = obj.get("kind")
        if object_kind not in {"unit", "gear", "spell", "rune"}:
            excluded.append({"object_id": object_id, "reason_code": "card_kind_not_observed"})
            continue
        timing = obj.get("play_timing", "default")
        verdict = _timing_verdict(timing_state, {"actor": actor, "kind": "play_card", "timing": timing,
                                                 "object_kind": object_kind})
        if verdict.get("legal") is not True:
            excluded.append({"object_id": object_id, "reason_code": verdict.get("reason_code", "timing_illegal"),
                             "check": "timing"})
            continue
        printed = obj.get("printed_cost")
        total, problem = _cost_total({"base": printed} if isinstance(printed, dict) else printed,
                                     effect_state=effect_state, card_id=object_id, actor=actor)
        if total is None:
            excluded.append({"object_id": object_id, "reason_code": problem, "check": "cost"})
            continue
        if play_transaction.affordability(resources, total, f"play_{object_kind}")["short"]:
            excluded.append({"object_id": object_id, "reason_code": "cost_unpayable", "check": "cost"})
            continue
        candidates.append({
            "candidate_id": f"play:{object_id}",
            "family": "play_card",
            "action": {"kind": "play_card", "actor": actor, "timing": timing, "object_kind": object_kind,
                       "card": object_id, "checks": ["timing", "cost"]},
            "required_facts": [f"hand:{actor}", f"printed_cost:{object_id}", f"resources:{actor}"],
            "rule_locators": list(verdict.get("rule_locators", [])) + ["Core 357.1"],
        })
    return _enumerated("play_card", [c["candidate_id"] for c in candidates],
                       ["Core 349", "Core 357.1"], excluded), candidates


def _enumerate_activate_ability(observation, timing_state, effect_state, actor):
    # The effect state carries no catalogue of a card's activated abilities —
    # those live in the compiled card programs — so this family has nothing to
    # read and says so instead of offering none.
    return _abstain("activate_ability", "capability_missing:activated_ability_catalogue",
                    ["a per-object list of activated abilities with their costs and timings"],
                    ["Core 349"]), []


def _enumerate_standard_move(observation, timing_state, effect_state, actor):
    verdict = _timing_verdict(timing_state, {"actor": actor, "kind": "standard_move", "timing": "default"})
    if verdict.get("legal") is not True:
        return _enumerated("standard_move", [], list(verdict.get("rule_locators", [])),
                           [{"reason_code": verdict.get("reason_code", "timing_illegal"), "check": "timing"}]), []
    candidates, excluded = [], []
    battlefields = sorted(effect_state.get("battlefields", {}))
    for object_id in sorted(effect_state.get("objects", {})):
        obj = effect_state["objects"][object_id]
        if obj.get("kind") != "unit" or obj.get("controller") != actor:
            continue
        location = effect_ir.find_location(effect_state, object_id)
        if effect_ir.zone_class(location) != "board":
            continue
        if obj.get("exhausted"):
            excluded.append({"object_id": object_id, "reason_code": "unit_is_exhausted"})
            continue
        here = location[1] if location[0] == "battlefield" else None
        destinations = [{"kind": "base", "player": actor}] if here is not None else []
        destinations += [{"kind": "battlefield", "battlefield": bf} for bf in battlefields if bf != here]
        for destination in destinations:
            label = destination.get("battlefield") or f"base:{destination['player']}"
            candidates.append({
                "candidate_id": f"move:{object_id}:{label}",
                "family": "standard_move",
                "action": {"kind": "standard_move", "actor": actor, "timing": "default", "object_kind": "unit",
                           "object_id": object_id, "destination": destination, "checks": ["timing"]},
                "required_facts": [f"board:{object_id}"],
                "rule_locators": list(verdict.get("rule_locators", [])),
            })
    return _enumerated("standard_move", [c["candidate_id"] for c in candidates],
                       list(verdict.get("rule_locators", [])), excluded), candidates


def _enumerate_hide(observation, timing_state, effect_state, actor):
    player = (effect_state.get("players") or {}).get(actor) or {"zones": {"hand": []}}
    cards = [{"object_id": object_id} for object_id in player["zones"]["hand"]
             if (effect_state["objects"].get(object_id) or {}).get("hidden") is True]
    verdict = _timing_verdict(timing_state, {"actor": actor, "kind": "standard_move", "timing": "default"})
    controlled = [bf for bf, entry in sorted(effect_state.get("battlefields", {}).items())
                  if entry.get("controller") == actor]
    candidates, excluded = [], []
    if verdict.get("legal") is not True:
        excluded.append({"reason_code": verdict.get("reason_code", "timing_illegal"), "check": "timing"})
    else:
        for fact in sorted(cards, key=lambda f: str(f.get("object_id"))):
            object_id = fact.get("object_id")
            for battlefield_id in controlled:
                zone = (effect_state["battlefields"][battlefield_id].get("facedown") or {})
                if len(zone.get("cards", []) or []) >= zone.get("capacity", 1):
                    excluded.append({"object_id": object_id, "battlefield": battlefield_id,
                                     "reason_code": "facedown_zone_full"})
                    continue
                candidates.append({
                    "candidate_id": f"hide:{object_id}:{battlefield_id}",
                    "family": "hide",
                    "action": {"kind": "hide", "actor": actor, "timing": "default", "object_kind": "spell",
                               "card": object_id, "battlefield": battlefield_id, "checks": ["timing"]},
                    "required_facts": [f"hand_card:{object_id}", f"battlefield:{battlefield_id}"],
                    "rule_locators": ["Core 811.1", "Core 107.3.f"],
                })
    return _enumerated("hide", [c["candidate_id"] for c in candidates],
                       ["Core 811.1"], excluded), candidates


def _enumerate_pass(family, observation, timing_state, effect_state, actor):
    verdict = _timing_verdict(timing_state, {"actor": actor, "kind": family, "timing": "default"})
    if verdict.get("legal") is not True:
        return _enumerated(family, [], list(verdict.get("rule_locators", [])),
                           [{"reason_code": verdict.get("reason_code", "timing_illegal"), "check": "timing"}]), []
    candidate = {
        "candidate_id": family,
        "family": family,
        "action": {"kind": family, "actor": actor, "timing": "default", "object_kind": None, "checks": ["timing"]},
        "required_facts": ["timing_state"],
        "rule_locators": list(verdict.get("rule_locators", [])),
    }
    return _enumerated(family, [candidate["candidate_id"]], list(verdict.get("rule_locators", [])), []), [candidate]


ENUMERATORS = {
    "play_card": _enumerate_play_card,
    "activate_ability": _enumerate_activate_ability,
    "standard_move": _enumerate_standard_move,
    "hide": _enumerate_hide,
}


def enumerate_actions(observation: dict[str, Any], acting_player: str) -> dict[str, Any]:
    """Phase B (ADR-0015 §1). Produces candidates for the families the engine
    covers *and* the observation confirms; every other family abstains by name.

    `complete_action_set` is always false: there is no machine-checkable proof
    that this enumeration is exhaustive, so the field says so rather than
    implying one. A family that would need a private zone this perspective
    cannot see, a fact the observation does not carry, or a capability the
    engine lacks, produces no candidate and says which.
    """
    obs_errors = validate_observation(observation)
    valid = not obs_errors
    if valid and observation["perspective"] in ("player1", "player2"):
        expected = {"player1": "p1", "player2": "p2"}[observation["perspective"]]
        if acting_player != expected:
            valid = False
            obs_errors = obs_errors + [f"acting_player must be {expected} for perspective {observation['perspective']}"]

    families: list[dict[str, Any]] = []
    enumerated: list[dict[str, Any]] = []
    if valid:
        completeness = observation.get("completeness", {})
        components = observation.get("component_states", {})
        timing_state = (components.get("timing_state") or {}).get("state")
        effect_state = (components.get("effect_state") or {}).get("state")
        for family in ENUMERABLE_FAMILIES:
            missing = [group for group in FAMILY_REQUIREMENTS[family] if completeness.get(group) != "complete"]
            if missing:
                families.append(_abstain(family, "observation_incomplete:" + ",".join(missing),
                                         [f"a complete {group} view" for group in missing]))
                continue
            if timing_state is None:
                families.append(_abstain(family, "observation_incomplete:timing_state", ["a timing_state component"]))
                continue
            if family in {"pass_priority", "pass_focus"}:
                record, produced = _enumerate_pass(family, observation, timing_state, effect_state, acting_player)
            elif effect_state is None:
                families.append(_abstain(family, "observation_incomplete:effect_state", ["an effect_state component"]))
                continue
            else:
                record, produced = ENUMERATORS[family](observation, timing_state, effect_state, acting_player)
            if isinstance(record, dict) and record.get("status") == "abstained":
                families.append(record)
                continue
            families.append(record)
            enumerated.extend(produced)

    enumerated.sort(key=lambda c: c["candidate_id"])
    candidates = [{
        "candidate_id": c["candidate_id"],
        "verdict": "legal",
        "reason_code": "ok",
        "explanation": f"Enumerated by the {c['family']} family from the observation's own facts.",
        "rule_locators": c["rule_locators"],
        "required_capabilities": ["timing_permission_v1"] + (["cost_payment_v1"] if "cost" in c["action"].get("checks", []) else []),
        "missing_information": [],
        "decision_id": None,
    } for c in enumerated]
    verdicts = [c["verdict"] for c in candidates]
    result = {
        "schema_version": RESULT_VERSION,
        "valid": valid,
        "errors": obs_errors,
        "observation_hash": observation.get("observation_hash"),
        "query_hash": None,
        "perspective": observation.get("perspective"),
        "acting_player": acting_player,
        "candidate_source_mode": "engine_enumerated",
        "enumeration_attempted": True,
        # ADR-0015 §1: never true without a machine-checkable completeness proof.
        "complete_action_set": False,
        "proof_scope": None,
        "candidates": candidates,
        "summary": {v: verdicts.count(v) for v in VERDICTS},
        "rule_locators": sorted({loc for c in candidates for loc in c["rule_locators"]}),
        "reason_code": "invalid_input" if not valid else ("ok" if candidates else "no_enumerated_actions"),
        "enumeration": {
            "families": families,
            "abstained": sorted(f["family"] for f in families if f["status"] == "abstained"),
            "actions": [{"candidate_id": c["candidate_id"], "family": c["family"], "action": c["action"],
                         "required_facts": c["required_facts"]} for c in enumerated],
            "sources_read": list(ENUMERATION_SOURCES),
        },
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
    enumeration = value.get("enumeration")
    if set(value) - {"enumeration"} != required:
        errors.append("result top-level fields are invalid")
    if value.get("schema_version") != RESULT_VERSION:
        errors.append(f"schema_version must be {RESULT_VERSION}")
    if value.get("complete_action_set") is not False or value.get("proof_scope") is not None:
        errors.append("no result may claim a complete action set without a machine-checkable proof (ADR-0015 §1)")
    if enumeration is None:
        if value.get("enumeration_attempted") is not False:
            errors.append("a result without an enumeration record must not claim to have enumerated")
    else:
        if value.get("enumeration_attempted") is not True or value.get("candidate_source_mode") != "engine_enumerated":
            errors.append("an enumerated result must say so in enumeration_attempted and candidate_source_mode")
        if not isinstance(enumeration, dict) or set(enumeration) != {"families", "abstained", "actions", "sources_read"}:
            errors.append("enumeration must be {families, abstained, actions, sources_read}")
        else:
            seen_families = []
            for record in enumeration["families"]:
                if not isinstance(record, dict) or record.get("family") not in ENUMERABLE_FAMILIES:
                    errors.append("an enumeration family record is invalid")
                    continue
                seen_families.append(record["family"])
                if record.get("status") not in {"enumerated", "abstained"}:
                    errors.append(f"family {record['family']} has no status")
                if record.get("status") == "abstained" and not record.get("missing_information"):
                    errors.append(f"family {record['family']} abstained without saying what is missing")
            if value.get("valid") is True and seen_families != list(ENUMERABLE_FAMILIES):
                errors.append("every enumerable family must report, in order")
            named = {c["candidate_id"] for c in value.get("candidates", []) if isinstance(c, dict)}
            if {a.get("candidate_id") for a in enumeration["actions"]} != named:
                errors.append("the enumerated actions and the candidate verdicts do not agree")
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
