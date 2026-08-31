#!/usr/bin/env python3
"""Validate the static Rule Consult demonstration and its data boundary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_prototype_ui import asset_order_errors  # noqa: E402
from rule_consult import validate_consultation  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOTYPE = REPO_ROOT / "prototype" / "rule-consult"
HTML = PROTOTYPE / "index.html"
JS = PROTOTYPE / "app.js"
CSS = PROTOTYPE / "styles.css"
SCHEMA = REPO_ROOT / "skill" / "schemas" / "rule-consultation.schema.json"
REGISTRY = REPO_ROOT / "skill" / "data" / "rules_source_registry.json"

REQUIRED_IDS = {
    "question-form",
    "fact-form",
    "assumption-form",
    "source-form",
    "answer-form",
    "authority-ladder",
    "copy-brief",
    "record",
    "export",
    "reset",
    "result",
    "language-toggle",
    "engine-form",
    "engine-select",
    "engine-check-view",
    "engine-count",
}
FORBIDDEN_NETWORK_OR_STORAGE = {
    "fetch(": "network request",
    "XMLHttpRequest": "network request",
    "WebSocket": "network connection",
    "EventSource": "network connection",
    "RTCPeerConnection": "peer connection",
    "localStorage": "persistent browser storage",
    "sessionStorage": "persistent browser storage",
}
FORBIDDEN_STATE_FIELDS = {
    "turnPlayer",
    "activePlayer",
    "currentPhase",
    "gameWinner",
    "damageTotal",
}


class PrototypeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.names = []
        self.scripts = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if "name" in values:
            self.names.append(values["name"])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(values["href"])


def first_option_value(html: str, field: str) -> str:
    """First <option value> of a named select, so samples mirror the real page."""
    block = re.search(rf'name="{re.escape(field)}"><select[^>]*>|name="{re.escape(field)}">', html)
    tail = html[block.end():] if block else html
    match = re.search(r'<option value="([^"]+)"', tail)
    return match.group(1) if match else ""


def main():
    errors = []
    for path in (HTML, JS, CSS, SCHEMA, REGISTRY):
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(REPO_ROOT)}")
    if errors:
        for error in errors:
            print(f"  - {error}")
        return 1

    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    parser = PrototypeParser()
    parser.feed(html)

    duplicate_ids = sorted(key for key, count in Counter(parser.ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate DOM ids: {duplicate_ids}")
    missing_ids = sorted(REQUIRED_IDS - set(parser.ids))
    if missing_ids:
        errors.append(f"missing required workflow ids: {missing_ids}")

    for asset in parser.scripts + parser.stylesheets:
        if not (PROTOTYPE / asset).resolve().is_file():
            errors.append(f"HTML references missing local asset: {asset}")
    errors.extend(asset_order_errors(parser.scripts, parser.stylesheets))

    required_copy = [
        "Unofficial",
        "No state effect",
        "never becomes an official ruling or changes a game state",
        "Community rulings",
        "Judge-prep handoff",
        "Head Judge",
        "Riot Games does not endorse or sponsor this project",
        # The engine-check panel's boundary, stated in the doctrine order: the
        # official source decides, the check is a consistency test beside it,
        # and abstention is not absence of an answer.
        "does not raise source confidence",
        "the component abstained",
        "This page runs no engine of its own",
    ]
    for phrase in required_copy:
        if phrase not in html:
            errors.append(f"prototype is missing required visible boundary copy: {phrase!r}")

    for token, meaning in FORBIDDEN_NETWORK_OR_STORAGE.items():
        if token in js:
            errors.append(f"app.js contains forbidden {meaning}: {token}")
    forbidden_fields = sorted(FORBIDDEN_STATE_FIELDS & set(parser.names))
    if forbidden_fields:
        errors.append(f"prototype exposes forbidden game-state fields: {forbidden_fields}")

    constants = {
        "schema_version": schema["properties"]["schema_version"]["const"],
        "mode": schema["properties"]["mode"]["const"],
        "official_status": schema["properties"]["official_status"]["const"],
        "state_effect": schema["properties"]["state_effect"]["const"],
    }
    for field, value in constants.items():
        pattern = rf"{re.escape(field)}\s*:\s*[\"']{re.escape(value)}[\"']"
        if not re.search(pattern, js):
            errors.append(f"app.js does not match schema constant {field}={value!r}")

    registry_ids = {source["source_id"] for source in registry["sources"]}
    js_source_ids = set(re.findall(r'source_id:\s*"([^"]+)"', js))
    if js_source_ids != registry_ids:
        errors.append(
            "prototype source mirror differs from registry: "
            f"missing={sorted(registry_ids - js_source_ids)}, extra={sorted(js_source_ids - registry_ids)}"
        )

    required_guards = [
        "High confidence is blocked while a material assumption remains.",
        "High confidence requires an official source.",
        "A source conflict cannot finalize at High confidence.",
        "Unofficial consultation finalized with no state effect.",
    ]
    for guard in required_guards:
        if guard not in js:
            errors.append(f"app.js is missing confidence/state guard: {guard!r}")

    # The check must be presented by the shared read-only viewer. A local
    # renderer here would be the start of three systems describing the same
    # outcome three different ways.
    if "RC_ENGINE_CHECK_VIEW.mount" not in js:
        errors.append("app.js does not render engine checks through the shared read-only viewer")
    if "engine_checks:[]" not in js.replace(" ", ""):
        errors.append("app.js does not initialize the schema's engine_checks array, so exports would omit attached checks")
    # Source confidence and engine coverage must stay separate fields: a
    # `supported` check does not raise confidence, and an `unsupported` one does
    # not lower it. Any expression joining the two would encode the opposite.
    # Quoted copy is removed first, so the guard reads code: the panel's own
    # text has to be able to say what the check does not do.
    js_code = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "", js)
    for pattern in (r"outcome[^;\n]{0,80}confidence", r"confidence[^;\n]{0,80}outcome"):
        for hit in re.findall(pattern, js_code):
            errors.append(f"app.js ties an engine outcome to source confidence: {hit!r}")

    # End to end: a consultation carrying a real envelope must still validate,
    # which is what makes this a wired consumer rather than a rendered demo.
    fixtures_js = (REPO_ROOT / "prototype" / "shared" / "engine-check-fixtures.js").read_text(encoding="utf-8")
    payload = json.loads(fixtures_js[fixtures_js.index("Object.freeze(") + len("Object.freeze("):fixtures_js.rindex(");")])
    sample = {
        "schema_version": constants["schema_version"], "mode": constants["mode"],
        "official_status": constants["official_status"], "state_effect": constants["state_effect"],
        "consultation_id": "11111111-2222-3333-4444-555555555555",
        "created_at": "2026-08-01T00:00:00Z", "created_by": "prototype-contract-check",
        "status": "draft", "question_type": first_option_value(html, "questionType"),
        "question": "Does the attached engine check validate inside a consultation?",
        "format": "standard", "ruleset_as_of": "2026-07-16",
        "facts": [{"text": "Both units are on the same battlefield.", "origin": first_option_value(html, "origin")}],
        "assumptions": [], "sources": [], "answer": None,
        "engine_checks": [item["check"] for item in payload["fixtures"]],
    }
    consultation_errors = validate_consultation(sample)
    if consultation_errors:
        errors.append(f"a consultation carrying the prototype's engine checks does not validate: {consultation_errors}")

    if "@media(max-width:760px)" not in css.replace(" ", ""):
        errors.append("styles.css has no narrow-screen layout contract")
    if "prefers-reduced-motion" not in css:
        errors.append("styles.css has no reduced-motion accommodation")

    node_check = subprocess.run(
        ["node", "--check", str(JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if node_check.returncode:
        errors.append(f"app.js failed node --check: {node_check.stderr.strip()}")

    print(
        f"[info] prototype: {len(parser.ids)} DOM ids, {len(parser.names)} named controls, "
        f"{len(registry_ids)} mirrored sources."
    )
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} Rule Consult prototype contract violation(s).")
        return 1

    print("\nOK: Rule Consult remains cited, unofficial, local-only, non-stateful, and schema-aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
