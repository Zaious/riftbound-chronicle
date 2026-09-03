#!/usr/bin/env python3
"""
R5-A: a deterministic coverage and abstention report over the fixtures that
already exist (package C-11).

R5's first tier is measurement, not learning: clause-level coverage, an
unsupported rate, conformance counts, and abstention split by *why* the engine
declined. None of that needs a simulator, a policy, or Riot authorization —
which is why it can be built now while R5-B/R5-C stay closed.

Everything here is run, not described. Every fixture below is pushed through
the real component and wrapped by the real `engine_check.build_engine_check`,
so the outcome counts are the engine's counts. The coverage denominator is the
capability manifest's `clauses` — the engine's own declaration of what it
cites — so "cited by a fixture" is measured against "declared by the engine",
never against a hand-maintained list.

Abstention is split five ways, as R5 asks:

  missing_state          the engine could not see enough state to answer:
                         invalid_input checks; legal-action candidates that
                         are indeterminate; Match Analyst logs carrying an
                         uncertainty ledger
  unsupported_mechanic   the engine has no semantics for it: unsupported checks
                         and unsupported legal-action candidates
  source_conflict        the sources disagree: rule-consult cases in the
                         source_conflict category; Match Analyst logs with
                         derived contradictions
  stale_data             a behavior manifest or entry that no longer matches
                         current card text
  decision_required      a controller choice must be supplied first

What this report refuses to be is stated in its `claims`, as constants: no
search, no policy strength, no P2-S, no matchup rates, no complete game, no
complete legality. A report that carried any of those would fail validation.

Usage:
    python3 skill/scripts/r5a_report.py build [--output report.json]
    python3 skill/scripts/r5a_report.py build --check      # CI: fail if the committed report is stale
    python3 skill/scripts/r5a_report.py validate report.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DATA = SKILL_DIR / "data"
DEFAULT_OUTPUT = DATA / "r5a_report" / "report.json"
sys.path.insert(0, str(SCRIPT_DIR))

import legal_action  # noqa: E402
import rules_core  # noqa: E402
from capability_manifest import build_manifest, capability_binding  # noqa: E402
from effect_ir import apply_program, hash_value, perform_lethal_cleanup  # noqa: E402
from engine_check import build_engine_check, canonical_hash  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

SCHEMA_VERSION = "r5a-report.v1"
ABSTENTION_BUCKETS = ("missing_state", "unsupported_mechanic", "source_conflict", "stale_data", "decision_required")
CLAIMS = {"search": False, "policy_strength": False, "p2s": False, "matchup_rates": False, "complete_game": False, "complete_legality": False}


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class Tally:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.abstention: dict[str, list[str]] = {b: [] for b in ABSTENTION_BUCKETS}

    def add(self, label: str, check: dict[str, Any]) -> None:
        self.checks.append({"label": label, "kind": check["check_kind"], "outcome": check["outcome"],
                            "reason_code": check["reason"]["code"], "rule_locators": list(check["rule_locators"])})
        outcome = check["outcome"]
        if outcome == "invalid_input":
            self.abstention["missing_state"].append(label)
        elif outcome == "unsupported":
            self.abstention["unsupported_mechanic"].append(label)
        elif outcome == "decision_required":
            self.abstention["decision_required"].append(label)

    def note(self, bucket: str, label: str) -> None:
        self.abstention[bucket].append(label)


def _run_rules_core(tally: Tally) -> dict[str, Any]:
    rc = _load_module("check_rules_core")
    cases = json.loads((DATA / "rules_core_cases.json").read_text(encoding="utf-8"))["cases"]
    passed = 0
    for case in cases:
        state = rc.FIXTURES[case["state"]]
        expected = case["expected"]
        hashes = {"timing_state": rules_core.state_hash(state)}
        if (resolve := case.get("resolve")) is not None:
            result = rules_core.complete_resolution(state, resolve["item_id"], effect_execution_confirmed=resolve["effect_execution_confirmed"])
            ok = result.get("applied") is True and all(result.get("transition", {}).get(k) == v for k, v in expected.items() if k in ("focus_before", "focus_after", "chain_empty")) \
                and ("state_label" not in expected or result.get("state_label") == expected["state_label"])
        elif (action := case.get("action")):
            result = rules_core.validate_timing(state, action)
            ok = all(result.get(k) == expected[k] for k in ("state_label", "legal", "reason_code") if k in expected)
            if "next_procedure" in expected:
                ok = ok and rules_core.next_procedure(state).get("procedure") == expected["next_procedure"]
        elif "next_procedure" in expected:
            result = rules_core.next_procedure(state)
            ok = all(result.get(src) == expected[k] for k, src in (("state_label", "state_label"), ("next_procedure", "procedure"), ("subject", "subject")) if k in expected)
        else:
            result = rules_core.finalize_oldest_pending(state)
            t = result.get("transition", {})
            ok = result.get("state_label") == expected.get("state_label") and t.get("item_id") == expected.get("finalized_item") \
                and t.get("immediate_resolution_required") == expected.get("immediate_resolution_required")
        passed += bool(ok)
        tally.add(f"rules_core:{case['case_id']}", build_engine_check("timing", result, input_hashes=hashes))
    return {"cases": len(cases), "passed": passed}


def _run_effects(tally: Tally) -> None:
    ce = _load_module("check_effect_ir")
    state = ce.base_state()
    draw = ce.program("r5a-draw", {"op": "draw", "player": "p1", "count": 1})
    tally.add("effect:draw", build_engine_check("effect", apply_program(copy.deepcopy(state), draw),
                                                input_hashes={"effect_state": hash_value(state), "effect_program": canonical_hash(draw)}))
    counter = ce.program("r5a-counter", {"op": "counter", "chain_item_id": "x"})
    tally.add("effect:counter_unsupported", build_engine_check("effect", apply_program(copy.deepcopy(state), counter),
                                                               input_hashes={"effect_state": hash_value(state), "effect_program": canonical_hash(counter)}))

    replacement_state = ce.base_state()
    for object_id in ("u3", "u4"):
        replacement_state["objects"][object_id] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
        replacement_state["players"]["p2"]["zones"]["base"].append(object_id)
    replacement_state["objects"]["u2"]["damage"] = 4
    replacement_state["objects"]["u3"]["damage"] = 2
    replacement_state["replacement_effects"] = [{"replacement_id": "guard-all", "controller": "p2", "source_object": "u4", "mode": "prevent_event",
                                                 "event_op": "kill", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"}]
    tally.add("cleanup:simultaneous_replacement_order", build_engine_check("cleanup", perform_lethal_cleanup(copy.deepcopy(replacement_state)),
                                                                            input_hashes={"effect_state": hash_value(replacement_state)}))

    optional_state = ce.base_state()
    optional_state["replacement_effects"] = [{"replacement_id": "optional-shield", "controller": "p2", "source_object": "u2", "mode": "prevent_event",
                                              "event_op": "deal_damage", "optional": True, "uses_remaining": 1, "target_object_id": "u2"}]
    optional = ce.program("r5a-optional", {"op": "deal_damage", "object_id": "u2", "amount": 2})
    tally.add("effect:optional_replacement_choice", build_engine_check("effect", apply_program(copy.deepcopy(optional_state), optional),
                                                                       input_hashes={"effect_state": hash_value(optional_state), "effect_program": canonical_hash(optional)}))


def _run_cli_examples(tally: Tally) -> None:
    ex = DATA / "engine_check_examples"
    load = lambda n: json.loads((ex / n).read_text(encoding="utf-8"))  # noqa: E731
    timing, action = load("timing-state.json"), load("proposed-action.json")
    th = {"timing_state": rules_core.state_hash(timing)}
    tally.add("cli:timing_payload", build_engine_check("timing", rules_core.validate_timing(timing, action), input_hashes={**th, "proposed_action": canonical_hash(action)}))
    tally.add("cli:timing_permissions", build_engine_check("timing", rules_core.derive_permissions(timing), input_hashes=th))
    tally.add("cli:timing_next", build_engine_check("timing", rules_core.next_procedure(timing), input_hashes=th))
    estate, program = load("effect-state.json"), load("effect-program.json")
    tally.add("cli:effect", build_engine_check("effect", apply_program(copy.deepcopy(estate), program), input_hashes={"effect_state": hash_value(estate), "effect_program": canonical_hash(program)}))
    closed = load("closed-timing-state.json")
    tally.add("cli:resolution", build_engine_check("resolution", resolve_with_program(closed, "spell-1", estate, program, None),
                                                   input_hashes={"timing_state": rules_core.state_hash(closed), "effect_state": hash_value(estate), "effect_program": canonical_hash(program)}))
    cstate, decisions = load("cleanup-state.json"), load("cleanup-decisions.json")
    tally.add("cli:cleanup_undecided", build_engine_check("cleanup", perform_lethal_cleanup(copy.deepcopy(cstate)), input_hashes={"effect_state": hash_value(cstate)}))
    tally.add("cli:cleanup_decided", build_engine_check("cleanup", perform_lethal_cleanup(copy.deepcopy(cstate), replacement_event_order=decisions.get("replacement_event_order"),
                                                                                           replacement_choices=decisions.get("replacement_choices")),
                                                        input_hashes={"effect_state": hash_value(cstate), "cleanup_decisions": canonical_hash(decisions)}))


def _run_legal_action(tally: Tally) -> dict[str, int]:
    fx = _load_module("build_legal_action_fixtures").build_fixtures()
    verdicts = {v: 0 for v in legal_action.VERDICTS}
    for name, item in fx.items():
        result = item["result"]
        tally.add(f"legal_action:{name}", build_engine_check("legal_action", result, input_hashes={"observation": item["observation"]["observation_hash"], "action_query": item["query"]["query_hash"]}))
        for c in result["candidates"]:
            verdicts[c["verdict"]] += 1
            if c["verdict"] == "indeterminate":
                tally.note("missing_state", f"legal_action:{name}:{c['candidate_id']}")
            elif c["verdict"] == "unsupported":
                tally.note("unsupported_mechanic", f"legal_action:{name}:{c['candidate_id']}")
    return verdicts


def _rule_consult(tally: Tally) -> dict[str, int]:
    cases = json.loads((DATA / "rule_consult_cases.json").read_text(encoding="utf-8"))["cases"]
    by_category: dict[str, int] = {}
    for case in cases:
        by_category[case["category"]] = by_category.get(case["category"], 0) + 1
        if case["category"] == "source_conflict":
            tally.note("source_conflict", f"rule_consult:{case['case_id']}")
    return dict(sorted(by_category.items()))


def _behavior_coverage(tally: Tally) -> dict[str, Any]:
    fx = _load_module("build_behavior_coverage_fixtures").build_fixtures()
    entries = fx["fixtures"] if isinstance(fx, dict) and "fixtures" in fx else fx
    statuses: dict[str, int] = {}
    stale_copies = 0
    for item in entries if isinstance(entries, list) else entries.values():
        cov = item.get("coverage", item)
        status = cov.get("status")
        statuses[status] = statuses.get(status, 0) + 1
        label = f"behavior_coverage:{item.get('fixture_id', status)}"
        if status == "stale":
            tally.note("stale_data", label)
        # A stale *entry* under an otherwise available manifest: the card was
        # re-worded and its program no longer matches. Counted per copy, as
        # the D-03 projection counts it.
        stale = int((cov.get("copy_weighted") or {}).get("stale", 0))
        if stale:
            stale_copies += stale
            tally.note("stale_data", f"{label}:copies={stale}")
    return {"statuses": dict(sorted(statuses.items())), "stale_copies": stale_copies}


def _match_analyst(tally: Tally) -> dict[str, Any]:
    ma = _load_module("check_match_analyst_fixtures")
    folder = DATA / "match_analyst_fixtures"
    out: dict[str, Any] = {}
    for path in sorted(folder.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        ledger = fixture.get("uncertainty_ledger") or []
        contradictions = ma.derive_contradictions(fixture.get("events", [])) if hasattr(ma, "derive_contradictions") else set()
        out[path.stem] = {"uncertainty_entries": len(ledger), "contradictions": len(contradictions)}
        if ledger:
            tally.note("missing_state", f"match_analyst:{path.stem}")
        if contradictions:
            tally.note("source_conflict", f"match_analyst:{path.stem}")
    return out


def build_report() -> dict[str, Any]:
    manifest = build_manifest()
    tally = Tally()
    conformance = _run_rules_core(tally)
    _run_effects(tally)
    _run_cli_examples(tally)
    la_verdicts = _run_legal_action(tally)
    rc_categories = _rule_consult(tally)
    behavior = _behavior_coverage(tally)
    analyst = _match_analyst(tally)

    outcomes: dict[str, dict[str, int]] = {}
    for c in tally.checks:
        outcomes.setdefault(c["kind"], {}).setdefault(c["outcome"], 0)
        outcomes[c["kind"]][c["outcome"]] += 1
    declared = list(manifest["clauses"])
    cited = sorted({loc for c in tally.checks for loc in c["rule_locators"]})
    cited_declared = [c for c in cited if c in declared]
    total = len(tally.checks)
    abst_total = sum(1 for c in tally.checks if c["outcome"] in ("invalid_input", "unsupported", "decision_required"))

    fixture_files = [DATA / "rules_core_cases.json", DATA / "rule_consult_cases.json", DATA / "legal_action_examples" / "fixtures.json",
                     *sorted((DATA / "engine_check_examples").glob("*.json")), *sorted((DATA / "match_analyst_fixtures").glob("*.json"))]
    report = {
        "schema_version": SCHEMA_VERSION,
        "identity": {**capability_binding(manifest), "ruleset": manifest["ruleset"],
                     "fixture_sources": [{"path": str(p.relative_to(SKILL_DIR)).replace("\\", "/"), "sha256": _file_hash(p)} for p in fixture_files]},
        "claims": dict(CLAIMS),
        "engine_checks": {"total": total, "by_kind": {k: dict(sorted(v.items())) for k, v in sorted(outcomes.items())},
                          "abstention_rate": round(abst_total / total, 4) if total else 0.0},
        "conformance": {"rules_core": conformance},
        "clause_coverage": {"declared": len(declared), "cited": len(cited_declared), "cited_ratio": round(len(cited_declared) / len(declared), 4) if declared else 0.0,
                            "cited_clauses": cited_declared, "uncited_clauses": [c for c in declared if c not in cited_declared],
                            "cited_outside_manifest": [c for c in cited if c not in declared]},
        "abstention": {b: {"count": len(v), "sources": sorted(v)} for b, v in tally.abstention.items()},
        "legal_action_verdicts": la_verdicts,
        "rule_consult_categories": rc_categories,
        "behavior_coverage": behavior,
        "match_analyst": analyst,
        "checks": sorted(tally.checks, key=lambda c: c["label"]),
    }
    report["report_hash"] = canonical_hash({k: v for k, v in report.items() if k != "report_hash"})
    return report


def validate_report(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["report must be an object"]
    errors: list[str] = []
    required = {"schema_version", "identity", "claims", "engine_checks", "conformance", "clause_coverage", "abstention",
                "legal_action_verdicts", "rule_consult_categories", "behavior_coverage", "match_analyst", "checks", "report_hash"}
    if set(value) != required:
        errors.append("report top-level fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if value.get("claims") != CLAIMS:
        errors.append("claims must be exactly the R5-A refusals: no search, policy strength, P2-S, matchup rates, complete game, complete legality")
    ident = value.get("identity", {})
    for key in ("manifest_id", "capability_set_id", "implementation_identity"):
        if not isinstance(ident.get(key), str) or not ident[key]:
            errors.append(f"identity.{key} is required")
    abst = value.get("abstention")
    if not isinstance(abst, dict) or set(abst) != set(ABSTENTION_BUCKETS):
        errors.append("abstention must carry exactly the five R5 buckets")
    else:
        for b, item in abst.items():
            if not isinstance(item, dict) or item.get("count") != len(item.get("sources", [])) or item.get("sources") != sorted(item.get("sources", [])):
                errors.append(f"abstention.{b} count/sources are inconsistent or unsorted")
    cov = value.get("clause_coverage", {})
    if not isinstance(cov, dict) or cov.get("cited") != len(cov.get("cited_clauses", [])) or cov.get("declared") != len(cov.get("cited_clauses", [])) + len(cov.get("uncited_clauses", [])):
        errors.append("clause_coverage counts do not add up")
    ec = value.get("engine_checks", {})
    if isinstance(ec, dict) and ec.get("total") != sum(sum(v.values()) for v in ec.get("by_kind", {}).values()):
        errors.append("engine_checks.total does not equal the per-kind sum")
    if not errors and value.get("report_hash") != canonical_hash({k: v for k, v in value.items() if k != "report_hash"}):
        errors.append("report_hash does not match the report")
    return errors


def render(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--output", type=Path, default=None)
    b.add_argument("--check", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("report", type=Path)
    args = parser.parse_args(argv)

    if args.command == "validate":
        try:
            value = json.loads(args.report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAILED: cannot read {args.report}: {exc}", file=sys.stderr)
            return 1
        errors = validate_report(value)
        if errors:
            print(f"FAILED: validate {args.report}:\n  - " + "\n  - ".join(errors), file=sys.stderr)
            return 1
        print(f"OK: validate {args.report} ({value['report_hash'][:23]})")
        return 0

    report = build_report()
    errors = validate_report(report)
    if errors:
        print("FAILED: built report is invalid: " + "; ".join(errors), file=sys.stderr)
        return 1
    text = render(report)
    target = args.output or DEFAULT_OUTPUT
    if args.check:
        current = target.read_text(encoding="utf-8").replace("\r\n", "\n") if target.exists() else ""
        if current != text:
            print(f"FAILED: {target} is stale; re-run r5a_report.py build and commit the diff", file=sys.stderr)
            return 1
        print(f"OK: {target} matches the live engine and fixtures")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    ec = report["engine_checks"]
    print(f"wrote {target}: {ec['total']} checks, abstention {ec['abstention_rate']}, clause coverage {report['clause_coverage']['cited']}/{report['clause_coverage']['declared']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
