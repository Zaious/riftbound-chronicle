#!/usr/bin/env python3
"""
Warn when Tier 2 findings in verification-log.md predate a format-changing
event for their own environment and haven't been re-checked since; note rows
checked inside a set's launch window.

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

Events are scoped per environment: a global set release doesn't move
Taiwan's OGN+OGS pool at all, and Taiwan's own launch date is the event that
matters there. Ban waves and rules revisions are company-wide ("*").

This is a WARNING gate for staleness, not a failure gate: a stale row isn't
a wrong row, it's a row whose real-play claims are older than the last
shake-up. It DOES fail on schema problems (a row with a missing or unknown
Environment), because the column only helps if every row has it.

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

# (date, label, kind, scope). scope is an environment tag or "*" for all.
# Keep sorted by date. Only include events that have actually happened by the
# file's last edit -- future releases go in FUTURE_EVENTS so --as-of can
# preview them without their counting today.
FORMAT_EVENTS = [
    ("2026-03-31", "First Constructed ban wave", "ban", "*"),
    ("2026-07-16", "Core Rules + Tournament Rules revision", "rules", "*"),
    ("2026-07-24", "Ban list update + Vendetta errata", "ban", "*"),
    ("2026-07-31", "Vendetta (VEN) release", "set", "global-vendetta"),
    ("2026-08-07", "Taiwan OGN launch (OGS Proving Grounds alongside)", "set", "taiwan-set1-banned"),
]
FUTURE_EVENTS = [
    ("2026-10-23", "Radiance (RAD) release", "set", "global-vendetta"),
]

# Rows checked inside this many days of their environment's most recent *set*
# event are flagged launch-window: the meta hasn't settled, so the row's value
# is the dated baseline, not the conclusion. Same standard the log already
# applied to Vendetta-launch Legends (Akali/Ambessa/Renekton, ~3 weeks in).
LAUNCH_WINDOW_DAYS = 30

# Row shape: | date | `environment` | Legend | ...  (environment column added 2026-08-18)
ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2})(?: \([^)]*\))? \| `?([a-z0-9-]+)`? \| ([^|]+?) \|", re.MULTILINE)
VALID_ENVIRONMENTS = {"global-vendetta", "taiwan-set1-banned"}  # keep in sync with data/tournament_lists/README.md


def parse_rows(text):
    """Return ([(date, environment, legend)], [schema problems])."""
    rows, bad = [], []
    for m in ROW_RE.finditer(text):
        env = m.group(2)
        if env not in VALID_ENVIRONMENTS:
            bad.append((m.group(1), env, m.group(3).strip()))
        rows.append((datetime.date.fromisoformat(m.group(1)), env, m.group(3).strip()))
    dated_lines = re.findall(r"^\| \d{4}-\d{2}-\d{2}", text, re.MULTILINE)
    if len(dated_lines) != len(rows):
        bad.append(("?", "<column missing or malformed>", f"{len(dated_lines) - len(rows)} row(s) did not parse"))
    return rows, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", type=datetime.date.fromisoformat, default=datetime.date.today())
    args = ap.parse_args()

    if not LOG.exists():
        print(f"FAILED: {LOG} not found")
        return 1
    rows, bad = parse_rows(LOG.read_text(encoding="utf-8"))
    if not rows:
        print("FAILED: no dated rows parsed from verification-log.md -- table format changed?")
        return 1
    if bad:
        print("[errors] Environment column problems (must be one of " + ", ".join(sorted(VALID_ENVIRONMENTS)) + "):")
        for d, env, legend in bad:
            print(f"  - {d} {legend}: environment {env!r}")
        print(f"\nFAILED: {len(bad)} row(s) with a missing/unknown Environment.")
        return 1

    events = [(datetime.date.fromisoformat(d), lbl, k, s) for d, lbl, k, s in FORMAT_EVENTS + FUTURE_EVENTS]
    events = [e for e in events if e[0] <= args.as_of]
    if not events:
        print(f"[info] no format events on or before {args.as_of}; nothing to compare against.")
        return 0

    def latest_for(env, kind=None):
        rel = [e for e in events if e[3] in ("*", env) and (kind is None or e[2] == kind)]
        return max(rel, key=lambda e: e[0]) if rel else None

    stale, launch = [], []
    for d, env, legend in rows:
        le = latest_for(env)
        if le and d < le[0]:
            stale.append((d, env, legend, le))
        ls = latest_for(env, "set")
        if ls and 0 <= (d - ls[0]).days < LAUNCH_WINDOW_DAYS:
            launch.append((d, env, legend, ls, (d - ls[0]).days))

    by_env = {}
    for _, env, _ in rows:
        by_env[env] = by_env.get(env, 0) + 1
    print(f"[info] {len(rows)} Tier 2 rows by environment: {by_env}")
    for env in sorted(by_env):
        le = latest_for(env)
        print(f"[info] {env}: latest format event on/before {args.as_of}: {le[0]} ({le[1]})")
    print(f"[info] {len(rows) - len(stale)} row(s) dated on/after their environment's latest event, {len(stale)} predate it.")

    if stale:
        print(f"\n[warn] {len(stale)} Tier 2 row(s) predate the last format event *for their own environment* and have not been re-checked since -- their real-play claims (which Champion is played, tier standing, named archetypes) may no longer hold. Candidates for the next Tier 2 pass, oldest first:")
        for d, env, legend, le in sorted(stale):
            print(f"  - {d}  [{env}]  {legend}  (event: {le[0]} {le[1]})")
    if launch:
        print(f"\n[note] {len(launch)} row(s) were checked within {LAUNCH_WINDOW_DAYS} days of their environment's latest set release -- launch-window rows: treat the finding as a dated baseline, not a settled read, and plan a re-check once the meta has had time to move:")
        for d, env, legend, ls, days in sorted(launch):
            print(f"  - {d}  [{env}]  {legend}  ({days} day(s) after {ls[1]})")

    upcoming = [e for e in [(datetime.date.fromisoformat(d), l, k, s) for d, l, k, s in FUTURE_EVENTS] if e[0] > args.as_of]
    if upcoming:
        nxt = min(upcoming, key=lambda e: e[0])
        will_stale = sum(1 for d, env, _ in rows if d < nxt[0] and nxt[3] in ("*", env))
        print(f"\n[info] next known event: {nxt[0]} ({nxt[1]}, scope {nxt[3]}) -- {will_stale} current row(s) in that scope will predate it; plan a re-check pass around then. Preview with --as-of {nxt[0]}.")

    print("\nOK: freshness report generated (warnings above are advisory, not failures).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
