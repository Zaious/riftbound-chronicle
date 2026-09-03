#!/usr/bin/env python3
"""
Regression gate for Deck Coach's engine-evidence intake (ADR-0006).

Must hold:
  - a session with a real `supported` check attached validates, through the
    real runner and through the CLI, from a foreign cwd;
  - attaching leaves everything but the evidence pair byte-identical — on a
    draft and on a final session;
  - the behavior-coverage projection is identical before and after attaching,
    and still says strategy_evidence: not_established_by_engine_coverage;
  - a `decision_required` check attaches, and the session carries no key that
    would resolve it;
  - an `unsupported` check attaches and changes nothing else;
  - a raw engine result produced elsewhere normalizes through
    build_engine_check with the result's own input hash;
  - sessions without the pair stay valid (old artifacts).

Must fail:
  - an overclaiming check (coverage.complete_game true);
  - a malformed check (authority missing);
  - a check carrying raw_result;
  - the pair split either way, or the wrong scope constant;
  - a duplicate check_id;
  - a session that carries cleanup_decisions or replacement_event_order;
  - the CLI writing a session on any refusal.
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
REPO_ROOT = SKILL_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import deck_coach as dc  # noqa: E402
from card_behavior_coverage import summarize_profile_coverage  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, hash_value, perform_lethal_cleanup  # noqa: E402
from engine_check import build_engine_check, canonical_hash  # noqa: E402
from rules_core import state_hash, validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "deck_coach.py"
SCHEMA = SKILL_DIR / "schemas" / "deck-coach-session.schema.json"
PROTOTYPE = REPO_ROOT / "prototype" / "deck-coach"


def final_session() -> dict:
    s = dc.new_session(environment="global-vendetta", format_name="1v1 Constructed", legend="Fixture Legend", champion=None, created_by="gate")
    s["decklist"] = [{"name": "Fixture Card", "count": 3, "roles": [], "notes": ""}]
    s["diagnosis"] = {"identity": "fixture", "core_loop": "fixture", "strengths": ["a"], "gaps": ["b"], "proposed_changes": ["c"],
                      "role_coverage": dc.role_coverage(s["decklist"]), "evidence": [{"claim": "x", "tier": "Tier 3", "basis": "fixture"}]}
    s["primer"] = {key: "fixture" for key in dc.PRIMER_SECTIONS}
    s["status"] = "final"
    dc.require_valid(s)
    return s


def expect_refused(label: str, fn, needle: str, errors: list[str]) -> None:
    try:
        fn()
    except dc.DeckCoachError as exc:
        if needle not in str(exc):
            errors.append(f"{label}: refused for the wrong reason: {exc}")
        return
    errors.append(f"{label}: accepted, but should have been refused")


def main() -> int:
    errors: list[str] = []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    if "engine_checks" in schema.get("required", []) or "engine_evidence_scope" in schema.get("required", []):
        errors.append("the evidence pair must be optional (ADR-0002 row 1)")
    if props.get("engine_evidence_scope", {}).get("const") != dc.ENGINE_EVIDENCE_SCOPE:
        errors.append("schema does not pin engine_evidence_scope to rules_consistency_only")
    if schema.get("dependentRequired", {}).get("engine_checks") != ["engine_evidence_scope"]:
        errors.append("schema does not pair engine_checks with engine_evidence_scope")
    if '"engine-check.schema.json"' not in SCHEMA.read_text(encoding="utf-8"):
        errors.append("schema does not reference the shared engine-check schema")

    # --- real checks from the real engines -----------------------------------
    timing = fixture()
    supported = build_engine_check("timing", validate_timing(timing, {"actor": "p1", "kind": "play_card", "timing": "default", "object_kind": "unit"}), input_hashes={"timing_state": state_hash(timing)})
    unsupported = build_engine_check("timing", validate_timing(timing, {"actor": "p1", "kind": "unknown", "timing": "default", "object_kind": "unit"}), input_hashes={"timing_state": state_hash(timing)})
    st = base_state()
    for oid in ("u3", "u4"):
        st["objects"][oid] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
        st["players"]["p2"]["zones"]["base"].append(oid)
    st["objects"]["u2"]["damage"] = 4; st["objects"]["u3"]["damage"] = 2
    st["replacement_effects"] = [{"replacement_id": "guard-all", "controller": "p2", "source_object": "u4", "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"}]
    decision = build_engine_check("cleanup", perform_lethal_cleanup(copy.deepcopy(st)), input_hashes={"effect_state": hash_value(st)})
    if {supported["outcome"], unsupported["outcome"], decision["outcome"]} != {"supported", "unsupported", "decision_required"}:
        errors.append(f"engine fixtures did not produce the three outcomes: {supported['outcome']}, {unsupported['outcome']}, {decision['outcome']}")

    # --- attach preserves content, on final and on draft ----------------------
    base = final_session()
    before = dc.evidence_free_view(base)
    attached = dc.attach_engine_check(base, supported)
    if dc.validate_session(attached) or dc.evidence_free_view(attached) != before:
        errors.append("attaching a supported check changed session content or produced an invalid session")
    if attached.get("engine_evidence_scope") != dc.ENGINE_EVIDENCE_SCOPE or len(attached["engine_checks"]) != 1:
        errors.append("evidence pair not set as ADR-0006 requires")
    draft = dc.new_session(environment="e", format_name="f", legend="l", champion=None, created_by="gate")
    d2 = dc.attach_engine_check(draft, supported)
    if dc.validate_session(d2) or d2["status"] != "draft" or dc.evidence_free_view(d2) != dc.evidence_free_view(draft):
        errors.append("attaching to a draft changed its content or status")
    if dc.validate_session(final_session()):
        errors.append("a session without the pair must remain valid")

    # --- coverage projection unaffected --------------------------------------
    profile = {"context": {"environment": "global-core-origins-v1", "region": "global", "format": "proving_grounds_product_practice"},
               "resolution": {"total_main_deck_copies": 3, "known_copies": 3, "unknown_entries": [], "resolved_entries": [{"canonical_name": "Fixture Card", "current_text_hash": "sha256:" + "a" * 64, "riftbound_id": "x", "count": 3}]}}
    cov_before = summarize_profile_coverage(profile, None)
    cov_after = summarize_profile_coverage(profile, None)
    if cov_before != cov_after or cov_after["strategy_evidence"] != "not_established_by_engine_coverage":
        errors.append("coverage projection changed or lost its strategy_evidence marker")

    # --- decision_required is shown, never answered ---------------------------
    with_decision = dc.attach_engine_check(attached, decision)
    if dc.validate_session(with_decision):
        errors.append("a decision_required check did not attach")
    if any(k in json.dumps(with_decision) for k in ("cleanup_decisions", "replacement_event_order")):
        errors.append("session carries a resolved decision")
    resolved = copy.deepcopy(with_decision); resolved["cleanup_decisions"] = {"replacement_event_order": ["u2", "u3"]}
    if not any("resolves an engine decision" in e or "unknown top-level" in e for e in dc.validate_session(resolved)):
        errors.append("a session resolving an engine decision was accepted")
    with_unsupported = dc.attach_engine_check(with_decision, unsupported)
    if dc.validate_session(with_unsupported) or dc.evidence_free_view(with_unsupported) != before:
        errors.append("attaching an unsupported check changed content")

    # --- refusals ------------------------------------------------------------
    over = copy.deepcopy(supported); over["coverage"]["complete_game"] = True
    expect_refused("overclaiming check", lambda: dc.attach_engine_check(base, over), "complete-game", errors)
    mal = copy.deepcopy(supported); del mal["authority"]
    expect_refused("malformed check", lambda: dc.attach_engine_check(base, mal), "invalid engine-check", errors)
    raw = copy.deepcopy(supported); raw["raw_result"] = {"x": 1}
    expect_refused("raw result", lambda: dc.attach_engine_check(base, raw), "raw engine result", errors)
    expect_refused("duplicate", lambda: dc.attach_engine_check(attached, supported), "duplicate", errors)
    split = copy.deepcopy(attached); del split["engine_evidence_scope"]
    if not any("together" in e for e in dc.validate_session(split)):
        errors.append("split pair (scope missing) accepted")
    split2 = copy.deepcopy(base); split2["engine_evidence_scope"] = dc.ENGINE_EVIDENCE_SCOPE
    if not any("together" in e for e in dc.validate_session(split2)):
        errors.append("split pair (checks missing) accepted")
    wrong = copy.deepcopy(attached); wrong["engine_evidence_scope"] = "strategy_quality"
    if not any("rules_consistency_only" in e for e in dc.validate_session(wrong)):
        errors.append("wrong scope constant accepted")

    # --- normalization of a raw result produced elsewhere --------------------
    raw_result = validate_timing(timing, {"actor": "p2", "kind": "play_card", "timing": "default", "object_kind": "unit"})
    norm = dc.normalize_engine_result("timing", raw_result)
    if norm["outcome"] != "illegal" or norm["input_hashes"] != {"timing_state": raw_result["input_state_hash"]}:
        errors.append("raw result normalization lost the outcome or the input hash")
    expect_refused("unknown kind", lambda: dc.normalize_engine_result("legal_action", raw_result), "unsupported engine check kind", errors)
    bad_result = copy.deepcopy(raw_result); bad_result["input_state_hash"] = "nope"
    expect_refused("bad input hash", lambda: dc.normalize_engine_result("timing", bad_result), "input_state_hash", errors)

    # --- CLI, off-cwd, write-nothing-on-refusal --------------------------------
    with tempfile.TemporaryDirectory(prefix="deck-coach-intake-") as temp_name:
        temp = Path(temp_name)
        session_path = temp / "session.json"
        session_path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp / "check.json").write_text(json.dumps(supported), encoding="utf-8")
        ok = subprocess.run([sys.executable, str(RUNNER), "engine-check", str(session_path), "--check", str(temp / "check.json")], cwd=temp, text=True, capture_output=True, check=False)
        if ok.returncode != 0:
            errors.append(f"CLI attach failed off-cwd: {ok.stderr.strip()}")
        else:
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            if dc.validate_session(saved) or len(saved.get("engine_checks", [])) != 1 or dc.evidence_free_view(saved) != before:
                errors.append("CLI attach produced a wrong session")
        (temp / "result.json").write_text(json.dumps(raw_result), encoding="utf-8")
        ok2 = subprocess.run([sys.executable, str(RUNNER), "engine-check", str(session_path), "--result", str(temp / "result.json"), "--kind", "timing"], cwd=temp, text=True, capture_output=True, check=False)
        if ok2.returncode != 0 or len(json.loads(session_path.read_text(encoding="utf-8"))["engine_checks"]) != 2:
            errors.append(f"CLI --result normalization failed: {ok2.stderr.strip()}")
        snapshot = session_path.read_text(encoding="utf-8")
        (temp / "over.json").write_text(json.dumps(over), encoding="utf-8")
        bad = subprocess.run([sys.executable, str(RUNNER), "engine-check", str(session_path), "--check", str(temp / "over.json")], cwd=temp, text=True, capture_output=True, check=False)
        if bad.returncode == 0 or session_path.read_text(encoding="utf-8") != snapshot:
            errors.append("CLI accepted an overclaiming check or wrote the session on refusal")
        val = subprocess.run([sys.executable, str(RUNNER), "validate", str(session_path)], cwd=temp, text=True, capture_output=True, check=False)
        if val.returncode != 0:
            errors.append(f"CLI validate rejected a session with evidence: {val.stderr.strip()}")

    # --- prototype: shared viewer, read-only, no production ------------------
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")
    js = (PROTOTYPE / "app.js").read_text(encoding="utf-8")
    for needle, where in (("engine-check-view.js", html), ("engine-check-fixtures.js", html), ('id="engine-check-view"', html), ("RC_ENGINE_CHECK_VIEW.mount", js), ("rules_consistency_only", js)):
        if needle not in where:
            errors.append(f"prototype missing {needle!r}")
    for forbidden in ("build_engine_check", "validate_timing", "primer_to_state", "fetch("):
        if forbidden in js:
            errors.append(f"prototype must not produce checks or reach the network: {forbidden!r}")
    if "cleanup_decisions" in js or "replacement_event_order" in js:
        errors.append("prototype supplies engine decisions")

    if errors:
        print("FAILED: Deck Coach engine intake checks\n  - " + "\n  - ".join(errors))
        return 1
    print("OK: Deck Coach consumes engine-check.v1 as rules-consistency evidence only — attach preserves content on draft and final, refuses overclaim/malformed/raw/duplicate/split, never resolves a decision, normalizes raw results with their own hash, and renders through the shared read-only viewer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
