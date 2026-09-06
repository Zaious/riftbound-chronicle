#!/usr/bin/env python3
"""
token-catalog.v1 — the tokens a card program may play (ADR-0012 §6).

Codex's G-1 ruling on DP-67: a clause inventory may only produce *candidates*.
Every catalogue entry is promoted by hand and carries the official text it was
promoted from with its hash, the characteristics that text states, the cards
that create it, and a review record naming the reviewer, the date and the
source document. There is no automatic promotion, and an entry whose text hash
does not match its text fails the gate — so an errata cannot slip in unread.

The catalogue is consumed when card programs are compiled, not by the engine
at runtime: `play_token` still carries the characteristics it applies, plus the
`token_id` they were compiled from, so a program's provenance can be checked
against this file without the engine reading data at transition time.

CLI:
  token_catalog.py validate [path]        shape, hashes and review records
  token_catalog.py promote <entry.json>   add one reviewed entry (refuses without a review)
  token_catalog.py verify-pack <pack.json>  every play_token names a catalogued token
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

CATALOG_VERSION = "token-catalog.v1"
DEFAULT_PATH = SKILL_DIR / "data" / "token_catalog" / "token_catalog.json"
SCHEMA_PATH = SKILL_DIR / "schemas" / "token-catalog.schema.json"
REQUIRED_ENTRY = {"token_id", "name", "kind", "base_might", "keywords", "text", "text_sha256", "source_cards", "review"}
OPTIONAL_ENTRY = {"effect_program_id"}
KINDS = {"unit", "gear", "battlefield"}


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DEFAULT_PATH).read_text(encoding="utf-8"))


def validate_catalog(value: Any) -> list[str]:
    """Shape plus the relations the shape cannot state: a hash that matches its
    text, a unique id, and a review record on every entry."""
    if not isinstance(value, dict):
        return ["token catalogue must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != CATALOG_VERSION:
        errors.append(f"schema_version must be {CATALOG_VERSION}")
    if value.get("status") != "draft":
        errors.append("status must be draft; the catalogue never activates a pack on its own")
    ruleset = value.get("ruleset")
    if not isinstance(ruleset, dict) or set(ruleset) != {"core", "faq_as_of"} or not all(isinstance(v, str) and v for v in ruleset.values()):
        errors.append("ruleset must be {core, faq_as_of}")
    entries = value.get("entries")
    if not isinstance(entries, list):
        return errors + ["entries must be an array"]
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict) or not REQUIRED_ENTRY <= set(entry) or set(entry) - REQUIRED_ENTRY - OPTIONAL_ENTRY:
            errors.append(f"{label} must carry exactly {sorted(REQUIRED_ENTRY)} (and optionally effect_program_id)")
            continue
        token_id = entry["token_id"]
        if not isinstance(token_id, str) or not token_id or token_id in seen:
            errors.append(f"{label}.token_id is invalid or duplicated")
        seen.add(token_id if isinstance(token_id, str) else "")
        if entry["kind"] not in KINDS:
            errors.append(f"{label}.kind must be one of {sorted(KINDS)}")
        if not isinstance(entry["base_might"], int) or isinstance(entry["base_might"], bool) or entry["base_might"] < 0:
            errors.append(f"{label}.base_might must be a non-negative integer")
        if not isinstance(entry["keywords"], list) or len(entry["keywords"]) != len(set(entry["keywords"])) or any(not isinstance(k, str) or not k for k in entry["keywords"]):
            errors.append(f"{label}.keywords must be a unique array of non-empty strings")
        if not isinstance(entry["text"], str):
            errors.append(f"{label}.text must be a string")
        elif entry["text_sha256"] != text_hash(entry["text"]):
            errors.append(f"{label}.text_sha256 does not hash {label}.text; the entry was edited without another review")
        sources = entry["source_cards"]
        if not isinstance(sources, list) or not sources or any(not isinstance(s, dict) or set(s) != {"name", "locator"} or not all(isinstance(v, str) and v for v in s.values()) for s in sources):
            errors.append(f"{label}.source_cards must name at least one card with a locator")
        review = entry["review"]
        if not isinstance(review, dict) or not {"reviewer", "date", "source"} <= set(review) or set(review) - {"reviewer", "date", "source", "note"}:
            errors.append(f"{label}.review must carry reviewer, date and source (note optional)")
        elif not all(isinstance(review[k], str) and review[k] for k in ("reviewer", "date", "source")):
            errors.append(f"{label}.review fields must be non-empty strings")
        elif len(review["date"]) != 10 or review["date"][4] != "-" or review["date"][7] != "-":
            errors.append(f"{label}.review.date must be YYYY-MM-DD")
    return errors


def entry_of(catalog: dict[str, Any], token_id: str) -> dict[str, Any] | None:
    return next((e for e in catalog.get("entries", []) if e.get("token_id") == token_id), None)


def promote(catalog: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Add one reviewed entry. Refuses an entry without a review record, one
    whose id already exists, and one whose hash was supplied wrongly — the
    hash is derived here from the text the reviewer approved."""
    if not isinstance(entry, dict):
        raise ValueError("an entry must be an object")
    if not isinstance(entry.get("review"), dict) or not all(entry["review"].get(k) for k in ("reviewer", "date", "source")):
        raise ValueError("promotion needs a review record naming the reviewer, the date and the source document (ADR-0012 §6); nothing is promoted automatically")
    if entry_of(catalog, entry.get("token_id", "")) is not None:
        raise ValueError(f"token_id {entry.get('token_id')!r} is already in the catalogue; a new text needs a new id")
    prepared = dict(entry)
    prepared["text_sha256"] = text_hash(prepared.get("text", ""))
    updated = {**catalog, "entries": sorted(catalog.get("entries", []) + [prepared], key=lambda e: e["token_id"])}
    problems = validate_catalog(updated)
    if problems:
        raise ValueError("the promoted entry would make the catalogue invalid: " + "; ".join(problems))
    return updated


def program_token_ids(value: Any) -> list[tuple[str, str | None]]:
    """Every play_token in a card pack or program, with the token_id it names."""
    found: list[tuple[str, str | None]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("op") == "play_token":
                found.append((path, node.get("token_id")))
            for key, child in node.items():
                walk(child, f"{path}/{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    walk(value, "")
    return found


def verify_pack(pack: Any, catalog: dict[str, Any]) -> list[str]:
    """Every play_token a pack compiles must name a catalogued token whose
    characteristics agree with the entry (ADR-0012 §6)."""
    errors: list[str] = []
    for path, token_id in program_token_ids(pack):
        if not token_id:
            errors.append(f"{path}: play_token names no token_id; a token must come from the reviewed catalogue")
            continue
        entry = entry_of(catalog, token_id)
        if entry is None:
            errors.append(f"{path}: token {token_id!r} is not in the catalogue (unsupported: token_not_in_catalogue)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
    v.add_argument("path", type=Path, nargs="?", default=DEFAULT_PATH)
    p = sub.add_parser("promote")
    p.add_argument("entry", type=Path)
    p.add_argument("--catalog", type=Path, default=DEFAULT_PATH)
    w = sub.add_parser("verify-pack")
    w.add_argument("pack", type=Path)
    w.add_argument("--catalog", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    if args.command == "validate":
        problems = validate_catalog(load_catalog(args.path))
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("token catalogue valid" if not problems else f"FAILED: {len(problems)} problem(s)")
        return 1 if problems else 0
    if args.command == "promote":
        catalog = load_catalog(args.catalog)
        try:
            updated = promote(catalog, json.loads(args.entry.read_text(encoding="utf-8")))
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        args.catalog.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"promoted; the catalogue now holds {len(updated['entries'])} token(s)")
        return 0
    problems = verify_pack(json.loads(args.pack.read_text(encoding="utf-8")), load_catalog(args.catalog))
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print("every play_token names a catalogued token" if not problems else f"FAILED: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
