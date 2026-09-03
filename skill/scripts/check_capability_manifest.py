#!/usr/bin/env python3
"""
Regression gate for the engine capability manifest (ADR-0002, package C-09).

What it must catch, each injected here and required to fail:

  - a committed manifest that no longer matches the engine (stale build);
  - a manifest that claims an operation the engine lacks (overstatement);
  - a manifest that omits one the engine has (understatement — the README gate
    already treats both directions as errors, and this does too);
  - a tampered implementation hash;
  - an engine-check bound to a different capability set than the manifest;
  - a malformed `capability` block on an engine-check;
  - the CLI writing output on failure, or passing from a foreign cwd only by
    accident of relative paths.

And what it must preserve: every engine-check emitted *without* a capability
block stays valid, because that is the ADR-0002 promise that makes the field
optional rather than a new schema major.
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

from capability_manifest import (  # noqa: E402
    DEFAULT_OUTPUT,
    ENGINE_SOURCES,
    SCHEMA_VERSION,
    binding_matches,
    build_manifest,
    capability_binding,
    validate_manifest,
    verify_manifest,
)
from check_rules_core import fixture  # noqa: E402
from engine_check import build_engine_check, validate_engine_check  # noqa: E402
from rules_core import state_hash, validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "capability_manifest.py"
SCHEMA = SKILL_DIR / "schemas" / "engine-capability-manifest.schema.json"
ENGINE_CHECK_SCHEMA = SKILL_DIR / "schemas" / "engine-check.schema.json"


def expect_findings(label: str, findings: list[str], needle: str, errors: list[str]) -> None:
    if not findings:
        errors.append(f"{label}: accepted, but should have been rejected")
    elif not any(needle in f for f in findings):
        errors.append(f"{label}: rejected for the wrong reason: {findings}")


def main() -> int:
    errors: list[str] = []

    # --- schema and runner agree ----------------------------------------------
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        errors.append("capability manifest schema and runner version diverged")
    ec_schema = json.loads(ENGINE_CHECK_SCHEMA.read_text(encoding="utf-8"))
    cap_prop = ec_schema.get("properties", {}).get("capability")
    if not isinstance(cap_prop, dict) or "capability" in ec_schema.get("required", []):
        errors.append("engine-check schema must declare `capability` as an optional property")

    # --- the committed manifest is what the engine says today -----------------
    live = build_manifest()
    if validate_manifest(live):
        errors.append(f"built manifest is invalid: {validate_manifest(live)}")
    if not DEFAULT_OUTPUT.exists():
        errors.append(f"committed manifest missing: {DEFAULT_OUTPUT}; run capability_manifest.py build")
        committed = live
    else:
        committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
        findings = verify_manifest(committed)
        if findings:
            errors.append("committed manifest is stale; re-run capability_manifest.py build and commit the diff: " + "; ".join(findings))

    # Derivation, not description: every engine op and procedure is listed.
    import effect_ir  # noqa: E402
    import rules_core  # noqa: E402
    if {op["id"] for op in live["operations"]} != set(effect_ir.SUPPORTED_OPS):
        errors.append("manifest operations do not equal effect_ir.SUPPORTED_OPS")
    if {p["id"] for p in live["procedures"]} != set(rules_core.SUPPORTED_PROCEDURES):
        errors.append("manifest procedures do not equal rules_core.SUPPORTED_PROCEDURES")
    if {p["id"] for p in live["procedures"]} & set(rules_core.RULES):
        errors.append("manifest treats a RULES topic as an executable procedure")
    for procedure in rules_core.SUPPORTED_PROCEDURES:
        if not callable(getattr(rules_core, procedure, None)):
            errors.append(f"declared procedure {procedure!r} is not callable")
    if [f["path"] for f in live["implementation"]["files"]] != list(ENGINE_SOURCES):
        errors.append("implementation identity does not cover the engine sources in order")
    if live["claims"] != {"complete_game": False, "complete_legality": False}:
        errors.append("manifest must reject complete-game and complete-legality")

    # --- injected drift, each must be caught ---------------------------------
    over = copy.deepcopy(live)
    over["operations"].append({"id": "counter", "rule_locators": ["Core 999"]})
    over["operations"].sort(key=lambda o: o["id"])
    expect_findings("overstated operation (validate)", validate_manifest(over), "capability_set_id", errors)

    under = copy.deepcopy(live)
    under["operations"] = [op for op in under["operations"] if op["id"] != "draw"]
    # Re-hash so the *shape* is valid; only `verify` can see the understatement.
    from capability_manifest import canonical_hash  # noqa: E402
    content = {k: under[k] for k in ("ruleset", "components", "operations", "procedures", "clauses", "exclusions", "claims")}
    under["capability_set_id"] = canonical_hash(content)
    under["manifest_id"] = "capability-manifest:" + under["capability_set_id"].split(":", 1)[1][:24]
    if validate_manifest(under):
        errors.append("understated manifest should still be well-formed")
    expect_findings("understated operation (verify)", verify_manifest(under), "engine supports 'draw'", errors)

    tampered = copy.deepcopy(live)
    tampered["implementation"]["files"][0]["sha256"] = "sha256:" + "0" * 64
    expect_findings("tampered file hash (validate)", validate_manifest(tampered), "does not hash its file list", errors)
    tampered["implementation"]["value"] = canonical_hash(tampered["implementation"]["files"])
    if validate_manifest(tampered):
        errors.append("re-hashed tampered implementation should be well-formed")
    expect_findings("stale implementation (verify)", verify_manifest(tampered), "stale implementation identity", errors)

    claims = copy.deepcopy(live)
    claims["claims"]["complete_game"] = True
    expect_findings("complete-game claim", validate_manifest(claims), "claims", errors)

    # --- engine-check binding ------------------------------------------------
    timing_state = fixture()
    action = {"actor": "p1", "kind": "play_card", "timing": "default", "object_kind": "unit"}
    result = validate_timing(timing_state, action)
    hashes = {"timing_state": state_hash(timing_state)}

    unbound = build_engine_check("timing", result, input_hashes=hashes)
    if "capability" in unbound or validate_engine_check(unbound):
        errors.append("an engine-check without a capability block must stay valid and carry no block")

    bound = build_engine_check("timing", result, input_hashes=hashes, capability=capability_binding(live))
    if validate_engine_check(bound) or not binding_matches(bound, live):
        errors.append("engine-check bound to the live manifest must validate and match it")
    if bound.get("outcome") != unbound.get("outcome") or bound.get("result_hash") != unbound.get("result_hash"):
        errors.append("binding a capability must not change the check's outcome or result hash")

    other = copy.deepcopy(live)
    other["capability_set_id"] = "sha256:" + "a" * 64
    if binding_matches(bound, other):
        errors.append("a check bound to one capability set matched a different one")

    malformed = copy.deepcopy(bound)
    malformed["capability"]["capability_set_id"] = "not-a-hash"
    if not validate_engine_check(malformed):
        errors.append("malformed capability block was accepted on an engine-check")
    extra = copy.deepcopy(bound)
    extra["capability"]["commit"] = "abc"
    if not validate_engine_check(extra):
        errors.append("capability block with unknown fields was accepted")
    try:
        build_engine_check("timing", result, input_hashes=hashes, capability={"manifest_id": "x"})
        errors.append("build_engine_check accepted an incomplete capability block")
    except ValueError:
        pass

    # --- CLI, off-cwd, and the write-nothing-on-failure contract -------------
    with tempfile.TemporaryDirectory(prefix="capability-manifest-") as temp_name:
        temp = Path(temp_name)
        out = temp / "manifest.json"
        built = subprocess.run(
            [sys.executable, str(RUNNER), "build", "--output", str(out)],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if built.returncode != 0 or not out.exists():
            errors.append(f"CLI build failed off-cwd: {built.stderr.strip()}")
        else:
            verified = subprocess.run([sys.executable, str(RUNNER), "verify", str(out)], cwd=temp, text=True, capture_output=True, check=False)
            if verified.returncode != 0:
                errors.append(f"CLI verify rejected a fresh build: {verified.stderr.strip()}")
            stale_path = temp / "stale.json"
            stale_path.write_text(json.dumps(tampered), encoding="utf-8")
            stale = subprocess.run([sys.executable, str(RUNNER), "verify", str(stale_path)], cwd=temp, text=True, capture_output=True, check=False)
            if stale.returncode == 0 or "stale implementation" not in stale.stderr:
                errors.append("CLI verify passed a stale manifest")
            garbage = temp / "garbage.json"
            garbage.write_text("{not json", encoding="utf-8")
            bad = subprocess.run([sys.executable, str(RUNNER), "validate", str(garbage)], cwd=temp, text=True, capture_output=True, check=False)
            if bad.returncode == 0:
                errors.append("CLI validate exited 0 on unreadable input")
            leftovers = {p.name for p in temp.iterdir()} - {"manifest.json", "stale.json", "garbage.json"}
            if leftovers:
                errors.append(f"CLI wrote unexpected files: {sorted(leftovers)}")

    if errors:
        print("FAILED: capability manifest checks\n  - " + "\n  - ".join(errors))
        return 1
    print(f"OK: capability manifest derives from the engine, catches drift both ways, binds into engine-check.v1 optionally, and runs off-cwd ({live['manifest_id']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
