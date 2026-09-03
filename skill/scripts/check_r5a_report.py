#!/usr/bin/env python3
"""
Regression gate for the R5-A coverage and abstention report (C-11).

Must hold:
  - the committed report equals a fresh build (deterministic, not stale);
  - two builds in one process are byte-identical;
  - the coverage denominator is the live capability manifest's clause list;
  - every check in the report was produced by the real engines — the outcome
    counts equal what re-running the same fixtures yields;
  - the five abstention buckets are all present and internally consistent;
  - identity names the live manifest and implementation.

Must fail:
  - a report claiming search, policy strength, P2-S, matchup rates, a complete
    game, or complete legality;
  - a report whose counts do not add up;
  - a report bound to a different capability set than the live engine;
  - the CLI exiting 0 on garbage, or `--check` passing a stale file.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from capability_manifest import build_manifest  # noqa: E402
from r5a_report import ABSTENTION_BUCKETS, CLAIMS, DEFAULT_OUTPUT, build_report, render, validate_report  # noqa: E402

RUNNER = SCRIPT_DIR / "r5a_report.py"


def expect_errors(label: str, errors: list[str], needle: str, out: list[str]) -> None:
    if not errors:
        out.append(f"{label}: accepted, but should have been rejected")
    elif not any(needle in e for e in errors):
        out.append(f"{label}: rejected for the wrong reason: {errors}")


def main() -> int:
    errors: list[str] = []
    live = build_report()
    if validate_report(live):
        errors.append(f"built report is invalid: {validate_report(live)}")
    again = build_report()
    if render(again) != render(live):
        errors.append("report is not deterministic across two builds")

    if not DEFAULT_OUTPUT.exists():
        errors.append(f"committed report missing: {DEFAULT_OUTPUT}; run r5a_report.py build")
    elif DEFAULT_OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") != render(live):
        errors.append("committed report is stale; re-run r5a_report.py build and commit the diff")

    manifest = build_manifest()
    if live["identity"]["capability_set_id"] != manifest["capability_set_id"] or live["identity"]["implementation_identity"] != manifest["implementation"]["value"]:
        errors.append("report identity does not name the live manifest")
    if live["clause_coverage"]["declared"] != len(manifest["clauses"]):
        errors.append("coverage denominator is not the manifest's clause list")
    if set(live["clause_coverage"]["cited_clauses"]) - set(manifest["clauses"]):
        errors.append("cited_clauses contains a clause the manifest does not declare")
    if live["clause_coverage"]["cited"] == 0:
        errors.append("no declared clause was cited by any fixture — the report is measuring nothing")
    if live["conformance"]["rules_core"]["passed"] != live["conformance"]["rules_core"]["cases"]:
        errors.append(f"rules_core conformance regressed: {live['conformance']['rules_core']}")
    if live["engine_checks"]["total"] < 30:
        errors.append(f"fewer fixtures than expected reached the engines: {live['engine_checks']['total']}")
    if set(live["abstention"]) != set(ABSTENTION_BUCKETS):
        errors.append("abstention buckets diverged")
    for bucket in ("unsupported_mechanic", "decision_required", "missing_state", "stale_data", "source_conflict"):
        if live["abstention"][bucket]["count"] == 0:
            errors.append(f"abstention bucket {bucket} is empty; a fixture that exercises it has gone missing")
    if set(live["legal_action_verdicts"]) != {"legal", "illegal", "indeterminate", "unsupported", "decision_required"} or any(v == 0 for v in live["legal_action_verdicts"].values()):
        errors.append("legal-action verdicts are not all reached in the report")
    if live["claims"] != CLAIMS or any(live["claims"].values()):
        errors.append("report must refuse every R5-A claim")

    # --- injections -----------------------------------------------------------
    for key in ("search", "policy_strength", "p2s", "matchup_rates"):
        bad = copy.deepcopy(live); bad["claims"][key] = True
        expect_errors(f"claim {key}", validate_report(bad), "claims", errors)
    bad = copy.deepcopy(live); bad["abstention"]["unsupported_mechanic"]["count"] += 1
    expect_errors("abstention count lie", validate_report(bad), "inconsistent", errors)
    bad = copy.deepcopy(live); bad["clause_coverage"]["cited"] += 1
    expect_errors("coverage count lie", validate_report(bad), "add up", errors)
    bad = copy.deepcopy(live); bad["engine_checks"]["total"] += 1
    expect_errors("engine check total lie", validate_report(bad), "per-kind", errors)
    bad = copy.deepcopy(live); bad["identity"]["capability_set_id"] = "sha256:" + "0" * 64
    if not validate_report(bad):
        # shape is fine; the gate itself is what catches a foreign identity
        if bad["identity"]["capability_set_id"] == manifest["capability_set_id"]:
            errors.append("identity injection did not change anything")

    # --- CLI ------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="r5a-report-") as temp_name:
        temp = Path(temp_name)
        out = temp / "report.json"
        built = subprocess.run([sys.executable, str(RUNNER), "build", "--output", str(out)], cwd=temp, text=True, capture_output=True, check=False)
        if built.returncode != 0 or not out.exists():
            errors.append(f"CLI build failed off-cwd: {built.stderr.strip()}")
        else:
            if json.loads(out.read_text(encoding="utf-8"))["report_hash"] != live["report_hash"]:
                errors.append("CLI build differs from the in-process build")
            checked = subprocess.run([sys.executable, str(RUNNER), "build", "--check", "--output", str(out)], cwd=temp, text=True, capture_output=True, check=False)
            if checked.returncode != 0:
                errors.append(f"--check rejected a fresh report: {checked.stderr.strip()}")
            stale = copy.deepcopy(live); stale["engine_checks"]["abstention_rate"] = 0.0
            out.write_text(json.dumps(stale), encoding="utf-8")
            stale_run = subprocess.run([sys.executable, str(RUNNER), "build", "--check", "--output", str(out)], cwd=temp, text=True, capture_output=True, check=False)
            if stale_run.returncode == 0:
                errors.append("--check passed a stale report")
            garbage = temp / "garbage.json"; garbage.write_text("{no", encoding="utf-8")
            if subprocess.run([sys.executable, str(RUNNER), "validate", str(garbage)], cwd=temp, text=True, capture_output=True, check=False).returncode == 0:
                errors.append("CLI validate exited 0 on garbage")

    if errors:
        print("FAILED: R5-A report checks\n  - " + "\n  - ".join(errors))
        return 1
    ec = live["engine_checks"]; cov = live["clause_coverage"]
    print(f"OK: R5-A report is deterministic, measured against the live manifest, refuses every learning claim, and reaches all five abstention buckets ({ec['total']} checks, abstention {ec['abstention_rate']}, clauses {cov['cited']}/{cov['declared']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
