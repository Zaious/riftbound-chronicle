#!/usr/bin/env python3
"""Check the grouped local-rule bootstrap contract without downloading PDFs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skill"
MANIFEST = SKILL_DIR / "data" / "rules_manifest.json"
REGISTRY = SKILL_DIR / "data" / "rules_source_registry.json"
SCRIPT = SKILL_DIR / "scripts" / "bootstrap_rules.py"
INDEX_SCRIPT = SKILL_DIR / "scripts" / "rules_index.py"


def main() -> int:
    errors = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source_ids = {item["source_id"] for item in registry["sources"]}
    groups = set(manifest.get("groups", {}))
    documents = manifest.get("documents", [])
    if manifest.get("schema_version") != "riftbound-local-rules-manifest.v2":
        errors.append("manifest must use v2 grouped contract")
    if set(manifest.get("default_groups", [])) != {"core-en"}:
        errors.append("default install must remain the controlling English pair")
    if not {"core-en", "supplemental-en", "zh-cn"}.issubset(groups):
        errors.append("manifest lacks required install groups")
    if {item["document_id"] for item in documents if item["install_group"] == "core-en"} != {"core-rules", "tournament-rules"}:
        errors.append("core-en must contain exactly Core and Tournament Rules")
    if len([item for item in documents if item["install_group"] == "zh-cn"]) < 11:
        errors.append("zh-cn pack must include rules, ban list, errata, official FAQs, and judge FAQs")
    seen_paths = set()
    for item in documents:
        required = {
            "document_id", "source_id", "install_group", "relative_path", "title", "version",
            "locale", "region", "document_class", "status", "superseded_by", "url", "source_page", "required",
        }
        if missing := required - set(item):
            errors.append(f"{item.get('document_id', 'unknown')}: missing {sorted(missing)}")
        if item.get("source_id") not in source_ids:
            errors.append(f"{item.get('document_id')}: source_id not in registry")
        if item.get("install_group") not in groups:
            errors.append(f"{item.get('document_id')}: unknown install group")
        if item.get("relative_path") in seen_paths:
            errors.append(f"duplicate relative_path: {item.get('relative_path')}")
        seen_paths.add(item.get("relative_path"))
        if not item.get("url", "").startswith("https://") or ".pdf" not in item.get("url", "").lower():
            errors.append(f"{item.get('document_id')}: source URL is not an HTTPS PDF")
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    if "skill/.local/rules/" not in gitignore:
        errors.append(".gitignore does not exclude skill/.local/rules/")
    bootstrap_text = SCRIPT.read_text(encoding="utf-8")
    for marker in ("--yes", "RIFTBOUND_RULES_DIR", "--include-zh-cn", "--include-supplemental-en"):
        if marker not in bootstrap_text:
            errors.append(f"bootstrap script lacks {marker}")
    for candidate in (SCRIPT, INDEX_SCRIPT):
        result = subprocess.run([sys.executable, "-m", "py_compile", str(candidate)], capture_output=True, text=True)
        if result.returncode:
            errors.append(f"{candidate.name} does not compile: {result.stderr.strip()}")
    print(f"[info] rules manifest: {len(documents)} documents across {len(groups)} opt-in groups; PDFs and index stay local.")
    if errors:
        print("\n[errors]")
        print("\n".join(f"  - {error}" for error in errors))
        return 1
    print("\nOK: grouped English/zh-CN bootstrap is explicit, ignored, source-linked, and index-ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
