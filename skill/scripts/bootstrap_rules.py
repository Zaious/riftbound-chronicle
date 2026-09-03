#!/usr/bin/env python3
"""Opt-in downloader for local Riftbound rules, FAQs, and errata documents.

The public repository ships only source pointers and verification tooling.
Downloaded Riot-owned documents and generated indexes stay under an ignored
local directory and are never a silent network fallback during consultation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SKILL_DIR = SCRIPT.parent.parent
MANIFEST_PATH = SKILL_DIR / "data" / "rules_manifest.json"
DEFAULT_RULES_DIR = SKILL_DIR / ".local" / "rules"
MAX_BYTES = 80 * 1024 * 1024


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def default_rules_dir() -> Path:
    configured = os.environ.get("RIFTBOUND_RULES_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_RULES_DIR


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_type(document: dict) -> str:
    return "html" if Path(document["relative_path"]).suffix.casefold() in {".html", ".htm"} else "pdf"


def validate_download(path: Path, kind: str, content_type: str) -> None:
    prefix = path.read_bytes()[:1024].lstrip().lower()
    if kind == "pdf" and not prefix.startswith(b"%pdf"):
        raise RuntimeError(f"download did not return a PDF (content type: {content_type})")
    if kind == "html" and not (prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html")):
        raise RuntimeError(f"download did not return HTML (content type: {content_type})")


def download(document: dict, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    request = urllib.request.Request(document["url"], headers={"User-Agent": "riftbound-chronicle-rules-bootstrap/2"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_type = response.headers.get_content_type()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_BYTES:
                raise RuntimeError(f"{document['document_id']} exceeds the {MAX_BYTES // (1024 * 1024)} MiB safety limit")
            with tempfile.NamedTemporaryFile(prefix=f"{document['document_id']}-", suffix=".part", dir=destination.parent, delete=False) as temp:
                temp_path = Path(temp.name)
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise RuntimeError(f"{document['document_id']} exceeds the {MAX_BYTES // (1024 * 1024)} MiB safety limit")
                    temp.write(chunk)
        kind = media_type(document)
        try:
            validate_download(temp_path, kind, content_type)
        except RuntimeError as error:
            raise RuntimeError(f"{document['document_id']}: {error}") from error
        os.replace(temp_path, destination)
    except Exception:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise
    return lock_record(document, destination)


def lock_record(document: dict, destination: Path) -> dict:
    return {
        "document_id": document["document_id"],
        "source_id": document["source_id"],
        "install_group": document["install_group"],
        "relative_path": document["relative_path"],
        "version": document["version"],
        "locale": document["locale"],
        "region": document["region"],
        "document_class": document["document_class"],
        "status": document["status"],
        "media_type": media_type(document),
        "path": str(destination),
        "sha256": sha256(destination),
        "bytes": destination.stat().st_size,
    }


def select_groups(args: argparse.Namespace, manifest: dict) -> list[str]:
    available = set(manifest["groups"])
    if args.all:
        return sorted(available)
    selected = set(args.group or manifest["default_groups"])
    if args.include_zh_cn:
        selected.add("zh-cn")
    if args.include_supplemental_en:
        selected.add("supplemental-en")
    unknown = selected - available
    if unknown:
        raise ValueError(f"unknown install group(s): {', '.join(sorted(unknown))}")
    return sorted(selected)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Download official Riftbound documents into an ignored local directory.")
    parser.add_argument("--rules-dir", type=Path, default=default_rules_dir(), help="Local ignored directory (or set RIFTBOUND_RULES_DIR).")
    parser.add_argument("--group", action="append", help="Install group; repeatable. Defaults to core-en.")
    parser.add_argument("--include-zh-cn", action="store_true", help="Also install the Simplified Chinese rules/FAQ/errata pack.")
    parser.add_argument("--include-supplemental-en", action="store_true", help="Also install available English errata PDFs.")
    parser.add_argument("--all", action="store_true", help="Install every manifest group.")
    parser.add_argument("--refresh", action="store_true", help="Redownload files that already exist instead of verifying them in place.")
    parser.add_argument("--yes", action="store_true", help="Confirm the official-source download without an interactive prompt.")
    args = parser.parse_args()
    manifest = load_manifest()
    try:
        groups = select_groups(args, manifest)
    except ValueError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2
    documents = [item for item in manifest["documents"] if item["install_group"] in groups]
    destination = args.rules_dir.expanduser().resolve()
    print(f"Install groups: {', '.join(groups)} ({len(documents)} documents)")
    print(f"Destination: {destination}")
    print("Downloaded official documents remain local, outside Git, and may be subject to Riot Games' rights and terms.")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Non-interactive mode requires --yes.", file=sys.stderr)
            return 2
        if input("Download selected documents now? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Cancelled; no files were downloaded.")
            return 1

    records = []
    for document in documents:
        target = destination / Path(document["relative_path"])
        try:
            if target.is_file() and not args.refresh:
                print(f"Verifying existing {document['title']} {document['version']} …")
                records.append(lock_record(document, target))
            else:
                print(f"Downloading {document['title']} {document['version']} …")
                records.append(download(document, target))
        except Exception as error:
            print(f"FAILED: {document['document_id']}: {error}", file=sys.stderr)
            return 1

    previous_records = []
    previous_groups = []
    lock_path = destination / "rules.lock.json"
    if lock_path.is_file():
        try:
            previous = json.loads(lock_path.read_text(encoding="utf-8"))
            previous_records = previous.get("documents", [])
            previous_groups = previous.get("selected_groups", [])
        except (json.JSONDecodeError, OSError):
            previous_records = []
    merged = {item["source_id"]: item for item in previous_records if Path(item.get("path", "")).is_file()}
    merged.update({item["source_id"]: item for item in records})
    lock = {
        "schema_version": "riftbound-local-rules-lock.v2",
        "manifest": str(MANIFEST_PATH.relative_to(SKILL_DIR)),
        "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "selected_groups": sorted(set(previous_groups) | set(groups)),
        "documents": sorted(merged.values(), key=lambda item: item["source_id"]),
    }
    destination.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Ready: {len(records)} documents verified. Run rules_index.py build to create the local search index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
