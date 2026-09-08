#!/usr/bin/env python3
"""`evidence-pack.v1`: an answer's receipts, and the tool that re-runs them.

The service's authority claim is that every mechanical conclusion can be
re-run by someone who is not us. This is the unit that makes that true. A pack
carries the engine identity the answer was produced under, the exact inputs,
the card programs the answer used, and the engine-check the engine emitted.
`verify` re-runs the inputs on the engine at hand and says, field by field,
whether it reproduces the check.

This tool is public on purpose. The compiled card corpus behind the service is
not — so a pack discloses the programs *this answer* used, and nothing else.
Re-runnability is per answer; the corpus is per service.

  python verify_evidence_pack.py build  --kind effect --state s.json --program p.json [--decisions d.json] --out pack.json
  python verify_evidence_pack.py verify pack.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from battlefield_control import STEPS as CONTROL_STEPS  # noqa: E402
from capability_manifest import build_manifest, capability_binding  # noqa: E402
from combat import STEPS as COMBAT_STEPS  # noqa: E402
from effect_ir import apply_program, hash_value  # noqa: E402
from engine_check import build_engine_check, canonical_hash, validate_engine_check  # noqa: E402
from engine_decisions import validate_engine_decisions  # noqa: E402
from legal_action import enumerate_actions, observation_hash  # noqa: E402
from rules_core import state_hash, validate_timing  # noqa: E402

PACK_VERSION = "evidence-pack.v1"
# Kinds this verifier can re-run. Anything else is refused by name, never
# reported as verified because nothing contradicted it — `resolution`, `play`,
# `cleanup`, `turn_step`, `hide_step` and `standard_move` are still outside.
#
# The five here are the entries the unified consultation command covers, and
# they are here because that command's contract requires its evidence to be
# re-runnable. Each re-run below mirrors the input hashes engine_check's own
# runner produces for the same kind, so a pack reproduces the check the CLI
# would have built rather than a look-alike of it.
VERIFIABLE_KINDS = {"effect", "timing", "combat_step", "control_step", "legal_action"}

# What each verifiable kind needs in `inputs`. A pack missing one of these is
# refused before anything is run.
REQUIRED_INPUTS = {
    "effect": ("effect_state", "effect_program"),
    "timing": ("timing_state", "timing_action"),
    "combat_step": ("timing_state", "effect_state", "step"),
    "control_step": ("timing_state", "effect_state", "step"),
    "legal_action": ("observation", "acting_player"),
}


class EvidencePackError(ValueError):
    pass


def live_engine() -> dict[str, Any]:
    manifest = build_manifest(SCRIPT_DIR)
    return {**capability_binding(manifest), "ruleset": copy.deepcopy(manifest["ruleset"])}


def _decisions_of(inputs: dict[str, Any]) -> dict[str, Any] | None:
    decisions = inputs.get("engine_decisions")
    if decisions is not None:
        problems = validate_engine_decisions(decisions)
        if problems:
            raise EvidencePackError("invalid engine-decisions.v1: " + "; ".join(problems))
    return decisions


def _two_state_hashes(inputs: dict[str, Any], decisions: dict[str, Any] | None) -> dict[str, str]:
    hashes = {"timing_state": state_hash(inputs["timing_state"]),
              "effect_state": hash_value(inputs["effect_state"])}
    if decisions is not None:
        hashes["engine_decisions"] = canonical_hash(decisions)
    return hashes


def _run(kind: str, inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    if kind in REQUIRED_INPUTS:
        missing = [name for name in REQUIRED_INPUTS[kind] if name not in inputs]
        if missing:
            raise EvidencePackError(f"a {kind} pack needs {missing} in its inputs (inputs_incomplete)")
    if kind == "timing":
        state = inputs["timing_state"]
        return validate_timing(state, inputs["timing_action"]), {"timing_state": state_hash(state)}
    if kind in {"combat_step", "control_step"}:
        steps = COMBAT_STEPS if kind == "combat_step" else CONTROL_STEPS
        step = inputs["step"]
        if step not in steps:
            raise EvidencePackError(f"{kind} step {step!r} is not one of {sorted(steps)} (unknown_step)")
        decisions = _decisions_of(inputs)
        result = steps[step](inputs["timing_state"], inputs["effect_state"], decisions)
        return result, _two_state_hashes(inputs, decisions)
    if kind == "legal_action":
        observation = inputs["observation"]
        result = enumerate_actions(observation, inputs["acting_player"])
        return result, {"observation": observation_hash(observation),
                        "query": canonical_hash({"acting_player": inputs["acting_player"]})}
    if kind == "effect":
        state, program = inputs["effect_state"], inputs["effect_program"]
        decisions = inputs.get("engine_decisions")
        if decisions is not None:
            problems = validate_engine_decisions(decisions)
            if problems:
                raise EvidencePackError("invalid engine-decisions.v1: " + "; ".join(problems))
        hashes = {"effect_state": hash_value(state), "effect_program": canonical_hash(program)}
        if decisions is not None:
            hashes["engine_decisions"] = canonical_hash(decisions)
        return apply_program(state, program, decisions=decisions), hashes
    raise EvidencePackError(f"kind {kind!r} is not verifiable by this tool (kind_not_verifiable)")


def build_pack(kind: str, inputs: dict[str, Any], *, programs_used: list[dict[str, Any]] | None = None,
               note: str = "") -> dict[str, Any]:
    if kind not in VERIFIABLE_KINDS:
        raise EvidencePackError(f"kind {kind!r} is not verifiable by this tool (kind_not_verifiable)")
    engine = live_engine()
    result, hashes = _run(kind, inputs)
    check = build_engine_check(kind, result, input_hashes=hashes,
                               capability={k: engine[k] for k in ("manifest_id", "capability_set_id", "implementation_identity")})
    programs = programs_used if programs_used is not None else ([inputs["effect_program"]] if kind == "effect" else [])
    if kind != "effect" and programs_used is None and "effect_program" in inputs:
        programs = [inputs["effect_program"]]
    pack = {
        "schema_version": PACK_VERSION,
        "engine": engine,
        "check_kind": kind,
        "inputs": copy.deepcopy(inputs),
        "programs_used": copy.deepcopy(programs),
        "engine_check": check,
        "note": note,
    }
    pack["pack_hash"] = canonical_hash({k: v for k, v in pack.items() if k != "pack_hash"})
    return pack


def validate_pack(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["evidence pack must be an object"]
    required = {"schema_version", "engine", "check_kind", "inputs", "programs_used", "engine_check", "note", "pack_hash"}
    if set(value) != required:
        errors.append(f"evidence pack must carry exactly {sorted(required)}")
    if value.get("schema_version") != PACK_VERSION:
        errors.append(f"schema_version must be {PACK_VERSION}")
    engine = value.get("engine")
    if not isinstance(engine, dict) or not {"manifest_id", "capability_set_id", "implementation_identity", "ruleset"} <= set(engine):
        errors.append("engine must carry manifest_id, capability_set_id, implementation_identity, ruleset")
    if value.get("check_kind") not in VERIFIABLE_KINDS:
        errors.append(f"check_kind {value.get('check_kind')!r} is not verifiable (kind_not_verifiable)")
    if not isinstance(value.get("inputs"), dict):
        errors.append("inputs must be an object")
    if not isinstance(value.get("programs_used"), list):
        errors.append("programs_used must be an array")
    if isinstance(value.get("engine_check"), dict):
        errors.extend(f"engine_check: {e}" for e in validate_engine_check(value["engine_check"]))
    else:
        errors.append("engine_check must be an engine-check.v1 object")
    if not errors and value.get("pack_hash") != canonical_hash({k: v for k, v in value.items() if k != "pack_hash"}):
        errors.append("pack_hash does not match the pack")
    return errors


def verify_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """Re-run the pack on the engine at hand. Every field is its own verdict;
    `verified` is true only when all of them hold."""
    problems = validate_pack(pack)
    if problems:
        return {"schema_version": "evidence-verification.v1", "verified": False, "reason_code": "invalid_pack",
                "errors": problems}
    engine = live_engine()
    engine_match = all(pack["engine"].get(k) == engine[k] for k in ("manifest_id", "capability_set_id", "implementation_identity"))
    result, hashes = _run(pack["check_kind"], pack["inputs"])
    inputs_match = hashes == pack["engine_check"]["input_hashes"]
    rerun = build_engine_check(pack["check_kind"], result, input_hashes=hashes,
                               capability={k: engine[k] for k in ("manifest_id", "capability_set_id", "implementation_identity")})
    result_match = rerun["result_hash"] == pack["engine_check"]["result_hash"]
    check_match = rerun["check_id"] == pack["engine_check"]["check_id"]
    outcome_match = rerun["outcome"] == pack["engine_check"]["outcome"]
    verified = engine_match and inputs_match and result_match and check_match
    if not engine_match:
        reason = "engine_mismatch"
    elif not inputs_match:
        reason = "inputs_tampered"
    elif not result_match:
        reason = "result_not_reproduced"
    else:
        reason = "ok"
    return {
        "schema_version": "evidence-verification.v1",
        "verified": verified,
        "reason_code": reason,
        "engine_match": engine_match,
        "inputs_match": inputs_match,
        "result_match": result_match,
        "check_match": check_match,
        "outcome_match": outcome_match,
        "pack_engine": {k: pack["engine"].get(k) for k in ("manifest_id", "ruleset")},
        "live_engine": {k: engine[k] for k in ("manifest_id", "ruleset")},
        "pack_check_id": pack["engine_check"]["check_id"],
        "rerun_check_id": rerun["check_id"],
        "note": ("the pack names a different engine build; re-run under that build to confirm its claim"
                 if not engine_match else ""),
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidencePackError(f"{path} must hold a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build and verify evidence packs")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--kind", default="effect", choices=sorted(VERIFIABLE_KINDS))
    build.add_argument("--state", type=Path, required=True)
    build.add_argument("--program", type=Path, required=True)
    build.add_argument("--decisions", type=Path)
    # The CLI builds effect packs. The other four kinds take inputs this flag
    # set cannot express; the consultation command builds those through
    # build_pack directly, and `verify` re-runs any of the five.
    build.add_argument("--note", default="")
    build.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("pack", type=Path)
    verify.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            inputs = {"effect_state": _load(args.state), "effect_program": _load(args.program)}
            if args.decisions is not None:
                inputs["engine_decisions"] = _load(args.decisions)
            pack = build_pack(args.kind, inputs, note=args.note)
            args.out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {args.out}: {pack['engine_check']['check_id']} under {pack['engine']['manifest_id']}")
            return 0
        verdict = verify_pack(_load(args.pack))
        text = json.dumps(verdict, ensure_ascii=False, indent=2)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if verdict["verified"] else 1
    except EvidencePackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
