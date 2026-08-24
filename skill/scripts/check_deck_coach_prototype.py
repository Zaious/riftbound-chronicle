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


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOTYPE = REPO_ROOT / "prototype" / "deck-coach"
HTML = PROTOTYPE / "index.html"
JS = PROTOTYPE / "app.js"
CSS = PROTOTYPE / "styles.css"
SCHEMA = REPO_ROOT / "skill" / "schemas" / "deck-coach-session.schema.json"
ROLES = REPO_ROOT / "skill" / "data" / "deck_coach_roles.json"
REQUIRED_IDS = {"context-form", "deck-form", "diagnosis-form", "primer-form", "role-coverage", "pipeline-import", "pipeline-summary", "copy-brief", "record", "export-json", "export-md", "reset"}
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
    if parser.scripts != ["app.js"] or parser.stylesheets != ["styles.css"]:
        errors.append("prototype must reference exactly local app.js and styles.css")
    for asset in parser.scripts + parser.stylesheets:
        if not (PROTOTYPE / asset).is_file():
            errors.append(f"missing local asset: {asset}")
    for token, meaning in FORBIDDEN.items():
        if token in js:
            errors.append(f"app.js contains forbidden {meaning}: {token}")
    for phrase in ("Role coverage", "not a score", "Closed-loop results", "does not recompute card data", "No rate analysis", "No game-state operations", "Riot Games does not endorse or sponsor this project"):
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
