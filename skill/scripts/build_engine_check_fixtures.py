#!/usr/bin/env python3
"""
Regenerate the shared engine-check viewer fixtures from the real engines.

The viewer under `prototype/shared/engine-check-view.js` must render all five
`engine-check.v1` outcomes. Hand-authored samples would drift from the envelope
the runner actually emits, and a viewer validated against invented data proves
nothing -- so every fixture here is produced by running the genuine components
(`rules_core.validate_timing`, `effect_ir.apply_program`,
`effect_ir.perform_lethal_cleanup`) and wrapping the result with the real
`engine_check.build_engine_check`.

The generated file is committed as plain JavaScript, not JSON: the prototype
pages open straight from disk and are forbidden from making network requests,
so a fetched .json fixture would never load. Re-run this script after any
change to the envelope, the outcome classifier, or the engines, and commit the
diff.

Usage:
    python3 skill/scripts/build_engine_check_fixtures.py [--check]

--check regenerates in memory and fails if the committed file is stale, which
is what CI uses.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent
OUT = REPO_ROOT / "prototype" / "shared" / "engine-check-fixtures.js"

sys.path.insert(0, str(SCRIPT_DIR))

from engine_check import build_engine_check, validate_engine_check  # noqa: E402
import effect_ir  # noqa: E402
import rules_core  # noqa: E402


def _load_check_module(name: str):
    """Import a check_*.py module for its canonical fixture builders.

    Those builders are the single source of the states the conformance suite
    already asserts against, so reusing them keeps the viewer fixtures and the
    engine fixtures from drifting apart.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_fixtures() -> dict:
    rules_core_checks = _load_check_module("check_rules_core")
    effect_checks = _load_check_module("check_effect_ir")

    cases = json.loads((SKILL_DIR / "data" / "rules_core_cases.json").read_text(encoding="utf-8"))["cases"]
    fixtures: list[dict] = []

    def add(label: str, note: str, kind: str, result: dict, hashes: dict, **kwargs) -> None:
        check = build_engine_check(kind, result, input_hashes=hashes, **kwargs)
        errors = validate_engine_check(check)
        if errors:
            raise SystemExit(f"{label}: generated check is invalid: {errors}")
        fixtures.append({"fixture_id": label, "note": note, "check": check})

    # supported / illegal -- taken from the timing conformance corpus so the
    # viewer shows exactly what the R1 kernel really returns.
    for outcome_wanted, note in (
        ("supported", "Timing kernel accepted the action inside its bounded coverage."),
        ("illegal", "A supported timing rule rejects the attempted action. This is a bounded rejection, not a card-legality ruling."),
    ):
        for case in cases:
            if "action" not in case:
                continue
            state = rules_core_checks.FIXTURES[case["state"]]
            result = rules_core.validate_timing(state, case["action"])
            probe = build_engine_check("timing", result, input_hashes={"state": rules_core.state_hash(state)})
            if probe["outcome"] == outcome_wanted:
                add(
                    outcome_wanted,
                    f"{note} Source case {case['case_id']}: {case['description']}",
                    "timing",
                    result,
                    {"state": rules_core.state_hash(state)},
                    assumptions=["Fixture state is treated as already confirmed."],
                    missing_information=[],
                )
                break
        else:
            raise SystemExit(f"no timing conformance case produces outcome {outcome_wanted!r}")

    # unsupported -- an operation the typed effect IR deliberately does not model.
    effect_state = effect_checks.base_state()
    unsupported = effect_ir.apply_program(
        copy.deepcopy(effect_state),
        effect_checks.program("viewer-unsupported", {"op": "counter", "chain_item_id": "chain-1"}),
    )
    add(
        "unsupported",
        "The effect IR has no model for this operation and fails closed rather than guessing one.",
        "effect",
        unsupported,
        {"state": effect_ir.hash_value(effect_state)},
        assumptions=[],
        missing_information=["Typed program for the Counter operation."],
    )

    # decision_required -- simultaneous replacement needing a controller ordering.
    decision_state = effect_checks.base_state()
    for object_id in ("u3", "u4"):
        decision_state["objects"][object_id] = {
            "owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2,
            "might_modifiers": [], "damage": 0, "exhausted": False,
        }
        decision_state["players"]["p2"]["zones"]["base"].append(object_id)
    decision_state["objects"]["u2"]["damage"] = 4
    decision_state["objects"]["u3"]["damage"] = 2
    decision_state["replacement_effects"] = [{
        "replacement_id": "guard-all", "controller": "p2", "source_object": "u4",
        "mode": "prevent_event", "event_op": "kill", "optional": False,
        "uses_remaining": None, "target_controller_relation": "friendly",
    }]
    decision = effect_ir.perform_lethal_cleanup(decision_state)
    add(
        "decision_required",
        "A controller must order simultaneous replacement events before cleanup can continue. The viewer presents the options; it never picks one.",
        "cleanup",
        decision,
        {"state": effect_ir.hash_value(decision_state)},
        assumptions=[],
        missing_information=["Controller ordering for the simultaneous replacement batch."],
    )

    # invalid_input -- malformed state, which is a data problem, not a ruling.
    malformed = {"schema_version": "not-a-real-state"}
    invalid = effect_ir.apply_program(
        malformed,
        effect_checks.program("viewer-invalid", {"op": "draw", "player": "p1", "count": 1}),
    )
    add(
        "invalid_input",
        "State or program is malformed. Repair the input; do not read this as a game ruling.",
        "effect",
        invalid,
        {"state": effect_ir.hash_value(malformed)},
        assumptions=[],
        missing_information=["A well-formed riftbound-effect-state.v1 document."],
    )

    covered = {item["check"]["outcome"] for item in fixtures}
    expected = {"supported", "illegal", "unsupported", "decision_required", "invalid_input"}
    if covered != expected:
        raise SystemExit(f"fixtures cover {sorted(covered)}; every outcome in {sorted(expected)} is required")

    return {
        "schema_version": "engine-check-view-fixtures.v1",
        "generated_by": "skill/scripts/build_engine_check_fixtures.py",
        "note": "Read-only demo data produced by the real engines. Not a rules authority; every check carries official_status unofficial and state_effect none.",
        "fixtures": fixtures,
    }


BANNER = """// GENERATED FILE -- do not edit by hand.
// Produced by skill/scripts/build_engine_check_fixtures.py from the real
// engines. Read-only demo data for prototype/shared/engine-check-view.js; not a
// rules authority. Regenerate and commit after any engine or envelope change.
"""


def render_module(payload: dict) -> str:
    """Wrap the fixture payload as a browser-loadable global assignment."""
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"{BANNER}window.RC_ENGINE_CHECK_FIXTURES = Object.freeze({body});\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the committed fixture file is stale")
    args = parser.parse_args()

    generated = build_fixtures()
    rendered = render_module(generated)

    if args.check:
        if not OUT.exists():
            print(f"FAILED: {OUT.relative_to(REPO_ROOT)} does not exist; run this script without --check")
            return 1
        if OUT.read_text(encoding="utf-8") != rendered:
            print(f"FAILED: {OUT.relative_to(REPO_ROOT)} is stale; re-run build_engine_check_fixtures.py and commit the diff")
            return 1
        print(f"OK: {len(generated['fixtures'])} engine-check fixtures are current.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {len(generated['fixtures'])} fixtures to {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
