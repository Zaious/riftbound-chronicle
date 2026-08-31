#!/usr/bin/env python3
"""
Validate the shared engine-check.v1 viewer: fixtures, rendering, and the three
invariants that make it safe for every system to reuse.

The viewer is where a bounded engine result becomes something a person reads, so
the failure that matters is not a crash -- it is a render that quietly reads
like more authority than the check carries. The three invariants, each asserted
below against a real render rather than against the source text:

  1. It never chooses. A `decision_required` render carries no interactive
     control and no language that ranks, defaults to, or recommends an option.
  2. It never widens a claim. The authority triple and the coverage limits are
     printed on every outcome, exactly as the check states them.
  3. It never mutates. No network, no storage, no listeners, no innerHTML.

Rendering is exercised through skill/scripts/engine_check_view_harness.mjs,
which runs the real viewer against a minimal DOM. `node --check` alone would
pass a viewer that had lost every one of these properties.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
VIEWER_JS = REPO_ROOT / "prototype" / "shared" / "engine-check-view.js"
VIEWER_CSS = REPO_ROOT / "prototype" / "shared" / "engine-check-view.css"
FIXTURES = REPO_ROOT / "prototype" / "shared" / "engine-check-fixtures.js"
HARNESS = SCRIPT_DIR / "engine_check_view_harness.mjs"

sys.path.insert(0, str(SCRIPT_DIR))

from engine_check import validate_engine_check  # noqa: E402
from build_engine_check_fixtures import build_fixtures, render_module  # noqa: E402

OUTCOME_ORDER = ["supported", "illegal", "unsupported", "decision_required", "invalid_input"]
INTERACTIVE_TAGS = {"button", "input", "select", "textarea", "form", "a", "dialog"}
# Wording that would turn a neutral presentation of options into a recommendation.
CHOOSING_WORDS = ("recommend", "suggest", "best option", "should pick", "preferred option", "we advise", "auto-select")
# Read-only means read-only; each of these would break it in a different way.
FORBIDDEN_JS = ("innerHTML", "outerHTML", "document.write", "fetch(", "localStorage", "sessionStorage",
                "addEventListener", "XMLHttpRequest", "eval(", "new Function")


def strip_comments(source: str) -> str:
    """Drop // and /* */ comments so source guards match code, not prose."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def text_of(node) -> str:
    return " ".join(item["text"] for item in walk(node) if item.get("text"))


def main() -> int:
    errors: list[str] = []

    for path in (VIEWER_JS, VIEWER_CSS, FIXTURES, HARNESS):
        if not path.is_file():
            errors.append(f"missing {path.relative_to(REPO_ROOT).as_posix()}")
    if errors:
        print("\n".join(f"  - {error}" for error in errors))
        return 1

    # --- fixtures are genuine engine output, and current -------------------
    committed = FIXTURES.read_text(encoding="utf-8")
    if committed != render_module(build_fixtures()):
        errors.append("engine-check-fixtures.js is stale; re-run build_engine_check_fixtures.py and commit the diff")

    # The fixtures ship as a browser-loadable global assignment, since the demo
    # pages open from disk and may not fetch. Unwrap the payload to inspect it.
    payload = committed[committed.index("Object.freeze(") + len("Object.freeze("):committed.rindex(");")]
    fixtures = json.loads(payload)["fixtures"]
    covered = {item["check"]["outcome"] for item in fixtures}
    if covered != set(OUTCOME_ORDER):
        errors.append(f"fixtures cover {sorted(covered)}; the viewer must be exercised on all of {sorted(OUTCOME_ORDER)}")
    for item in fixtures:
        schema_errors = validate_engine_check(item["check"])
        if schema_errors:
            errors.append(f"fixture {item['fixture_id']}: invalid engine-check.v1: {schema_errors}")

    # --- source-level read-only guards -------------------------------------
    # Comments are stripped first: the viewer's own header explains why it never
    # touches innerHTML, and a guard that matched its own rationale would be a
    # guard nobody could ever satisfy.
    viewer_source = strip_comments(VIEWER_JS.read_text(encoding="utf-8"))
    for token in FORBIDDEN_JS:
        if token in viewer_source:
            errors.append(f"engine-check-view.js contains {token!r}; the viewer must stay read-only and build nodes via textContent")

    css = VIEWER_CSS.read_text(encoding="utf-8")
    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", css)
    if literals:
        errors.append(
            f"engine-check-view.css defines its own colours {sorted(set(literals))}; "
            "every colour must come from a shared token so the host theme stays authoritative")

    for path in (VIEWER_JS, HARNESS):
        node_check = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if node_check.returncode:
            errors.append(f"{path.name} failed node --check: {node_check.stderr.strip()}")

    # --- real renders ------------------------------------------------------
    run = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if run.returncode:
        errors.append(f"render harness failed: {run.stderr.strip() or run.stdout.strip()}")
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} engine-check viewer violation(s).")
        return 1

    report = json.loads(run.stdout)
    by_id = {item["fixture_id"]: item for item in fixtures}

    if list(report["outcomes"]) != OUTCOME_ORDER:
        errors.append(f"viewer declares outcomes {report['outcomes']}; it must cover exactly the engine-check.v1 vocabulary")

    for rendered in report["rendered"]:
        fixture_id = rendered["fixture_id"]
        check = by_id[fixture_id]["check"]
        tree = rendered["tree"]
        text = text_of(tree)
        prefix = f"render {fixture_id}"

        if tree["dataset"].get("outcome") != check["outcome"]:
            errors.append(f"{prefix}: root does not carry data-outcome={check['outcome']!r}")
        if f"ecv-outcome-{check['outcome']}" not in tree["class"]:
            errors.append(f"{prefix}: root is missing the outcome class")

        # Invariant 2: the authority triple and the coverage limits, every time.
        for field, value in check["authority"].items():
            if f"{field}: {value}" not in text:
                errors.append(f"{prefix}: authority {field}={value!r} is not shown")
        if check["coverage"]["id"] not in text:
            errors.append(f"{prefix}: coverage id {check['coverage']['id']!r} is not shown")
        for label, key in (("Complete game", "complete_game"), ("Complete legality", "complete_legality")):
            stated = "yes" if check["coverage"][key] else "no"
            if f"{label}: {stated}" not in text:
                errors.append(f"{prefix}: coverage must state {label}: {stated}")
        for scope_key in ("supported_scope", "unsupported_scope"):
            for entry in check["coverage"].get(scope_key, []):
                if entry not in text:
                    errors.append(f"{prefix}: coverage {scope_key} entry {entry!r} is not shown")
        for locator in check.get("rule_locators", []):
            if locator not in text:
                errors.append(f"{prefix}: rule locator {locator!r} is not shown")
        for missing in check.get("missing_information", []):
            if missing not in text:
                errors.append(f"{prefix}: missing_information {missing!r} is not shown")
        for assumption in check.get("assumptions", []):
            if assumption not in text:
                errors.append(f"{prefix}: assumption {assumption!r} is not shown")

        # Invariant 3 (and 1's mechanism): nothing clickable anywhere.
        for node in walk(tree):
            if node["tag"] in INTERACTIVE_TAGS:
                errors.append(f"{prefix}: renders interactive <{node['tag']}>; the viewer is read-only")

        # Bilingual: the demos default to zh-Hant, so the zh path must be real.
        zh_text = text_of(rendered["tree_zh"])
        if not any("一" <= ch <= "鿿" for ch in zh_text):
            errors.append(f"{prefix}: zh-Hant render produced no Traditional Chinese text")

    # Invariant 1: decision_required presents, never decides.
    decision = next((item for item in report["rendered"] if item["outcome"] == "decision_required"), None)
    if decision is None:
        errors.append("no decision_required render was produced")
    else:
        text = text_of(decision["tree"]).lower()
        zh_text = text_of(decision["tree_zh"])
        for word in CHOOSING_WORDS:
            if word in text:
                errors.append(f"decision_required render contains choosing language {word!r}; it must present options neutrally")
        required = by_id["decision_required"]["check"]["decision_required"]
        for key in ("kind", "controller", "decision_schema"):
            if str(required[key]).lower() not in text:
                errors.append(f"decision_required render omits {key}={required[key]!r}")
        for event_id in required.get("event_ids", []):
            if event_id.lower() not in text:
                errors.append(f"decision_required render omits pending event {event_id!r}")
        if "不會替" not in zh_text:
            errors.append("decision_required zh render does not say that the viewer makes no decision")

    # Degenerate input renders an explanation instead of throwing.
    for case in report["degenerate"]:
        if "engine-check.v1" not in text_of(case["tree"]):
            errors.append(f"degenerate input {case['label']!r} did not render the not-an-engine-check explanation")

    # mount() replaces; a stale check must not linger beside a new one.
    if report["mounted"]["child_count"] != 1:
        errors.append(f"mount() left {report['mounted']['child_count']} children; it must replace the container contents")

    print(f"[info] engine-check viewer: {len(fixtures)} engine-generated fixtures, "
          f"{len(OUTCOME_ORDER)} outcomes, rendered in zh-Hant and English, read-only and non-deciding.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} engine-check viewer violation(s).")
        return 1
    print("\nOK: shared engine-check viewer renders every outcome without widening, choosing, or mutating.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
