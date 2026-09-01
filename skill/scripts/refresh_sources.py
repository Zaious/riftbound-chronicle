#!/usr/bin/env python3
"""
Propose a source-registry refresh. Never perform one.

`rules_source_registry.json` carries a `last_checked` date that is typed by
hand, which means it records that someone intended to check, not that anything
was checked. This tool turns that into evidence: it captures what the official
URLs currently return, diffs that against the registry, and writes a report a
human reads before editing the registry themselves.

Three properties are structural here, not conventions:

  1. It never writes the registry. There is no promote command, no --apply, no
     --yes. The report ends in a proposal a person types in. A tool that can
     update its own baseline can quietly launder an unverified change into the
     source of authority.

  2. Everything it writes lands under skill/.local/refresh-reports/, which is
     git-ignored. Reports quote third-party pages, and a fetched excerpt that
     drifts into a tracked path becomes a redistribution problem in a public
     repository. Every write goes through report_path(), which resolves the
     target and refuses anything outside that directory.

  3. Capture and analysis are separate commands. `capture` touches the network
     and writes a snapshot; `report` reads a snapshot and touches nothing. So
     the analysis is deterministic, reviewable, and testable offline -- and the
     one step that leaves the machine is the one step you can audit on its own.

Usage:
    python3 skill/scripts/refresh_sources.py plan
    python3 skill/scripts/refresh_sources.py capture --name 2026-09-01
    python3 skill/scripts/refresh_sources.py report --snapshot <dir> --name 2026-09-01

`plan` and `report` never open a socket. Only `capture` does, it sends no
credentials, and it refuses anything that is not a plain https URL on a public
host.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REGISTRY = SKILL_DIR / "data" / "rules_source_registry.json"
REPORTS_DIR = SKILL_DIR / ".local" / "refresh-reports"

USER_AGENT = "riftbound-chronicle-refresh/1.0 (+unofficial fan project; read-only source check)"
FETCH_TIMEOUT_SECONDS = 20
# Link text is kept only to make a discovered URL identifiable in the report.
MAX_LINK_TEXT = 120


class RefreshError(RuntimeError):
    """A refusal, not a crash: the caller asked for something out of bounds."""


# --------------------------------------------------------------------------
# Output boundary
# --------------------------------------------------------------------------

def report_path(name: str, filename: str) -> Path:
    """Resolve one output path, or refuse.

    This is the only place the tool is allowed to decide where to write. It
    resolves the candidate and requires it to sit inside REPORTS_DIR, so a
    crafted --name ('../../skill/data', an absolute path, a Windows drive
    letter) cannot walk out into tracked files.
    """
    if not name or name.strip() != name:
        raise RefreshError("report name must be a non-empty name without surrounding whitespace")
    for part in (name, filename):
        candidate = Path(part)
        if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
            raise RefreshError(f"refusing path component outside the report directory: {part!r}")
        if any(separator in part for separator in ("/", "\\")):
            raise RefreshError(f"report path components must not contain separators: {part!r}")

    base = REPORTS_DIR.resolve() if REPORTS_DIR.exists() else REPORTS_DIR
    target = (base / name / filename).resolve()
    if base not in target.parents:
        raise RefreshError(f"resolved output {target} escapes {base}")
    return target


def write_output(name: str, filename: str, text: str) -> Path:
    target = report_path(name, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# Fetch boundary
# --------------------------------------------------------------------------

def assert_fetchable(url: str) -> None:
    """Refuse anything that is not a plain public https URL.

    The registry is data, and data can be wrong or hostile. Without this a bad
    entry could point the fetcher at a loopback address or an internal host and
    turn a source check into a request nobody reviewed.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise RefreshError(f"refusing non-https URL: {url}")
    if parsed.username or parsed.password or "@" in (parsed.netloc.rsplit(":", 1)[0]):
        raise RefreshError(f"refusing URL carrying credentials: {url}")
    if not parsed.hostname:
        raise RefreshError(f"refusing URL without a host: {url}")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise RefreshError(f"refusing non-public address: {url}")


def fetch_metadata(url: str) -> dict[str, Any]:
    """One read-only GET, recording metadata only.

    Bodies are read only for HTML index pages, and only so new links can be
    discovered. Document bodies (the PDFs) are never stored: the tool reports
    what changed about a source, never the source itself.
    """
    assert_fetchable(url)
    request = urllib.request.Request(url, method="GET", headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
    })
    record: dict[str, Any] = {"url": url}
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            headers = response.headers
            content_type = (headers.get("Content-Type") or "").split(";")[0].strip()
            record.update({
                "status": response.status,
                "final_url": response.geturl(),
                "content_type": content_type,
                "content_length": headers.get("Content-Length"),
                "last_modified": headers.get("Last-Modified"),
                "etag": headers.get("ETag"),
            })
            record["html"] = response.read().decode("utf-8", errors="replace") if content_type == "text/html" else None
    except urllib.error.HTTPError as error:
        record.update({"status": error.code, "final_url": url, "error": f"HTTP {error.code}"})
    except (urllib.error.URLError, socket.timeout, OSError) as error:
        record.update({"status": None, "final_url": url, "error": str(error)})
    return record


# --------------------------------------------------------------------------
# Analysis (offline)
# --------------------------------------------------------------------------

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())[:MAX_LINK_TEXT]))
            self._href, self._text = None, []


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def fetch_plan(registry: dict[str, Any]) -> list[dict[str, str]]:
    """What a capture would request, and why, without requesting anything."""
    plan = []
    for source in registry["sources"]:
        if source.get("status") == "superseded":
            reason = "skipped: superseded entries are history, not a current answer"
        elif source.get("resolve_at_query_time"):
            reason = "resolve_at_query_time is true, so the live document governs"
        else:
            reason = "dated snapshot; checked for reachability and silent revision"
        plan.append({
            "source_id": source["source_id"],
            "url": source["url"],
            "authority": source["authority"],
            "status": source.get("status", "active"),
            "registry_version": source.get("version"),
            "reason": reason,
            "would_fetch": source.get("status") != "superseded",
        })
    return plan


def registry_hygiene(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings that need no network at all -- the registry against itself."""
    findings: list[dict[str, Any]] = []
    by_id = {source["source_id"]: source for source in registry["sources"]}
    seen_urls: dict[str, str] = {}

    for source in registry["sources"]:
        source_id = source["source_id"]
        successor = source.get("superseded_by")
        if source.get("status") == "superseded":
            if not successor:
                findings.append({"kind": "superseded_without_successor", "source_id": source_id,
                                 "detail": "status is superseded but superseded_by is empty, so nothing points at the current document"})
            elif successor not in by_id:
                findings.append({"kind": "dangling_successor", "source_id": source_id,
                                 "detail": f"superseded_by refers to {successor!r}, which is not in the registry"})
        elif successor:
            findings.append({"kind": "successor_on_active_entry", "source_id": source_id,
                             "detail": f"entry is {source.get('status')!r} but declares superseded_by {successor!r}"})

        url = source.get("url", "")
        if url in seen_urls and seen_urls[url] != source_id:
            findings.append({"kind": "duplicate_url", "source_id": source_id,
                             "detail": f"shares its URL with {seen_urls[url]}; one of them is probably stale"})
        seen_urls.setdefault(url, source_id)

        try:
            assert_fetchable(url)
        except RefreshError as error:
            findings.append({"kind": "unfetchable_url", "source_id": source_id, "detail": str(error)})

    return findings


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(fragment="", query="")).rstrip("/").lower()


def analyze(registry: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Diff a captured snapshot against the registry. No network, no writes."""
    responses = {record["url"]: record for record in snapshot.get("responses", [])}
    by_url = {normalize_url(source["url"]): source for source in registry["sources"]}
    findings: list[dict[str, Any]] = list(registry_hygiene(registry))

    for source in registry["sources"]:
        source_id, url = source["source_id"], source["url"]
        record = responses.get(url)
        if record is None:
            if source.get("status") != "superseded":
                findings.append({"kind": "not_captured", "source_id": source_id,
                                 "detail": "the snapshot has no response for this source, so nothing is known about it"})
            continue
        if record.get("error") or record.get("status") != 200:
            findings.append({"kind": "unreachable", "source_id": source_id,
                             "detail": f"{record.get('error') or 'HTTP ' + str(record.get('status'))} for {url}"})
            continue
        if normalize_url(record.get("final_url", url)) != normalize_url(url):
            findings.append({"kind": "redirected", "source_id": source_id,
                             "detail": f"registry URL redirects to {record['final_url']}",
                             "proposed_url": record["final_url"]})
        previous = (snapshot.get("previous_validators") or {}).get(source_id)
        current = {"etag": record.get("etag"), "last_modified": record.get("last_modified")}
        if previous and any(previous.get(key) != current.get(key) for key in ("etag", "last_modified")):
            findings.append({"kind": "changed_without_version_bump", "source_id": source_id,
                             "detail": f"the document changed ({previous} -> {current}) while the registry still records "
                                       f"version {source.get('version')!r}"})

    entrypoint_id = registry.get("live_entrypoint")
    entrypoint = next((item for item in registry["sources"] if item["source_id"] == entrypoint_id), None)
    if entrypoint is not None:
        record = responses.get(entrypoint["url"])
        if record and record.get("html"):
            parser = LinkParser()
            parser.feed(record["html"])
            for href, text in parser.links:
                absolute = urllib.parse.urljoin(record.get("final_url") or entrypoint["url"], href)
                if not absolute.startswith("https://"):
                    continue
                if normalize_url(absolute) in by_url:
                    continue
                if not any(marker in absolute.lower() for marker in (".pdf", "/rules", "errata", "faq", "ban")):
                    continue
                findings.append({"kind": "undocumented_source", "source_id": None,
                                 "detail": f"{entrypoint_id} links to {absolute} ({text or 'no link text'}), "
                                           "which no registry entry covers"})

    return {
        "schema_version": "riftbound-source-refresh-report.v1",
        "registry_last_checked": registry.get("last_checked"),
        "snapshot_name": snapshot.get("name"),
        "captured_at": snapshot.get("captured_at"),
        "sources_in_registry": len(registry["sources"]),
        "responses_in_snapshot": len(responses),
        "findings": findings,
        "human_approval_required": True,
        "applied": False,
        "note": ("This report proposes; it never edits rules_source_registry.json. "
                 "Verify each finding against the official document before changing the registry by hand."),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Source registry refresh proposal",
        "",
        f"- Snapshot: `{report.get('snapshot_name')}` captured {report.get('captured_at')}",
        f"- Registry `last_checked`: {report.get('registry_last_checked')}",
        f"- Sources in registry: {report['sources_in_registry']}; responses in snapshot: {report['responses_in_snapshot']}",
        "",
        "**Nothing here has been applied.** This tool cannot edit the registry. Verify each",
        "finding against the official document, then make the change by hand and update",
        "`last_checked` to the date you actually verified it.",
        "",
    ]
    if not report["findings"]:
        lines += ["## No findings", "",
                  "Every captured source resolved to its registry URL unchanged, and the registry is",
                  "internally consistent. This is evidence for a `last_checked` bump and nothing more."]
        return "\n".join(lines) + "\n"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in report["findings"]:
        grouped.setdefault(finding["kind"], []).append(finding)
    lines.append(f"## {len(report['findings'])} finding(s)")
    lines.append("")
    for kind, items in sorted(grouped.items()):
        lines.append(f"### {kind.replace('_', ' ')} ({len(items)})")
        lines.append("")
        for finding in items:
            label = finding.get("source_id") or "(not in registry)"
            lines.append(f"- **{label}** — {finding['detail']}")
        lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def command_plan(args: argparse.Namespace) -> int:
    plan = fetch_plan(load_registry())
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    would = [item for item in plan if item["would_fetch"]]
    print(f"[info] {len(would)} of {len(plan)} registry sources would be requested; no request was made.")
    for item in plan:
        marker = "fetch " if item["would_fetch"] else "skip  "
        print(f"  {marker} {item['source_id']:<44} {item['reason']}")
    return 0


def command_capture(args: argparse.Namespace) -> int:
    registry = load_registry()
    plan = [item for item in fetch_plan(registry) if item["would_fetch"]]
    print(f"[info] requesting {len(plan)} official URLs, read-only, no credentials.")
    responses = []
    for item in plan:
        try:
            record = fetch_metadata(item["url"])
        except RefreshError as error:
            record = {"url": item["url"], "status": None, "error": str(error)}
        record["source_id"] = item["source_id"]
        responses.append(record)
        print(f"  {record.get('status') or 'ERR':>4}  {item['source_id']}")
    snapshot = {
        "schema_version": "riftbound-source-snapshot.v1",
        "name": args.name,
        "captured_at": args.captured_at,
        "responses": responses,
    }
    target = write_output(args.name, "snapshot.json", json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    print(f"[info] snapshot written to {target}")
    print("[info] nothing was applied; run `report --snapshot` on this directory to diff it.")
    return 0


def command_report(args: argparse.Namespace) -> int:
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    report = analyze(load_registry(), snapshot)
    json_path = write_output(args.name, "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    markdown_path = write_output(args.name, "report.md", render_markdown(report))
    print(f"[info] {len(report['findings'])} finding(s); the registry was not modified.")
    print(f"[info] {json_path}")
    print(f"[info] {markdown_path}")
    print("[info] human approval required: review each finding, then edit the registry by hand.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="print what a capture would request; makes no request")
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(handler=command_plan)

    capture = sub.add_parser("capture", help="perform read-only requests and write a snapshot under skill/.local")
    capture.add_argument("--name", required=True, help="report directory name under skill/.local/refresh-reports/")
    capture.add_argument("--captured-at", required=True, help="date you ran this, recorded in the snapshot")
    capture.set_defaults(handler=command_capture)

    report = sub.add_parser("report", help="diff a snapshot against the registry; no network, no registry writes")
    report.add_argument("--snapshot", required=True, type=Path)
    report.add_argument("--name", required=True)
    report.set_defaults(handler=command_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except RefreshError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
