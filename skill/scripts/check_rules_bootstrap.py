#!/usr/bin/env python3
"""Check the local-rule bootstrap contract without downloading source PDFs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skill"
MANIFEST = SKILL_DIR / "data" / "rules_manifest.json"
SCRIPT = SKILL_DIR / "scripts" / "bootstrap_rules.py"


def main() -> int:
    errors = []
    if not MANIFEST.is_file() or not SCRIPT.is_file():
        errors.append("rules manifest or bootstrap script is missing")
        print("\n".join(errors))
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    documents = manifest.get("documents", [])
    if {item.get("document_id") for item in documents} != {"core-rules", "tournament-rules"}:
        errors.append("manifest must contain exactly Core Rules and Tournament Rules")
    for item in documents:
        for field in ("filename", "title", "version", "url", "source_page"):
            if not item.get(field):
                errors.append(f"{item.get('document_id', 'unknown')}: missing {field}")
        if not item.get("url", "").lower().endswith(".pdf"):
            errors.append(f"{item.get('document_id', 'unknown')}: source URL is not a PDF")
        if item.get("source_page") != "https://playriftbound.com/en-us/rules-hub/":
            errors.append(f"{item.get('document_id', 'unknown')}: source page must be the official Rules Hub")
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    if "skill/.local/rules/" not in gitignore:
        errors.append(".gitignore does not exclude skill/.local/rules/")
    if "--yes" not in SCRIPT.read_text(encoding="utf-8") or "RIFTBOUND_RULES_DIR" not in SCRIPT.read_text(encoding="utf-8"):
        errors.append("bootstrap script lacks explicit confirmation or configurable destination")
    result = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPT)], capture_output=True, text=True)
    if result.returncode:
        errors.append(f"bootstrap script does not compile: {result.stderr.strip()}")
    print(f"[info] rules manifest: {len(documents)} official documents; PDFs intentionally absent from repository.")
    if errors:
        print("\n[errors]")
        print("\n".join(f"  - {error}" for error in errors))
        return 1
    print("\nOK: local Core + Tournament rule bootstrap is explicit, ignored, and source-pinned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
