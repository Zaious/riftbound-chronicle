#!/usr/bin/env python3
"""Regression gate for `evidence-pack.v1` and its verifier.

Must hold:
  - a pack built from a state and a program verifies on the same engine, and
    the verification names the engine build, the check id and the result
    hash it reproduced;
  - the verifier is not a rubber stamp: a pack whose expected result hash was
    edited is `result_not_reproduced`, a pack whose inputs were edited after
    building is `inputs_tampered`, and a pack naming another engine build is
    `engine_mismatch` — each false on exactly the field that was touched;
  - the pack carries the programs the answer used, so a third party re-runs
    without the corpus;
  - a kind the verifier cannot re-run is refused by name, never "verified"
    because nothing contradicted it;
  - the CLI round trip works off-cwd, and building is deterministic.
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

import verify_evidence_pack as vp  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from engine_check import canonical_hash  # noqa: E402

TOOL = SCRIPT_DIR / "verify_evidence_pack.py"


def rehash(pack):
    pack = copy.deepcopy(pack)
    pack["pack_hash"] = canonical_hash({k: v for k, v in pack.items() if k != "pack_hash"})
    return pack


def main() -> int:
    errors: list[str] = []
    state = base_state()
    prog = program("evidence", {"op": "deal_damage", "effect_id": "dmg", "object_id": "u2", "amount": 2})
    pack = vp.build_pack("effect", {"effect_state": state, "effect_program": prog}, note="gate fixture")
    if found := vp.validate_pack(pack):
        errors.append(f"a freshly built pack does not validate: {found}")
    if pack["programs_used"] != [prog]:
        errors.append("the pack does not carry the program the answer used")
    verdict = vp.verify_pack(pack)
    if verdict.get("verified") is not True or verdict.get("reason_code") != "ok":
        errors.append(f"a pack built on this engine did not verify: {verdict}")
    if verdict.get("rerun_check_id") != pack["engine_check"]["check_id"] or verdict.get("live_engine", {}).get("manifest_id") != pack["engine"]["manifest_id"]:
        errors.append("the verification does not name the check id and the build it reproduced")

    # --- not a rubber stamp -----------------------------------------------------------------
    forged = copy.deepcopy(pack)
    forged["engine_check"]["result_hash"] = "sha256:" + "0" * 64
    forged = rehash(forged)
    v = vp.verify_pack(forged)
    if v.get("verified") or v.get("reason_code") != "result_not_reproduced" or v.get("inputs_match") is not True:
        errors.append(f"an edited result hash was not caught on exactly that field: {v}")
    tampered = copy.deepcopy(pack)
    tampered["inputs"]["effect_state"]["objects"]["u2"]["damage"] = 3
    tampered = rehash(tampered)
    v = vp.verify_pack(tampered)
    if v.get("verified") or v.get("reason_code") != "inputs_tampered" or v.get("engine_match") is not True:
        errors.append(f"edited inputs were not caught on exactly that field: {v}")
    foreign = copy.deepcopy(pack)
    foreign["engine"]["manifest_id"] = "capability-manifest:000000000000000000000000"
    foreign["engine"]["implementation_identity"] = "sha256:" + "1" * 64
    foreign = rehash(foreign)
    v = vp.verify_pack(foreign)
    if v.get("verified") or v.get("reason_code") != "engine_mismatch" or not v.get("note"):
        errors.append(f"a pack naming another build was not reported as an engine mismatch with guidance: {v}")
    if v.get("result_match") is not True:
        errors.append("an engine mismatch hid whether the result was still reproduced")
    unhashed = copy.deepcopy(pack)
    unhashed["note"] = "edited without rehashing"
    if vp.verify_pack(unhashed).get("reason_code") != "invalid_pack":
        errors.append("a pack edited without its hash was accepted")

    # --- refused by name --------------------------------------------------------------------
    try:
        vp.build_pack("combat_step", {"effect_state": state, "effect_program": prog})
        errors.append("a kind the verifier cannot re-run was built anyway")
    except vp.EvidencePackError as exc:
        if "kind_not_verifiable" not in str(exc):
            errors.append(f"the refusal is not named: {exc}")
    bad_kind = copy.deepcopy(pack)
    bad_kind["check_kind"] = "combat_step"
    bad_kind = rehash(bad_kind)
    if vp.verify_pack(bad_kind).get("verified") is not False:
        errors.append("a pack of an unverifiable kind was verified")

    # --- CLI off-cwd, and deterministic -----------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="evidence-") as temp_name:
        temp = Path(temp_name)
        (temp / "s.json").write_text(json.dumps(state), encoding="utf-8")
        (temp / "p.json").write_text(json.dumps(prog), encoding="utf-8")
        built = subprocess.run([sys.executable, str(TOOL), "build", "--state", "s.json", "--program", "p.json", "--out", "pack.json"],
                               cwd=temp, capture_output=True, text=True)
        checked = subprocess.run([sys.executable, str(TOOL), "verify", "pack.json", "--out", "verdict.json"],
                                 cwd=temp, capture_output=True, text=True)
        if built.returncode != 0 or checked.returncode != 0:
            errors.append(f"the CLI round trip failed off-cwd: {built.stderr.strip()} {checked.stderr.strip()}")
        else:
            cli_pack = json.loads((temp / "pack.json").read_text(encoding="utf-8"))
            if cli_pack["engine_check"]["check_id"] != pack["engine_check"]["check_id"]:
                errors.append("the CLI built a different check than the library did for the same inputs")
            if json.loads((temp / "verdict.json").read_text(encoding="utf-8")).get("verified") is not True:
                errors.append("the CLI verdict file does not say verified")
        (temp / "bad.json").write_text(json.dumps(forged), encoding="utf-8")
        if subprocess.run([sys.executable, str(TOOL), "verify", "bad.json"], cwd=temp, capture_output=True, text=True).returncode != 1:
            errors.append("the CLI did not exit 1 on a pack it could not reproduce")
    if vp.build_pack("effect", {"effect_state": state, "effect_program": prog}, note="gate fixture") != pack:
        errors.append("building a pack is not deterministic")

    if errors:
        print("FAILED: evidence pack checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"evidence pack checks passed: build/verify round trip under {pack['engine']['manifest_id']}, three forgeries caught on their own field")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
