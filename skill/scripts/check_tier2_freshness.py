#!/usr/bin/env python3
"""
Warn when Tier 2 findings in verification-log.md predate a format-changing
event and haven't been re-checked since.

Why this exists: the errata overlay has a 90-day freshness gate, but the
Tier 2 log had none -- and Tier 2 findings go stale faster and less
predictably than errata. In one session (2026-08-18) the same log recorded
Zed's "maybe tier 1" rating flipping to rogue-tier within a month, Master
Yi's real Chosen Champion changing between sets, and three Vendetta-launch
Legends carrying explicit low-confidence flags because the set was three
weeks old. A dated row tells a reader *when* something was true; nothing
told them *whether an event since then* makes it worth re-checking.

TCG staleness is stepwise, not linear -- a finding from the day before a
new set is far more suspect than one from 60 quiet days earlier -- so this
gate is event-driven, not day-count-driven. FORMAT_EVENTS below is the
single source of truth for "things that plausibly reshuffle real play";
add a row when a set releases, a ban wave lands, or a rules revision
changes a mechanic decks were built around.

This is a WARNING gate, not a failure gate: a stale row isn't a wrong row,
it's a row whose real-play claims are older than the last shake-up. The
report is meant to drive the next Tier 2 pass, not block CI. It exits 0
unless the log's own table can't be parsed.

Usage:
    python3 skill/scripts/check_tier2_freshness.py [--as-of YYYY-MM-DD]

--as-of lets you ask "which rows will be stale once event X lands" by
setting the reference date forward; default is today.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
LOG = SKILL_DIR / "references" / "deckbuilding" / "references" / "verification-log.md"

# (date, label, kind). Keep sorted by date. Only include events that have
# actually happened by the file's last edit -- a future release goes in the
# FUTURE_EVENTS list so --as-of can preview it without it counting today.
FORMAT_EVENTS = [
    ("2026-03-31", "First Constructed ban wave", "ban"),
    ("2026-07-16", "Core Rules + Tournament Rules revision", "rules"),
    ("2026-07-24", "Ban list update + Vendetta errata", "ban"),
    ("2026-07-31", "Vendetta (VEN) release", "set"),
]
FUTURE_EVENTS = [
    ("2026-10-23", "Radiance (RAD) release", "set"),
]

ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2})(?: \([^)]*\))? \| ([^|]+?) \|", re.MULTILINE)


def parse_rows(text):
    rows = []
    for m in ROW_RE.finditer(text):
        rows.append((datetime.date.fromisoformat(m.group(1)), m.group(2).strip()))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", type=datetime.date.fromisoformat, default=datetime.date.today())
    args = ap.parse_args()

    if not LOG.exists():
        print(f"FAILED: {LOG} not found")
        return 1
    rows = parse_rows(LOG.read_text(encoding="utf-8"))
    if not rows:
        print("FAILED: no dated rows parsed from verification-log.md -- table format changed?")
        return 1

    events = [(datetime.date.fromisoformat(d), lbl, k) for d, lbl, k in FORMAT_EVENTS + FUTURE_EVENTS]
    events = [e for e in events if e[0] <= args.as_of]
    if not events:
        print(f"[info] no format events on or before {args.as_of}; nothing to compare against.")
        return 0
    latest = max(events, key=lambda e: e[0])

    stale = [(d, legend) for d, legend in rows if d < latest[0]]
    fresh = len(rows) - len(stale)

    print(f"[info] {len(rows)} Tier 2 rows; latest format event on/before {args.as_of}: {latest[0]} ({latest[1]}).")
    print(f"[info] {fresh} row(s) dated on/after that event, {len(stale)} row(s) predate it.")

    if stale:
        print(f"\n[warn] {len(stale)} Tier 2 row(s) predate the last format event ({latest[1]}) and have not been re-checked since -- their real-play claims (which Champion is played, tier standing, named archetypes) may no longer hold. Candidates for the next Tier 2 pass, oldest first:")
        for d, legend in sorted(stale):
            print(f"  - {d}  {legend}")

    upcoming = [e for e in [(datetime.date.fromisoformat(d), l, k) for d, l, k in FUTURE_EVENTS] if e[0] > args.as_of]
    if upcoming:
        nxt = min(upcoming, key=lambda e: e[0])
        will_stale = sum(1 for d, _ in rows if d < nxt[0])
        print(f"\n[info] next known event: {nxt[0]} ({nxt[1]}) -- all {will_stale} current row(s) will predate it; plan a re-check pass around then. Preview with --as-of {nxt[0]}.")

    print("\nOK: freshness report generated (warnings above are advisory, not failures).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
