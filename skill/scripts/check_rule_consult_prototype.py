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
    if parser.scripts != ["app.js"]:
        errors.append(f"expected exactly one local script app.js, got {parser.scripts}")
    if parser.stylesheets != ["styles.css"]:
        errors.append(f"expected exactly one local stylesheet styles.css, got {parser.stylesheets}")

    required_copy = [
        "Unofficial",
        "No state effect",
        "never becomes an official ruling or changes a game state",
        "Community rulings",
        "Head Judge",
        "Riot Games does not endorse or sponsor this project",
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
