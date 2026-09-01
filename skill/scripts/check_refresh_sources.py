#!/usr/bin/env python3
"""
Offline regression checks for the source-registry refresh tool.

The tool's value is entirely in what it refuses to do, so that is what this
checks. Three properties would each be a real incident if they broke:

  - It cannot write outside skill/.local/refresh-reports/. A report quotes
    third-party pages; one that lands in a tracked path is redistribution from
    a public repository. Proven by feeding report_path() traversal, absolute,
    and separator-bearing names and confirming nothing is created.
  - It cannot modify the registry. There is no apply/promote/--yes path, and
    the registry file's bytes are unchanged after a full plan-and-report run.
  - It cannot reach the network outside `capture`. Proven by disabling socket
    creation for the whole analysis run, not by reading the source.

Everything here runs offline against skill/data/refresh_fixtures/. No test in
this file may open a socket, and none needs credentials.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from unittest import mock
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent
FIXTURES = SKILL_DIR / "data" / "refresh_fixtures"
REGISTRY = SKILL_DIR / "data" / "rules_source_registry.json"
TOOL = SCRIPT_DIR / "refresh_sources.py"

sys.path.insert(0, str(SCRIPT_DIR))

import refresh_sources as rs  # noqa: E402

# Names a hostile or careless caller might pass. Each must be refused outright.
ESCAPING_NAMES = [
    "..",
    "../data",
    "../../skill/data",
    "..\\..\\skill\\data",
    "nested/name",
    "nested\\name",
    "/etc",
    "C:\\Windows",
    "",
    " leading-space",
]
# Findings the analyzer must still be able to produce. A refresh tool that has
# quietly stopped noticing one of these looks exactly like a clean run.
REQUIRED_FINDING_KINDS = {
    "redirected", "unreachable", "not_captured",
    "changed_without_version_bump", "undocumented_source",
}
HYGIENE_KINDS = {
    "superseded_without_successor", "dangling_successor",
    "successor_on_active_entry", "duplicate_url", "unfetchable_url",
}


class NoNetwork:
    """Make any socket creation raise for the duration of a block."""

    def __enter__(self):
        self._real = socket.socket

        def refuse(*args, **kwargs):
            raise AssertionError("offline analysis attempted to open a socket")

        socket.socket = refuse
        return self

    def __exit__(self, *exception):
        socket.socket = self._real
        return False


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    errors: list[str] = []

    for path in (TOOL, FIXTURES / "snapshot.json", FIXTURES / "hub.html", REGISTRY):
        if not path.is_file():
            errors.append(f"missing {path.relative_to(REPO_ROOT).as_posix()}")
    if errors:
        print("\n".join(f"  - {error}" for error in errors))
        return 1

    registry_before = digest(REGISTRY)
    snapshot = json.loads((FIXTURES / "snapshot.json").read_text(encoding="utf-8"))

    # --- the output boundary is where it says it is ------------------------
    if rs.REPORTS_DIR.resolve() != (SKILL_DIR / ".local" / "refresh-reports").resolve():
        errors.append(f"reports directory moved to {rs.REPORTS_DIR}; the git-ignored boundary no longer holds")
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(rs.REPORTS_DIR / "sample" / "report.md")],
        capture_output=True, text=True, check=False)
    if ignored.returncode != 0:
        errors.append("git does not ignore skill/.local/refresh-reports/; reports would be committable")

    with tempfile.TemporaryDirectory(prefix="refresh-guard-") as temp_name:
        temp = Path(temp_name)
        sandbox = temp / "reports"
        sandbox.mkdir()
        real_reports_dir = rs.REPORTS_DIR
        rs.REPORTS_DIR = sandbox
        try:
            # --- path guard --------------------------------------------------
            for name in ESCAPING_NAMES:
                try:
                    resolved = rs.report_path(name, "report.md")
                except rs.RefreshError:
                    continue
                errors.append(f"report_path accepted escaping name {name!r} -> {resolved}")
            for filename in ("../registry.json", "nested/report.md", "/tmp/report.md"):
                try:
                    resolved = rs.report_path("ok", filename)
                except rs.RefreshError:
                    continue
                errors.append(f"report_path accepted escaping filename {filename!r} -> {resolved}")

            # Resolution is probed with every hostile name above. Actual write
            # attempts use only the relative ones, so that a regressed guard
            # lands inside this temp tree -- where the sweep below catches it --
            # instead of the test itself writing to C:\Windows or /etc.
            for name in ("..", "../data", "..\\data", "nested/name"):
                try:
                    rs.write_output(name, "report.md", "should never be written")
                except rs.RefreshError:
                    continue
                except OSError as error:
                    errors.append(f"write_output attempted a write for escaping name {name!r}: {error}")
                    continue
                errors.append(f"write_output wrote through escaping name {name!r}")
            outside = [item for item in temp.iterdir() if item != sandbox]
            if outside:
                errors.append(f"a refused write still created {outside}")

            # --- analysis is offline, and reports what it must ---------------
            with NoNetwork():
                registry = rs.load_registry()
                plan = rs.fetch_plan(registry)
                report = rs.analyze(registry, snapshot)
                markdown = rs.render_markdown(report)
                written = rs.write_output("offline-run", "report.json",
                                          json.dumps(report, ensure_ascii=False, indent=2) + "\n")

            if not written.is_file() or sandbox.resolve() not in written.resolve().parents:
                errors.append("a legitimate report was not written inside the reports directory")

            superseded = {item["source_id"] for item in registry["sources"] if item.get("status") == "superseded"}
            if any(item["would_fetch"] for item in plan if item["source_id"] in superseded):
                errors.append("the plan would re-fetch a superseded source; history is not a current answer")
            if len(plan) != len(registry["sources"]):
                errors.append("the plan does not account for every registry source")

            kinds = {finding["kind"] for finding in report["findings"]}
            missing = sorted(REQUIRED_FINDING_KINDS - kinds)
            if missing:
                errors.append(f"the offline fixture no longer exercises {missing}; those failures would go unnoticed")
            if report.get("human_approval_required") is not True or report.get("applied") is not False:
                errors.append("the report does not state that it is an unapplied proposal")
            for phrase in ("has been applied", "by hand"):
                if phrase not in markdown:
                    errors.append(f"the rendered report does not tell the reader {phrase!r}")

            # Registry hygiene must fire on a broken registry, in memory only.
            broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
            broken["sources"] = [dict(source) for source in broken["sources"]]
            broken["sources"][1]["status"] = "superseded"
            broken["sources"][1]["superseded_by"] = None
            broken["sources"][2]["superseded_by"] = "no-such-source"
            broken["sources"][3]["url"] = broken["sources"][4]["url"]
            broken["sources"][5]["url"] = "http://insecure.example/rules.pdf"
            broken["sources"][6]["status"] = "superseded"
            broken["sources"][6]["superseded_by"] = "also-missing"
            hygiene = {finding["kind"] for finding in rs.registry_hygiene(broken)}
            missing_hygiene = sorted(HYGIENE_KINDS - hygiene)
            if missing_hygiene:
                errors.append(f"registry hygiene no longer detects {missing_hygiene}")
            if rs.registry_hygiene(registry):
                errors.append(f"the committed registry itself has hygiene findings: {rs.registry_hygiene(registry)}")
        finally:
            rs.REPORTS_DIR = real_reports_dir

    # --- the fetch boundary refuses anything that is not a public https URL --
    for url in ("http://playriftbound.com/x.pdf", "ftp://example.com/x", "https://user:pass@example.com/x",
                "https://127.0.0.1/x", "https://10.0.0.5/x", "https://[::1]/x", "https:///x"):
        try:
            rs.assert_fetchable(url)
        except rs.RefreshError:
            continue
        errors.append(f"the fetch guard accepted {url!r}")
    try:
        rs.assert_fetchable("https://playriftbound.com/en-us/rules-hub/")
    except rs.RefreshError as error:
        errors.append(f"the fetch guard rejected a legitimate official URL: {error}")

    # Hostnames and redirects must be checked after DNS resolution as well as
    # syntactically. Otherwise a harmless-looking registry hostname can resolve
    # to loopback/private infrastructure and bypass the literal-IP guard.
    private_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))]
    public_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with mock.patch.object(socket, "getaddrinfo", return_value=private_answer):
        try:
            rs.assert_public_resolution("https://example.com/rules")
        except rs.RefreshError:
            pass
        else:
            errors.append("DNS guard accepted a hostname resolving to a private address")
        try:
            rs.PublicOnlyRedirectHandler().redirect_request(
                urllib.request.Request("https://example.com/start"), None, 302, "Found", {},
                "https://redirect.example/rules",
            )
        except rs.RefreshError:
            pass
        else:
            errors.append("redirect guard accepted a redirect resolving to a private address")
    with mock.patch.object(socket, "getaddrinfo", return_value=public_answer):
        try:
            rs.assert_public_resolution("https://example.com/rules")
        except rs.RefreshError as error:
            errors.append(f"DNS guard rejected a mocked public destination: {error}")

    # --- there is no way to apply anything -----------------------------------
    subcommands = set(rs.build_parser()._subparsers._group_actions[0].choices)
    for forbidden in ("apply", "promote", "write-registry", "accept", "update"):
        if forbidden in subcommands:
            errors.append(f"the CLI exposes a {forbidden!r} command; this tool must never update its own baseline")
    if subcommands != {"plan", "capture", "report"}:
        errors.append(f"the CLI surface changed to {sorted(subcommands)}; every command must be read-only or capture-only")
    # write_output is the single write path, and it is the one the guard covers.
    source = TOOL.read_text(encoding="utf-8")
    write_sites = [line.strip() for line in source.splitlines()
                   if ".write_text(" in line and "def " not in line]
    if len(write_sites) != 1 or not write_sites[0].startswith("target.write_text("):
        errors.append(f"the tool has write sites the path guard does not cover: {write_sites}")

    # --- CLI runs end to end, off-cwd, without touching the registry ---------
    with tempfile.TemporaryDirectory(prefix="refresh-cli-") as temp_name:
        run = subprocess.run([sys.executable, str(TOOL), "plan"], cwd=temp_name,
                             capture_output=True, text=True, check=False)
        if run.returncode != 0:
            errors.append(f"`plan` failed off-cwd: {run.stderr.strip()}")
        elif "no request was made" not in run.stdout:
            errors.append("`plan` does not state that it made no request")

        # The escape target is checked and cleaned up, not just asserted about:
        # while proving this guard was load-bearing, a run with the guard
        # removed wrote a report into the repository root and it was very nearly
        # committed. A test that can litter the repo when it fails is a test
        # that will eventually put its litter in a commit.
        escape_target = REPO_ROOT / "escape"
        existed_before = escape_target.exists()
        run = subprocess.run(
            [sys.executable, str(TOOL), "report", "--snapshot", str(FIXTURES / "snapshot.json"),
             "--name", "../../../escape"],
            cwd=temp_name, capture_output=True, text=True, check=False)
        if run.returncode == 0:
            errors.append("`report --name ../../../escape` succeeded; the path guard is not wired into the CLI")
        if escape_target.exists() and not existed_before:
            errors.append(f"the CLI wrote outside the report directory: {escape_target}")
            shutil.rmtree(escape_target, ignore_errors=True)

    if digest(REGISTRY) != registry_before:
        errors.append("rules_source_registry.json changed during this run; the tool is not read-only")

    print(f"[info] refresh tooling: {len(ESCAPING_NAMES)} escaping names refused, "
          f"{len(REQUIRED_FINDING_KINDS)} finding kinds exercised offline, registry byte-identical, "
          "reports confined to a git-ignored path.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} refresh-tooling violation(s).")
        return 1
    print("\nOK: the refresh tool proposes offline, writes only into skill/.local, and cannot update its own baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
