#!/usr/bin/env python3
"""Download the two official Riftbound rule PDFs into an ignored local folder.

This is intentionally opt-in. The public Skill ships pointers and a verifier,
not Riot-owned PDFs. The downloaded files remain local to the user's Skill
installation and are never used as a silent network fallback during a query.
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


def download(document: dict, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with urllib.request.urlopen(document["url"], timeout=60) as response:
            content_type = response.headers.get_content_type()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_BYTES:
                raise RuntimeError(f"{document['document_id']} exceeds the {MAX_BYTES // (1024 * 1024)} MiB safety limit")
            with tempfile.NamedTemporaryFile(prefix=f"{document['document_id']}-", suffix=".part", dir=destination.parent, delete=False) as temp:
                temp_path = Path(temp.name)
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise RuntimeError(f"{document['document_id']} exceeds the {MAX_BYTES // (1024 * 1024)} MiB safety limit")
                    temp.write(chunk)
        if temp_path.read_bytes()[:4] != b"%PDF":
            raise RuntimeError(f"{document['document_id']} did not return a PDF (content type: {content_type})")
        os.replace(temp_path, destination)
    except Exception:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise
    return {"document_id": document["document_id"], "filename": document["filename"], "version": document["version"], "path": str(destination), "sha256": sha256(destination), "bytes": destination.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download official Riftbound rules into an ignored local directory.")
    parser.add_argument("--rules-dir", type=Path, default=default_rules_dir(), help="Local ignored directory for the two PDFs (or set RIFTBOUND_RULES_DIR).")
    parser.add_argument("--yes", action="store_true", help="Confirm the official-source download without an interactive prompt.")
    args = parser.parse_args()
    manifest = load_manifest()
    destination = args.rules_dir.expanduser().resolve()
    print(f"Official source documents will be downloaded to: {destination}")
    print("The PDFs are not included in Git and may be subject to Riot Games' rights and terms.")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Non-interactive mode requires --yes.", file=sys.stderr)
            return 2
        answer = input("Download Core Rules and Tournament Rules now? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled; no files were downloaded.")
            return 1

    records = []
    for document in manifest["documents"]:
        target = destination / document["filename"]
        print(f"Downloading {document['title']} {document['version']} …")
        try:
            records.append(download(document, target))
        except Exception as error:
            print(f"FAILED: {error}", file=sys.stderr)
            return 1
    lock = {"schema_version": "riftbound-local-rules-lock.v1", "manifest": str(MANIFEST_PATH.relative_to(SKILL_DIR)), "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "documents": records}
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "rules.lock.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Ready: {len(records)} documents verified in {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
