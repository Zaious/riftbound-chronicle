#!/usr/bin/env python3
"""
keyword-catalog.v1 — which keywords the engine implements, and how (ADR-0013 §4).

Codex's G-2 ruling on DP-70: a keyword is never claimed because its string
appears on a card. Every entry names the official locator, the production that
implements it — a module and a symbol that must exist in the live engine — the
layer it acts in, the zone it is active in, its identity and duration boundary,
and the gate that exercises it. An entry with `production: null` is a keyword
the engine knows of and does not implement; asking for it answers
`unsupported: keyword_not_implemented`.

`verify` derives its answer from the engine rather than from the file: every
keyword the engine treats as a characteristic, a grantable value or a play
permission must be catalogued with a production, and every production named
must resolve to a real symbol.

CLI:
  keyword_catalog.py validate [path]   shape and review records
  keyword_catalog.py verify [path]     productions resolve; engine keywords are all catalogued
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

CATALOG_VERSION = "keyword-catalog.v1"
DEFAULT_PATH = SKILL_DIR / "data" / "keyword_catalog" / "keyword_catalog.json"
REQUIRED_ENTRY = {"keyword_id", "name", "locators", "production", "active_zone", "boundary", "review"}
OPTIONAL_ENTRY = {"fixture"}
LAYERS = {"trait", "ability", "arithmetic", "timing", "cost", "procedure", "characteristic"}
ZONES = {"board", "hand_or_champion_zone", "chain", "any", "deck_construction"}


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DEFAULT_PATH).read_text(encoding="utf-8"))


def validate_catalog(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["keyword catalogue must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != CATALOG_VERSION:
        errors.append(f"schema_version must be {CATALOG_VERSION}")
    if value.get("status") != "draft":
        errors.append("status must be draft")
    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        return errors + ["entries must be a non-empty array"]
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict) or not REQUIRED_ENTRY <= set(entry) or set(entry) - REQUIRED_ENTRY - OPTIONAL_ENTRY:
            errors.append(f"{label} must carry exactly {sorted(REQUIRED_ENTRY)} (and optionally fixture)")
            continue
        keyword_id = entry["keyword_id"]
        if not isinstance(keyword_id, str) or not keyword_id or keyword_id in seen:
            errors.append(f"{label}.keyword_id is invalid or duplicated")
        seen.add(keyword_id if isinstance(keyword_id, str) else "")
        if not isinstance(entry["locators"], list) or not entry["locators"] or any(not isinstance(x, str) or not x.startswith("Core ") for x in entry["locators"]):
            errors.append(f"{label}.locators must be a non-empty array of Core locators")
        production = entry["production"]
        if production is not None:
            if not isinstance(production, dict) or not {"module", "symbol", "layer"} <= set(production) or set(production) - {"module", "symbol", "layer", "note"}:
                errors.append(f"{label}.production must be null or {{module, symbol, layer, note?}}")
            elif production["layer"] not in LAYERS:
                errors.append(f"{label}.production.layer must be one of {sorted(LAYERS)}")
        if entry["active_zone"] not in ZONES:
            errors.append(f"{label}.active_zone must be one of {sorted(ZONES)}")
        boundary = entry["boundary"]
        if not isinstance(boundary, dict) or set(boundary) != {"identity", "duration"} or not all(isinstance(v, str) and v for v in boundary.values()):
            errors.append(f"{label}.boundary must state the identity and the duration")
        review = entry["review"]
        if not isinstance(review, dict) or not {"reviewer", "date", "source"} <= set(review) or not all(isinstance(review.get(k), str) and review.get(k) for k in ("reviewer", "date", "source")):
            errors.append(f"{label}.review must carry reviewer, date and source")
    return errors


ENGINE_SOURCES = ("effect_ir.py", "combat.py", "play_transaction.py", "hidden.py", "resolution_bridge.py",
                  "rules_core.py", "battlefield_control.py", "turn_cycle.py")


def engine_keywords() -> dict[str, dict[str, Any]]:
    """Derived from the engine: which keywords it can carry, and which it acts
    on. A keyword the engine merely *accepts* on an object (it is in the
    characteristic vocabulary) must be catalogued; a keyword some procedure
    reads must also have a production. The difference is measured by where the
    literal appears, not by a hand-written list."""
    import effect_ir
    carryable = set(effect_ir.OBJECT_KEYWORDS) | set(effect_ir.GRANTABLE_KEYWORDS)
    carryable |= {p for p in effect_ir.PLAY_PERMISSIONS if p != "open_battlefield"}
    carryable |= {"hidden", "unique", "repeat"}
    declarations = ("OBJECT_KEYWORDS", "GRANTABLE_KEYWORDS", "PLAY_PERMISSIONS")
    found: dict[str, dict[str, Any]] = {}
    for keyword in sorted(carryable):
        acted_on: list[str] = []
        for name in ENGINE_SOURCES:
            path = SCRIPT_DIR / name
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                if f'"{keyword}"' not in line or any(token in line for token in declarations):
                    continue
                # A validator's allow-list is vocabulary, not behaviour: it says
                # the word may be written, not that anything acts on it.
                enclosing = next((l.split("(")[0][4:] for l in reversed(lines[:number]) if l.startswith("def ")), "")
                if enclosing.startswith("validate") or enclosing.endswith("_errors"):
                    continue
                acted_on.append(f"{name}:{number}")
        found[keyword] = {"carryable": True, "acted_on": acted_on}
    return found


def verify(catalog: dict[str, Any]) -> list[str]:
    """Derived from the engine, not from the file."""
    problems: list[str] = []
    by_id = {e["keyword_id"]: e for e in catalog.get("entries", []) if isinstance(e, dict)}
    for keyword, facts in sorted(engine_keywords().items()):
        entry = by_id.get(keyword)
        if entry is None:
            problems.append(f"the engine can carry {keyword!r} but the catalogue does not list it")
            continue
        if facts["acted_on"] and entry["production"] is None:
            problems.append(f"{keyword!r} is read by {facts['acted_on'][:3]} but the catalogue claims no production")
        if not facts["acted_on"] and entry["production"] is not None:
            problems.append(f"{keyword!r} claims a production but no engine procedure reads it; a keyword is not implemented by being spellable")
    for entry in by_id.values():
        production = entry["production"]
        if production is None:
            continue
        try:
            module = importlib.import_module(production["module"])
        except ImportError:
            problems.append(f"{entry['keyword_id']}: production module {production['module']!r} does not import")
            continue
        if not hasattr(module, production["symbol"]):
            problems.append(f"{entry['keyword_id']}: production {production['module']}.{production['symbol']} does not exist")
        fixture = entry.get("fixture")
        if fixture and not (SCRIPT_DIR / fixture).exists():
            problems.append(f"{entry['keyword_id']}: fixture {fixture} does not exist")
    return problems


def keyword_supported(catalog: dict[str, Any], keyword: str) -> tuple[bool, str]:
    entry = next((e for e in catalog.get("entries", []) if e.get("keyword_id") == keyword), None)
    if entry is None:
        return False, f"{keyword!r} is not in the keyword catalogue (unsupported: keyword_not_implemented)"
    if entry["production"] is None:
        return False, f"{keyword!r} is catalogued with no production (unsupported: keyword_not_implemented)"
    return True, f"{entry['production']['module']}.{entry['production']['symbol']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "verify"):
        p = sub.add_parser(name)
        p.add_argument("path", type=Path, nargs="?", default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    catalog = load_catalog(args.path)
    problems = validate_catalog(catalog) if args.command == "validate" else verify(catalog)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        return 1
    print("keyword catalogue valid" if args.command == "validate" else "every engine keyword is catalogued and every production resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
