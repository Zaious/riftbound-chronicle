#!/usr/bin/env python3
"""
Regression gate for the bounded legal-action service, Phase A (ADR-0003, C-10).

Injected and required to fail:
  - a Player 2 observation or query carrying a Player 1 private key;
  - a result that claims complete_action_set or enumeration_attempted;
  - a result whose candidates are out of order, or whose summary lies;
  - an indeterminate verdict that names nothing missing;
  - a query bound to the wrong observation hash;
  - a prose-only candidate classified as anything but indeterminate;
  - stale committed fixtures;
  - the CLI exiting 0 on an invalid pair or writing on failure.

Required to hold:
  - all five verdicts are reachable from real timing states;
  - later_revealed/contradictory facts change neither verdicts nor hashes;
  - classification is deterministic (same inputs, same result_hash);
  - the result wraps into engine-check.v1 as kind legal_action without the
    envelope inventing an outcome the result did not carry.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import legal_action as la  # noqa: E402
from build_legal_action_fixtures import OUT, build_fixtures, render  # noqa: E402
from engine_check import build_engine_check, validate_engine_check  # noqa: E402

RUNNER = SCRIPT_DIR / "legal_action.py"
SCHEMAS = {name: SKILL_DIR / "schemas" / f"{name}.schema.json" for name in ("observation", "action-query", "legal-action-result")}


def expect_errors(label: str, errors: list[str], needle: str, out: list[str]) -> None:
    if not errors:
        out.append(f"{label}: accepted, but should have been rejected")
    elif not any(needle in e for e in errors):
        out.append(f"{label}: rejected for the wrong reason: {errors}")


def main() -> int:
    errors: list[str] = []

    # --- schemas agree with the runner ----------------------------------------
    for name, path in SCHEMAS.items():
        schema = json.loads(path.read_text(encoding="utf-8"))
        const = schema.get("properties", {}).get("schema_version", {}).get("const")
        want = {"observation": la.OBSERVATION_VERSION, "action-query": la.QUERY_VERSION, "legal-action-result": la.RESULT_VERSION}[name]
        if const != want:
            errors.append(f"{name} schema version diverged from runner")
    result_schema = json.loads(SCHEMAS["legal-action-result"].read_text(encoding="utf-8"))
    for key in ("enumeration_attempted", "complete_action_set"):
        if result_schema["properties"][key] != {"const": False}:
            errors.append(f"result schema must pin {key} to false in Phase A")
    if set(result_schema["properties"]["candidates"]["items"]["properties"]["verdict"]["enum"]) != set(la.VERDICTS):
        errors.append("result schema verdict vocabulary diverged")

    # --- fixtures: fresh, valid, and covering the five verdicts ---------------
    fixtures = build_fixtures()
    committed = OUT / "fixtures.json"
    if not committed.exists() or committed.read_text(encoding="utf-8").replace("\r\n", "\n") != render(fixtures):
        errors.append("legal-action fixtures are stale; re-run build_legal_action_fixtures.py and commit the diff")
    seen_verdicts: set[str] = set()
    for name, fx in fixtures.items():
        for label, value, fn in (("observation", fx["observation"], la.validate_observation), ("query", fx["query"], la.validate_query), ("result", fx["result"], la.validate_result)):
            found = fn(value)
            if found:
                errors.append(f"fixture {name} {label} invalid: {found}")
        if not fx["result"]["valid"]:
            errors.append(f"fixture {name} result is not valid: {fx['result']['errors']}")
        seen_verdicts |= {c["verdict"] for c in fx["result"]["candidates"]}
        if fx["result"]["enumeration_attempted"] or fx["result"]["complete_action_set"]:
            errors.append(f"fixture {name} claims enumeration or completeness")
    missing = set(la.VERDICTS) - seen_verdicts
    if missing:
        errors.append(f"fixtures do not reach every verdict; missing {sorted(missing)}")

    # Specific expectations that pin the classifier to the timing kernel.
    by = {n: f["result"] for n, f in fixtures.items()}
    cand = lambda n, cid: next(c for c in by[n]["candidates"] if c["candidate_id"] == cid)  # noqa: E731
    if cand("neutral_open_mixed", "c1-play-unit")["verdict"] != "legal":
        errors.append("default play in Neutral Open by the Turn Player must be legal")
    if cand("neutral_closed_reaction_window", "c2-default")["verdict"] != "illegal" or "Core 807" not in cand("neutral_closed_reaction_window", "c2-default")["rule_locators"]:
        errors.append("default play in a Closed state must be illegal with the reaction locators")
    if cand("neutral_closed_reaction_window", "c1-reaction")["verdict"] != "legal":
        errors.append("a Reaction in a Closed state must be legal")
    for cid in ("c1-play", "c2-prose"):
        c = cand("prose_only_indeterminate", cid)
        if c["verdict"] != "indeterminate" or not c["missing_information"]:
            errors.append(f"prose-only {cid} must be indeterminate and name what is missing")
    if cand("pending_decision", "c1-after-order")["verdict"] != "decision_required" or cand("pending_decision", "c1-after-order")["decision_id"] != "d1":
        errors.append("a candidate depending on a listed pending decision must be decision_required")
    if cand("pending_decision", "c2-unknown-ref")["verdict"] != "indeterminate":
        errors.append("an unknown decision reference must be indeterminate, not decision_required")
    if cand("showdown_open_focus", "c3-p2-acts")["verdict"] != "indeterminate":
        errors.append("a candidate for a different actor must not be classified as that actor")

    # --- hindsight: hashes and verdicts identical with and without later facts -
    a, b = by["hindsight_without"], by["hindsight_with"]
    if fixtures["hindsight_without"]["observation"]["observation_hash"] != fixtures["hindsight_with"]["observation"]["observation_hash"]:
        errors.append("later_revealed/contradictory facts changed the observation hash")
    if [c["verdict"] for c in a["candidates"]] != [c["verdict"] for c in b["candidates"]] or a["result_hash"] != b["result_hash"]:
        errors.append("hindsight facts changed verdicts or the result hash")

    # --- determinism ----------------------------------------------------------
    fx = fixtures["neutral_open_mixed"]
    again = la.classify_candidates(copy.deepcopy(fx["observation"]), copy.deepcopy(fx["query"]))
    if again["result_hash"] != fx["result"]["result_hash"]:
        errors.append("classification is not deterministic")

    # --- perspective boundary --------------------------------------------------
    leaked_obs = copy.deepcopy(fixtures["neutral_closed_reaction_window"]["observation"])
    leaked_obs["facts"]["inferred"].append({"fact_id": "leak", "text": "x", "provenance": "unknown", "player1_hand": ["Reaction"]} if False else {"fact_id": "leak", "text": "x", "provenance": "unknown"})
    leaked_obs["source"]["player1_hand"] = ["a Reaction"]
    leaked_obs["observation_hash"] = la.observation_hash(leaked_obs)
    expect_errors("player2 observation with player1_hand", la.validate_observation(leaked_obs), "Player 1 private", errors)
    leaked_q = copy.deepcopy(fixtures["neutral_closed_reaction_window"]["query"])
    leaked_q["candidates"][0]["action"]["opponent_hand"] = ["Reaction"]
    leaked_q["query_hash"] = la.canonical_hash({k: v for k, v in leaked_q.items() if k != "query_hash"})
    expect_errors("player2 query with opponent_hand", la.validate_query(leaked_q), "Player 1 private", errors)
    res = la.classify_candidates(fixtures["neutral_closed_reaction_window"]["observation"], leaked_q)
    if res["valid"] or not res["candidates"] == []:
        errors.append("classifier produced verdicts for a query carrying hidden information")
    wrong_actor = copy.deepcopy(fixtures["neutral_closed_reaction_window"]["query"])
    wrong_actor["acting_player"] = "p1"
    wrong_actor["query_hash"] = la.canonical_hash({k: v for k, v in wrong_actor.items() if k != "query_hash"})
    if la.classify_candidates(fixtures["neutral_closed_reaction_window"]["observation"], wrong_actor)["valid"]:
        errors.append("a player2 observation accepted a p1 acting player")

    # --- result invariants -----------------------------------------------------
    good = copy.deepcopy(fx["result"])
    over = copy.deepcopy(good); over["complete_action_set"] = True
    expect_errors("complete_action_set true", la.validate_result(over), "complete action set", errors)
    enum = copy.deepcopy(good); enum["enumeration_attempted"] = True
    expect_errors("enumeration_attempted true", la.validate_result(enum), "enumeration", errors)
    disordered = copy.deepcopy(good); disordered["candidates"].reverse()
    expect_errors("candidates out of order", la.validate_result(disordered), "candidate_id order", errors)
    lying = copy.deepcopy(good); lying["summary"]["legal"] += 1
    expect_errors("summary mismatch", la.validate_result(lying), "summary", errors)
    silent = copy.deepcopy(by["prose_only_indeterminate"]); silent["candidates"][0]["missing_information"] = []
    expect_errors("indeterminate without missing info", la.validate_result(silent), "name what is missing", errors)
    unbound = copy.deepcopy(fx["query"]); unbound["observation_hash"] = "sha256:" + "0" * 64
    unbound["query_hash"] = la.canonical_hash({k: v for k, v in unbound.items() if k != "query_hash"})
    if la.classify_candidates(fx["observation"], unbound)["valid"]:
        errors.append("a query bound to a different observation hash was classified")

    # --- engine-check wrapping ------------------------------------------------
    hashes = {"observation": fx["observation"]["observation_hash"], "action_query": fx["query"]["query_hash"]}
    wrapped = build_engine_check("legal_action", fx["result"], input_hashes=hashes)
    if validate_engine_check(wrapped) or wrapped["outcome"] != "supported" or wrapped["coverage"]["id"] != "legal_action_v1":
        errors.append(f"legal-action result did not wrap as a supported legal_action_v1 check: {wrapped.get('outcome')}")
    if wrapped["coverage"]["complete_legality"] is not False or "engine_enumeration" not in wrapped["coverage"]["unsupported_scope"]:
        errors.append("legal_action engine-check must declare enumeration unsupported")
    dec = build_engine_check("legal_action", by["pending_decision"], input_hashes=hashes)
    if dec["outcome"] != "decision_required":
        errors.append("a result with a decision_required candidate must wrap as decision_required")
    inv = build_engine_check("legal_action", la.classify_candidates(fx["observation"], unbound), input_hashes=hashes)
    if inv["outcome"] != "invalid_input":
        errors.append("an invalid result must wrap as invalid_input")

    # --- CLI, off-cwd ---------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="legal-action-") as temp_name:
        temp = Path(temp_name)
        (temp / "obs.json").write_text(json.dumps(fx["observation"]), encoding="utf-8")
        (temp / "query.json").write_text(json.dumps(fx["query"]), encoding="utf-8")
        out = temp / "result.json"
        ok = subprocess.run([sys.executable, str(RUNNER), "classify", str(temp / "obs.json"), str(temp / "query.json"), "--output", str(out)], cwd=temp, text=True, capture_output=True, check=False)
        if ok.returncode != 0 or not out.exists():
            errors.append(f"CLI classify failed off-cwd: {ok.stderr.strip()}")
        elif json.loads(out.read_text(encoding="utf-8"))["result_hash"] != fx["result"]["result_hash"]:
            errors.append("CLI result differs from the in-process result")
        val = subprocess.run([sys.executable, str(RUNNER), "validate", str(out)], cwd=temp, text=True, capture_output=True, check=False)
        if out.exists() and val.returncode != 0:
            errors.append(f"CLI validate rejected its own output: {val.stderr.strip()}")
        (temp / "bad.json").write_text(json.dumps(unbound), encoding="utf-8")
        bad_out = temp / "bad-result.json"
        bad = subprocess.run([sys.executable, str(RUNNER), "classify", str(temp / "obs.json"), str(temp / "bad.json"), "--output", str(bad_out)], cwd=temp, text=True, capture_output=True, check=False)
        if bad.returncode == 0 or bad_out.exists():
            errors.append("CLI classify exited 0 or wrote output for an unbound query")

    if errors:
        print("FAILED: legal-action checks\n  - " + "\n  - ".join(errors))
        return 1
    print(f"OK: legal-action Phase A reaches all five verdicts from real timing states, refuses hidden information, ignores hindsight, never enumerates, and wraps into engine-check.v1 ({len(fixtures)} fixtures).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
