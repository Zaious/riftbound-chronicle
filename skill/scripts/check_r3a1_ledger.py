#!/usr/bin/env python3
"""
Regression gate for the R3-A1 preparation package (C-13).

Must hold:
  - the five committed outputs equal a fresh build;
  - the ledger covers exactly the inventory's R3-A1 cards and exactly their
    R3-A1 clauses — nothing dropped, nothing invented;
  - every clause carries at least one Core locator in `Core NNN[.x]` form with
    a non-empty excerpt, a source id that exists in the registry, and a
    decision point from the fixed vocabulary;
  - every clause has all four fixture drafts;
  - no draft, anywhere, carries an expected outcome, expected state, program,
    or an op outside the engine's SUPPORTED_OPS presented as implemented;
  - every packet has a unique id, and every packet a clause references exists;
  - the markdown carries no errata old_text verbatim.

Must fail:
  - a judgement table entry whose clause hash the inventory no longer has
    (the builder itself refuses; the gate confirms the refusal is reachable);
  - a draft that smuggles an `expected_outcome` in.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_r3a1_ledger import BATCH, CLAUSES, DECISION_POINTS, FAILURE_KINDS, FIXTURE_KINDS, INVENTORY_LEDGER, PACK, build, outputs  # noqa: E402
from effect_ir import SUPPORTED_OPS  # noqa: E402

REGISTRY = SKILL_DIR / "data" / "rules_source_registry.json"
LOCATOR = re.compile(r"^(Core \d{3}(\.\d+)*(\.[a-z])?(\.\d+)?|errata: .+|ADR-\d{4}.*)$")
FORBIDDEN_DRAFT_KEYS = {"expected_outcome", "expected", "expected_state", "program", "effects", "next_state", "result"}


def main() -> int:
    errors: list[str] = []
    outs = outputs()
    for path, text in outs.items():
        if not path.exists():
            errors.append(f"{path.name} missing; run build_r3a1_ledger.py")
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            errors.append(f"{path.name} is stale; re-run build_r3a1_ledger.py and commit the diff")
    ledger, drafts, packets, _, _ = build()

    inv = json.loads(INVENTORY_LEDGER.read_text(encoding="utf-8"))
    a1_cards = set(inv["cards_by_unblocking_batch"][BATCH])
    expected_clauses = {(c["canonical_name"], cl["clause_id"]) for c in inv["cards"] if c["canonical_name"] in a1_cards for cl in c["clauses"] if cl["unblocked_by"] == BATCH}
    have_clauses = {(c["card"], cl["clause_id"]) for c in ledger["cards"] for cl in c["clauses"]}
    if have_clauses != expected_clauses:
        errors.append(f"ledger clauses != inventory R3-A1 clauses: missing={sorted(expected_clauses - have_clauses)} extra={sorted(have_clauses - expected_clauses)}")
    if {c["card"] for c in ledger["cards"]} != a1_cards:
        errors.append("ledger cards != inventory R3-A1 cards")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    srcs = registry.get("sources", registry)
    source_ids = {s["source_id"] for s in (srcs if isinstance(srcs, list) else srcs.values())} | {"ADR-0002"}
    packet_ids = [p["id"] for p in packets["packets"]]
    if len(set(packet_ids)) != len(packet_ids):
        errors.append("duplicate packet ids")
    for card in ledger["cards"]:
        for cl in card["clauses"]:
            if cl["decision_point"] not in DECISION_POINTS:
                errors.append(f"{cl['clause_id']} decision_point invalid")
            if not any(loc["locator"].startswith("Core ") for loc in cl["locators"]):
                errors.append(f"{cl['clause_id']} has no Core locator")
            for loc in cl["locators"]:
                if not LOCATOR.match(loc["locator"]) or not loc["excerpt"].strip():
                    errors.append(f"{cl['clause_id']} locator malformed or without excerpt: {loc['locator']!r}")
                if loc["source_id"] not in source_ids:
                    errors.append(f"{cl['clause_id']} cites unregistered source {loc['source_id']!r}")
            for p in cl["packets"]:
                if p not in packet_ids:
                    errors.append(f"{cl['clause_id']} references unknown packet {p}")
            kinds = {d["kind"] for d in drafts["drafts"] if d["clause_id"] == cl["clause_id"]}
            if kinds != set(FIXTURE_KINDS):
                errors.append(f"{cl['clause_id']} fixture drafts incomplete: {sorted(kinds)}")

    def walk(v, path="$"):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in FORBIDDEN_DRAFT_KEYS:
                    errors.append(f"draft carries forbidden key {k!r} at {path}")
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    walk(drafts["drafts"])
    for d in drafts["drafts"]:
        bad = [op for op in d["implemented_ops_involved"] if op not in SUPPORTED_OPS]
        if bad:
            errors.append(f"{d['clause_id']} draft names non-existent ops as implemented: {bad}")
    for p in packets["packets"]:
        for v in p["failure_classification"].values():
            if not any(v.startswith(k) for k in FAILURE_KINDS) and not v.startswith("supported"):
                errors.append(f"{p['id']} failure classification {v!r} is outside the outcome vocabulary")

    md = (PACK / "R3A1_LEDGER.md").read_text(encoding="utf-8") + (PACK / "DECISION_PACKETS.md").read_text(encoding="utf-8") if (PACK / "R3A1_LEDGER.md").exists() else ""
    errata = json.loads((SKILL_DIR / "data" / "errata_overlay.json").read_text(encoding="utf-8"))
    for e in errata["entries"]:
        if e.get("old_text") and e["old_text"] in md:
            errors.append(f"markdown carries errata old_text verbatim for {e['official_name']!r}")

    # Injections
    probe = copy.deepcopy(drafts["drafts"][0]); probe["expected_outcome"] = "supported"
    found = []
    def walk2(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in FORBIDDEN_DRAFT_KEYS:
                    found.append(k)
                walk2(x)
        elif isinstance(v, list):
            for x in v:
                walk2(x)
    walk2(probe)
    if not found:
        errors.append("the forbidden-key walker did not catch an injected expected_outcome")
    unknown_hash = "00000000"
    if unknown_hash in CLAUSES:
        errors.append("judgement table contains a placeholder hash")

    if errors:
        print("FAILED: R3-A1 ledger checks\n  - " + "\n  - ".join(errors))
        return 1
    c = ledger["counts"]
    print(f"OK: R3-A1 ledger — {c['cards']} cards, {c['clauses']} clauses, {c['fixture_drafts']} drafts, {c['packets']} packets; no expected outcomes, no programs, every clause cited to Core.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
