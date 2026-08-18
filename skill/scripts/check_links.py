#!/usr/bin/env python3
"""
Find broken relative markdown links -- and broken #fragment anchors -- across
this repo.

Written for CI (see .github/workflows/ci.yml) after this session's own
restructuring (splitting a 46-entry catalog into per-Legend files,
moving data/ and scripts/ inside skill/) made stale internal links a
real, concrete risk rather than a hypothetical one -- exactly the kind
of thing a link check would have caught immediately instead of relying
on a human noticing.

Checks every `[text](path)`-style relative link in every .md file in the
repo (skips absolute URLs and mailto:). A link's file part is checked for
existence; a link's `#fragment` part (including same-file `#fragment`
links, which used to be skipped entirely) is checked against the target
file's actual ATX headings, using a GitHub-Flavored-Markdown-compatible
slug algorithm (lowercase, strip non-alphanumeric except spaces/hyphens,
spaces -> hyphens, de-duplicate repeated headings with a numeric suffix).
This won't catch every edge case GFM's real slugger handles (e.g. emoji,
some Unicode categories), but it catches the common failure mode this
repo actually has: a heading gets renamed or removed and a link to it
goes stale silently.

Usage:
    python3 skill/scripts/check_links.py

Exit code 0 if every relative link and fragment resolves, 1 otherwise.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
CODE_SPAN_RE = re.compile(r"`([^`]*)`")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)")
SLUG_STRIP_RE = re.compile(r"[^\w\s-]")


def is_external_or_special(target):
    return target.startswith("http://") or target.startswith("https://") or target.startswith("mailto:")


def slugify(heading_text):
    """GFM-compatible heading slug: strip inline markup, lowercase, drop
    punctuation (keep word chars/spaces/hyphens), spaces -> hyphens.
    Code spans are unwrapped but their content (including _ and *, which
    GFM doesn't treat as emphasis markers inside a code span) is kept
    literally -- only markup outside code spans is emphasis/link syntax."""
    # Protect code-span content first so emphasis-stripping below doesn't
    # eat underscores/asterisks that are part of a literal filename/token.
    placeholders = []

    def stash_code(m):
        placeholders.append(m.group(1))
        return f"\x00{len(placeholders) - 1}\x00"

    text = CODE_SPAN_RE.sub(stash_code, heading_text)
    text = MD_LINK_RE.sub(lambda m: m.group(1), text)
    text = EMPHASIS_RE.sub("", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)
    text = text.strip().lower()
    text = SLUG_STRIP_RE.sub("", text)
    return re.sub(r"\s+", "-", text)


def extract_anchors(text):
    """All valid #fragment targets for a file: one slug per heading, with
    GFM's own de-duplication (repeated heading text gets -1, -2, ... )."""
    seen = {}
    anchors = set()
    for _, heading_text in HEADING_RE.findall(text):
        base = slugify(heading_text)
        if base in seen:
            seen[base] += 1
            anchors.add(f"{base}-{seen[base]}")
        else:
            seen[base] = 0
            anchors.add(base)
    return anchors


def main():
    broken = []
    checked = 0
    fragments_checked = 0

    all_md = [p for p in REPO_ROOT.rglob("*.md") if ".git" not in p.parts]
    anchor_cache = {}

    def anchors_for(path):
        if path not in anchor_cache:
            anchor_cache[path] = extract_anchors(path.read_text(encoding="utf-8")) if path.exists() else None
        return anchor_cache[path]

    for md_file in all_md:
        text = md_file.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if is_external_or_special(target):
                continue
            file_part, _, fragment = target.partition("#")
            line_no = text.count("\n", 0, match.start()) + 1

            target_file = md_file if not file_part else (md_file.parent / file_part).resolve()
            if file_part:
                checked += 1
                if not target_file.exists():
                    broken.append(f"{md_file.relative_to(REPO_ROOT)}:{line_no}  ->  {target}  (resolved: {target_file}, does not exist)")
                    continue

            if fragment:
                fragments_checked += 1
                valid_anchors = anchors_for(target_file)
                if valid_anchors is not None and fragment not in valid_anchors:
                    broken.append(f"{md_file.relative_to(REPO_ROOT)}:{line_no}  ->  {target}  (#{fragment} not found in {target_file.relative_to(REPO_ROOT)}'s headings)")

    print(f"[info] checked {checked} relative links and {fragments_checked} #fragment anchors across {len(all_md)} markdown files.")

    if broken:
        print("\n[broken links]")
        for b in broken:
            print(f"  - {b}")
        print(f"\nFAILED: {len(broken)} broken link(s)/anchor(s).")
        return 1

    print("\nOK: no broken relative links or fragment anchors found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
