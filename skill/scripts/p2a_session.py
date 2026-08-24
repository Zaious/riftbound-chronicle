#!/usr/bin/env python3
"""Create and validate an append-only P2-A manual-play session ledger.

The ledger deliberately does not model or resolve Riftbound rules. It stores
human-confirmed state summaries, unverified Agent proposals, and separate
human legality confirmations. A legal action never derives the resulting
state; the next authoritative position must be recorded with ``state``.

Examples:
    python3 p2a_session.py new demo.json --player1-deck "Deck A" \
        --player2-deck "Deck B" --format "1v1 Constructed" \
        --ruleset-version "Rules Hub 2026-08-24" --created-by Alice
    python3 p2a_session.py state demo.json --turn 1 --turn-player "Player 1" \
        --phase Main --public-state "Both Legends in zone; no units in play" \
        --player2-hand "four cards held by Player 2" --confirmed-by Alice
    python3 p2a_session.py propose demo.json --action-id p2-001 \
        --objective "Develop battlefield presence" \
        --description "Play the confirmed two-cost unit" \
        --reason "It advances the deck's early board plan"
    python3 p2a_session.py confirm demo.json --action-id p2-001 --legal \
        --confirmed-by Alice --resolution-summary "Human resolved the play"
    python3 p2a_session.py validate demo.json
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


SCHEMA_VERSION = "p2a-session.v1"
ALLOWED_TOP_LEVEL = {
    "schema_version",
    "mode",
    "automation_level",
    "p2s_enabled",
    "state_authority",
    "legality_authority",
    "session_id",
    "created_at",
    "created_by",
    "format",
    "ruleset_version",
    "decks",
    "events",
}
ALLOWED_EVENT_FIELDS = {
    "state_confirmed": {
        "seq", "type", "recorded_at", "authority", "confirmed_by", "turn",
        "turn_player", "phase", "public_state", "player2_private_hand", "notes",
    },
    "action_proposed": {
        "seq", "type", "recorded_at", "action_id", "state_seq", "objective", "description",
        "reason", "alternative", "assumptions", "legality_status",
    },
    "action_confirmed": {
        "seq", "type", "recorded_at", "action_id", "legal", "confirmed_by",
        "resolution_summary", "state_transition",
    },
}
FORBIDDEN_HIDDEN_KEYS = {
    "player1_hand",
    "player1_private_hand",
    "player1_private",
    "opponent_hand",
    "opponent_private_hand",
    "opponent_private",
    "deck_order",
}


class ProtocolError(ValueError):
    """Raised when a P2-A session violates the manual-authority contract."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _nonempty(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")


def _find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key.lower() in FORBIDDEN_HIDDEN_KEYS:
                hits.append(child_path)
            hits.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return hits


def validate_session(session: Any) -> list[str]:
    """Return every protocol error found; an empty list means valid."""
    errors: list[str] = []
    if not isinstance(session, dict):
        return ["session must be a JSON object"]

    missing = ALLOWED_TOP_LEVEL - set(session)
    unknown = set(session) - ALLOWED_TOP_LEVEL
    if missing:
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")

    expected_constants = {
        "schema_version": SCHEMA_VERSION,
        "mode": "player2-agent",
        "automation_level": "P2-A",
        "p2s_enabled": False,
        "state_authority": "user_confirmed",
        "legality_authority": "user_confirmed",
    }
    for field, expected in expected_constants.items():
        if session.get(field) != expected:
            errors.append(f"{field} must be {expected!r}, got {session.get(field)!r}")

    for field in ("session_id", "created_at", "created_by", "format", "ruleset_version"):
        _nonempty(session.get(field), field, errors)

    decks = session.get("decks")
    if not isinstance(decks, dict) or set(decks) != {"player1", "player2"}:
        errors.append("decks must contain exactly player1 and player2 labels")
    else:
        _nonempty(decks.get("player1"), "decks.player1", errors)
        _nonempty(decks.get("player2"), "decks.player2", errors)

    hidden_hits = _find_forbidden_keys(session)
    if hidden_hits:
        errors.append("Player 1/opponent hidden information fields are forbidden: " + ", ".join(hidden_hits))

    events = session.get("events")
    if not isinstance(events, list):
        errors.append("events must be an array")
        return errors

    proposed: dict[str, tuple[int, int]] = {}
    confirmed: set[str] = set()
    have_state = False
    current_state_seq = 0
    awaiting_state_snapshot = False

    for index, event in enumerate(events):
        label = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{label} must be an object")
            continue

        if event.get("seq") != index + 1:
            errors.append(f"{label}.seq must be {index + 1}")
        event_type = event.get("type")
        if event_type not in ALLOWED_EVENT_FIELDS:
            errors.append(f"{label}.type {event_type!r} is not allowed")
            continue

        missing_event = ALLOWED_EVENT_FIELDS[event_type] - set(event)
        unknown_event = set(event) - ALLOWED_EVENT_FIELDS[event_type]
        if missing_event:
            errors.append(f"{label} missing fields: {sorted(missing_event)}")
        if unknown_event:
            errors.append(f"{label} has unknown fields: {sorted(unknown_event)}")
        _nonempty(event.get("recorded_at"), f"{label}.recorded_at", errors)

        if awaiting_state_snapshot and event_type != "state_confirmed":
            errors.append(
                f"{label} must be state_confirmed: a legal action was accepted and the resulting state requires a new human snapshot"
            )

        if event_type == "state_confirmed":
            if event.get("authority") != "user_confirmed":
                errors.append(f"{label}.authority must be 'user_confirmed'")
            _nonempty(event.get("confirmed_by"), f"{label}.confirmed_by", errors)
            if not isinstance(event.get("turn"), int) or event.get("turn", -1) < 0:
                errors.append(f"{label}.turn must be a non-negative integer")
            if event.get("turn_player") not in {"Player 1", "Player 2"}:
                errors.append(f"{label}.turn_player must be 'Player 1' or 'Player 2'")
            _nonempty(event.get("phase"), f"{label}.phase", errors)
            _nonempty(event.get("public_state"), f"{label}.public_state", errors)
            if not isinstance(event.get("player2_private_hand"), str):
                errors.append(f"{label}.player2_private_hand must be a string")
            if not isinstance(event.get("notes"), str):
                errors.append(f"{label}.notes must be a string")
            have_state = True
            current_state_seq = event.get("seq") if isinstance(event.get("seq"), int) else 0
            awaiting_state_snapshot = False

        elif event_type == "action_proposed":
            if not have_state:
                errors.append(f"{label} requires an earlier human-confirmed state")
            action_id = event.get("action_id")
            _nonempty(action_id, f"{label}.action_id", errors)
            state_seq = event.get("state_seq")
            if not isinstance(state_seq, int) or state_seq < 1:
                errors.append(f"{label}.state_seq must reference a confirmed state sequence")
            elif state_seq != current_state_seq:
                errors.append(
                    f"{label}.state_seq must be the current confirmed state ({current_state_seq}), got {state_seq}"
                )
            if isinstance(action_id, str):
                if action_id in proposed:
                    errors.append(f"{label}.action_id {action_id!r} was already proposed")
                else:
                    proposed[action_id] = (index, state_seq if isinstance(state_seq, int) else 0)
            for field in ("objective", "description", "reason"):
                _nonempty(event.get(field), f"{label}.{field}", errors)
            if not isinstance(event.get("alternative"), str):
                errors.append(f"{label}.alternative must be a string")
            assumptions = event.get("assumptions")
            if not isinstance(assumptions, list) or not all(isinstance(x, str) for x in assumptions):
                errors.append(f"{label}.assumptions must be an array of strings")
            if event.get("legality_status") != "unverified":
                errors.append(f"{label}.legality_status must be 'unverified'")

        elif event_type == "action_confirmed":
            action_id = event.get("action_id")
            _nonempty(action_id, f"{label}.action_id", errors)
            if not isinstance(action_id, str) or action_id not in proposed:
                errors.append(f"{label} references action_id {action_id!r} before a proposal")
            if isinstance(action_id, str):
                if action_id in confirmed:
                    errors.append(f"{label}.action_id {action_id!r} was already confirmed")
                confirmed.add(action_id)
                proposal = proposed.get(action_id)
                if proposal is not None and proposal[1] != current_state_seq:
                    errors.append(
                        f"{label} confirms a proposal from state {proposal[1]}, but current state is {current_state_seq}"
                    )
            if not isinstance(event.get("legal"), bool):
                errors.append(f"{label}.legal must be boolean")
            _nonempty(event.get("confirmed_by"), f"{label}.confirmed_by", errors)
            if not isinstance(event.get("resolution_summary"), str):
                errors.append(f"{label}.resolution_summary must be a string")
            expected_transition = "pending_user_snapshot" if event.get("legal") is True else "none"
            if event.get("state_transition") != expected_transition:
                errors.append(
                    f"{label}.state_transition must be {expected_transition!r} for legal={event.get('legal')!r}"
                )
            if event.get("legal") is True:
                awaiting_state_snapshot = True

    return errors


def require_valid(session: Any) -> None:
    errors = validate_session(session)
    if errors:
        raise ProtocolError("\n".join(f"- {error}" for error in errors))


def new_session(
    *, player1_deck: str, player2_deck: str, format_name: str,
    ruleset_version: str, created_by: str,
) -> dict[str, Any]:
    session = {
        "schema_version": SCHEMA_VERSION,
        "mode": "player2-agent",
        "automation_level": "P2-A",
        "p2s_enabled": False,
        "state_authority": "user_confirmed",
        "legality_authority": "user_confirmed",
        "session_id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "created_by": created_by,
        "format": format_name,
        "ruleset_version": ruleset_version,
        "decks": {"player1": player1_deck, "player2": player2_deck},
        "events": [],
    }
    require_valid(session)
    return session


def _append(session: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(session)
    event = dict(event)
    event["seq"] = len(updated["events"]) + 1
    event["recorded_at"] = now_iso()
    updated["events"].append(event)
    require_valid(updated)
    return updated


def add_state(
    session: dict[str, Any], *, turn: int, turn_player: str, phase: str,
    public_state: str, player2_private_hand: str, confirmed_by: str,
    notes: str = "",
) -> dict[str, Any]:
    return _append(session, {
        "type": "state_confirmed",
        "authority": "user_confirmed",
        "confirmed_by": confirmed_by,
        "turn": turn,
        "turn_player": turn_player,
        "phase": phase,
        "public_state": public_state,
        "player2_private_hand": player2_private_hand,
        "notes": notes,
    })


def add_proposal(
    session: dict[str, Any], *, action_id: str, objective: str,
    description: str, reason: str, alternative: str = "",
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    state_seq = max(
        (event["seq"] for event in session.get("events", []) if event.get("type") == "state_confirmed"),
        default=0,
    )
    return _append(session, {
        "type": "action_proposed",
        "action_id": action_id,
        "state_seq": state_seq,
        "objective": objective,
        "description": description,
        "reason": reason,
        "alternative": alternative,
        "assumptions": assumptions or [],
        "legality_status": "unverified",
    })


def add_confirmation(
    session: dict[str, Any], *, action_id: str, legal: bool,
    confirmed_by: str, resolution_summary: str = "",
) -> dict[str, Any]:
    return _append(session, {
        "type": "action_confirmed",
        "action_id": action_id,
        "legal": legal,
        "confirmed_by": confirmed_by,
        "resolution_summary": resolution_summary,
        "state_transition": "pending_user_snapshot" if legal else "none",
    })


def load_session(path: Path) -> dict[str, Any]:
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProtocolError(f"session file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON in {path}: {exc}") from exc
    require_valid(session)
    return session


def save_session(path: Path, session: dict[str, Any]) -> None:
    require_valid(session)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(session, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="create a new P2-A session")
    new.add_argument("path", type=Path)
    new.add_argument("--player1-deck", required=True)
    new.add_argument("--player2-deck", required=True)
    new.add_argument("--format", dest="format_name", required=True)
    new.add_argument("--ruleset-version", required=True)
    new.add_argument("--created-by", required=True)

    state = sub.add_parser("state", help="append a human-confirmed state snapshot")
    state.add_argument("path", type=Path)
    state.add_argument("--turn", type=int, required=True)
    state.add_argument("--turn-player", choices=["Player 1", "Player 2"], required=True)
    state.add_argument("--phase", required=True)
    state.add_argument("--public-state", required=True)
    state.add_argument("--player2-hand", default="")
    state.add_argument("--confirmed-by", required=True)
    state.add_argument("--notes", default="")

    propose = sub.add_parser("propose", help="append an unverified Agent action proposal")
    propose.add_argument("path", type=Path)
    propose.add_argument("--action-id", required=True)
    propose.add_argument("--objective", required=True)
    propose.add_argument("--description", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--alternative", default="")
    propose.add_argument("--assumption", action="append", default=[])

    confirm = sub.add_parser("confirm", help="append a human legality confirmation")
    confirm.add_argument("path", type=Path)
    confirm.add_argument("--action-id", required=True)
    legality = confirm.add_mutually_exclusive_group(required=True)
    legality.add_argument("--legal", action="store_true")
    legality.add_argument("--illegal", action="store_true")
    confirm.add_argument("--confirmed-by", required=True)
    confirm.add_argument("--resolution-summary", default="")

    validate = sub.add_parser("validate", help="validate a session without modifying it")
    validate.add_argument("path", type=Path)

    show = sub.add_parser("show", help="print a validated session")
    show.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            if args.path.exists():
                raise ProtocolError(f"refusing to overwrite existing session: {args.path}")
            session = new_session(
                player1_deck=args.player1_deck,
                player2_deck=args.player2_deck,
                format_name=args.format_name,
                ruleset_version=args.ruleset_version,
                created_by=args.created_by,
            )
            save_session(args.path, session)
        else:
            session = load_session(args.path)
            if args.command == "state":
                session = add_state(
                    session,
                    turn=args.turn,
                    turn_player=args.turn_player,
                    phase=args.phase,
                    public_state=args.public_state,
                    player2_private_hand=args.player2_hand,
                    confirmed_by=args.confirmed_by,
                    notes=args.notes,
                )
                save_session(args.path, session)
            elif args.command == "propose":
                session = add_proposal(
                    session,
                    action_id=args.action_id,
                    objective=args.objective,
                    description=args.description,
                    reason=args.reason,
                    alternative=args.alternative,
                    assumptions=args.assumption,
                )
                save_session(args.path, session)
            elif args.command == "confirm":
                session = add_confirmation(
                    session,
                    action_id=args.action_id,
                    legal=args.legal,
                    confirmed_by=args.confirmed_by,
                    resolution_summary=args.resolution_summary,
                )
                save_session(args.path, session)
            elif args.command == "validate":
                print(f"OK: valid P2-A session ({len(session['events'])} event(s))")
                return 0
            elif args.command == "show":
                print(json.dumps(session, ensure_ascii=False, indent=2))
                return 0

        print(f"OK: {args.command} ({args.path})")
        return 0
    except ProtocolError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
