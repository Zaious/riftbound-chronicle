#!/usr/bin/env python3
"""Check the grouped local-rule bootstrap contract without downloading PDFs."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from bootstrap_rules import media_type, validate_download


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
    origins_faq = next((item for item in documents if item.get("source_id") == "origins-faq-2025-10-16"), None)
    if not origins_faq or origins_faq.get("install_group") != "supplemental-en" or origins_faq.get("status") != "superseded":
        errors.append("historical English Origins FAQ must be downloadable in supplemental-en but non-controlling")
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
        suffix = Path(item.get("relative_path", "")).suffix.casefold()
        if not item.get("url", "").startswith("https://") or suffix not in {".pdf", ".html", ".htm"}:
            errors.append(f"{item.get('document_id')}: source is not an HTTPS PDF/HTML document")
        if suffix in {".html", ".htm"} and item.get("status") != "superseded":
            errors.append(f"{item.get('document_id')}: historical HTML FAQ must not be installed as controlling")
    # Ask git whether the path is ignored, rather than looking for a literal
    # line: what matters is that a downloaded PDF cannot be committed, and any
    # pattern covering it (`skill/.local/` covers `skill/.local/rules/`) is a
    # correct answer. Matching the line text made a broader, still-correct rule
    # read as a regression.
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "skill/.local/rules/core-rules.pdf"],
        capture_output=True, text=True, check=False)
    if ignored.returncode != 0:
        errors.append("git does not ignore skill/.local/rules/; a downloaded official PDF could be committed")
    bootstrap_text = SCRIPT.read_text(encoding="utf-8")
    for marker in ("--yes", "RIFTBOUND_RULES_DIR", "--include-zh-cn", "--include-supplemental-en"):
        if marker not in bootstrap_text:
            errors.append(f"bootstrap script lacks {marker}")
    for candidate in (SCRIPT, INDEX_SCRIPT):
        result = subprocess.run([sys.executable, "-m", "py_compile", str(candidate)], capture_output=True, text=True)
        if result.returncode:
            errors.append(f"{candidate.name} does not compile: {result.stderr.strip()}")
    with tempfile.TemporaryDirectory(prefix="rules-media-") as folder:
        root = Path(folder)
        pdf = root / "rule.pdf"
        html = root / "faq.html"
        wrong = root / "wrong.pdf"
        pdf.write_bytes(b"%PDF-1.7\nfixture")
        html.write_text("<!doctype html><html><body>fixture</body></html>", encoding="utf-8")
        wrong.write_text("<html>not pdf</html>", encoding="utf-8")
        try:
            validate_download(pdf, "pdf", "application/pdf")
            validate_download(html, "html", "text/html")
        except RuntimeError as error:
            errors.append(f"valid local media fixture rejected: {error}")
        try:
            validate_download(wrong, "pdf", "text/html")
            errors.append("HTML payload accepted as PDF")
        except RuntimeError:
            pass
        faq = next(item for item in documents if item.get("source_id") == "origins-faq-2025-10-16")
        if media_type(faq) != "html":
            errors.append("Origins FAQ is not classified as HTML")
    print(f"[info] rules manifest: {len(documents)} documents across {len(groups)} opt-in groups; documents and index stay local.")
    if errors:
        print("\n[errors]")
        print("\n".join(f"  - {error}" for error in errors))
        return 1
    print("\nOK: grouped English/zh-CN bootstrap is explicit, ignored, source-linked, and index-ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
