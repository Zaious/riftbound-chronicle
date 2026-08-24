#!/usr/bin/env python3
"""Create, finalize, and validate an unofficial Rule Consult artifact.

The artifact separates supplied facts, material assumptions, source locators,
analysis, confidence, and escalation. It never changes a P2-A state and never
claims to be an official Riot or tournament ruling.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
REGISTRY_PATH = SKILL_DIR / "data" / "rules_source_registry.json"
SCHEMA_VERSION = "rule-consultation.v1"
QUESTION_TYPES = {"general_mechanic", "specific_interaction", "tournament_procedure", "source_conflict"}
CONFIDENCE = {"High", "Medium", "Low"}
ESCALATION_TARGETS = {"none", "more_facts", "head_judge", "riot_clarification"}
ALLOWED_TOP = {
    "schema_version", "mode", "official_status", "state_effect",
    "consultation_id", "created_at", "created_by", "status",
    "question_type", "question", "format", "ruleset_as_of", "facts",
    "assumptions", "sources", "answer",
}
FORBIDDEN_KEYS = {
    "official_ruling", "binding_ruling", "penalty_assigned", "state_transition",
    "game_state_update", "legal_action_set", "winner",
}


class ConsultationError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_registry() -> dict[str, Any]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ConsultationError(f"cannot load source registry: {exc}") from exc
    return registry


def registry_by_id() -> dict[str, dict[str, Any]]:
    return {source["source_id"]: source for source in load_registry().get("sources", [])}


def _nonempty(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")


def _forbidden_paths(value: Any, path: str = "$") -> list[str]:
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key.lower() in FORBIDDEN_KEYS:
                hits.append(child_path)
            hits.extend(_forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_forbidden_paths(child, f"{path}[{index}]"))
    return hits


def validate_consultation(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["consultation must be a JSON object"]

    missing = ALLOWED_TOP - set(value)
    unknown = set(value) - ALLOWED_TOP
    if missing:
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")

    constants = {
        "schema_version": SCHEMA_VERSION,
        "mode": "rule-consult",
        "official_status": "unofficial",
        "state_effect": "none",
    }
    for field, expected in constants.items():
        if value.get(field) != expected:
            errors.append(f"{field} must be {expected!r}, got {value.get(field)!r}")

    for field in ("consultation_id", "created_at", "created_by", "question", "format", "ruleset_as_of"):
        _nonempty(value.get(field), field, errors)
    if value.get("status") not in {"draft", "final"}:
        errors.append("status must be 'draft' or 'final'")
    if value.get("question_type") not in QUESTION_TYPES:
        errors.append(f"question_type must be one of {sorted(QUESTION_TYPES)}")

    forbidden = _forbidden_paths(value)
    if forbidden:
        errors.append("consultation contains forbidden authority/state fields: " + ", ".join(forbidden))

    facts = value.get("facts")
    if not isinstance(facts, list):
        errors.append("facts must be an array")
        facts = []
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or set(fact) != {"text", "origin"}:
            errors.append(f"facts[{index}] must contain exactly text and origin")
            continue
        _nonempty(fact.get("text"), f"facts[{index}].text", errors)
        if fact.get("origin") not in {"user", "official_source"}:
            errors.append(f"facts[{index}].origin must be user or official_source")

    assumptions = value.get("assumptions")
    if not isinstance(assumptions, list):
        errors.append("assumptions must be an array")
        assumptions = []
    for index, assumption in enumerate(assumptions):
        if not isinstance(assumption, dict) or set(assumption) != {"text", "material"}:
            errors.append(f"assumptions[{index}] must contain exactly text and material")
            continue
        _nonempty(assumption.get("text"), f"assumptions[{index}].text", errors)
        if not isinstance(assumption.get("material"), bool):
            errors.append(f"assumptions[{index}].material must be boolean")

    known_sources = registry_by_id()
    sources = value.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be an array")
        sources = []
    seen_sources = set()
    official_count = 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or set(source) != {"source_id", "locator", "accessed_at"}:
            errors.append(f"sources[{index}] must contain exactly source_id, locator, and accessed_at")
            continue
        source_id = source.get("source_id")
        if source_id not in known_sources:
            errors.append(f"sources[{index}] references unknown registry source {source_id!r}")
        elif known_sources[source_id].get("authority") == "official":
            official_count += 1
        _nonempty(source.get("locator"), f"sources[{index}].locator", errors)
        _nonempty(source.get("accessed_at"), f"sources[{index}].accessed_at", errors)
        key = (source_id, source.get("locator"))
        if key in seen_sources:
            errors.append(f"sources[{index}] duplicates source and locator {key!r}")
        seen_sources.add(key)

    answer = value.get("answer")
    if answer is not None:
        expected_answer_fields = {
            "conclusion", "conditional", "analysis_steps", "confidence",
            "confidence_reason", "escalation_required", "escalation_target",
            "escalation_reason",
        }
        if not isinstance(answer, dict) or set(answer) != expected_answer_fields:
            errors.append(f"answer must contain exactly {sorted(expected_answer_fields)}")
        else:
            _nonempty(answer.get("conclusion"), "answer.conclusion", errors)
            if not isinstance(answer.get("conditional"), bool):
                errors.append("answer.conditional must be boolean")
            steps = answer.get("analysis_steps")
            if not isinstance(steps, list) or not steps or not all(isinstance(step, str) and step.strip() for step in steps):
                errors.append("answer.analysis_steps must be a non-empty array of non-empty strings")
            if answer.get("confidence") not in CONFIDENCE:
                errors.append(f"answer.confidence must be one of {sorted(CONFIDENCE)}")
            _nonempty(answer.get("confidence_reason"), "answer.confidence_reason", errors)
            if not isinstance(answer.get("escalation_required"), bool):
                errors.append("answer.escalation_required must be boolean")
            target = answer.get("escalation_target")
            if target not in ESCALATION_TARGETS:
                errors.append(f"answer.escalation_target must be one of {sorted(ESCALATION_TARGETS)}")
            if answer.get("escalation_required") is True:
                if target == "none":
                    errors.append("an escalated answer cannot use escalation_target 'none'")
                _nonempty(answer.get("escalation_reason"), "answer.escalation_reason", errors)
            elif target != "none":
                errors.append("a non-escalated answer must use escalation_target 'none'")
            if answer.get("confidence") == "High" and any(
                isinstance(item, dict) and item.get("material") is True for item in assumptions
            ):
                errors.append("High confidence is incompatible with an unresolved material assumption")
            if answer.get("confidence") == "High" and official_count == 0:
                errors.append("High confidence requires at least one official source")
            if value.get("question_type") == "source_conflict" and answer.get("confidence") == "High":
                errors.append("source_conflict consultations cannot finalize at High confidence")

    if value.get("status") == "final":
        if not facts:
            errors.append("final consultation requires at least one fact")
        if not sources:
            errors.append("final consultation requires at least one source")
        if official_count == 0:
            errors.append("final consultation requires at least one official source")
        if answer is None:
            errors.append("final consultation requires an answer")
    elif answer is not None:
        errors.append("draft consultation must keep answer null; use finalize to attach the answer")

    return errors


def require_valid(value: Any) -> None:
    errors = validate_consultation(value)
    if errors:
        raise ConsultationError("\n".join(f"- {error}" for error in errors))


def new_consultation(*, question_type: str, question: str, format_name: str, ruleset_as_of: str, created_by: str) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "mode": "rule-consult",
        "official_status": "unofficial",
        "state_effect": "none",
        "consultation_id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "created_by": created_by,
        "status": "draft",
        "question_type": question_type,
        "question": question,
        "format": format_name,
        "ruleset_as_of": ruleset_as_of,
        "facts": [],
        "assumptions": [],
        "sources": [],
        "answer": None,
    }
    require_valid(value)
    return value


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConsultationError(f"consultation file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConsultationError(f"invalid JSON in {path}: {exc}") from exc
    require_valid(value)
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    require_valid(value)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def mutate_draft(value: dict[str, Any]) -> dict[str, Any]:
    if value["status"] != "draft":
        raise ConsultationError("final consultation is immutable")
    return copy.deepcopy(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new")
    new.add_argument("path", type=Path)
    new.add_argument("--question-type", choices=sorted(QUESTION_TYPES), required=True)
    new.add_argument("--question", required=True)
    new.add_argument("--format", dest="format_name", required=True)
    new.add_argument("--ruleset-as-of", required=True)
    new.add_argument("--created-by", required=True)
    fact = sub.add_parser("fact")
    fact.add_argument("path", type=Path)
    fact.add_argument("--text", required=True)
    fact.add_argument("--origin", choices=["user", "official_source"], required=True)
    assumption = sub.add_parser("assumption")
    assumption.add_argument("path", type=Path)
    assumption.add_argument("--text", required=True)
    assumption.add_argument("--material", action="store_true")
    source = sub.add_parser("source")
    source.add_argument("path", type=Path)
    source.add_argument("--source-id", choices=sorted(registry_by_id()), required=True)
    source.add_argument("--locator", required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("path", type=Path)
    finalize.add_argument("--conclusion", required=True)
    finalize.add_argument("--conditional", action="store_true")
    finalize.add_argument("--step", action="append", required=True)
    finalize.add_argument("--confidence", choices=sorted(CONFIDENCE), required=True)
    finalize.add_argument("--confidence-reason", required=True)
    finalize.add_argument("--escalation-target", choices=sorted(ESCALATION_TARGETS), default="none")
    finalize.add_argument("--escalation-reason", default="")
    for command in ("validate", "show"):
        child = sub.add_parser(command)
        child.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            if args.path.exists():
                raise ConsultationError(f"refusing to overwrite existing consultation: {args.path}")
            value = new_consultation(
                question_type=args.question_type,
                question=args.question,
                format_name=args.format_name,
                ruleset_as_of=args.ruleset_as_of,
                created_by=args.created_by,
            )
        else:
            value = load(args.path)
            if args.command == "validate":
                print(f"OK: valid {value['status']} Rule Consult artifact")
                return 0
            if args.command == "show":
                print(json.dumps(value, ensure_ascii=False, indent=2))
                return 0
            value = mutate_draft(value)
            if args.command == "fact":
                value["facts"].append({"text": args.text.strip(), "origin": args.origin})
            elif args.command == "assumption":
                value["assumptions"].append({"text": args.text.strip(), "material": args.material})
            elif args.command == "source":
                value["sources"].append({"source_id": args.source_id, "locator": args.locator.strip(), "accessed_at": now_iso()})
            elif args.command == "finalize":
                target = args.escalation_target
                value["status"] = "final"
                value["answer"] = {
                    "conclusion": args.conclusion.strip(),
                    "conditional": args.conditional,
                    "analysis_steps": [step.strip() for step in args.step],
                    "confidence": args.confidence,
                    "confidence_reason": args.confidence_reason.strip(),
                    "escalation_required": target != "none",
                    "escalation_target": target,
                    "escalation_reason": args.escalation_reason.strip(),
                }
        save(args.path, value)
        print(f"OK: {args.command} ({args.path})")
        return 0
    except ConsultationError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
