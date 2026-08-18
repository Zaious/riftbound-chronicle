#!/usr/bin/env python3
"""
Validate that every deck-primer worked example in the gameplay book actually
follows the fixed eight-section contract the book itself declares.

This is the *offline, fixture* version of the "golden prompt" check a
2026-08-18 audit suggested. The audit's suggestion was to run a real prompt
through the model in CI and check the output shape; that verifies model
behaviour, not repo content, and it'd be non-deterministic, need an API key
in CI, and burn tokens on every push. What CI *can* deterministically verify
is that the book's own published examples honour the contract they claim to
-- if the template drifts (a section renamed, an example silently missing a
section, a Tier tag dropped), that's caught here. Model-behaviour evaluation
belongs in a separate, deliberately-run eval, not push-time CI.

Contract (from gameplay.md's "Deck primer -- the fixed output format"):
  - Exactly these eight numbered sections, in this order, each starting with
    the bolded section name.
  - Every section body contains at least one Tier tag (Tier 1 / Tier 2 /
    Tier 3, or CONFIRMED-family verdicts which the book treats as Tier 2
    status), so a reader can find each claim's evidence level without
    re-deriving it -- the whole point of section 8.
  - Section 8 (Evidence ledger) is present and non-trivial.

Usage:
    python3 skill/scripts/check_deck_primer.py

Exit 0 if every worked example passes, 1 otherwise.
"""

import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
GAMEPLAY = SKILL_DIR / "references" / "gameplay" / "gameplay.md"

SECTIONS = [
    "Identity",
    "Core loop",
    "Mulligan targets",
    "Turn-by-turn priorities",
    "When to fight, when to hold",
    "Common lines",
    "Common mistakes",
    "Evidence ledger",
]

TIER_TAG_RE = re.compile(r"\bTier [123]\b|\bCONFIRMED\b|\bPARTIALLY CONFIRMED\b|\bNOT CONFIRMED\b")
EXAMPLE_HEADER_RE = re.compile(r"^\*\*Worked example[^*]*\*\*", re.MULTILINE)
SECTION_RE = re.compile(r"^(\d)\. \*\*([^*]+)\*\*", re.MULTILINE)


def split_examples(text):
    """Return list of (title_line, body) for each '**Worked example ...**' block,
    each body running until the next worked example or the next '## ' heading."""
    starts = [m.start() for m in EXAMPLE_HEADER_RE.finditer(text)]
    if not starts:
        return []
    out = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[s:end]
        next_h2 = re.search(r"^## ", chunk, re.MULTILINE)
        if next_h2:
            chunk = chunk[: next_h2.start()]
        title = chunk.split("\n", 1)[0]
        # Keep error messages readable: the header line is a full paragraph.
        short = re.sub(r"\*\*", "", title)
        short = short[:70].rstrip() + ("…" if len(short) > 70 else "")
        out.append((short, chunk))
    return out


def check_example(title, body, errors):
    found = SECTION_RE.findall(body)
    names = [n.strip() for _, n in found]
    nums = [int(d) for d, _ in found]

    def norm(s):
        s = s.lower()
        s = re.sub(r"^\d+[–-]\d+\s+", "", s)  # "2–4 common lines" -> "common lines"
        s = re.sub(r"^\d+[–-]\d+\s+", "", s)
        return s.strip()

    expected_norm = [s.lower() for s in SECTIONS]
    got_norm = [norm(n) for n in names]

    if got_norm != expected_norm:
        errors.append(
            f"{title}: sections do not match the fixed contract.\n"
            f"      expected: {SECTIONS}\n"
            f"      got:      {names}"
        )
        return
    if nums != list(range(1, 9)):
        errors.append(f"{title}: section numbering is {nums}, expected 1..8")

    # Per-section Tier tag presence.
    positions = [m.start() for m in SECTION_RE.finditer(body)] + [len(body)]
    for i, name in enumerate(SECTIONS):
        seg = body[positions[i]:positions[i + 1]]
        if not TIER_TAG_RE.search(seg):
            errors.append(f"{title}: section {i + 1} ({name}) carries no Tier / verdict tag -- every claim needs its evidence level visible")

    ledger = body[positions[7]:positions[8]]
    if len(ledger.strip().splitlines()) < 3:
        errors.append(f"{title}: Evidence ledger is too thin ({len(ledger.strip().splitlines())} line(s)) -- one line per major claim, not a one-line summary")


def main():
    if not GAMEPLAY.exists():
        print(f"FAILED: {GAMEPLAY} not found")
        return 1
    text = GAMEPLAY.read_text(encoding="utf-8")

    # The contract itself must still be declared in the book.
    if "### Deck primer" not in text:
        print("FAILED: gameplay.md no longer declares a '### Deck primer' section -- the fixed-format contract this checks against is gone")
        return 1

    examples = split_examples(text)
    if not examples:
        print("FAILED: gameplay.md contains no '**Worked example ...**' deck primer -- the book promises at least one")
        return 1

    errors = []
    for title, body in examples:
        check_example(title, body, errors)

    print(f"[info] checked {len(examples)} deck-primer worked example(s) in gameplay.md against the eight-section contract.")
    if errors:
        print("\n[errors]")
        for e in errors:
            print(f"  - {e}")
        print(f"\nFAILED: {len(errors)} contract violation(s).")
        return 1
    print("\nOK: every deck-primer worked example follows the fixed contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
