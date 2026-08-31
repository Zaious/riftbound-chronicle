#!/usr/bin/env python3
"""Validate the shared visual shell and bilingual contract across all demos."""

from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOTYPE = REPO_ROOT / "prototype"
SHARED_THEME = PROTOTYPE / "shared" / "theme.css"
SHARED_I18N = PROTOTYPE / "shared" / "i18n.js"
SYSTEMS = {
    "deck-coach": "deck-coach",
    "rule-consult": "rule-consult",
    "p2a": "player2-agent",
}
PALETTE = {"#0d0808", "#161011", "#392524", "#c59a5c", "#bd4848", "#ededed", "#a1a1aa"}


class ShellParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html_attrs = {}
        self.ids = set()
        self.stylesheets = []
        self.scripts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            self.html_attrs = values
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values.get("href"))
        if tag == "script" and values.get("src"):
            self.scripts.append(values.get("src"))
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])


def asset_order_errors(scripts, stylesheets):
    """Shared loading-order contract for every demo page.

    Stated as an order rather than an exact list so a page can adopt a shared
    component (the engine-check viewer was the first) without the contract
    having to be rewritten each time. What must not drift is the order: the
    host's own layout first, then the shared theme, then shared component
    styles; and the shared runtime before any shared component, with the
    page's own app.js last so it can use what the others defined.
    """
    errors = []
    if stylesheets[:2] != ["styles.css", "../shared/theme.css"]:
        errors.append(f"expected local layout followed by shared theme, got {stylesheets}")
    for extra in stylesheets[2:]:
        if not (extra.startswith("../shared/") and extra.endswith(".css")):
            errors.append(f"extra stylesheet {extra!r} must be a shared component style under ../shared/")
    if not scripts or scripts[0] != "../shared/i18n.js" or scripts[-1] != "app.js":
        errors.append(f"expected shared i18n first and local app.js last, got {scripts}")
    for extra in scripts[1:-1]:
        if not (extra.startswith("../shared/") and extra.endswith(".js")):
            errors.append(f"extra script {extra!r} must be a shared component under ../shared/")
    return errors


def main() -> int:
    errors = []
    if not SHARED_THEME.is_file():
        errors.append("missing prototype/shared/theme.css")
    if not SHARED_I18N.is_file():
        errors.append("missing prototype/shared/i18n.js")
    if errors:
        print("\n".join(f"  - {error}" for error in errors))
        return 1

    theme = SHARED_THEME.read_text(encoding="utf-8").lower()
    i18n = SHARED_I18N.read_text(encoding="utf-8")
    missing_palette = sorted(PALETTE - set(re.findall(r"#[0-9a-f]{6}", theme)))
    if missing_palette:
        errors.append(f"shared theme is missing RiftBoundC palette tokens: {missing_palette}")
    for token in ("--rc-bg", "--rc-card", "--rc-border", "--rc-gold", "--rc-red", ".language-toggle", ".topbar", "1560px"):
        if token not in theme:
            errors.append(f"shared theme is missing shell token {token!r}")
    for token in ('let locale = "zh-Hant"', "MutationObserver", "rc:localechange", "Switch to English", "切換為繁體中文"):
        if token not in i18n:
            errors.append(f"shared i18n is missing bilingual behavior {token!r}")
    for forbidden in ("localStorage", "sessionStorage", "fetch("):
        if forbidden in i18n:
            errors.append(f"shared i18n contains forbidden runtime behavior: {forbidden}")

    for folder, system in SYSTEMS.items():
        path = PROTOTYPE / folder / "index.html"
        html = path.read_text(encoding="utf-8")
        parser = ShellParser()
        parser.feed(html)
        if parser.html_attrs.get("lang") != "zh-Hant":
            errors.append(f"{folder}: default document language must be zh-Hant")
        if parser.html_attrs.get("data-system") != system:
            errors.append(f"{folder}: data-system must be {system!r}")
        if "language-toggle" not in parser.ids:
            errors.append(f"{folder}: missing language toggle")
        errors.extend(f"{folder}: {error}" for error in asset_order_errors(parser.scripts, parser.stylesheets))
        for href in ("../deck-coach/index.html", "../rule-consult/index.html", "../p2a/index.html"):
            own_href = "#top" if href.startswith(f"../{folder}/") else href
            if own_href not in parser.links:
                errors.append(f"{folder}: three-system navigation is missing {own_href!r}")
        for required in ("符文戰場編年史", "Riftbound Chronicle · Assistant Lab", "topbar-actions"):
            if required not in html:
                errors.append(f"{folder}: shared brand shell is missing {required!r}")
        if not re.search(r"<title>.*[\u4e00-\u9fff].*[A-Za-z].*</title>", html):
            errors.append(f"{folder}: document title is not visibly bilingual")

    node = subprocess.run(["node", "--check", str(SHARED_I18N)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if node.returncode:
        errors.append(f"shared i18n failed node --check: {node.stderr.strip()}")

    print(f"[info] shared shell: {len(SYSTEMS)} demos; {len(PALETTE)} site palette anchors; default zh-Hant with English toggle.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} shared UI contract violation(s).")
        return 1
    print("\nOK: all demos share the RiftBoundC visual shell and bilingual runtime.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
