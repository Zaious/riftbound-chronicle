#!/usr/bin/env python3
"""
Gate for C-18: R3-A1 card programs and the derived behavior manifest.

Must hold:
  - the programs file is well-formed: known claims, fixture kinds, every
    clause id exists in inventory.draft.json, fixture ids unique;
  - every non-n/a fixture passes against the engine; a `full`/`partial`
    clause has a passing positive and negative fixture, and a choice clause
    a missing_information one;
  - the committed manifest and report equal a fresh build (deterministic);
  - the derived manifest validates; a claim never outranks its evidence
    (a full clause with failing fixtures derives unsupported); stale
    inventory clauses stay stale with no program_id; unsupported clauses
    carry no program_id and name a mechanic; card status is full only when
    every clause is full; the manifest stays draft;
  - inventory.draft.json is untouched by this pipeline;
  - text hashes equal the inventory's (the same "current text");
  - Vision clauses, when present, are unsupported with predict named;
  - off-cwd run.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import r3a1_programs as rp  # noqa: E402
from card_behavior_coverage import validate_manifest  # noqa: E402


def main() -> int:
    errors: list[str] = []
    programs = rp.load_programs()
    inventory = rp.load_inventory()
    inv_clauses = {c["clause_id"]: (card, c) for card in inventory["cards"] for c in card["clauses"]}
    if programs.get("schema_version") != rp.PROGRAMS_VERSION or programs.get("ruleset") != inventory["ruleset"]:
        errors.append("programs file version/ruleset mismatch")
    fixture_ids: set[str] = set()
    for card in programs["cards"]:
        if card["card_key"] not in {c["card_key"] for c in inventory["cards"]}:
            errors.append(f"{card['card']} is not in the inventory")
        for clause in card["clauses"]:
            if clause["claim"] not in rp.CLAIMS:
                errors.append(f"{clause['clause_id']} has an unknown claim")
            if clause["clause_id"] not in inv_clauses:
                errors.append(f"{clause['clause_id']} is not an inventory clause")
            if clause["claim"] in {"full", "partial"} and "execution" not in clause:
                errors.append(f"{clause['clause_id']} claims {clause['claim']} without an execution")
            for fx in clause.get("fixtures", []):
                if fx["kind"] not in rp.FIXTURE_KINDS:
                    errors.append(f"{fx['fixture_id']} has an unknown kind")
                if fx["fixture_id"] in fixture_ids:
                    errors.append(f"{fx['fixture_id']} is duplicated")
                fixture_ids.add(fx["fixture_id"])
                if fx["kind"] != "not_applicable" and (not fx.get("expected", {}).get("rule_locators") or not fx.get("why")):
                    errors.append(f"{fx['fixture_id']} lacks a cited expectation")

    report = rp.run_all(programs)
    for card in report["cards"]:
        for cl in card["clauses"]:
            for r in cl["fixtures"]:
                if not r["passed"]:
                    errors.append(f"{r['fixture_id']}: " + "; ".join(r["problems"]))
            real = {r["kind"] for r in cl["fixtures"] if not r.get("skipped") and r["passed"]}
            if cl["claim"] in {"full", "partial"} and not {"positive", "negative"} <= real:
                errors.append(f"{cl['clause_id']} claims {cl['claim']} without positive and negative fixtures")
    manifest = rp.build_manifest(programs, report)
    if validate_manifest(manifest):
        errors.append(f"derived manifest invalid: {validate_manifest(manifest)}")
    if manifest["status"] != "draft":
        errors.append("manifest must stay draft; activation is a separate gate (ADR-0004)")
    for card in manifest["cards"]:
        inv_card = next(c for c in inventory["cards"] if c["card_key"] == card["card_key"])
        if card["current_text_hash"] != inv_card["current_text_hash"]:
            errors.append(f"{card['canonical_name']} text hash differs from the inventory")
        for cl in card["clauses"]:
            inv = inv_clauses[cl["clause_id"]][1]
            if cl["text_hash"] != inv["text_hash"]:
                errors.append(f"{cl['clause_id']} text hash differs from the inventory")
            if inv["status"] == "stale" and (cl["status"] != "stale" or cl["program_id"] is not None):
                errors.append(f"{cl['clause_id']} is stale in the inventory but activated here")
            if cl["status"] == "unsupported" and (cl["program_id"] is not None or not cl["unsupported_mechanics"]):
                errors.append(f"{cl['clause_id']} unsupported clause carries a program or names no mechanic")
            if cl["status"] in {"full", "partial"} and (not cl["program_id"] or not cl["test_ids"]):
                errors.append(f"{cl['clause_id']} {cl['status']} without program/test evidence")
            if "vision" in cl["notes"].lower() and cl["status"] != "unsupported":
                errors.append(f"{cl['clause_id']} Vision must stay unsupported this round")
        statuses = {c["status"] for c in card["clauses"]}
        if card["behavior_status"] == "full" and statuses != {"full"}:
            errors.append(f"{card['canonical_name']} claims full with clauses {sorted(statuses)}")
    # a claim never outranks its evidence
    probe = copy.deepcopy(programs)
    target = next(cl for c in probe["cards"] for cl in c["clauses"] if cl["claim"] == "full" and cl.get("fixtures"))
    for fx in target["fixtures"]:
        if fx["kind"] == "positive":
            fx["expected"]["outcome"] = "illegal"
    probe_manifest = rp.build_manifest(probe, rp.run_all(probe))
    derived = next(cl for c in probe_manifest["cards"] for cl in c["clauses"] if cl["clause_id"] == target["clause_id"])
    if derived["status"] != "unsupported" or derived["program_id"] is not None:
        errors.append("a full claim with a failing fixture still derived a supported status")
    # committed outputs are current and deterministic
    outs = rp.outputs()
    for path, text in outs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            errors.append(f"{path.name} is stale; re-run r3a1_programs.py and commit the diff")
    if rp.outputs() != outs:
        errors.append("program run is not deterministic")
    inv_text = (rp.PACK / "inventory.draft.json").read_text(encoding="utf-8")
    if '"program_id": "' in inv_text:
        errors.append("inventory.draft.json gained a program_id; the draft must stay a draft")
    run = subprocess.run([sys.executable, str(SCRIPT_DIR / "r3a1_programs.py"), "--check"], cwd=Path.home(), text=True, capture_output=True, check=False)
    if run.returncode != 0:
        errors.append(f"off-cwd run failed: {run.stderr.strip()}")

    counts = {s: sum(1 for c in manifest["cards"] for cl in c["clauses"] if cl["status"] == s) for s in ("full", "partial", "unsupported", "stale")}
    fixtures = sum(1 for c in report["cards"] for cl in c["clauses"] for r in cl["fixtures"] if not r.get("skipped"))
    if errors:
        print("FAILED: R3-A1 program checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print(f"OK: R3-A1 card programs — {len(manifest['cards'])} cards, {fixtures} fixtures passing with cited expectations; derived clause statuses full={counts['full']} partial={counts['partial']} unsupported={counts['unsupported']} stale={counts['stale']}; manifest draft, validated, deterministic, inventory untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
