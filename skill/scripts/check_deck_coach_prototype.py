#!/usr/bin/env python3
"""Validate the static Deck Coach demonstration against its contracts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_behavior_coverage_fixtures import build_fixtures, render_module  # noqa: E402
from check_prototype_ui import asset_order_errors  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOTYPE = REPO_ROOT / "prototype" / "deck-coach"
HTML = PROTOTYPE / "index.html"
JS = PROTOTYPE / "app.js"
CSS = PROTOTYPE / "styles.css"
SCHEMA = REPO_ROOT / "skill" / "schemas" / "deck-coach-session.schema.json"
ROLES = REPO_ROOT / "skill" / "data" / "deck_coach_roles.json"
REQUIRED_IDS = {"context-form", "deck-form", "diagnosis-form", "primer-form", "role-coverage", "pipeline-import", "pipeline-summary", "copy-brief", "record", "export-json", "export-md", "reset", "language-toggle", "coverage-status", "coverage-explanation", "coverage-counts", "coverage-cards", "coverage-warnings", "coverage-fixture"}
COVERAGE_STATUSES = {"unavailable", "available", "stale", "incompatible"}
COVERAGE_COUNTS = {"full", "partial", "unsupported", "stale", "uncovered"}
FIXTURES = REPO_ROOT / "prototype" / "shared" / "behavior-coverage-fixtures.js"
# Claims the panel must never make. Coverage is a count of executable clause
# support; it is not evidence about how the deck should be piloted.
FORBIDDEN_COVERAGE_CLAIMS = (
    "coverage score", "coverage rating", "well covered deck", "better deck",
    "recommended because", "coverage suggests", "therefore keep",
)
FORBIDDEN = {"fetch(": "network request", "XMLHttpRequest": "network request", "WebSocket": "network connection", "localStorage": "persistent storage", "sessionStorage": "persistent storage"}


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.scripts, self.stylesheets = [], [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(values["href"])


def main():
    errors = []
    for path in (HTML, JS, CSS, SCHEMA, ROLES):
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(REPO_ROOT)}")
    if errors:
        print("\n".join(f"  - {item}" for item in errors))
        return 1
    html, js, css = HTML.read_text(encoding="utf-8"), JS.read_text(encoding="utf-8"), CSS.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    roles = json.loads(ROLES.read_text(encoding="utf-8"))
    parser = Parser(); parser.feed(html)
    duplicates = sorted(key for key, count in Counter(parser.ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate DOM ids: {duplicates}")
    if missing := REQUIRED_IDS - set(parser.ids):
        errors.append(f"missing workflow ids: {sorted(missing)}")
    errors.extend(asset_order_errors(parser.scripts, parser.stylesheets))
    for asset in parser.scripts + parser.stylesheets:
        if not (PROTOTYPE / asset).is_file():
            errors.append(f"missing local asset: {asset}")
    for token, meaning in FORBIDDEN.items():
        if token in js:
            errors.append(f"app.js contains forbidden {meaning}: {token}")
    for phrase in ("Role coverage", "not a score", "Closed-loop results", "does not recompute card data", "No rate analysis", "No game-state operations", "Riot Games does not endorse or sponsor this project",
                   # The coverage panel's boundary, in the order it has to read:
                   # what the number is, what it is not, and that the previews
                   # are demonstrations rather than a shipped R3 pack.
                   "It is a coverage number, not a judgement about the deck",
                   "strategy_evidence: not_established_by_engine_coverage",
                   "says nothing about deck identity, mulligans, sequencing, lines, or mistakes",
                   "demonstration manifests, not an R3 pack"):
        if phrase not in html:
            errors.append(f"missing visible boundary copy: {phrase!r}")

    constants = {"schema_version": schema["properties"]["schema_version"]["const"], "mode": schema["properties"]["mode"]["const"]}
    for field, value in constants.items():
        if not re.search(rf'{field}\s*:\s*"{re.escape(value)}"', js):
            errors.append(f"app.js does not match schema constant {field}={value!r}")
    registry_roles = {item["role_id"] for item in roles["roles"]}
    js_roles = set(re.findall(r'role_id:"([^"]+)"', js))
    if js_roles != registry_roles:
        errors.append(f"prototype role mirror differs: missing={sorted(registry_roles-js_roles)}, extra={sorted(js_roles-registry_roles)}")
    primer_fields = schema["properties"]["primer"]["oneOf"][1]["required"]
    primer_match = re.search(r'const PRIMER=\[([^]]+)\]', js)
    js_primer = re.findall(r'"([^"]+)"', primer_match.group(1)) if primer_match else []
    if js_primer != primer_fields:
        errors.append(f"prototype primer order differs from schema: {js_primer}")
    for artifact_version in ("deck-profile.v1", "recommendation-mask.v1", "deck-coach-evaluation.v1"):
        if artifact_version not in js:
            errors.append(f"prototype cannot import closed-loop artifact {artifact_version}")
    # --- behavior coverage panel --------------------------------------------
    if "deck-behavior-coverage.v1" not in js:
        errors.append("prototype cannot import the deck-behavior-coverage.v1 artifact")
    for selector in sorted(set(re.findall(r'\$\("#([a-z0-9-]+)"\)', js))):
        if selector not in set(parser.ids):
            errors.append(f"app.js queries #{selector}, which the page does not define")

    # All four availability statuses must have their own explanation. They are
    # not interchangeable: "no pack exists" and "the pack does not apply here"
    # produce identical zeroes and mean different things about the deck.
    status_copy = set(re.findall(r"^(unavailable|available|stale|incompatible):\{zh:", js, re.M))
    if status_copy != COVERAGE_STATUSES:
        errors.append(f"app.js explains statuses {sorted(status_copy)}; all of {sorted(COVERAGE_STATUSES)} are required")
    counts_rendered = set(re.findall(r'\["(full|partial|unsupported|stale|uncovered)",', js))
    if counts_rendered != COVERAGE_COUNTS:
        errors.append(f"app.js renders copy counts {sorted(counts_rendered)}; all of {sorted(COVERAGE_COUNTS)} are required")
    if "not_established_by_engine_coverage" not in html:
        errors.append("the page does not show strategy_evidence: not_established_by_engine_coverage")
    if "rc:localechange" not in js:
        errors.append("app.js does not re-render coverage on a locale change")

    # Coverage must not leak into strategy. The panel may sit beside the
    # diagnosis and the primer; it may not feed them.
    for match in re.findall(r"[^;\n]{0,120}(?:coverageView|COVERAGE_FIXTURES)[^;\n]{0,120}", js):
        if re.search(r"review\.(primer|diagnosis)|\.decklist\s*=", match):
            errors.append(f"coverage data reaches a strategic field: {match.strip()[:90]!r}")
    js_prose = " ".join(re.findall(r'"([^"]{8,})"', js)).lower() + " " + html.lower()
    for claim in FORBIDDEN_COVERAGE_CLAIMS:
        if claim in js_prose:
            errors.append(f"the coverage panel makes a strategic claim: {claim!r}")

    # Fixtures: current, generated from the real projection, and covering every
    # status plus every non-zero count the page can display.
    if not FIXTURES.is_file():
        errors.append("missing prototype/shared/behavior-coverage-fixtures.js")
    else:
        committed = FIXTURES.read_text(encoding="utf-8")
        if committed != render_module(build_fixtures()):
            errors.append("behavior-coverage fixtures are stale; re-run build_behavior_coverage_fixtures.py and commit the diff")
        payload = json.loads(committed[committed.index("Object.freeze(") + len("Object.freeze("):committed.rindex(");")])
        coverages = [item["coverage"] for item in payload["fixtures"]]
        statuses = {coverage["status"] for coverage in coverages}
        if statuses != COVERAGE_STATUSES:
            errors.append(f"fixtures cover statuses {sorted(statuses)}; the panel must be exercised on all four")
        for key in sorted(COVERAGE_COUNTS):
            if not any(coverage["copy_weighted"][key] for coverage in coverages):
                errors.append(f"no fixture exercises a non-zero {key!r} copy count, so that counter has never rendered")
        for coverage in coverages:
            if coverage["strategy_evidence"] != "not_established_by_engine_coverage":
                errors.append("a fixture lost its strategy_evidence marker")
            counts = coverage["copy_weighted"]
            if sum(counts[key] for key in COVERAGE_COUNTS) != counts["total"]:
                errors.append(f"fixture {coverage['status']} copy counts do not sum to its total")
        if "not an R3" not in payload["note"] and "not a production" not in payload["note"]:
            errors.append("the fixture file does not state that its manifests are demonstrations, not an R3 pack")

    for link in ("../rule-consult/index.html", "../p2a/index.html"):
        if f'href="{link}"' not in html:
            errors.append(f"three-system navigation is missing {link}")
    if "@media(max-width:760px)" not in css.replace(" ", ""):
        errors.append("styles.css has no narrow-screen layout")
    if "prefers-reduced-motion" not in css:
        errors.append("styles.css has no reduced-motion accommodation")
    node = subprocess.run(["node", "--check", str(JS)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if node.returncode:
        errors.append(f"app.js failed node --check: {node.stderr.strip()}")
    print(f"[info] prototype: {len(parser.ids)} ids, {len(registry_roles)} roles, {len(js_primer)} primer sections.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} Deck Coach prototype violation(s).")
        return 1
    print("\nOK: Deck Coach prototype is local-only, qualitative, schema-aligned, and three-system connected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
