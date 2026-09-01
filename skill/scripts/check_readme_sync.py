#!/usr/bin/env python3
"""
Keep the three READMEs honest against the code they describe.

Why this exists: README maintenance is split from feature work (the feature
author and the README author are not the same agent), so the READMEs go stale
silently -- and they already did. On 2026-08-30 all three claimed to list "the
same deterministic checks used by CI" while omitting four of them, including
every rules-core gate, and the two localizations had drifted differently from
the English. A prose file cannot be trusted to track a moving codebase unless
something checks it.

This gate asserts the claims that are mechanically checkable:

1. Routed modes. The system table in each README must list exactly the modes
   `skill/SKILL.md` actually routes -- no more (do not advertise an ungated
   system) and no fewer (do not hide a shipped one). This is the check that
   fires the day `match-analyst` is wired in.
2. Cross-language agreement. All three READMEs must name the same systems.
3. Cited counts. Any "N executable cases"-style figure must match the real
   length of the data file it describes.
4. Referenced scripts and prototype pages must exist.

It deliberately does NOT check prose quality, translation faithfulness, or
whether the framing is good. Those need a human.

Usage:
    python3 skill/scripts/check_readme_sync.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = ROOT / "skill"
READMES = ["README.md", "README.zh-TW.md", "README.ko.md"]

# Counts a README may cite, mapped to the file that decides the true number.
COUNTED = {
    "rules_core_cases.json": SKILL / "data" / "rules_core_cases.json",
    "deck_coach_cases.json": SKILL / "data" / "deck_coach_cases.json",
    "rule_consult_cases.json": SKILL / "data" / "rule_consult_cases.json",
}


def routed_modes() -> set[str]:
    """Modes SKILL.md actually routes, read from its 'Choose the mode' bullets."""
    t = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"## Choose the mode(.*?)^## ", t, re.S | re.M)
    if not m:
        return set()
    return set(re.findall(r"references/([a-z0-9-]+)/\1\.md", m.group(1)))


def case_count(path: Path) -> int:
    d = json.loads(path.read_text(encoding="utf-8"))
    c = d.get("cases", d) if isinstance(d, dict) else d
    return len(c)


def main() -> int:
    errors: list[str] = []
    modes = routed_modes()
    if not modes:
        print("FAILED: could not parse routed modes from SKILL.md -- did its 'Choose the mode' section change shape?")
        return 1

    listed_per_file: dict[str, set[str]] = {}
    for name in READMES:
        p = ROOT / name
        if not p.exists():
            errors.append(f"{name}: missing")
            continue
        t = p.read_text(encoding="utf-8")

        # 1 + 2: systems named in the file's table rows (`mode` in a leading table cell)
        listed = set(re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", t, re.M))
        listed_per_file[name] = listed
        extra = listed - modes
        missing = modes - listed
        if extra:
            errors.append(
                f"{name}: lists {sorted(extra)} in its system table, but SKILL.md does not route them. "
                f"Either the mode was wired in (update SKILL.md) or the README is advertising an ungated system."
            )
        if missing:
            errors.append(
                f"{name}: SKILL.md routes {sorted(missing)} but the README's system table omits them -- "
                f"a shipped mode users cannot discover."
            )

        # 3: cited counts must match the data
        for label, path in COUNTED.items():
            if not path.exists():
                continue
            real = case_count(path)
            # Compare any number written near the file's own name. Localisations use
            # their own wording for "cases", so anchor on the filename, not the noun.
            stem = path.stem.replace("_", "[ _-]")
            if re.search(stem, t):
                # One number, before the filename, on the same line. Keep any
                # other figure (fixture counts, dates) out of that window: this
                # gate cannot tell which number the claim is about, and a second
                # one in range reads as a wrong case count.
                nums = {int(n) for n in re.findall(rf"(\d+)[^\n]{{0,80}}{stem}", t)}
                bad = {n for n in nums if n != real}
                if bad:
                    errors.append(f"{name}: cites {sorted(bad)} near {path.name} but the file holds {real} cases")

        # 4: referenced scripts and prototype pages exist
        for rel in set(re.findall(r"skill/scripts/([a-z0-9_]+\.py)", t)):
            if not (SKILL / "scripts" / rel).exists():
                errors.append(f"{name}: references skill/scripts/{rel}, which does not exist")
        for rel in set(re.findall(r"\(prototype/([a-z0-9-]+)/index\.html\)", t)):
            if not (ROOT / "prototype" / rel / "index.html").exists():
                errors.append(f"{name}: links prototype/{rel}/index.html, which does not exist")

    names = [s for s in listed_per_file.values()]
    if names and any(s != names[0] for s in names):
        errors.append(
            "the three READMEs do not name the same systems: "
            + "; ".join(f"{k}={sorted(v)}" for k, v in listed_per_file.items())
        )

    print(f"[info] SKILL.md routes {len(modes)} mode(s): {sorted(modes)}")
    for k, v in listed_per_file.items():
        print(f"[info] {k} lists {sorted(v)}")

    if errors:
        print("\n[errors]")
        for e in errors:
            print(f"  - {e}")
        print(f"\nFAILED: {len(errors)} README/code mismatch(es).")
        return 1
    print("\nOK: all three READMEs match the routed modes, cited counts, and referenced paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
