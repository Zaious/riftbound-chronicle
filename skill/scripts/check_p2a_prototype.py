#!/usr/bin/env python3
"""Validate the no-build P2-A application-flow prototype.

This is intentionally a static contract check, not a browser screenshot test.
It verifies that the visible prototype exposes the required human-confirmed
workflow, keeps its DOM identifiers coherent, ships valid JavaScript, and
does not introduce network/model calls or browser persistence behind the
manual Agent bridge.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOTYPE = REPO_ROOT / "prototype" / "p2a"
HTML = PROTOTYPE / "index.html"
JS = PROTOTYPE / "app.js"
CSS = PROTOTYPE / "styles.css"
SCHEMA = REPO_ROOT / "skill" / "schemas" / "p2a-session.schema.json"

REQUIRED_IDS = {
    "session-form",
    "state-form",
    "proposal-form",
    "confirmation-form",
    "copy-brief",
    "proposal-select",
    "ledger",
    "export-session",
    "reset-session",
    "status-banner",
}
REQUIRED_EVENT_TYPES = {"state_confirmed", "action_proposed", "action_confirmed"}
FORBIDDEN_NETWORK_OR_STORAGE = {
    "fetch(": "network request",
    "XMLHttpRequest": "network request",
    "WebSocket": "network connection",
    "EventSource": "network connection",
    "RTCPeerConnection": "peer connection",
    "localStorage": "persistent browser storage",
    "sessionStorage": "persistent browser storage",
}
FORBIDDEN_HIDDEN_FIELD_NAMES = {
    "player1Hand",
    "player1PrivateHand",
    "opponentHand",
    "opponentPrivateHand",
    "deckOrder",
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
    for path in (HTML, JS, CSS, SCHEMA):
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

    hidden_fields = sorted(FORBIDDEN_HIDDEN_FIELD_NAMES & set(parser.names))
    if hidden_fields:
        errors.append(f"prototype exposes forbidden Player 1/opponent hidden fields: {hidden_fields}")
    if "player2Hand" not in parser.names:
        errors.append("prototype has no Player 2 private-hand field")

    required_copy = [
        "Human authority",
        "P2-S off",
        "Legality: unverified",
        "No shuffle, draw, phase advance",
        "Riot Games does not endorse or sponsor this project",
        "Rule Consult opens separately and cannot read or write this session",
    ]
    for phrase in required_copy:
        if phrase not in html:
            errors.append(f"prototype is missing required visible boundary copy: {phrase!r}")

    if html.count('href="../rule-consult/index.html"') < 2:
        errors.append("prototype must expose both system-nav and workflow links to Rule Consult")
    if 'href="../rule-consult/index.html" target="_blank" rel="noreferrer"' not in html:
        errors.append("Rule Consult integration must open separately to preserve in-tab P2-A state")

    for token, meaning in FORBIDDEN_NETWORK_OR_STORAGE.items():
        if token in js:
            errors.append(f"app.js contains forbidden {meaning}: {token}")

    for event_type in REQUIRED_EVENT_TYPES:
        if event_type not in js:
            errors.append(f"app.js never emits required event type {event_type!r}")

    schema_constants = {
        "schema_version": schema["properties"]["schema_version"]["const"],
        "mode": schema["properties"]["mode"]["const"],
        "automation_level": schema["properties"]["automation_level"]["const"],
        "state_authority": schema["properties"]["state_authority"]["const"],
        "legality_authority": schema["properties"]["legality_authority"]["const"],
    }
    for field, value in schema_constants.items():
        pattern = rf"{re.escape(field)}\s*:\s*[\"']{re.escape(value)}[\"']"
        if not re.search(pattern, js):
            errors.append(f"app.js does not match schema constant {field}={value!r}")
    if not re.search(r"p2s_enabled\s*:\s*false", js):
        errors.append("app.js must hard-code p2s_enabled: false")

    if "state_seq: latestState().seq" not in js:
        errors.append("Agent proposals are not visibly bound to the latest confirmed state")
    if 'state_transition: legal ? "pending_user_snapshot" : "none"' not in js:
        errors.append("human confirmation does not preserve the pending-user-snapshot boundary")
    if "@media (max-width: 760px)" not in css:
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
        f"{len(js.splitlines())} JS lines, {len(css.splitlines())} CSS lines."
    )
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} P2-A prototype contract violation(s).")
        return 1

    print("\nOK: P2-A prototype preserves the manual bridge, schema constants, local-only runtime, and responsive workflow structure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
