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


# Text the shared runtime is not expected to translate, each for a stated
# reason. Anything not listed here must have a zh-Hant rendering.
UNTRANSLATED_BY_DESIGN = {
    # Required verbatim in all three demos by the brand-shell assertion below.
    "Riftbound Chronicle · Assistant Lab",
    # Project vocabulary the Chinese prose itself keeps in English: i18n.js
    # renders these as "Tier 1／Tier 2／Tier 3" and "Tier 排名".
    "Tier 1", "Tier 2", "Tier 3",
    # p2a-session.v1 verification_requirement values. These are shown verbatim
    # because they are exactly what the exported artifact records; a translated
    # label beside a different token in the JSON would be worse than English.
    # The sentence explaining each one is translated.
    "standard_human_confirmation", "heightened_manual_verification",
    "controller_decision_and_recheck", "input_repair_and_recheck",
    "official_source_review_before_override",
}


def visible_english(html: str) -> set[str]:
    """Visible text nodes that are English prose, not markup or Chinese copy."""
    body = html.split("<body>", 1)[-1]
    body = re.sub(r"<(script|style)\b.*?</\1>", "", body, flags=re.S)
    texts = {item.strip() for item in re.split(r"<[^>]+>", body) if item.strip()}
    return {item for item in texts
            if re.search(r"[A-Za-z]{3}", item) and not re.search(r"[一-鿿]", item)}


def has_translation(text: str, i18n: str) -> bool:
    """Mirror i18n.js: dictionary key, numbered heading, or regex pattern.

    Every rule is read out of i18n.js rather than reimplemented from memory. A
    checker that knows a fallback the runtime has lost passes a page that
    renders in English, which is the failure it exists to catch.
    """
    if f'"{text}":' in i18n:
        return True
    numbered = re.fullmatch(r"(\d+)\.\s+(.+)", text)
    if numbered and r"/^(\d+)\.\s+(.+)$/" in i18n and f'"{numbered.group(2)}":' in i18n:
        return True
    for pattern in re.findall(r"\[/\^(.+?)\$/", i18n):
        try:
            if re.fullmatch(pattern, text):
                return True
        except re.error:
            continue
    return False


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

        # The demos default to zh-Hant, so English copy with no rendering fails
        # nowhere -- it just silently shows in English on a Chinese page. Once
        # something looked, every demo had some: the whole eight-part primer
        # heading list, a judge-prep card, and two footer lines.
        for text in sorted(visible_english(html) - UNTRANSLATED_BY_DESIGN):
            if not has_translation(text, i18n):
                errors.append(f"{folder}: visible copy has no zh-Hant rendering in shared/i18n.js: {text[:60]!r}")

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
