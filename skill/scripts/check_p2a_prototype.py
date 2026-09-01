#!/usr/bin/env python3
"""Validate the no-build P2-A application-flow prototype.

This is intentionally a static contract check, not a browser screenshot test.
It verifies that the visible prototype exposes the required human-confirmed
workflow, keeps its DOM identifiers coherent, ships valid JavaScript, and
does not introduce network/model calls or browser persistence behind the
manual Agent bridge.
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_prototype_ui import asset_order_errors  # noqa: E402
from p2a_session import VERIFICATION_REQUIREMENTS, validate_session, verification_requirement  # noqa: E402

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
    "language-toggle",
    "engine-select",
    "attach-check",
    "engine-check-view",
    "engine-count",
    "verification-requirement",
    "requirement-value",
    "requirement-explanation",
    "verification-demand",
}
FIXTURES = REPO_ROOT / "prototype" / "shared" / "engine-check-fixtures.js"
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
    errors.extend(asset_order_errors(parser.scripts, parser.stylesheets))

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
        # The engine panel's boundary, in the order it has to be read: evidence
        # not a ruling, attaching nothing raises the burden, no engine state is
        # accepted or stored, and a non-standard requirement demands a written
        # verification summary before a legal confirmation.
        "Optional evidence, never a ruling",
        "attaching nothing raises that burden rather than lowering it",
        "accepts no engine state, and stores no raw engine result",
        "Verification summary required",
    ]
    for phrase in required_copy:
        if phrase not in html:
            errors.append(f"prototype is missing required visible boundary copy: {phrase!r}")

    if html.count('href="../rule-consult/index.html"') < 2:
        errors.append("prototype must expose both system-nav and workflow links to Rule Consult")
    if 'href="../rule-consult/index.html" target="_blank" rel="noreferrer"' not in html:
        errors.append("Rule Consult integration must open separately to preserve in-tab P2-A state")

    # Every id app.js reaches for must exist in the page. A static contract
    # check otherwise passes a panel whose controls are never wired, because
    # nothing here opens a browser.
    for selector in sorted(set(re.findall(r'\$\("#([a-z0-9-]+)"\)', js))):
        if selector not in set(parser.ids):
            errors.append(f"app.js queries #{selector}, which the page does not define")

    # --- the engine panel ---------------------------------------------------
    # The shared viewer, not a local renderer: one outcome must not acquire a
    # different meaning here than it has in Rule Consult.
    if "RC_ENGINE_CHECK_VIEW.mount" not in js:
        errors.append("app.js does not render engine checks through the shared read-only viewer")
    # The viewer writes its bilingual text at mount time, so the shared runtime
    # cannot retranslate it afterwards.
    if "rc:localechange" not in js:
        errors.append("app.js does not re-render on a locale change, so the panel would not follow the language toggle")
    if "raw_result" not in js:
        errors.append("app.js does not refuse a check carrying raw_result at the P2-A information boundary")
    for forbidden in ("next_state", "input_state_hash", "proposed_state"):
        if re.search(rf"\b{forbidden}\b", js):
            errors.append(f"app.js reads engine state field {forbidden!r}; P2-A displays no engine state")

    # The JS ladder and p2a_session.verification_requirement must agree on every
    # combination of outcomes, not just the ones a fixture happens to produce.
    # Two implementations of one rule in two languages drift silently otherwise.
    ladder = re.findall(r'outcomes\.has\("([a-z_]+)"\)\) return "([a-z_]+)"', js)
    if not ladder:
        errors.append("app.js has no verification-requirement ladder to compare against p2a_session")
    else:
        empty_default = re.search(r'outcomes\.size === 0 \|\| outcomes\.has\("unsupported"\)\) return "([a-z_]+)"', js)
        final_default = re.search(r'return "([a-z_]+)";\s*\n\s*\}', js)

        def js_requirement(outcomes):
            for outcome, requirement in ladder:
                if outcome in outcomes:
                    return requirement
            if empty_default and (not outcomes or "unsupported" in outcomes):
                return empty_default.group(1)
            return final_default.group(1) if final_default else None

        outcomes_vocabulary = ["supported", "illegal", "unsupported", "decision_required", "invalid_input"]
        for size in range(0, len(outcomes_vocabulary) + 1):
            for combination in itertools.combinations(outcomes_vocabulary, size):
                expected = verification_requirement([{"outcome": outcome} for outcome in combination])
                actual = js_requirement(set(combination))
                if actual != expected:
                    errors.append(f"app.js maps outcomes {sorted(combination)} to {actual!r}; p2a_session says {expected!r}")
        if {requirement for _, requirement in ladder} | {empty_default.group(1) if empty_default else None,
                                                        final_default.group(1) if final_default else None} != VERIFICATION_REQUIREMENTS:
            errors.append("app.js does not present all five verification requirements")

    # Every outcome needs a UI fixture, and the panel must be able to reach it.
    fixtures_js = FIXTURES.read_text(encoding="utf-8")
    payload = json.loads(fixtures_js[fixtures_js.index("Object.freeze(") + len("Object.freeze("):fixtures_js.rindex(");")])
    fixture_checks = [item["check"] for item in payload["fixtures"]]
    fixture_outcomes = {check["outcome"] for check in fixture_checks}
    if fixture_outcomes != set(outcomes_vocabulary):
        errors.append(f"the shared fixtures cover {sorted(fixture_outcomes)}; the panel needs one per outcome")
    for check in fixture_checks:
        if "raw_result" in check:
            errors.append(f"fixture {check['check_id']} carries raw_result and could not be attached")

    # End to end: what the page exports must satisfy the real validator, for
    # every outcome and for the no-evidence case, with the requirement the
    # runner derives -- otherwise the UI records something P2-A rejects.
    def session_with(engine_checks, *, confirm_legal=None, summary=""):
        events = [
            {"seq": 1, "type": "state_confirmed", "recorded_at": "2026-09-01T00:00:01Z",
             "authority": "user_confirmed", "confirmed_by": "operator", "turn": 3,
             "turn_player": "Player 1", "phase": "main", "public_state": "as read at the table",
             "player2_private_hand": "", "notes": ""},
            {"seq": 2, "type": "action_proposed", "recorded_at": "2026-09-01T00:00:02Z",
             "action_id": "p2-001", "state_seq": 1, "objective": "contest",
             "description": "play a unit", "reason": "pressure", "alternative": "hold",
             "assumptions": [], "legality_status": "unverified",
             "engine_checks": engine_checks,
             "verification_requirement": verification_requirement(engine_checks)},
        ]
        if confirm_legal is not None:
            events.append({"seq": 3, "type": "action_confirmed", "recorded_at": "2026-09-01T00:00:03Z",
                           "action_id": "p2-001", "legal": confirm_legal, "confirmed_by": "operator",
                           "resolution_summary": summary,
                           "state_transition": "pending_user_snapshot" if confirm_legal else "none"})
        return {"schema_version": "p2a-session.v1", "mode": "player2-agent", "automation_level": "P2-A",
                "p2s_enabled": False, "state_authority": "user_confirmed",
                "legality_authority": "user_confirmed",
                "session_id": "11111111-2222-3333-4444-555555555555",
                "created_at": "2026-09-01T00:00:00Z", "created_by": "operator",
                "format": "1v1 Constructed", "ruleset_version": "2026-07-16",
                "decks": {"player1": "unknown", "player2": "Rengar"}, "events": events}

    for check in fixture_checks + [None]:
        attached = [] if check is None else [check]
        label = "no attached check" if check is None else check["outcome"]
        found = validate_session(session_with(attached))
        if found:
            errors.append(f"a session recorded from this page with {label} does not validate: {found}")

    illegal = next((check for check in fixture_checks if check["outcome"] == "illegal"), None)
    if illegal is not None:
        # illegal must remain overridable by a human against an official source,
        # and that override must leave a record.
        if not validate_session(session_with([illegal], confirm_legal=True, summary="Read Core 358.4; the table agreed.")):
            pass
        else:
            errors.append("a documented human override of an illegal check was rejected by the validator")
        if not validate_session(session_with([illegal], confirm_legal=True)):
            errors.append("an undocumented human override of an illegal check was accepted; the summary is not enforced")

    for token in ("standard_human_confirmation", "!values.resolution.trim()"):
        if token not in js:
            errors.append(f"app.js does not gate the verification summary on the recorded requirement ({token!r} missing)")

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
