#!/usr/bin/env python3
"""Build, query, and audit a local page-addressable Riftbound rules index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SKILL_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = SKILL_DIR / "data" / "rules_manifest.json"
REGISTRY_PATH = SKILL_DIR / "data" / "rules_source_registry.json"
ALIASES_PATH = SKILL_DIR / "data" / "rules_query_aliases.json"
DEFAULT_RULES_DIR = SKILL_DIR / ".local" / "rules"
DEFAULT_INDEX_NAME = "rules-index.sqlite3"
RULE_START = re.compile(r"(?m)^\s*(\d{3}(?:\.\d+)*(?:\.[a-z])?\.?)\s+(?=\S)", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'.:-]*|[\u3400-\u9fff]+")
SPACE = re.compile(r"\s+")
AUTHORITY_WEIGHT = {"official": 4.0, "judge_guidance": 1.0, "community": 0.0}


class IndexError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rules_dir(value: Path | None) -> Path:
    if value:
        return value.expanduser().resolve()
    configured = os.environ.get("RIFTBOUND_RULES_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_RULES_DIR


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pages(path: Path) -> list[str]:
    executable = shutil.which("pdftotext")
    if executable:
        result = subprocess.run(
            [executable, "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
        )
        if result.returncode == 0:
            text = result.stdout.decode("utf-8", errors="replace")
            pages = text.split("\f")
            if pages and not pages[-1].strip():
                pages.pop()
            return pages
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IndexError("PDF extraction requires pdftotext or the optional pypdf package") from exc
    try:
        return [(page.extract_text() or "") for page in PdfReader(str(path)).pages]
    except Exception as exc:
        raise IndexError(f"cannot extract {path.name}: {exc}") from exc


def normalize(text: str) -> str:
    return SPACE.sub(" ", text.replace("\x00", " ")).strip()


def split_page(text: str, page: int) -> list[tuple[str, str]]:
    matches = list(RULE_START.finditer(text))
    if matches:
        chunks = []
        preface = normalize(text[:matches[0].start()])
        if len(preface) >= 40:
            chunks.append((f"page-{page}-context", preface))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = normalize(text[match.start():end])
            if body:
                chunks.append((match.group(1).rstrip("."), body))
        return chunks

    blocks = [normalize(block) for block in re.split(r"\n\s*\n", text) if normalize(block)]
    chunks: list[tuple[str, str]] = []
    buffer = ""
    paragraph = 1
    for block in blocks:
        candidate = f"{buffer} {block}".strip()
        if buffer and len(candidate) > 1400:
            chunks.append((f"page-{page}-paragraph-{paragraph}", buffer))
            paragraph += 1
            buffer = block
        else:
            buffer = candidate
    if buffer:
        chunks.append((f"page-{page}-paragraph-{paragraph}", buffer))
    return chunks


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE documents (
          source_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, title TEXT NOT NULL,
          version TEXT NOT NULL, locale TEXT NOT NULL, region TEXT NOT NULL,
          document_class TEXT NOT NULL, authority TEXT NOT NULL, status TEXT NOT NULL,
          superseded_by TEXT, controlling_language INTEGER NOT NULL, relative_path TEXT NOT NULL,
          sha256 TEXT NOT NULL, page_count INTEGER NOT NULL
        );
        CREATE TABLE chunks (
          chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
          page INTEGER NOT NULL, locator TEXT NOT NULL, text TEXT NOT NULL,
          compact_text TEXT NOT NULL,
          FOREIGN KEY(source_id) REFERENCES documents(source_id)
        );
        CREATE INDEX chunks_source_page ON chunks(source_id, page);
        CREATE INDEX chunks_locator ON chunks(locator);
        """
    )


def build_index(root: Path, index_path: Path) -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    registry = {item["source_id"]: item for item in load_json(REGISTRY_PATH)["sources"]}
    lock_path = root / "rules.lock.json"
    locked = {}
    if lock_path.is_file():
        locked = {item["source_id"]: item for item in load_json(lock_path).get("documents", [])}
    installed = []
    for document in manifest["documents"]:
        path = root / Path(document["relative_path"])
        if path.is_file():
            installed.append((document, path))
    if not installed:
        raise IndexError(f"no manifest PDFs found in {root}; run bootstrap_rules.py first")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{index_path.name}.", suffix=".tmp", dir=index_path.parent)
    os.close(descriptor)
    temp = Path(temp_name)
    document_count = chunk_count = 0
    try:
        connection = sqlite3.connect(temp)
        create_schema(connection)
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", "riftbound-rules-index.v1"))
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("built_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")))
        for document, path in installed:
            source = registry[document["source_id"]]
            digest = sha256(path)
            if source["status"] == "superseded":
                continue
            if document["source_id"] in locked and locked[document["source_id"]].get("sha256") != digest:
                raise IndexError(f"hash mismatch against rules.lock.json: {document['source_id']}")
            pages = extract_pages(path)
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source["source_id"], document["document_id"], source["title"], source["version"],
                    source["locale"], source["region"], source["document_class"], source["authority"],
                    source["status"], source["superseded_by"], int(source["controlling_language"]),
                    document["relative_path"], digest, len(pages),
                ),
            )
            document_count += 1
            for page_number, page_text in enumerate(pages, 1):
                for locator, body in split_page(page_text, page_number):
                    connection.execute(
                        "INSERT INTO chunks(source_id, page, locator, text, compact_text) VALUES (?, ?, ?, ?, ?)",
                        (source["source_id"], page_number, locator, body, re.sub(r"\s+", "", body.casefold())),
                    )
                    chunk_count += 1
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("document_count", str(document_count)))
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("chunk_count", str(chunk_count)))
        connection.commit()
        connection.close()
        os.replace(temp, index_path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return {"index": str(index_path), "documents": document_count, "chunks": chunk_count}


def query_concepts(query: str) -> list[list[str]]:
    raw = [item.casefold() for item in WORD.findall(query) if len(item) > 1 or item.isdigit()]
    aliases = load_json(ALIASES_PATH)["groups"]
    joined = query.casefold()
    concepts: list[list[str]] = []
    consumed = set()
    for group in aliases:
        folded = [item.casefold() for item in group]
        if any(item in joined or item in raw for item in folded):
            concepts.append(folded)
            consumed.update(item for item in raw if any(item in alias.split() for alias in folded))
    concepts.extend([item] for item in raw if item not in consumed)
    unique = []
    seen = set()
    for concept in concepts:
        key = tuple(concept)
        if key not in seen:
            unique.append(concept)
            seen.add(key)
    return unique


def score_row(row: sqlite3.Row, query: str, concepts: Iterable[list[str]], preferred_locale: str | None) -> float:
    text = row["text"].casefold()
    compact = row["compact_text"]
    query_folded = query.casefold().strip()
    score = 0.0
    locator_match = False
    if query_folded and query_folded in text:
        score += 18
    if query_folded and re.sub(r"\s+", "", query_folded) in compact:
        score += 12
    matched = 0
    concept_count = 0
    for alternatives in concepts:
        concept_count += 1
        occurrences = []
        for term in alternatives:
            compact_term = re.sub(r"\s+", "", term)
            if term in text or (compact_term and compact_term in compact):
                occurrences.append(text.count(term))
            if term.rstrip(".") == row["locator"].casefold().rstrip("."):
                score += 35
                locator_match = True
        if occurrences:
            matched += 1
            score += 4 + min(max(occurrences), 3)
    minimum_matches = 2 if concept_count >= 2 else 1
    if not locator_match and matched < minimum_matches and query_folded not in text and re.sub(r"\s+", "", query_folded) not in compact:
        return 0.0
    score += AUTHORITY_WEIGHT.get(row["authority"], 0)
    score += 1.5 if row["controlling_language"] else 0
    score += 6.0 if preferred_locale and row["locale"].casefold() == preferred_locale.casefold() else 0
    return score


def search(index_path: Path, query: str, *, limit: int, locale: str | None, region: str | None,
           document_class: str | None, include_superseded: bool) -> list[dict[str, Any]]:
    if not index_path.is_file():
        raise IndexError(f"index not found: {index_path}; run rules_index.py build")
    concepts = query_concepts(query)
    preferred_locale = locale or ("zh-CN" if re.search(r"[\u3400-\u9fff]", query) else "en-US")
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    sql = """
      SELECT c.*, d.title, d.version, d.locale, d.region, d.document_class,
             d.authority, d.status, d.superseded_by, d.controlling_language
      FROM chunks c JOIN documents d USING(source_id) WHERE 1=1
    """
    params: list[Any] = []
    if not include_superseded:
        sql += " AND d.status <> 'superseded'"
    if locale:
        sql += " AND d.locale = ?"
        params.append(locale)
    if region:
        sql += " AND (d.region = ? OR d.region = 'global')"
        params.append(region)
    if document_class:
        sql += " AND d.document_class = ?"
        params.append(document_class)
    ranked = []
    for row in connection.execute(sql, params):
        score = score_row(row, query, concepts, preferred_locale)
        if score:
            excerpt = row["text"][:700] + ("…" if len(row["text"]) > 700 else "")
            ranked.append({
                "score": round(score, 2), "source_id": row["source_id"], "title": row["title"],
                "version": row["version"], "locale": row["locale"], "region": row["region"],
                "document_class": row["document_class"], "authority": row["authority"],
                "status": row["status"], "superseded_by": row["superseded_by"],
                "controlling_language": bool(row["controlling_language"]), "page": row["page"],
                "locator": row["locator"], "excerpt": excerpt,
            })
    connection.close()
    ranked.sort(key=lambda item: (-item["score"], item["source_id"], item["page"], item["locator"]))
    selected: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    per_locale: dict[str, int] = {}
    locale_cap = (limit + 1) // 2 if preferred_locale == "zh-CN" and not locale else limit
    for item in ranked:
        if per_source.get(item["source_id"], 0) >= 3:
            continue
        if per_locale.get(item["locale"], 0) >= locale_cap:
            continue
        selected.append(item)
        per_source[item["source_id"]] = per_source.get(item["source_id"], 0) + 1
        per_locale[item["locale"]] = per_locale.get(item["locale"], 0) + 1
        if len(selected) == limit:
            return selected
    if len(selected) < limit:
        selected_ids = {id(item) for item in selected}
        selected.extend(item for item in ranked if id(item) not in selected_ids)
    return selected[:limit]


def audit(root: Path, index_path: Path) -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    installed = []
    missing = []
    for item in manifest["documents"]:
        target = root / Path(item["relative_path"])
        (installed if target.is_file() else missing).append(item["source_id"])
    indexed = []
    if index_path.is_file():
        connection = sqlite3.connect(index_path)
        indexed = [row[0] for row in connection.execute("SELECT source_id FROM documents ORDER BY source_id")]
        connection.close()
    return {
        "manifest_documents": len(manifest["documents"]), "installed": installed,
        "missing": missing, "indexed": indexed, "unindexed_installed": sorted(set(installed) - set(indexed)),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--rules-dir", type=Path, help="Local rules folder (or RIFTBOUND_RULES_DIR).")
    root.add_argument("--index", type=Path, help="Index path; defaults to RULES_DIR/rules-index.sqlite3.")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("build")
    query = commands.add_parser("search")
    query.add_argument("query")
    query.add_argument("--limit", type=int, default=8)
    query.add_argument("--locale")
    query.add_argument("--region")
    query.add_argument("--document-class")
    query.add_argument("--include-superseded", action="store_true")
    query.add_argument("--json", action="store_true")
    commands.add_parser("audit")
    return root


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    root = rules_dir(args.rules_dir)
    index_path = args.index.expanduser().resolve() if args.index else root / DEFAULT_INDEX_NAME
    try:
        if args.command == "build":
            result = build_index(root, index_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "audit":
            print(json.dumps(audit(root, index_path), ensure_ascii=False, indent=2))
        else:
            results = search(
                index_path, args.query, limit=max(1, min(args.limit, 50)), locale=args.locale,
                region=args.region, document_class=args.document_class,
                include_superseded=args.include_superseded,
            )
            if args.json:
                print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))
            else:
                for index, item in enumerate(results, 1):
                    control = "controlling" if item["controlling_language"] else "translation/supporting"
                    print(f"[{index}] {item['title']} ({item['version']}, {item['locale']}, {item['authority']}, {control})")
                    print(f"    {item['source_id']} · p.{item['page']} · {item['locator']} · score {item['score']}")
                    print(f"    {item['excerpt']}")
                if not results:
                    print("No indexed passage matched. Broaden the wording or verify that the relevant document group is installed.")
        return 0
    except (IndexError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
