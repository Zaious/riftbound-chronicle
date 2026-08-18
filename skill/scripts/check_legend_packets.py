#!/usr/bin/env python3
"""
Validate the shape of extract_legend_packets.py's output.

This used to be an inline Python snippet inside .github/workflows/ci.yml,
which is exactly why it went red for five consecutive commits without
anyone noticing locally: the local scripts all passed, but the CI-only
assertion ("every packet has exactly 2 Champions") encoded the very
assumption extract_legend_packets.py had just been fixed to stop making.
Pulling it into a real script means the same gate runs locally and in CI,
so local-green/CI-red can't silently recur.

What this checks (and why each rule is shaped the way it is):

- At least 46 packets. The catalog is 46 Legends; the extractor also
  emits Kai'Sa and Annie (the deckbuilding book's canonical worked
  examples, not catalog rows), so 48 is the current real count. ">= 46"
  rather than "== 48" so a genuinely new Legend in a fresh harvest
  doesn't break CI -- a *drop* below the catalog size is the real bug.
- Every packet has at least 2 Champions. Two is the floor (one per
  Domain), not the ceiling -- see extract_legend_packets.py's docstring
  for why "exactly 2" was wrong.
- Packets with more than 2 Champions must be on the known-extra-print
  allowlist below. A new Legend showing up with 3+ Champions is either
  a genuine new extra print (add it to the allowlist after confirming
  it's real -- and then its Tier 1 catalog entry needs updating too, per
  verification-log.md's follow-up rows) or a new source-data mispairing
  like Kennen's -- either way it deserves a human look, not a silent pass.
- Kennen specifically: its "Yordle" tag pulls in other Yordle Champions
  (Fizz, Vex, Poppy, Teemo). The extractor's Domain filter narrows the
  worst of it but the packet still carries more than Kennen's own two
  real Champions. This script asserts the two real ones are present
  and tolerates the rest, rather than pretending the packet is clean.
  The mispairing itself is a source-data issue, documented in
  extract_legend_packets.py, not something to hide with a stricter
  filter that might drop a real Champion elsewhere.

Usage:
    python3 skill/scripts/check_legend_packets.py [PACKETS_JSON]

Defaults to regenerating packets fresh via extract_legend_packets.py if
no path is given, so it stays in sync with whatever the extractor now
does. Exit code 0 on pass, 1 on failure.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXTRACTOR = HERE / "extract_legend_packets.py"

MIN_PACKETS = 46

# Legends confirmed (verification-log.md, 2026-08-18) to have a genuine
# additional Champion print sharing a Domain with an earlier one. Keyed by
# the extractor's own legend_name output. Values: the number of real
# distinct Champions expected. Update this list *only* after confirming a
# new entry is a real print via card data + real-play research, not on
# the strength of the extractor emitting a third row.
KNOWN_EXTRA_PRINTS = {
    "Draven - Glorious Executioner": 3,   # Vanquisher, Showboat, Audacious
    "Fiora - Grand Duelist": 3,           # Peerless, Worthy, Victorious
    "Jayce - Defender of Tomorrow": 3,    # Brilliant Inventor, Man of Progress, Hammer in Hand
    "Master Yi - Wuju Bladesman": 4,      # Meditative, Unstoppable, Honed, Tempered
    "Rengar - Pridestalker": 3,           # Unseen, Pouncing, Trophy Hunter
    "Shen - Eye of Twilight": 3,          # Scourge of Shadows, Leader of the Kinkou Order, Kinkou
    "Vex - Gloomist": 3,                  # Mocking, Cheerless, Apathetic
    "Vi - Piltover Enforcer": 3,          # Hotheaded, Destructive, Peacekeeper
}

# Kennen's packet is a known source-data mispairing (see extractor
# docstring): the extractor's legend_name for it carries the raw "Yordle,"
# prefix. Its two real Champions must be present; extra tag-matched rows
# are tolerated (and warned about) but not treated as legitimate.
KENNEN_LEGEND_NAME = "Yordle, Kennen - Heart of the Tempest"
KENNEN_REAL_CHAMPIONS = {"Kennen, Storm of Shuriken", "Kennen, Keeper of Balance"}


def load_packets(path):
    if path is None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            out = Path(tmp.name)
        result = subprocess.run(
            [sys.executable, str(EXTRACTOR), "--out", str(out)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            print("FAILED: extract_legend_packets.py did not exit cleanly.")
            sys.exit(1)
        path = out
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    packets = load_packets(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    errors = []
    warnings = []

    if len(packets) < MIN_PACKETS:
        errors.append(f"expected at least {MIN_PACKETS} Legend packets, got {len(packets)}")

    for p in packets:
        name = p["legend_name"]
        champs = p["champions"]
        n = len(champs)

        if name == KENNEN_LEGEND_NAME:
            names = {c["name"] for c in champs}
            missing = KENNEN_REAL_CHAMPIONS - names
            if missing:
                errors.append(f"{name}: missing real Champion(s) {sorted(missing)} -- got {sorted(names)}")
            extra = names - KENNEN_REAL_CHAMPIONS
            if extra:
                warnings.append(f"{name}: {len(extra)} tag-mispaired non-Kennen candidate(s) still present ({sorted(extra)}) -- known Yordle-tag source-data issue, tolerated, not a legitimate Champion pool")
            continue

        if n < 2:
            errors.append(f"{name}: only {n} Champion(s) found ({[c['name'] for c in champs]}) -- every Legend needs at least one per Domain")
        elif n > 2:
            expected = KNOWN_EXTRA_PRINTS.get(name)
            if expected is None:
                errors.append(
                    f"{name}: {n} Champions ({[c['name'] for c in champs]}) but not on the known-extra-print allowlist. "
                    f"Either a genuine new extra print (confirm via card data + real play, then add to KNOWN_EXTRA_PRINTS "
                    f"AND update its catalog entry per verification-log.md's follow-up pattern) or a new source-data mispairing -- needs a human look."
                )
            elif n != expected:
                errors.append(f"{name}: allowlist expects {expected} Champions, extractor produced {n} ({[c['name'] for c in champs]}) -- allowlist or extractor is stale")

    for legend in KNOWN_EXTRA_PRINTS:
        if not any(p["legend_name"] == legend for p in packets):
            errors.append(f"allowlisted Legend {legend!r} not present in packets at all -- allowlist key may be stale against the extractor's legend_name format")

    regular = sum(1 for p in packets if len(p["champions"]) == 2)
    extra = sum(1 for p in packets if p["legend_name"] in KNOWN_EXTRA_PRINTS)
    print(f"[info] {len(packets)} Legend packets: {regular} with exactly 2 Champions, {extra} on the known-extra-print allowlist, {1 if any(p['legend_name'] == KENNEN_LEGEND_NAME for p in packets) else 0} known-mispaired (Kennen).")

    for w in warnings:
        print(f"[warn] {w}")

    if errors:
        print("\n[errors]")
        for e in errors:
            print(f"  - {e}")
        print(f"\nFAILED: {len(errors)} packet-shape error(s).")
        return 1

    print("\nOK: Legend packet shape is as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
