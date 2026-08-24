#!/usr/bin/env python3
"""Create, validate, and render a structured Deck Coach artifact."""

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
ROLE_PATH = SKILL_DIR / "data" / "deck_coach_roles.json"
SCHEMA_VERSION = "deck-coach-session.v1"
PRIMER_SECTIONS = (
    "identity", "core_loop", "mulligan_targets", "turn_priorities",
    "fight_or_hold", "common_lines", "common_mistakes", "evidence_ledger",
)
TIER_VALUES = {"Tier 1", "Tier 2", "Tier 3"}
ALLOWED_TOP = {
    "schema_version", "mode", "session_id", "created_at", "created_by", "status",
    "environment", "format", "legend", "chosen_champion", "decklist", "diagnosis", "primer",
}
FORBIDDEN_RATE_KEYS = {"win_rate", "play_rate", "matchup_win_rate", "usage_rate", "tier_rank", "score"}


class DeckCoachError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def role_ids() -> tuple[str, ...]:
    data = json.loads(ROLE_PATH.read_text(encoding="utf-8"))
    return tuple(role["role_id"] for role in data["roles"])


def _nonempty(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")


def _forbidden_paths(value: Any, path: str = "$") -> list[str]:
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key.lower() in FORBIDDEN_RATE_KEYS:
                hits.append(child_path)
            hits.extend(_forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_forbidden_paths(child, f"{path}[{index}]"))
    return hits


def role_coverage(decklist: list[dict[str, Any]]) -> dict[str, list[str]]:
    known = role_ids()
    seen = {role for card in decklist for role in card.get("roles", []) if role in known}
    return {"present": [role for role in known if role in seen], "not_observed": [role for role in known if role not in seen]}


def validate_session(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["session must be a JSON object"]
    missing, unknown = ALLOWED_TOP - set(value), set(value) - ALLOWED_TOP
    if missing:
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if value.get("mode") != "deck-coach":
        errors.append("mode must be 'deck-coach'")
    if value.get("status") not in {"draft", "final"}:
        errors.append("status must be draft or final")
    for field in ("session_id", "created_at", "created_by", "environment", "format", "legend"):
        _nonempty(value.get(field), field, errors)
    if value.get("chosen_champion") is not None and not isinstance(value.get("chosen_champion"), str):
        errors.append("chosen_champion must be a string or null")
    forbidden = _forbidden_paths(value)
    if forbidden:
        errors.append("session contains forbidden rate/score fields: " + ", ".join(forbidden))

    known_roles = set(role_ids())
    decklist = value.get("decklist")
    if not isinstance(decklist, list):
        errors.append("decklist must be an array")
        decklist = []
    for index, card in enumerate(decklist):
        if not isinstance(card, dict) or set(card) != {"name", "count", "roles", "notes"}:
            errors.append(f"decklist[{index}] must contain exactly name, count, roles, and notes")
            continue
        _nonempty(card.get("name"), f"decklist[{index}].name", errors)
        if not isinstance(card.get("count"), int) or isinstance(card.get("count"), bool) or card["count"] < 1:
            errors.append(f"decklist[{index}].count must be a positive integer")
        roles = card.get("roles")
        if not isinstance(roles, list) or len(roles) != len(set(roles)):
            errors.append(f"decklist[{index}].roles must be a unique array")
        elif unknown_roles := set(roles) - known_roles:
            errors.append(f"decklist[{index}] uses unknown roles: {sorted(unknown_roles)}")
        if not isinstance(card.get("notes"), str):
            errors.append(f"decklist[{index}].notes must be a string")

    diagnosis = value.get("diagnosis")
    if diagnosis is not None:
        expected = {"identity", "core_loop", "strengths", "gaps", "proposed_changes", "role_coverage", "evidence"}
        if not isinstance(diagnosis, dict) or set(diagnosis) != expected:
            errors.append(f"diagnosis must contain exactly {sorted(expected)}")
        else:
            _nonempty(diagnosis.get("identity"), "diagnosis.identity", errors)
            _nonempty(diagnosis.get("core_loop"), "diagnosis.core_loop", errors)
            for field in ("strengths", "gaps", "proposed_changes"):
                items = diagnosis.get(field)
                if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
                    errors.append(f"diagnosis.{field} must be an array of non-empty strings")
            if diagnosis.get("role_coverage") != role_coverage(decklist):
                errors.append("diagnosis.role_coverage must be derived from decklist roles")
            evidence = diagnosis.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append("diagnosis.evidence must be a non-empty array")
            else:
                for index, item in enumerate(evidence):
                    if not isinstance(item, dict) or set(item) != {"claim", "tier", "basis"}:
                        errors.append(f"diagnosis.evidence[{index}] must contain claim, tier, and basis")
                    elif item.get("tier") not in TIER_VALUES:
                        errors.append(f"diagnosis.evidence[{index}].tier is invalid")
                    else:
                        _nonempty(item.get("claim"), f"diagnosis.evidence[{index}].claim", errors)
                        _nonempty(item.get("basis"), f"diagnosis.evidence[{index}].basis", errors)

    primer = value.get("primer")
    if primer is not None:
        if not isinstance(primer, dict) or tuple(primer) != PRIMER_SECTIONS:
            errors.append(f"primer must contain the eight ordered sections: {list(PRIMER_SECTIONS)}")
        else:
            for field in PRIMER_SECTIONS:
                _nonempty(primer.get(field), f"primer.{field}", errors)

    if value.get("status") == "final":
        if not decklist:
            errors.append("final session requires at least one decklist entry")
        if diagnosis is None:
            errors.append("final session requires diagnosis")
        if primer is None:
            errors.append("final session requires primer")
    elif diagnosis is not None or primer is not None:
        errors.append("draft session must keep diagnosis and primer null; use finalize")
    return errors


def require_valid(value: Any) -> None:
    errors = validate_session(value)
    if errors:
        raise DeckCoachError("\n".join(f"- {error}" for error in errors))


def new_session(*, environment: str, format_name: str, legend: str, champion: str | None, created_by: str) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "mode": "deck-coach",
        "session_id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "created_by": created_by,
        "status": "draft",
        "environment": environment,
        "format": format_name,
        "legend": legend,
        "chosen_champion": champion or None,
        "decklist": [],
        "diagnosis": None,
        "primer": None,
    }
    require_valid(value)
    return value


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise DeckCoachError(f"cannot load session: {exc}") from exc
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


def render_markdown(value: dict[str, Any]) -> str:
    require_valid(value)
    if value["status"] != "final":
        raise DeckCoachError("only a final session can render a primer")
    labels = {
        "identity": "Identity", "core_loop": "Core loop", "mulligan_targets": "Mulligan targets",
        "turn_priorities": "Turn-by-turn priorities", "fight_or_hold": "When to fight, when to hold",
        "common_lines": "Common lines", "common_mistakes": "Common mistakes", "evidence_ledger": "Evidence ledger",
    }
    lines = [f"# {value['legend']} — Deck Primer", "", f"Environment: {value['environment']} · Format: {value['format']}", ""]
    for number, key in enumerate(PRIMER_SECTIONS, 1):
        lines.extend([f"{number}. **{labels[key]}**", "", value["primer"][key], ""])
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new")
    new.add_argument("path", type=Path)
    new.add_argument("--environment", required=True)
    new.add_argument("--format", dest="format_name", required=True)
    new.add_argument("--legend", required=True)
    new.add_argument("--champion")
    new.add_argument("--created-by", required=True)
    card = sub.add_parser("add-card")
    card.add_argument("path", type=Path)
    card.add_argument("--name", required=True)
    card.add_argument("--count", required=True, type=int)
    card.add_argument("--role", action="append", choices=role_ids(), default=[])
    card.add_argument("--notes", default="")
    finalize = sub.add_parser("finalize")
    finalize.add_argument("path", type=Path)
    finalize.add_argument("--diagnosis", type=Path, required=True, help="JSON object with identity, core_loop, strengths, gaps, proposed_changes, and evidence")
    finalize.add_argument("--primer", type=Path, required=True, help="JSON object containing the fixed eight primer sections")
    for command in ("validate", "show", "render"):
        child = sub.add_parser(command)
        child.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            if args.path.exists():
                raise DeckCoachError(f"refusing to overwrite existing session: {args.path}")
            value = new_session(environment=args.environment, format_name=args.format_name, legend=args.legend, champion=args.champion, created_by=args.created_by)
        else:
            value = load(args.path)
            if args.command == "validate":
                print(f"OK: valid {value['status']} Deck Coach artifact")
                return 0
            if args.command == "show":
                print(json.dumps(value, ensure_ascii=False, indent=2))
                return 0
            if args.command == "render":
                print(render_markdown(value), end="")
                return 0
            if value["status"] != "draft":
                raise DeckCoachError("final session is immutable")
            value = copy.deepcopy(value)
            if args.command == "add-card":
                value["decklist"].append({"name": args.name.strip(), "count": args.count, "roles": args.role, "notes": args.notes.strip()})
            elif args.command == "finalize":
                diagnosis = json.loads(args.diagnosis.read_text(encoding="utf-8"))
                primer = json.loads(args.primer.read_text(encoding="utf-8"))
                diagnosis["role_coverage"] = role_coverage(value["decklist"])
                value["diagnosis"], value["primer"], value["status"] = diagnosis, primer, "final"
        save(args.path, value)
        print(f"OK: {args.command} ({args.path})")
        return 0
    except (DeckCoachError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
