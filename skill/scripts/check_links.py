#!/usr/bin/env python3
"""
Find broken relative markdown links across this repo.

Written for CI (see .github/workflows/ci.yml) after this session's own
restructuring (splitting a 46-entry catalog into per-Legend files,
moving data/ and scripts/ inside skill/) made stale internal links a
real, concrete risk rather than a hypothetical one -- exactly the kind
of thing a link check would have caught immediately instead of relying
on a human noticing.

Checks every `[text](path)`-style relative link in every .md file in
the repo (skips absolute URLs, anchors-only links, and mailto:).
A link with a `#fragment` is checked only for the file part; fragment
targets aren't validated (would need a heading-slug parser per file).

Usage:
    python3 skill/scripts/check_links.py

Exit code 0 if every relative link resolves, 1 otherwise.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def is_external_or_special(target):
    return (
        target.startswith("http://")
        or target.startswith("https://")
        or target.startswith("mailto:")
        or target.startswith("#")
    )


def main():
    broken = []
    checked = 0

    for md_file in REPO_ROOT.rglob("*.md"):
        if ".git" in md_file.parts:
            continue
        text = md_file.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if is_external_or_special(target):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            checked += 1
            resolved = (md_file.parent / file_part).resolve()
            if not resolved.exists():
                line_no = text.count("\n", 0, match.start()) + 1
                broken.append(f"{md_file.relative_to(REPO_ROOT)}:{line_no}  ->  {target}  (resolved: {resolved}, does not exist)")

    print(f"[info] checked {checked} relative links across {sum(1 for _ in REPO_ROOT.rglob('*.md') if '.git' not in _.parts)} markdown files.")

    if broken:
        print("\n[broken links]")
        for b in broken:
            print(f"  - {b}")
        print(f"\nFAILED: {len(broken)} broken link(s).")
        return 1

    print("\nOK: no broken relative links found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
