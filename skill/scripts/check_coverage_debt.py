#!/usr/bin/env python3
"""Regression gate for C-62 (ADR-0016 §3): the coverage debt ledger.

Must hold:
  - the committed ledger is what a fresh build produces;
  - it holds exactly the corpus clauses the grammar does not parse — every one
    of them, once, with its own text — and none it does parse;
  - the entries are in the declared ranking order, and the ranking fields are
    measured rather than asserted: the deck-slot count really reads the deck
    lists this repo carries;
  - every entry names the rule family and the capability it is missing;
  - there is no repayment quota, and the ledger says so;
  - the delta is real: teaching the grammar one more production moves those
    clauses out of the debt and reports them as repaid.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import coverage_debt as cd  # noqa: E402


def corpus_texts():
    for path in cd.pack_files("r3a1_programs.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for card in data["cards"]:
            for clause in card["clauses"]:
                yield clause


def main() -> int:
    errors: list[str] = []
    if not cd.OUT.exists():
        print("FAILED: coverage debt checks")
        print("  - no committed ledger; run coverage_debt.py build")
        return 1
    committed = json.loads(cd.OUT.read_text(encoding="utf-8"))
    fresh = cd.build()
    if {k: v for k, v in committed.items() if k != "delta"} != fresh:
        errors.append("the committed coverage debt is stale; re-run coverage_debt.py build and commit the diff")

    grammar = cg.load_grammar()
    expected, parsed = [], 0
    for clause in corpus_texts():
        if cg.compile_clause(clause["text"], grammar).get("unsupported"):
            expected.append(clause["clause_id"])
        else:
            parsed += 1
    listed = [entry["clause_id"] for entry in committed["entries"]]
    if sorted(listed) != sorted(expected):
        missing = sorted(set(expected) - set(listed))
        extra = sorted(set(listed) - set(expected))
        errors.append(f"the debt does not hold exactly the unparsed clauses: missing={missing[:3]} extra={extra[:3]}")
    if len(listed) != len(set(listed)):
        errors.append("a clause appears in the debt more than once")
    if committed["counts"]["clauses_parsed"] != parsed:
        errors.append(f"the parsed count disagrees with the grammar: {committed['counts']['clauses_parsed']} vs {parsed}")

    # --- the ranking is the declared one, and its inputs are measured -----------------------------
    if committed["ranking"] != ["deck_slots", "deck_count", "risk", "missing_capability", "clause_id"]:
        errors.append(f"the ranking is not the declared one: {committed['ranking']}")
    keys = [(-e["deck_slots"], -e["deck_count"], cd.RISK_ORDER[e["risk"]], e["missing_capability"], e["clause_id"])
            for e in committed["entries"]]
    if keys != sorted(keys):
        errors.append("the debt is not in its own ranking order")
    slots = cd.deck_slots()
    if not slots:
        errors.append("the deck-slot count read no deck list at all")
    elif slots.get("inferna") != 3:
        errors.append(f"the deck-slot count did not read the committed list's own copies: inferna={slots.get('inferna')}")

    # --- every entry says what it is waiting for ---------------------------------------------------
    for entry in committed["entries"]:
        if not entry.get("text") or entry.get("reason_code") not in cg.ABSTENTION_REASONS:
            errors.append(f"a debt entry carries no text or an unknown reason: {entry.get('clause_id')} "
                          f"{entry.get('reason_code')}")
        if not entry.get("rule_family") or not entry.get("missing_capability"):
            errors.append(f"a debt entry does not name its rule family or missing capability: {entry.get('clause_id')}")
        if entry.get("risk") not in cd.RISK_ORDER:
            errors.append(f"a debt entry has an unknown risk: {entry.get('risk')}")

    # --- the promotion rule is measurable ------------------------------------------------------------
    promotion = committed["counts"].get("promotion") or {}
    if set(promotion) != {"grammar_reproduced", "hand_written", "in_debt_but_claimed"}:
        errors.append(f"the ledger does not report the promotion split: {promotion}")
    elif promotion["in_debt_but_claimed"] != promotion["hand_written"]:
        errors.append("a clause claimed full or partial is counted as hand-written without being in the debt")
    elif promotion["grammar_reproduced"] + promotion["hand_written"] == 0:
        errors.append("the promotion split counted no claimed clause at all")

    # --- a splitter change is not a repayment (DP-90) -------------------------------------------------
    if committed["entries"]:
        renormalised = copy.deepcopy(committed)
        renormalised["normalization_version"] = "split_clauses:0000000000000000"
        # A build on a different splitter, with one clause id moved: the id-level
        # difference must be filed as a normalisation reclassification, not repaid.
        moved = copy.deepcopy(fresh)
        moved["entries"] = moved["entries"][1:]
        movement = cd.delta(moved, renormalised)
        if movement["repaid"] or movement["added"]:
            errors.append(f"a splitter change was reported as repayment: repaid={movement['repaid'][:2]}")
        if committed["entries"][0]["clause_id"] not in movement["normalization_reclassification"]:
            errors.append(f"the moved clause was not filed as a normalisation reclassification: {movement}")
        if movement.get("normalization_baseline") != renormalised["normalization_version"]:
            errors.append("the movement does not keep the old normalisation baseline")
        # the same movement on the same splitter is a real repayment
        same = cd.delta(moved, committed)
        if committed["entries"][0]["clause_id"] not in same["repaid"] or same["normalization_reclassification"]:
            errors.append(f"negative mutation failed: on one splitter the same movement was not a repayment: {same}")
    if not committed.get("normalization_version", "").startswith("split_clauses:"):
        errors.append(f"the ledger does not record which splitter produced it: {committed.get('normalization_version')}")

    # --- no quota -----------------------------------------------------------------------------------
    if committed.get("quota") is not None or "no repayment quota" not in committed.get("note", "").lower():
        errors.append("the ledger does not say that there is no repayment quota")

    # --- the delta is real ---------------------------------------------------------------------------
    if committed["entries"]:
        target = committed["entries"][0]
        # A probe, not a promotion: a production that matches the debt's own
        # top clause literally and lowers to nothing, just to see the ledger
        # move. It is never written to the contract.
        import re as _re
        taught = copy.deepcopy(grammar)
        taught["productions"].insert(0, {
            "production_id": "no_rules_text", "form": target["text"],
            "template": _re.escape(cg.normalize(target["text"])), "slots": {},
            "normalization": "clause-grammar.v1/normalize", "rule_locators": ["Core 185"], "ast_node": "empty",
            "required_capability": [], "boundary": "probe", "golden": [target["text"]], "negative": ["x"]})
        original = cg.load_grammar
        try:
            cg.load_grammar = lambda path=None: taught
            after = cd.build()
        finally:
            cg.load_grammar = original
        movement = cd.delta(after, committed)
        if target["clause_id"] not in movement["repaid"]:
            errors.append(f"teaching the grammar the top debt clause did not report it repaid: {movement['repaid'][:3]}")
        if after["counts"]["clauses_in_debt"] >= committed["counts"]["clauses_in_debt"]:
            errors.append("the debt did not shrink when the grammar grew")

    if errors:
        print("FAILED: coverage debt checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"coverage debt checks passed: {committed['counts']['clauses_in_debt']} clauses in debt, "
          f"{committed['counts']['clauses_parsed']} parsed, ranked by {', '.join(committed['ranking'])}, no quota")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
