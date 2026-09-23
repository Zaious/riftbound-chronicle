#!/usr/bin/env python3
"""Every engine check is a step in the CI workflow.

A check that no workflow names has never run: its passing message is a claim nobody
tested. check_location_ref.py - the gate for the relational "here" capability - sat
outside the workflow from the commit that added it until 2026-09-23, so neither the
public CI nor the private overlay's runner (which reads this workflow's list) ever
ran it. This refuses the next one.

    python skill/scripts/check_ci_lists_every_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SCRIPTS = ROOT / "skill" / "scripts"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    listed = set(re.findall(r"^        run: python3 skill/scripts/(check_\w+\.py)$", text, re.M))
    present = {path.name for path in SCRIPTS.glob("check_*.py")}
    missing = sorted(present - listed)
    stale = sorted(listed - present)
    for name in missing:
        print(f"FAILED: skill/scripts/{name} is not a step in {WORKFLOW.relative_to(ROOT).as_posix()}; it never runs")
    for name in stale:
        print(f"FAILED: the workflow runs skill/scripts/{name}, which does not exist")
    if missing or stale:
        return 1
    print(f"every engine check is a CI step ({len(present)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
